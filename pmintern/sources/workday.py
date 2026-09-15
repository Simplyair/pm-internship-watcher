"""Workday-hosted career sites (Salesforce, NVIDIA, and many large employers).

The board token is "tenant:wdHost:siteName", e.g. "salesforce:wd12:External_Career_Site",
taken from the careers URL https://<tenant>.<wdHost>.myworkdayjobs.com/<siteName>.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from ..http import FetchError, post_json
from ..models import Job

API = "https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
PUBLIC = "https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{path}"

PAGE = 20
# Searched server-side, then filtered locally. Only internship-shaped terms:
# a broad "product" search pulled every full-time product role on large boards
# (Loblaw: 317 postings fetched to find 17 internships, 21 seconds).
# (term, max pages)
SEARCH_TERMS = (
    ("intern", 12),
    ("co-op", 6),
    ("rotational", 2),
    ("associate product manager", 2),
    ("new grad", 2),
)
# Workday ranks by relevance but scatters matches, so a fixed small page cap
# loses recall (RTX: 47 internships found with deep paging, 20 with 3 pages).
# Instead page until a whole page contains nothing early-career, then stop.
# Word boundaries matter: a bare "intern" also matches "Internal Audit" and
# "International", which kept every page of RBC's global board looking relevant
# and paged it for 90 seconds.
RELEVANT = re.compile(
    r"\bintern(?:ship)?s?\b|\bco-?op\b|\brotational\b|\bnew grad|\bgraduate\b"
    r"|\bassociate product\b|\bapprentice|\bstudent\b",
    re.I)


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


def _page(url: str, term: str, page: int) -> list:
    payload = {"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE, "searchText": term}
    data = post_json(url, payload, timeout=30)
    if not isinstance(data, dict) or "jobPostings" not in data:
        raise FetchError("workday: unexpected response")
    return data


def fetch(board: str, company: str) -> list[Job]:
    tenant, wd, site = _parse(board)
    url = API.format(tenant=tenant, wd=wd, site=site)
    seen: dict[str, Job] = {}

    def add(items):
        for item in items:
            path = item.get("externalPath") or ""
            job_id = (item.get("bulletFields") or [path])[0] or path
            if job_id in seen:
                continue
            location = item.get("locationsText") or ""
            if not location or re.match(r"^\d+\s+Location", location):
                location = _location_from_path(path) or location
            seen[job_id] = Job(
                source="workday", company=company, board=board,
                external_id=str(job_id), title=(item.get("title") or "").strip(),
                location=location.strip(),
                url=PUBLIC.format(tenant=tenant, wd=wd, site=site, path=path),
                extra={"postedOn": item.get("postedOn") or ""},
            )

    for term, max_pages in SEARCH_TERMS:
        first = _page(url, term, 0)
        postings = first.get("jobPostings") or []
        add(postings)
        total = int(first.get("total") or 0)
        pages = min(max_pages, -(-total // PAGE))
        if pages <= 1 or not any(RELEVANT.search(i.get("title") or "") for i in postings):
            continue
        # The first response states the total, so the remaining pages are known
        # up front and can be fetched concurrently. Serial paging took ~90s on
        # RBC's boards, which hold 70+ internships each.
        with ThreadPoolExecutor(max_workers=4) as pool:
            for data in pool.map(lambda n: _page(url, term, n), range(1, pages)):
                add(data.get("jobPostings") or [])
    return list(seen.values())
