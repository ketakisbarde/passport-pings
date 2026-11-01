"""Passport Pings: greeting selection, persistent journal, and Discord delivery."""

import argparse
from datetime import date, datetime
from html import escape
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
FIELDS = (
    "greeting", "language", "meaning", "usage_note",
    "country_code", "city", "airport_code",
)


def country_flag(country_code: str) -> str:
    """Convert an uppercase country code into a flag; validate format only."""
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        raise ValueError("Use a two-letter uppercase country code, such as IN.")
    return "".join(
        chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country_code
    )


def validate_greetings(greetings: object) -> list[dict[str, str]]:
    """Check structural validity, not translation or airport accuracy."""
    if not isinstance(greetings, list) or not greetings:
        raise ValueError("The greeting collection must be a nonempty list.")
    validated: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(greetings):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {index} must be a dictionary.")
        for field in FIELDS:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"Entry {index}: {field} must contain text.")
        country_flag(entry["country_code"])
        if not re.fullmatch(r"[A-Z]{3}", entry["airport_code"]):
            raise ValueError(f"Entry {index}: invalid IATA airport-code format.")
        key = (entry["language"].strip().casefold(), entry["greeting"].strip().casefold())
        if key in seen:
            raise ValueError(f"Duplicate language/phrase at entry {index}.")
        seen.add(key)
        validated.append({field: entry[field] for field in FIELDS})
    return validated


def format_ping(entry: dict[str, str], ping_number: int) -> str:
    """Keep the familiar notebook output; don't print or send from here."""
    return (
        f"{country_flag(entry['country_code'])} PASSPORT PINGS — #{ping_number}\n"
        f"{entry['greeting']}!\n\n"
        f"Language: {entry['language']}\n"
        f"Meaning: {entry['meaning']}\n"
        f"Usage: {entry['usage_note']}\n"
        f"Featured destination: {entry['city']} ({entry['airport_code']})\n"
        f"Featured country: {entry['country_code']}"
    )


def generate_ping(
    greetings: list[dict[str, str]], next_turn: int,
) -> tuple[str, int]:
    """Return the next message and turn, just as in the notebook."""
    if not greetings:
        raise ValueError("Add at least one greeting.")
    if type(next_turn) is not int or next_turn < 0:
        raise ValueError("The turn counter must be a nonnegative integer.")
    entry = greetings[next_turn % len(greetings)]
    return format_ping(entry, next_turn + 1), next_turn + 1


def load_config(root: Path) -> dict[str, str]:
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object.")
    fields = ("timezone", "commit_author_name", "commit_author_email")
    if any(not isinstance(config.get(field), str) or not config[field].strip()
           for field in fields):
        raise ValueError("Timezone and commit author name/email are required.")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+", config["commit_author_email"]):
        raise ValueError("Invalid commit author email format.")
    ZoneInfo(config["timezone"])
    return {field: config[field] for field in fields}


def load_greetings(root: Path) -> list[dict[str, str]]:
    return validate_greetings(
        json.loads((root / "data" / "greetings.json").read_text(encoding="utf-8"))
    )


def load_journal(root: Path) -> list[dict]:
    """The tracked journal is the state: its length is the next turn."""
    state = json.loads((root / "journal.json").read_text(encoding="utf-8"))
    if not isinstance(state, dict) or type(state.get("schema_version")) is not int:
        raise ValueError("Journal must contain an integer schema_version.")
    if state["schema_version"] != 1 or not isinstance(state.get("entries"), list):
        raise ValueError("Unsupported or malformed journal schema.")
    entries = state["entries"]
    previous_date = None
    for turn, record in enumerate(entries):
        if not isinstance(record, dict) or not isinstance(record.get("date"), str):
            raise ValueError(f"Journal entry {turn} has no valid date.")
        day = date.fromisoformat(record["date"])
        if record["date"] != day.isoformat() or (previous_date and day <= previous_date):
            raise ValueError("Journal dates must be canonical, unique, and increasing.")
        if type(record.get("turn")) is not int or record["turn"] != turn:
            raise ValueError("Journal turns must be consecutive from zero.")
        entry = validate_greetings([record.get("entry")])[0]
        if record.get("message") != format_ping(entry, turn + 1):
            raise ValueError(f"Journal entry {turn} message does not match its snapshot.")
        previous_date = day
    return entries


