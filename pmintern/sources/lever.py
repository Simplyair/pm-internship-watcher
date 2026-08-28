"""Lever public postings API."""
from __future__ import annotations

from datetime import datetime, timezone

from ..http import FetchError, get_json
from ..models import Job

API = "https://api.lever.co/v0/postings/{board}?mode=json"


def fetch(board: str, company: str) -> list[Job]:
    data = get_json(API.format(board=board))
    # Lever answers 200 with {"ok": false} for boards that do not exist.
    if isinstance(data, dict):
        raise FetchError(f"lever board {board!r}: {data.get('error', 'unexpected response')}")
    jobs = []
    for item in data:
        categories = item.get("categories") or {}
        locations = categories.get("allLocations") or []
        if not locations and categories.get("location"):
            locations = [categories["location"]]
        posted = ""
        created = item.get("createdAt")
        if isinstance(created, (int, float)):
            posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
        jobs.append(Job(
            source="lever",
            company=company,
            board=board,
            external_id=str(item.get("id", "")),
            title=(item.get("text") or "").strip(),
            location=" / ".join(str(loc) for loc in locations if loc),
            url=item.get("hostedUrl") or item.get("applyUrl") or "",
            posted_at=posted,
            department=categories.get("department") or "",
            extra={"commitment": categories.get("commitment") or ""},
        ))
    return jobs
