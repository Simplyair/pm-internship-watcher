"""Greenhouse public job board API."""
from __future__ import annotations

from ..http import get_json
from ..models import Job

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def fetch(board: str, company: str) -> list[Job]:
    data = get_json(API.format(board=board))
    jobs = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name") or ""
        jobs.append(Job(
            source="greenhouse",
            company=company,
            board=board,
            external_id=str(item.get("id", "")),
            title=(item.get("title") or "").strip(),
            location=location.strip(),
            url=item.get("absolute_url") or "",
            posted_at=item.get("first_published") or item.get("updated_at") or "",
        ))
    return jobs
