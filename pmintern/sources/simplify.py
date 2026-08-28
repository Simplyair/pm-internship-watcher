"""SimplifyJobs community internship list.

A large, continuously updated public listing that covers companies running
their own career sites (Google, Meta, Amazon, Microsoft, Apple, NVIDIA),
which the ATS adapters cannot reach. The `board` value selects the repo.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..http import get_json
from ..models import Job

FEED = ("https://raw.githubusercontent.com/SimplifyJobs/"
        "{board}/dev/.github/scripts/listings.json")


def fetch(board: str, company: str) -> list[Job]:
    data = get_json(FEED.format(board=board), timeout=45)
    jobs = []
    for item in data:
        # The feed keeps historical rows; only alert on live ones.
        if not item.get("active") or not item.get("is_visible", True):
            continue
        posted = ""
        stamp = item.get("date_posted")
        if isinstance(stamp, (int, float)) and stamp > 0:
            posted = datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()
        jobs.append(Job(
            source="simplify",
            company=(item.get("company_name") or "").strip(),
            board=board,
            external_id=str(item.get("id", "")),
            title=(item.get("title") or "").strip(),
            location=", ".join(item.get("locations") or []),
            url=item.get("url") or "",
            posted_at=posted,
            department=item.get("category") or "",
            extra={"terms": item.get("terms") or [],
                   "sponsorship": item.get("sponsorship") or ""},
        ))
    return jobs
