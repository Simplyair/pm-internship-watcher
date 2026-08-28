"""Ashby public job board API."""
from __future__ import annotations

from ..http import get_json
from ..models import Job

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def fetch(board: str, company: str) -> list[Job]:
    data = get_json(API.format(board=board))
    jobs = []
    for item in data.get("jobs", []):
        if item.get("isListed") is False:
            continue
        locations = [item.get("location") or ""]
        for secondary in item.get("secondaryLocations") or []:
            name = secondary.get("location")
            if name:
                locations.append(name)
        jobs.append(Job(
            source="ashby",
            company=company,
            board=board,
            external_id=str(item.get("id", "")),
            title=(item.get("title") or "").strip(),
            location=" / ".join(dict.fromkeys(loc for loc in locations if loc)),
            url=item.get("jobUrl") or item.get("applyUrl") or "",
            posted_at=item.get("publishedAt") or "",
            department=item.get("department") or "",
            extra={"employmentType": item.get("employmentType") or ""},
        ))
    return jobs
