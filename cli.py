#!/usr/bin/env python3
"""PM internship watcher + application tracker.

    python3 cli.py scan              one scan, alert on anything new
    python3 cli.py watch             scan forever on POLL_MINUTES
    python3 cli.py list              show tracked postings
    python3 cli.py status <id> applied
    python3 cli.py stats
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser

from pmintern import config, store, telegram
from pmintern.config import COMPANIES_PATH
from pmintern.http import FetchError
from pmintern.match import location_region
from pmintern.runner import notify, process_callbacks, scan
from pmintern.sources import fetch


def bot_from_env(require_chat: bool = True) -> telegram.Telegram:
    token = config.get("TELEGRAM_BOT_TOKEN")
    chat = config.get("TELEGRAM_CHAT_ID")
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    if require_chat and not chat:
        sys.exit("TELEGRAM_CHAT_ID is not set. Message your bot once, then run: python3 cli.py chatid")
    return telegram.Telegram(token, chat)


def resolve_key(conn, prefix: str) -> str:
    """Accept a unique key prefix so you can type 4-6 characters."""
    rows = conn.execute(
        "SELECT key, company, title FROM jobs WHERE key LIKE ?", (prefix + "%",)
    ).fetchall()
    if not rows:
        sys.exit(f"no tracked posting starts with {prefix!r}")
    if len(rows) > 1:
        print(f"{prefix!r} is ambiguous:")
        for row in rows[:10]:
            print(f"  {row['key']}  {row['company']} - {row['title']}")
        sys.exit(1)
    return rows[0]["key"]


# --- commands --------------------------------------------------------------

def cmd_scan(args) -> None:
    conn = store.connect()
    dry = args.dry_run or config.get_bool("DRY_RUN")
    started = time.time()
    result = scan(conn, require_location=not args.any_location, verbose=args.verbose)

    print(f"scanned {result.scanned_boards} boards in {time.time()-started:.0f}s | "
          f"{result.matched} matching postings live | {len(result.new_jobs)} new"
          + (f" | {result.closed} closed" if result.closed else ""))
    if result.failed_boards and args.verbose:
        for name, err in result.failed_boards:
            print(f"  ! {name}: {err}")
    elif result.failed_boards:
        print(f"  ({len(result.failed_boards)} boards unreachable; run `health` for detail)")

    if not result.new_jobs:
        return
    if dry:
        notify(conn, None, result, dry_run=True)  # type: ignore[arg-type]
        print(f"\n[dry run] {len(result.new_jobs)} alert(s) not sent")
        return
    bot = bot_from_env()
    sent = notify(conn, bot, result)
    print(f"sent {sent} alert(s) to Telegram")


def cmd_watch(args) -> None:
    minutes = args.every or config.get_int("POLL_MINUTES", 15)
    conn = store.connect()
    dry = args.dry_run or config.get_bool("DRY_RUN")
    bot = None if dry else bot_from_env()
    print(f"watching {len(json.loads(COMPANIES_PATH.read_text())['companies'])} boards "
          f"every {minutes} min. Ctrl-C to stop.")
    while True:
        try:
            result = scan(conn, require_location=not args.any_location)
            stamp = time.strftime("%H:%M")
            line = (f"[{stamp}] {result.matched} live | {len(result.new_jobs)} new"
                    + (f" | {result.closed} closed" if result.closed else ""))
            if result.new_jobs:
                sent = notify(conn, bot, result, dry_run=dry)
                line += f" | {sent} alerted"
            if bot:
                acted = process_callbacks(conn, bot)
                if acted:
                    line += f" | {acted} triaged"
            print(line, flush=True)
        except KeyboardInterrupt:
            print("\nstopped.")
            return
        except Exception as exc:  # keep the watcher alive across transient faults
            print(f"[{time.strftime('%H:%M')}] scan error: {type(exc).__name__}: {exc}", flush=True)
        try:
            time.sleep(minutes * 60)
        except KeyboardInterrupt:
            print("\nstopped.")
            return


def cmd_list(args) -> None:
    conn = store.connect()
    statuses = args.status.split(",") if args.status else None
    rows = store.find_jobs(conn, status=statuses, company=args.company,
                           include_closed=args.all, limit=args.limit)
    if not rows:
        print("nothing tracked yet — run: python3 cli.py scan")
        return
    print(f"{'id':<8} {'status':<10} {'company':<22} {'title':<44} location")
    print("-" * 110)
    for row in rows:
        closed = " (closed)" if row["closed_at"] else ""
        print(f"{row['key'][:8]:<8} {row['status']:<10} {row['company'][:21]:<22} "
              f"{row['title'][:43]:<44} {row['location'][:24]}{closed}")
    print(f"\n{len(rows)} shown. Mark one: python3 cli.py status <id> applied")


def cmd_status(args) -> None:
    conn = store.connect()
    key = resolve_key(conn, args.id)
    try:
        store.set_status(conn, key, args.new_status)
    except ValueError as exc:
        sys.exit(str(exc))
    row = store.get_job(conn, key)
    print(f"{row['company']} — {row['title']} -> {args.new_status}")


def cmd_note(args) -> None:
    conn = store.connect()
    key = resolve_key(conn, args.id)
    store.set_notes(conn, key, args.text)
    print("noted.")


def cmd_show(args) -> None:
    conn = store.connect()
    row = store.get_job(conn, resolve_key(conn, args.id))
    for field in ("company", "title", "location", "status", "url", "posted_at",
                  "first_seen", "status_at", "closed_at", "source", "notes"):
        if row[field]:
            print(f"{field:<11} {row[field]}")
    if args.open and row["url"]:
        webbrowser.open(row["url"])


def cmd_stats(args) -> None:
    conn = store.connect()
    data = store.stats(conn)
    total, open_n = data.pop("_total"), data.pop("_open")
    if not total:
        print("nothing tracked yet — run: python3 cli.py scan")
        return
    print(f"{total} postings tracked ({open_n} still open)\n")
    for status in store.STATUSES:
        if data.get(status):
            print(f"  {status:<10} {data[status]}")
    applied = sum(data.get(s, 0) for s in ("applied", "interview", "offer", "rejected"))
    if applied:
        print(f"\n  applied to {applied} of {total} seen "
              f"({100*applied/total:.0f}%)")


def cmd_health(args) -> None:
    conn = store.connect()
    rows = conn.execute(
        "SELECT * FROM board_health ORDER BY fails DESC, company"
    ).fetchall()
    broken = [r for r in rows if r["fails"] > 0]
    if not broken:
        print(f"all {len(rows)} boards healthy")
        return
    print(f"{len(broken)} board(s) failing:\n")
    for row in broken:
        print(f"  {row['fails']:>3}x  {row['company'] or row['board']:<24} "
              f"{row['source']:<11} {row['last_error'][:60]}")
    print("\nDrop one with: python3 cli.py disable <board>")


def cmd_verify(args) -> None:
    from concurrent.futures import ThreadPoolExecutor
    doc = json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))
    companies = doc["companies"]

    def probe(company):
        try:
            return company, len(fetch(company["source"], company["board"], company["name"])), ""
        except Exception as exc:
            return company, -1, str(exc)[:70]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(probe, companies))

    dead = [(c, e) for c, n, e in results if n < 0]
    empty = [c for c, n, _ in results if n == 0]
    print(f"{len(results) - len(dead)}/{len(results)} boards responded"
          + (f", {len(empty)} returned zero postings" if empty else ""))
    for company, err in dead:
        print(f"  dead: {company['name']:<24} {company['source']:<11} {err}")
    if dead and args.prune:
        keep = {(c["source"], c["board"]) for c, n, _ in results if n >= 0}
        doc["companies"] = [c for c in companies if (c["source"], c["board"]) in keep]
        COMPANIES_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"pruned {len(dead)} dead board(s) from companies.json")
    elif dead:
        print("\nre-run with --prune to remove them")


def cmd_add(args) -> None:
    doc = json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))
    if any(c["source"] == args.source and c["board"] == args.board for c in doc["companies"]):
        sys.exit(f"{args.source}:{args.board} is already in companies.json")
    try:
        jobs = fetch(args.source, args.board, args.name)
    except Exception as exc:
        sys.exit(f"could not read that board: {exc}")
    doc["companies"].append({"name": args.name, "source": args.source,
                             "board": args.board, "enabled": True})
    doc["companies"].sort(key=lambda c: c["name"].lower())
    COMPANIES_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"added {args.name} ({args.source}:{args.board}) — {len(jobs)} postings on that board")


def cmd_disable(args) -> None:
    doc = json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))
    hits = [c for c in doc["companies"]
            if args.board.lower() in (c["board"].lower(), c["name"].lower())]
    if not hits:
        sys.exit(f"no company matching {args.board!r}")
    for company in hits:
        company["enabled"] = False
        print(f"disabled {company['name']}")
    COMPANIES_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def cmd_setup(args) -> None:
    """Guided first-time setup: verify the token, find the chat id, save it."""
    token = config.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Step 1 is not done yet — your bot token is missing.\n")
        print("  1. Open Telegram and message @BotFather  (https://t.me/BotFather)")
        print("  2. Send:  /newbot   then pick a name and a username ending in 'bot'")
        print("  3. BotFather replies with a long token like 123456789:AAE...")
        print(f"  4. Paste it after TELEGRAM_BOT_TOKEN= in {config.ENV_PATH}")
        print("\nThen run this again:  python3 cli.py setup")
        sys.exit(1)

    try:
        bot = telegram.Telegram(token)
        info = bot.me()
    except FetchError:
        sys.exit("That token was rejected by Telegram. Check for a typo or a missing\n"
                 "character, or ask @BotFather for a new one with /token.")

    username = info.get("username", "")
    print(f"Token works — connected to @{username}\n")

    existing = config.get("TELEGRAM_CHAT_ID")
    if existing and not args.force:
        print(f"Chat id already set ({existing}). Re-run with --force to change it.")
    else:
        print(f"Now open your bot and send it any message (just say hi):")
        print(f"   https://t.me/{username}\n")
        print("Waiting for it", end="", flush=True)
        chat_id, who = _await_first_message(bot, seconds=args.wait)
        print()
        if not chat_id:
            sys.exit(f"\nDid not see a message in {args.wait}s. Open https://t.me/{username}, "
                     "send 'hi',\nthen run: python3 cli.py setup")
        config.set_env_value("TELEGRAM_CHAT_ID", str(chat_id))
        print(f"Got it — message from {who}. Saved chat id {chat_id} to .env\n")
        bot.chat_id = str(chat_id)

    bot.chat_id = config.get("TELEGRAM_CHAT_ID")
    bot.send("<b>PM internship watcher is connected.</b>\n"
             "New product management internships in the US and Canada will show up here.")
    print("Sent a confirmation message — check Telegram.\n")
    print("Setup is done. Next:")
    print("   python3 cli.py scan     send yourself everything open right now")
    print("   ./scripts/install-launchd.sh    keep it running every 15 minutes")


def _await_first_message(bot, seconds: int = 180):
    """Long-poll Telegram until someone messages the bot. Returns (chat_id, name)."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            updates = bot.get_updates(timeout=15)
        except FetchError:
            time.sleep(2)
            print(".", end="", flush=True)
            continue
        for update in updates:
            msg = update.get("message") or {}
            chat = msg.get("chat") or {}
            if chat.get("id"):
                name = chat.get("username") or chat.get("first_name") or chat.get("title") or "you"
                return chat["id"], name
        print(".", end="", flush=True)
    return None, ""


