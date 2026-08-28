"""SQLite storage: dedupe ledger for alerts + the application tracker."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH
from .models import Job

STATUSES = ("new", "saved", "applied", "interview", "offer", "rejected", "ignored")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key         TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    company     TEXT NOT NULL,
    board       TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    location    TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    posted_at   TEXT NOT NULL DEFAULT '',
    department  TEXT NOT NULL DEFAULT '',
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    closed_at   TEXT NOT NULL DEFAULT '',
    notified_at TEXT NOT NULL DEFAULT '',
    message_id  INTEGER,
    status      TEXT NOT NULL DEFAULT 'new',
    status_at   TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    dupe_key    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_seen    ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_health (
    source     TEXT NOT NULL,
    board      TEXT NOT NULL,
    company    TEXT NOT NULL DEFAULT '',
    last_ok    TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    fails      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, board)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "dupe_key" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN dupe_key TEXT NOT NULL DEFAULT ''")
        conn.commit()
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dupe ON jobs(dupe_key)")
    _backfill_dupe_keys(conn)
    return conn


def _backfill_dupe_keys(conn: sqlite3.Connection) -> None:
    """Fill dupe_key on rows written before cross-source dedupe existed."""
    rows = conn.execute(
        "SELECT key, company, title FROM jobs WHERE dupe_key = ''"
    ).fetchall()
    if not rows:
        return
    for row in rows:
        stub = Job(source="", company=row["company"], board="", external_id="",
                   title=row["title"], location="", url="")
        conn.execute("UPDATE jobs SET dupe_key = ? WHERE key = ?",
                     (stub.dupe_key, row["key"]))
    conn.commit()


def record_seen(conn: sqlite3.Connection, jobs: list[Job]) -> list[Job]:
    """Insert jobs we have never seen. Returns only the genuinely new ones."""
    stamp = now()
    fresh: list[Job] = []
    for job in jobs:
        twin = conn.execute(
            "SELECT key FROM jobs WHERE dupe_key = ? AND key != ? AND closed_at = ''",
            (job.dupe_key, job.key),
        ).fetchone()
        if twin:
            # Same role already tracked from another feed; refresh it, stay quiet.
            conn.execute("UPDATE jobs SET last_seen = ? WHERE key = ?", (stamp, twin["key"]))
            continue
        cur = conn.execute("SELECT 1 FROM jobs WHERE key = ?", (job.key,))
        if cur.fetchone():
            conn.execute(
                "UPDATE jobs SET last_seen = ?, closed_at = '' WHERE key = ?",
                (stamp, job.key),
            )
            continue
        conn.execute(
            """INSERT INTO jobs (key, source, company, board, external_id, title,
                                 location, url, posted_at, department,
                                 first_seen, last_seen, status, status_at, dupe_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'new',?,?)""",
            (job.key, job.source, job.company, job.board, job.external_id,
             job.title, job.location, job.url, job.posted_at, job.department,
             stamp, stamp, stamp, job.dupe_key),
        )
        fresh.append(job)
    conn.commit()
    return fresh


def mark_notified(conn: sqlite3.Connection, key: str, message_id: int | None) -> None:
    conn.execute(
        "UPDATE jobs SET notified_at = ?, message_id = ? WHERE key = ?",
        (now(), message_id, key),
    )
    conn.commit()


def mark_closed(conn: sqlite3.Connection, keys: list[str]) -> int:
    """Flag postings that disappeared from their board (likely filled)."""
    stamp = now()
    changed = 0
    for key in keys:
        cur = conn.execute(
            "UPDATE jobs SET closed_at = ? WHERE key = ? AND closed_at = ''",
            (stamp, key),
        )
        changed += cur.rowcount
    conn.commit()
    return changed


def set_status(conn: sqlite3.Connection, key: str, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    cur = conn.execute(
        "UPDATE jobs SET status = ?, status_at = ? WHERE key = ?",
        (status, now(), key),
    )
    conn.commit()
    return cur.rowcount > 0


def set_notes(conn: sqlite3.Connection, key: str, notes: str) -> bool:
    cur = conn.execute("UPDATE jobs SET notes = ? WHERE key = ?", (notes, key))
    conn.commit()
    return cur.rowcount > 0


def get_job(conn: sqlite3.Connection, key: str):
    cur = conn.execute("SELECT * FROM jobs WHERE key = ?", (key,))
    return cur.fetchone()


def find_jobs(conn, status=None, company=None, include_closed=True, limit=200):
    sql = "SELECT * FROM jobs WHERE 1=1"
    args: list = []
    if status:
        sql += f" AND status IN ({','.join('?' * len(status))})"
        args += list(status)
    if company:
        sql += " AND lower(company) LIKE ?"
        args.append(f"%{company.lower()}%")
    if not include_closed:
        sql += " AND closed_at = ''"
    sql += " ORDER BY first_seen DESC LIMIT ?"
    args.append(limit)
    return conn.execute(sql, args).fetchall()


def keys_for_board(conn, source: str, board: str) -> set[str]:
    rows = conn.execute(
        "SELECT key FROM jobs WHERE source = ? AND board = ? AND closed_at = ''",
        (source, board),
    ).fetchall()
    return {row["key"] for row in rows}


def stats(conn) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
    out = {row["status"]: row["n"] for row in rows}
    out["_total"] = sum(out.values())
    out["_open"] = conn.execute(
        "SELECT COUNT(*) n FROM jobs WHERE closed_at = ''"
    ).fetchone()["n"]
    return out


def get_meta(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
    return row["v"] if row else default


def set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, str(value)),
    )
    conn.commit()


def record_board(conn, source, board, company, ok: bool, error: str = "") -> None:
    conn.execute(
        """INSERT INTO board_health (source, board, company, last_ok, last_error, fails)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(source, board) DO UPDATE SET
             company    = excluded.company,
             last_ok    = CASE WHEN ? THEN excluded.last_ok ELSE board_health.last_ok END,
             last_error = excluded.last_error,
             fails      = CASE WHEN ? THEN 0 ELSE board_health.fails + 1 END""",
        (source, board, company, now() if ok else "", error, 0 if ok else 1, ok, ok),
    )
    conn.commit()


def unhealthy_boards(conn, min_fails: int = 3):
    return conn.execute(
        "SELECT * FROM board_health WHERE fails >= ? ORDER BY fails DESC",
        (min_fails,),
    ).fetchall()
