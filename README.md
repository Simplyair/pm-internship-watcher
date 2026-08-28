# PM Internship Watcher

Polls ~210 job sources every 15 minutes for **product management internships
in the US and Canada**, alerts you on Telegram the moment one appears, and tracks
what you've applied to.

No dependencies — Python 3.9+ standard library only.

---

## Setup (5 minutes)

**1. Create the bot**

In Telegram, message [@BotFather](https://t.me/BotFather) → `/newbot` → follow the
prompts → copy the token it gives you.

**2. Configure**

```bash
cp .env.example .env
```

Open `.env` and paste the token into `TELEGRAM_BOT_TOKEN`.

**3. Find your chat id**

Open your new bot in Telegram and send it any message (just "hi"), then:

```bash
python3 cli.py chatid
```

Put the number it prints into `TELEGRAM_CHAT_ID` in `.env`.

**4. Confirm it works**

```bash
python3 cli.py test
```

You should get a Telegram message.

**5. First scan**

```bash
python3 cli.py scan
```

The first run sends one digest of every PM internship currently open. After that,
you get an individual alert per new posting.

---

## Running it continuously

**On your Mac** (simplest — but only scans while the Mac is awake):

```bash
./scripts/install-launchd.sh
```

Scans every 15 minutes in the background, starts again automatically on reboot.
Stop it with `launchctl bootout gui/$(id -u)/com.pmintern.watcher`.

**In the cloud** (scans even with your laptop closed): push to a **private**
GitHub repo and add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as Actions
secrets. `.github/workflows/watch.yml` then scans every 30 minutes.

Budget: 48 runs/day is about 1,440 billed minutes a month, roughly half of the
3,000 that GitHub Pro (free via the Student Developer Pack) includes for private
repos. Going to every 15 minutes would roughly double that and risk running out
mid-month, at which point scheduled runs stop silently.

Run the cloud watcher **or** the Mac one, not both — they keep separate
databases and would each alert you.

GitHub also disables scheduled workflows after 60 days of repo inactivity, so
push a commit occasionally or re-enable it in the Actions tab.

**In a terminal** (for testing): `python3 cli.py watch`

---

## Alerts

Each alert carries four buttons:

| Button | Effect |
|---|---|
| **Apply** | opens the posting |
| **Applied** | marks it `applied` in the tracker |
| **Save** | marks it `saved` |
| **Ignore** | marks it `ignored` |

Taps are picked up on the next scan (or immediately with `python3 cli.py triage`).

---

## Tracker

```bash
python3 cli.py list                      # everything still open
python3 cli.py list --status applied     # just what you've applied to
python3 cli.py list --company stripe
python3 cli.py list --all                # include postings that have come down

python3 cli.py status 5ff0 applied       # ids can be any unique prefix
python3 cli.py status 5ff0 interview
python3 cli.py note   5ff0 "referred by Sam"
python3 cli.py show   5ff0 --open        # detail, and open in browser

python3 cli.py stats                     # funnel summary
```

Statuses: `new`, `saved`, `applied`, `interview`, `offer`, `rejected`, `ignored`.

Everything lives in `jobs.db` (SQLite) — back it up, or open it with any SQLite
browser if you'd rather work in a spreadsheet.

---

## Companies

`companies.json` holds the ~200 boards being polled. Every entry was verified
against the live API.

```bash
python3 cli.py add "Company Name" greenhouse their-board-token
python3 cli.py disable stripe        # stop polling one
python3 cli.py verify                # check every board still responds
python3 cli.py verify --prune        # and drop the dead ones
python3 cli.py health                # which boards have been failing
```

To find a board token, open a company's careers page and look at the URL of an
actual posting:

| ATS | URL looks like | token |
|---|---|---|
| Greenhouse | `job-boards.greenhouse.io/**stripe**/jobs/123` | `stripe` |
| Lever | `jobs.lever.co/**binance**/uuid` | `binance` |
| Ashby | `jobs.ashbyhq.com/**ramp**/uuid` | `ramp` |
| Workday | `**salesforce**.**wd12**.myworkdayjobs.com/**External_Career_Site**` | `salesforce:wd12:External_Career_Site` |

### The Simplify feed

Google, Meta, Microsoft, NVIDIA, TikTok and other companies run their own career
sites with no public API. Those are covered by one entry in `companies.json`
pointing at the [SimplifyJobs internship list](https://github.com/SimplifyJobs/Summer2027-Internships),
a large community-maintained feed updated continuously.

When the summer cycle rolls over, update that entry's board from
`Summer2027-Internships` to the following year's repo.

Postings that appear both there and on a company's own ATS are deduplicated by
company + title, so you only get alerted once.

`add` verifies the board before saving it, so a wrong guess fails loudly.

---

## What gets matched

A posting alerts you if the title reads as product management **and** as an
internship **and** the location is US/Canada (or unstated).

Deliberately excluded: product **marketing**, product **design**, product
**engineering**, and senior roles. Titles containing "internal" or
"international" don't count as internships.

Locations outside the US/Canada are filtered out, but a bare "Remote" with no
country is kept — better one extra glance than a missed posting.

Tune any of this in `pmintern/match.py`. To see what the filter is doing without
sending anything:

```bash
python3 cli.py scan --dry-run --verbose
```

---

## Notes

- A full scan of all 203 boards takes about 5 seconds.
- These are the companies' own public job board APIs — no scraping, no blocking,
  and postings show up here before they reach LinkedIn or Indeed aggregators.
- LinkedIn and Indeed are deliberately not used: both prohibit scraping and block
  it aggressively.
- Postings that disappear from a board are marked closed rather than deleted, so
  your application history survives.