def atomic_write(path: Path, content: str) -> None:
    """Replace a file only after all its content has been written."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def render_journal(entries: list[dict]) -> str:
    sections = [
        "# Passport Pings journal\n\n"
        "These entries and their commits are automated language-learning activity.\n"
        "The greeting dataset is a draft, not a verified phrasebook.\n"
    ]
    for record in reversed(entries):
        # JSON remains authoritative; HTML escaping keeps dataset text from becoming markup.
        sections.append(
            f"## {record['date']}\n\n<pre>{escape(record['message'])}</pre>\n"
        )
    return "\n".join(sections) + "\n"


def prepare_ping(root: Path, day: date) -> tuple[dict, bool]:
    """Create at most one entry per configured local date; reruns reuse it."""
    greetings = load_greetings(root)
    entries = load_journal(root)
    existing = next((record for record in entries if record["date"] == day.isoformat()), None)
    if existing is not None:
        # Rebuild the derived Markdown if an earlier process stopped between writes.
        atomic_write(root / "JOURNAL.md", render_journal(entries))
        return existing, False
    if entries and day < date.fromisoformat(entries[-1]["date"]):
        raise ValueError("Refusing to create an entry before the latest journal date.")
    turn = len(entries)
    message, _ = generate_ping(greetings, turn)
    record = {
        "date": day.isoformat(),
        "turn": turn,
        "entry": greetings[turn % len(greetings)].copy(),
        "message": message,
    }
    entries.append(record)
    # One authoritative JSON file prevents the counter and journal from diverging.
    atomic_write(
        root / "journal.json",
        json.dumps({"schema_version": 1, "entries": entries}, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write(root / "JOURNAL.md", render_journal(entries))
    return record, True


def send_discord(record: dict, webhook: str, commit_url: str) -> str:
    """Send after publication; wait for Discord's message ID as confirmation."""
    parsed = urlsplit(webhook)
    if (parsed.scheme != "https" or parsed.netloc != "discord.com"
            or not re.fullmatch(r"/api/webhooks/\d+/[A-Za-z0-9._-]+", parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError("Use a standard HTTPS discord.com incoming webhook URL.")
    commit = urlsplit(commit_url)
    if (commit.scheme != "https" or commit.netloc != "github.com"
            or not re.fullmatch(r"/[^/]+/[^/]+/commit/[0-9a-f]{40}", commit.path)
            or commit.query or commit.fragment):
        raise ValueError("A full GitHub commit URL is required.")
    content = f"{record['message']}\n\nJournal date: {record['date']}\nView commit: {commit_url}"
    if len(content) > 2000:
        raise ValueError("Discord message exceeds 2,000 characters.")
    payload = json.dumps({
        "content": content,
        "username": "Passport Pings",
        "allowed_mentions": {"parse": []},
    }).encode("utf-8")
    request = Request(
        webhook + "?wait=true", data=payload, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "PassportPings/1.0"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        # Never include the credential-bearing webhook URL or response body in logs.
        error.close()
        raise RuntimeError(f"Discord returned HTTP {error.code}; delivery not confirmed.") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Discord connection failed; delivery not confirmed.") from None
    if not isinstance(result, dict) or not isinstance(result.get("id"), str):
        raise RuntimeError("Discord did not return a message ID; delivery not confirmed.")
    return result["id"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "prepare", "notify"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--commit-url")
    parser.add_argument("--journal-date")
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_config(root)
    if args.command == "preview":
        greetings = load_greetings(root)
        print(generate_ping(greetings, len(load_journal(root)))[0])
    elif args.command == "prepare":
        day = datetime.now(ZoneInfo(config["timezone"])).date()
        record, created = prepare_ping(root, day)
        print(record["message"])
        print("Created journal entry." if created else "Reused today's existing entry.")
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"created={'true' if created else 'false'}\n")
                stream.write(f"journal_date={record['date']}\n")
    else:
        webhook = os.environ.get("DISCORD_WEBHOOK_URL")
        if not webhook:
            print("::warning::DISCORD_WEBHOOK_URL is not configured; notification skipped.")
            return
        if not args.commit_url or not args.journal_date:
            parser.error("notify requires --commit-url and --journal-date.")
        records = load_journal(root)
        record = next((item for item in records if item["date"] == args.journal_date), None)
        if record is None:
            raise ValueError("Requested notification date is not in the journal.")
        message_id = send_discord(record, webhook, args.commit_url)
        print(f"Discord confirmed message {message_id}.")


if __name__ == "__main__":
    # Preserve flags/accents even when a Windows terminal defaults to a legacy encoding.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
