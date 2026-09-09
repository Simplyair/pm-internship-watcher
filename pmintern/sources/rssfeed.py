"""Google-Jobs-style RSS feeds published by employers' own career sites.

Large banks and retailers often run bespoke career sites with no JSON API but
do publish an RSS feed for Google Jobs. These feeds are big -- Scotiabank's is
45MB uncompressed -- and serve `Cache-Control: no-store` with no ETag, so
conditional requests are impossible.

Rather than re-download that on every 5-minute scan, the *parsed* result is
cached and refreshed at most once an hour. Bank co-op postings do not appear
minute-to-minute, and the cache directory is carried between CI runs.

The board token is the feed URL.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from ..config import ROOT
from ..http import FetchError, get_text
from ..models import Job

CACHE_DIR = ROOT / ".cache"
MAX_AGE_SECONDS = 60 * 60          # refresh the feed at most hourly

ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
# Career-site titles carry the location in a trailing parenthesis:
#   "Velocity - Product Management Internship - Winter 2027 (Toronto, ON, CA)"
LOCATION_RE = re.compile(r"\(([^()]{2,80})\)\s*$")
TAG_RE = {}


def _tag(block: str, name: str) -> str:
    pattern = TAG_RE.setdefault(
        name, re.compile(rf"<{name}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{name}>", re.S))
    match = pattern.search(block)
    return match.group(1).strip() if match else ""


def _cache_path(url: str):
    return CACHE_DIR / f"rss-{hashlib.sha1(url.encode()).hexdigest()[:12]}.json"


def _parse(body: str, board: str, company: str) -> list[Job]:
    jobs = []
    for block in ITEM_RE.findall(body):
        raw_title = _tag(block, "title")
        link = _tag(block, "link")
        if not raw_title or not link:
            continue

        location, title = "", raw_title
        match = LOCATION_RE.search(raw_title)
        if match:
            location = match.group(1).strip()
            title = raw_title[: match.start()].strip(" -–")

        id_match = re.search(r"/(\d{4,})/?(?:\?|$)", link)
        external_id = id_match.group(1) if id_match else \
            hashlib.sha1(link.encode()).hexdigest()[:12]

        jobs.append(Job(source="rss", company=company, board=board,
                        external_id=external_id, title=title,
                        location=location, url=link))
    return jobs


def _to_cache(jobs: list[Job]) -> str:
    return json.dumps([{"i": j.external_id, "t": j.title,
                        "l": j.location, "u": j.url} for j in jobs])


def _from_cache(text: str, board: str, company: str) -> list[Job]:
    return [Job(source="rss", company=company, board=board, external_id=d["i"],
                title=d["t"], location=d["l"], url=d["u"])
            for d in json.loads(text)]


def fetch(board: str, company: str) -> list[Job]:
    cache = _cache_path(board)
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < MAX_AGE_SECONDS
    if fresh:
        return _from_cache(cache.read_text(encoding="utf-8"), board, company)

    try:
        jobs = _parse(get_text(board), board, company)
    except FetchError:
        # A stale copy beats dropping the source entirely for one bad fetch.
        if cache.exists():
            return _from_cache(cache.read_text(encoding="utf-8"), board, company)
        raise

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(_to_cache(jobs), encoding="utf-8")
    return jobs
