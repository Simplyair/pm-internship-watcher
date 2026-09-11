"""Scan every configured board, store what is new, and alert on it."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import store, telegram
from .config import COMPANIES_PATH
from .http import FetchError
from .match import location_region, matches, matches_watchlist
from .models import Job
from .sources import fetch

MAX_ALERTS_PER_CYCLE = 25   # beyond this, the rest go out as one digest
SEND_DELAY = 1.2            # seconds between sends; Telegram throttles ~1/s


@dataclass
class ScanResult:
    new_jobs: list
    matched: int = 0
    all_matched: list = None
    scanned_boards: int = 0
    failed_boards: list = None
    closed: int = 0
    seeded: bool = False


def load_companies(path=COMPANIES_PATH) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [c for c in doc.get("companies", []) if c.get("enabled", True)]


def load_watchlist(path=COMPANIES_PATH) -> list[dict]:
    """Per-company widening rules; see companies.json."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("watchlist", [])


def _scan_board(company: dict) -> tuple[dict, list[Job] | None, str]:
    try:
        jobs = fetch(company["source"], company["board"], company["name"])
        return company, jobs, ""
    except (FetchError, ValueError) as exc:
        return company, None, str(exc)[:200]


def scan(conn, *, workers: int = 12, require_location: bool = True,
         verbose: bool = False, record: bool = True) -> ScanResult:
    companies = load_companies()
    watchlist = load_watchlist()
    was_empty = store.stats(conn)["_total"] == 0
    failed: list[tuple[str, str]] = []
    all_matched: list[Job] = []
    seen_by_board: dict[tuple[str, str], set] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for company, jobs, error in pool.map(_scan_board, companies):
            source, board = company["source"], company["board"]
            if jobs is None:
                failed.append((company["name"], error))
                store.record_board(conn, source, board, company["name"], False, error)
                if verbose:
                    print(f"  ! {company['name']}: {error}")
                continue
            store.record_board(conn, source, board, company["name"], True)
            hits = [j for j in jobs
                    if matches(j, require_location=require_location)
                    or matches_watchlist(j, watchlist)]
            seen_by_board[(source, board)] = {j.key for j in hits}
            all_matched.extend(hits)
            if verbose and hits:
                for hit in hits:
                    print(f"  + {hit}")

    if not record:
        # Dry runs must not mark postings as seen, or the real run goes silent.
        rows = conn.execute("SELECT key, dupe_key FROM jobs WHERE closed_at = ''").fetchall()
        known = {row["key"] for row in rows}
        known_dupes = {row["dupe_key"] for row in rows if row["dupe_key"]}
        preview, seen_dupes = [], set()
        for job in all_matched:
            if job.key in known or job.dupe_key in known_dupes or job.dupe_key in seen_dupes:
                continue
            seen_dupes.add(job.dupe_key)
            preview.append(job)
        return ScanResult(new_jobs=preview, all_matched=all_matched,
                          matched=len(all_matched),
                          scanned_boards=len(companies) - len(failed),
                          failed_boards=failed, closed=0, seeded=not known)

    new_jobs = store.record_seen(conn, all_matched)

    # Anything we previously tracked on a board we just scanned successfully,
    # but did not see this time, has come down.
    closed_keys = []
    for (source, board), live_keys in seen_by_board.items():
        for key in store.keys_for_board(conn, source, board) - live_keys:
            closed_keys.append(key)
    closed = store.mark_closed(conn, closed_keys)

    return ScanResult(new_jobs=new_jobs, all_matched=all_matched,
                      matched=len(all_matched),
                      scanned_boards=len(companies) - len(failed),
                      failed_boards=failed, closed=closed, seeded=was_empty)


