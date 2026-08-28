"""Workday-hosted career sites (Salesforce, NVIDIA, and many large employers).

The board token is "tenant:wdHost:siteName", e.g. "salesforce:wd12:External_Career_Site",
taken from the careers URL https://<tenant>.<wdHost>.myworkdayjobs.com/<siteName>.
"""
from __future__ import annotations

import re

from ..http import FetchError, post_json
from ..models import Job

API = "https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
PUBLIC = "https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{path}"

PAGE = 20
MAX_PAGES = 8          # 160 postings per search term is plenty for internships
SEARCH_TERMS = ("intern", "product")


def _parse(board: str) -> tuple[str, str, str]:
    parts = board.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"workday board must be 'tenant:wdHost:site', got {board!r}")
    return parts[0], parts[1], parts[2]


def _location_from_path(path: str) -> str:
    """Workday's list payload often says '2 Locations'; the path has the real one."""
    match = re.match(r"^/job/([^/]+)/", path or "")
    if not match:
        return ""
    return match.group(1).replace("---", ", ").replace("--", "-").replace("-", " ").strip()


def fetch(board: str, company: str) -> list[Job]:
    tenant, wd, site = _parse(board)
    url = API.format(tenant=tenant, wd=wd, site=site)
    seen: dict[str, Job] = {}

    for term in SEARCH_TERMS:
        for page in range(MAX_PAGES):
            payload = {"appliedFacets": {}, "limit": PAGE,
                       "offset": page * PAGE, "searchText": term}
            data = post_json(url, payload, timeout=30)
            if not isinstance(data, dict) or "jobPostings" not in data:
                raise FetchError(f"workday {board}: unexpected response")
            postings = data.get("jobPostings") or []
            for item in postings:
                path = item.get("externalPath") or ""
                job_id = (item.get("bulletFields") or [path])[0] or path
                if job_id in seen:
                    continue
                location = item.get("locationsText") or ""
                if not location or re.match(r"^\d+\s+Location", location):
                    location = _location_from_path(path) or location
                seen[job_id] = Job(
                    source="workday",
                    company=company,
                    board=board,
                    external_id=str(job_id),
                    title=(item.get("title") or "").strip(),
                    location=location.strip(),
                    url=PUBLIC.format(tenant=tenant, wd=wd, site=site, path=path),
                    extra={"postedOn": item.get("postedOn") or ""},
                )
            if len(postings) < PAGE:
                break
    return list(seen.values())
