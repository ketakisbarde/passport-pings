# Passport Pings

Created by **Ketaki Barde**. A Python learning project sharing greetings, cities,
and airport codes through automated GitHub journal entries and Discord messages.

## What is ready

- The original [learning notebook](./passport-pings-playground.ipynb) is preserved.
- [160 greeting dictionaries](./data/greetings.json) were exported from its larger
  collection without executing the notebook.
- [The Python runner](./passport_pings.py) retains `country_flag`, `format_ping`,
  and `generate_ping`, adding persistent storage and notification delivery.
- Three scheduled runs a week: **Monday, Wednesday, Friday, 9:17 a.m.
  America/Los_Angeles**, including daylight-saving changes.
- MIT licensed; copyright **2026 Ketaki Barde**.

This is an automation bot, not an AI agent. Model-generated captions or quizzes
and a Python app are possible later; neither is needed for the core workflow.

## Data quality

The collection contains 160 distinct **language/phrase** entries across 32
languages, including greetings, nighttime wishes, and farewells. Some languages
share spellings. At three entries per week, it lasts over 53 weeks before cycling.
Countries and airports are featured destinations, not exclusive homes of languages.

**The dataset is a draft, not a source-verified phrasebook.** Validation checks
required fields, duplicates, and code formats; it cannot verify translations,
natural usage, romanization, or airport assignments. Add verification sources and
review entries before presenting the collection as authoritative.
Morning/evening phrases are taught as vocabulary, not matched to delivery time.

## Run on your Mac

Use Python 3.11 or newer:

```bash
git clone https://github.com/ketakisbarde/passport-pings.git
cd passport-pings
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python passport_pings.py preview
```

`preview` only prints the next entry. It never advances the journal.
`python passport_pings.py prepare` writes today's entry locally; it does not commit
or push. A rerun reuses today's snapshot rather than advancing again.
Don't manually commit experimental journal changes unless you want to publish them.

## Workflow and state

```text
Test -> select/reuse today's entry -> save -> commit/push -> notify Discord
```

The tracked [journal.json](./journal.json) is authoritative state. Its entry count
is the next turn; each record contains a date, turn, greeting snapshot, and message.
[JOURNAL.md](./JOURNAL.md) is a derived human-readable view. JSON is atomically
replaced before Markdown; reruns repair a missing Markdown view without losing
the saved selection. Malformed or missing state fails explicitly, never resets.
Existing entries retain their snapshots if the dataset is edited.

Workflow concurrency serializes writers. Only journal files are staged, and
pushes are ordinary forward-only pushes. A competing manual push causes a clear
failure; the next run starts from the latest published journal.
Keep the journal's schema intact and don't edit it casually.

## Configure your identity

Edit [config.json](./config.json):

- `timezone`: timezone used to determine today's journal date.
- `commit_author_name`: your name.
- `commit_author_email`: an email associated with your GitHub account. It will
  be public in Git commits; use your GitHub noreply email if desired.

The current configuration uses Ketaki's previously supplied personal commit email.
If changing the timezone, also change `timezone` in the scheduled workflow.
The email association cannot be established by a local format check.
Automated activity is openly labeled as such, not evidence of manual daily coding.

## Set up Discord

1. In your personal Discord server, select a channel such as `#passport-pings`.
2. Create an incoming webhook under the channel's **Integrations** settings.
3. On GitHub, open **Settings -> Secrets and variables -> Actions**.
4. Add a repository secret named **DISCORD_WEBHOOK_URL** with that URL.

Do not paste the URL into chat, notebook cells, committed files, or command history.
It contains a credential allowing posts to its channel. Delete/recreate the webhook
if it leaks. Keep credentials in your environment or GitHub secrets.

Notifications are sent **only after a successful push**. Discord mentions are
disabled; HTTP failures/timeouts fail the notification step without logging the
credential-bearing URL. Delivery success requires a Discord message ID.
If no secret exists, the workflow explicitly warns and skips notifications while
still publishing the journal.

## First manual run

On GitHub, open **Actions -> Passport Pings -> Run workflow**, select **main**,
and leave `resend_today` unchecked. Verify:

1. Tests pass.
2. The bot publishes at most one entry for the local date.
3. The commit contains only the journal files.
4. Discord receives the message, or the step reports the missing secret.
5. A second run on the same date reuses the entry without another routine notification.

If Discord failed after the push, set `resend_today` to retry delivery explicitly.
If the earlier response was lost, that retry may duplicate a message. There is no
exactly-once guarantee across GitHub and Discord; the bot does not silently claim one.

## Scheduling

The workflow includes the schedule and a manual trigger. GitHub uses the default
branch, `main`; non-main manual runs do not write the journal. Runs may be delayed
or dropped during heavy load and public-repository schedules can be disabled
after 60 days without repository activity. Monitor the Actions tab.

The bot uses GitHub's repository-scoped `GITHUB_TOKEN` with `contents: write`;
no personal access token is required. Repository/organization policy or branch
protection can still prevent pushes. If a write is denied, inspect the run and
your repository's **Settings -> Actions -> General** policies rather than
granting unrelated permissions.

Commits made with `GITHUB_TOKEN` do not normally trigger another push workflow,
avoiding a self-triggering loop. Tests therefore also run inside every scheduled
or manually triggered Passport Pings workflow.

## Reuse, credit, and future scope

Inspired by [Steven Kneiser's commit-bot](https://github.com/theshteves/commit-bot),
which appends timestamps through Bash/local cron. This is a separate Python
implementation producing a language-learning journal, not a copy of that script.

Licensed under [MIT](./LICENSE). Preserve the copyright and license notice when
reusing copies or substantial portions. A visible link back is appreciated.

For your own copy, set your identity/timezone, add your own Discord secret,
and initialize a new empty journal rather than inheriting another user's activity.
Forked workflows must be enabled and reviewed explicitly.

Future work: reviewed phrase sources, configurable destinations, optional
AI captions/quizzes, and an app using the same selection/formatting functions.