def notify(conn, bot: telegram.Telegram, result: ScanResult, dry_run: bool = False,
           digest: bool = False) -> int:
    """Send alerts for new jobs. First run sends one digest instead of a flood."""
    jobs = result.new_jobs
    if not jobs:
        return 0

    if result.seeded or digest:
        header = (f"<b>Tracker started</b>\n{len(jobs)} open PM internships found. "
                  f"You will get an individual alert for each new one from now on.")
        if digest and not result.seeded:
            header = (f"<b>{len(jobs)} postings added</b>\nFrom newly added sources. "
                      f"Individual alerts resume for anything new after this.")
        text = _digest(jobs, header=header)
        if dry_run:
            print(text)
        else:
            bot.send(text)
            for job in jobs:
                store.mark_notified(conn, job.key, None)
        return len(jobs)

    # Canadian roles go out first so they sit at the top of the notification
    # stack rather than buried under US postings.
    jobs = sorted(jobs, key=lambda j: 0 if location_region(j.location) in ("ca", "na") else 1)

    sent = 0
    for job in jobs[:MAX_ALERTS_PER_CYCLE]:
        text = telegram.job_message(job, location_region(job.location))
        markup = telegram.job_keyboard(job.key, job.url)
        if dry_run:
            print(f"\n--- would send ---\n{text}")
            sent += 1
            continue
        try:
            res = bot.send(text, reply_markup=markup)
            store.mark_notified(conn, job.key, res.get("message_id"))
            sent += 1
        except FetchError as exc:
            print(f"  ! telegram send failed for {job}: {exc}")
        time.sleep(SEND_DELAY)

    overflow = jobs[MAX_ALERTS_PER_CYCLE:]
    if overflow:
        text = _digest(overflow, header=f"<b>+{len(overflow)} more new postings</b>")
        if dry_run:
            print(text)
        else:
            bot.send(text)
            for job in overflow:
                store.mark_notified(conn, job.key, None)
        sent += len(overflow)
    return sent


def _digest(jobs: list[Job], header: str) -> str:
    ordered = sorted(jobs, key=lambda j: 0 if location_region(j.location) in ("ca", "na") else 1)
    canada = sum(1 for j in ordered if location_region(j.location) in ("ca", "na"))
    lines = [header]
    if canada:
        lines.append(f"\U0001F1E8\U0001F1E6 {canada} in Canada, listed first")
    lines.append("")
    for job in ordered[:40]:
        flag = "\U0001F1E8\U0001F1E6 " if location_region(job.location) in ("ca", "na") else ""
        label = telegram.esc(f"{job.company} - {job.title}")
        lines.append(f'- {flag}<a href="{telegram.esc(job.url)}">{label}</a>'
                     if job.url else f"- {flag}{label}")
    if len(jobs) > 40:
        lines.append(f"\n...and {len(jobs) - 40} more. Run: python3 cli.py list")
    return "\n".join(lines)


def process_callbacks(conn, bot: telegram.Telegram) -> int:
    """Apply Applied/Save/Ignore taps from Telegram to the tracker."""
    offset = int(store.get_meta(conn, "tg_offset", "0") or 0)
    try:
        updates = bot.get_updates(offset=offset)
    except FetchError as exc:
        print(f"  ! could not read Telegram updates: {exc}")
        return 0

    handled = 0
    for update in updates:
        offset = max(offset, update["update_id"] + 1)
        query = update.get("callback_query")
        if not query:
            continue
        data = query.get("data", "")
        bot.answer_callback(query["id"])
        if not data.startswith("s:"):
            continue
        _, status, key = (data.split(":", 2) + ["", ""])[:3]
        if status not in store.STATUSES or not store.get_job(conn, key):
            continue
        store.set_status(conn, key, status)
        row = store.get_job(conn, key)
        message = query.get("message") or {}
        if message.get("message_id"):
            bot.edit_markup(message["message_id"],
                            telegram.decided_keyboard(status, row["url"]))
        bot.answer_callback(query["id"], f"Marked {status}")
        handled += 1

    store.set_meta(conn, "tg_offset", offset)
    return handled