def cmd_chatid(args) -> None:
    bot = bot_from_env(require_chat=False)
    info = bot.me()
    print(f"bot: @{info.get('username')}")
    updates = bot.get_updates()
    chats = {}
    for update in updates:
        msg = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name", "")
    if not chats:
        print("\nNo messages seen yet. Open Telegram, send your bot any message,\n"
              f"then run this again. (Find it at https://t.me/{info.get('username')})")
        return
    print("\nchat id(s) found — put one in .env as TELEGRAM_CHAT_ID:")
    for chat_id, name in chats.items():
        print(f"  {chat_id}   {name}")


def cmd_test(args) -> None:
    bot = bot_from_env()
    info = bot.me()
    bot.send(f"<b>PM internship watcher</b>\nConnected as @{telegram.esc(info.get('username',''))}. "
             f"Alerts will arrive here.")
    print(f"sent a test message as @{info.get('username')} — check Telegram")


def cmd_triage(args) -> None:
    conn = store.connect()
    bot = bot_from_env()
    print(f"applied {process_callbacks(conn, bot)} button tap(s)")


# --- argument parsing ------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="one scan; alert on new postings")
    p.add_argument("--dry-run", action="store_true", help="print alerts instead of sending")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--any-location", action="store_true", help="do not filter to US/Canada")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("watch", help="scan on a loop")
    p.add_argument("--every", type=int, metavar="MIN", help="minutes between scans")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--any-location", action="store_true")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("list", help="show tracked postings")
    p.add_argument("--status", help="comma-separated: new,saved,applied,interview,offer,rejected,ignored")
    p.add_argument("--company")
    p.add_argument("--all", action="store_true", help="include closed postings")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("status", help="set a posting's status")
    p.add_argument("id")
    p.add_argument("new_status", choices=store.STATUSES)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("note", help="attach a note to a posting")
    p.add_argument("id"); p.add_argument("text")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("show", help="full detail for one posting")
    p.add_argument("id"); p.add_argument("--open", action="store_true", help="open in browser")
    p.set_defaults(func=cmd_show)

    sub.add_parser("stats", help="application funnel summary").set_defaults(func=cmd_stats)
    sub.add_parser("health", help="which boards are failing").set_defaults(func=cmd_health)

    p = sub.add_parser("verify", help="check every board still responds")
    p.add_argument("--prune", action="store_true", help="delete dead boards from companies.json")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("add", help="add a company board")
    p.add_argument("name"); p.add_argument("source", choices=["greenhouse", "lever", "ashby"])
    p.add_argument("board")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("disable", help="stop polling a company")
    p.add_argument("board")
    p.set_defaults(func=cmd_disable)

    p = sub.add_parser("setup", help="guided first-time Telegram setup")
    p.add_argument("--wait", type=int, default=180, metavar="SEC",
                   help="how long to wait for your first message")
    p.add_argument("--force", action="store_true", help="re-detect the chat id")
    p.set_defaults(func=cmd_setup)

    sub.add_parser("chatid", help="find your Telegram chat id").set_defaults(func=cmd_chatid)
    sub.add_parser("test", help="send a test Telegram message").set_defaults(func=cmd_test)
    sub.add_parser("triage", help="pull pending button taps from Telegram").set_defaults(func=cmd_triage)
    return parser


def main() -> None:
    config.load_env()
    args = build_parser().parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted.")
    except FetchError as exc:
        sys.exit(f"network error: {exc}")


if __name__ == "__main__":
    main()
