from datetime import date
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import passport_pings as bot


class PassportPingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        for name in ("config.json",):
            shutil.copyfile(bot.ROOT / name, self.root / name)
        shutil.copyfile(
            bot.ROOT / "data" / "greetings.json", self.root / "data" / "greetings.json",
        )
        (self.root / "journal.json").write_text(
            json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8",
        )

    def test_dataset_has_year_of_distinct_entries(self):
        greetings = bot.load_greetings(self.root)
        self.assertEqual(len(greetings), 160)
        self.assertEqual(len({(e["language"], e["greeting"]) for e in greetings}), 160)
        self.assertEqual(len({e["language"] for e in greetings}), 32)

    def test_flags_and_format(self):
        self.assertEqual(bot.country_flag("IN"), "\U0001f1ee\U0001f1f3")
        entry = bot.load_greetings(self.root)[0]
        message = bot.format_ping(entry, 1)
        self.assertIn("PASSPORT PINGS — #1", message)
        self.assertIn(f"Featured destination: {entry['city']} ({entry['airport_code']})", message)

    def test_invalid_codes_and_duplicate_phrases(self):
        for code in ("in", "IND", "1N", ""):
            with self.subTest(code=code), self.assertRaises(ValueError):
                bot.country_flag(code)
        entry = bot.load_greetings(self.root)[0]
        with self.assertRaises(ValueError):
            bot.validate_greetings([entry, entry.copy()])
        with self.assertRaises(ValueError):
            bot.validate_greetings([{**entry, "airport_code": "sf0"}])
        with self.assertRaises(ValueError):
            bot.validate_greetings([{**entry, "language": ""}])

    def test_generation_wraps_after_160_entries(self):
        greetings = bot.load_greetings(self.root)
        message, updated = bot.generate_ping(greetings, 160)
        self.assertEqual(updated, 161)
        self.assertEqual(message, bot.format_ping(greetings[0], 161))
        for turn in (-1, True, 1.5):
            with self.subTest(turn=turn), self.assertRaises(ValueError):
                bot.generate_ping(greetings, turn)

    def test_prepare_persists_and_rerun_is_idempotent(self):
        day = date(2026, 11, 2)
        first, created = bot.prepare_ping(self.root, day)
        self.assertTrue(created)
        before = (self.root / "journal.json").read_bytes()
        repeated, created = bot.prepare_ping(self.root, day)
        self.assertFalse(created)
        self.assertEqual(first, repeated)
        self.assertEqual((self.root / "journal.json").read_bytes(), before)
        second, created = bot.prepare_ping(self.root, date(2026, 11, 4))
        self.assertTrue(created)
        self.assertEqual(second["turn"], 1)
        self.assertEqual(len(bot.load_journal(self.root)), 2)

    def test_160_dates_visit_each_entry(self):
        from datetime import timedelta
        records = []
        for turn in range(160):
            record, created = bot.prepare_ping(self.root, date(2026, 1, 1) + timedelta(days=turn))
            self.assertTrue(created)
            records.append(record)
        keys = {(r["entry"]["language"], r["entry"]["greeting"]) for r in records}
        self.assertEqual(len(keys), 160)

    def test_snapshots_survive_dataset_edits(self):
        day = date(2026, 11, 2)
        original, _ = bot.prepare_ping(self.root, day)
        path = self.root / "data" / "greetings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data[0]["greeting"] = "Edited greeting"
        path.write_text(json.dumps(data), encoding="utf-8")
        repeated, created = bot.prepare_ping(self.root, day)
        self.assertFalse(created)
        self.assertEqual(original, repeated)

    def test_rebuild_markdown_after_interrupted_write(self):
        day = date(2026, 11, 2)
        bot.prepare_ping(self.root, day)
        expected = (self.root / "JOURNAL.md").read_bytes()
        (self.root / "JOURNAL.md").unlink()
        _, created = bot.prepare_ping(self.root, day)
        self.assertFalse(created)
        self.assertEqual((self.root / "JOURNAL.md").read_bytes(), expected)

    def test_corrupt_or_missing_state_fails_instead_of_resetting(self):
        path = self.root / "journal.json"
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            bot.prepare_ping(self.root, date(2026, 11, 2))
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            bot.prepare_ping(self.root, date(2026, 11, 2))

    def test_invalid_journal_records_fail(self):
        day = date(2026, 11, 2)
        bot.prepare_ping(self.root, day)
        path = self.root / "journal.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for field, value in (("turn", 4), ("message", "changed"), ("date", "bad-date")):
            modified = json.loads(json.dumps(original))
            modified["entries"][0][field] = value
            path.write_text(json.dumps(modified), encoding="utf-8")
            with self.subTest(field=field), self.assertRaises(ValueError):
                bot.load_journal(self.root)

    def test_past_date_rejected(self):
        bot.prepare_ping(self.root, date(2026, 11, 4))
        with self.assertRaises(ValueError):
            bot.prepare_ping(self.root, date(2026, 11, 2))

    def test_timezone_config_and_identity(self):
        config = bot.load_config(self.root)
        self.assertEqual(config["timezone"], "America/Los_Angeles")
        self.assertTrue(config["commit_author_email"])
        path = self.root / "config.json"
        path.write_text('{"timezone": "UTC"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            bot.load_config(self.root)

    def test_discord_payload_and_confirmation(self):
        record, _ = bot.prepare_ping(self.root, date(2026, 11, 2))
        with patch("passport_pings.urlopen") as send:
            send.return_value.__enter__.return_value.read.return_value = b'{"id":"123"}'
            message_id = bot.send_discord(
                record, "https://discord.com/api/webhooks/123/test-token",
                "https://github.com/example/project/commit/" + "a" * 40,
            )
            self.assertEqual(message_id, "123")
            request = send.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(payload["allowed_mentions"], {"parse": []})
            self.assertIn(record["message"], payload["content"])
            self.assertTrue(request.full_url.endswith("?wait=true"))
            self.assertEqual(send.call_args.kwargs["timeout"], 20)

    def test_discord_errors_do_not_expose_credentials(self):
        record, _ = bot.prepare_ping(self.root, date(2026, 11, 2))
        webhook = "https://discord.com/api/webhooks/123/secret-token"
        commit = "https://github.com/example/project/commit/" + "a" * 40
        failures = (
            HTTPError(webhook, 429, "rate limited", {}, None),
            URLError(webhook),
            TimeoutError(),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch("passport_pings.urlopen", side_effect=failure):
                    with self.assertRaises(RuntimeError) as caught:
                        bot.send_discord(record, webhook, commit)
                    self.assertNotIn("secret-token", str(caught.exception))

    def test_discord_rejects_untrusted_endpoint_and_invalid_commit(self):
        record, _ = bot.prepare_ping(self.root, date(2026, 11, 2))
        with patch("passport_pings.urlopen") as send:
            with self.assertRaises(ValueError):
                bot.send_discord(record, "https://example.com/webhook", "invalid")
            with self.assertRaises(ValueError):
                bot.send_discord(record, "https://discord.com/api/webhooks/123/token", "invalid")
            send.assert_not_called()

    def test_missing_webhook_reports_explicit_skip(self):
        import io
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.argv", ["passport_pings.py", "notify", "--root", str(self.root)]):
                with patch("sys.stdout", output):
                    bot.main()
        self.assertIn("notification skipped", output.getvalue())


if __name__ == "__main__":
    unittest.main()
