"""Watch individual job pages that cannot be discovered through any board.

Some employers (Google, Dayforce) render a job's own page server-side but gate
or omit the listing, so the page can be read once you have its URL even though
it can never be found by scanning. This polls those URLs and alerts the moment
a posting flips from "not yet open" to open.

Configured in watched_urls.json; state is kept in the meta table so it survives
between runs and in CI.
"""
from __future__ import annotations

import hashlib
import html
import json
import re

from . import store
from .config import ROOT
from .http import FetchError, get_text

CONFIG_PATH = ROOT / "watched_urls.json"


def load() -> list[dict]:
    if not CONFIG_PATH.exists():
        return []
    return [w for w in json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if w.get("enabled", True)]


def visible_text(page: str) -> str:
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def state_of(text: str, watch: dict) -> str:
    """'open', 'closed', or 'unknown' for one fetched page."""
    low = text.lower()
    gone = [p.lower() for p in watch.get("open_when_gone", [])]
    present = [p.lower() for p in watch.get("open_when_present", [])]
    if gone and any(p in low for p in gone):
        return "closed"          # the "not yet accepting" notice is still up
    if present and any(p in low for p in present):
        return "open"
    if gone:
        return "open"            # the gate sentence is gone
    return "unknown"


def _key(url: str) -> str:
    return "urlwatch:" + hashlib.sha1(url.encode()).hexdigest()[:16]


def check(conn, watch: dict) -> tuple[str, str, str]:
    """Return (state, previous_state, detail). Never raises for a fetch failure."""
    key = _key(watch["url"])
    previous = store.get_meta(conn, key, "")
    try:
        text = visible_text(get_text(watch["url"], timeout=45))
    except FetchError as exc:
        return "error", previous, str(exc)[:120]

    state = state_of(text, watch)
    title = ""
    match = re.search(r"^(.{0,110}?)\s+—\s+Google Careers", text)
    if match:
        title = match.group(1)
    if state != previous:
        store.set_meta(conn, key, state)
    return state, previous, title


def message(watch: dict, title: str) -> str:
    name = html.escape(watch.get("name") or watch["url"])
    lines = ["\U0001F6A8 <b>IT'S OPEN</b>", f"<b>{name}</b>"]
    if title:
        lines.append(html.escape(title))
    lines.append(f'\n<a href="{html.escape(watch["url"])}">Apply now</a>')
    return "\n".join(lines)
