"""Oracle Cloud HCM recruiting sites (American Express, Fortinet, Definity...).

A large employer platform that the board adapters never covered, costing ~51
postings in the historical data alone. Vanity domains such as
careers.americanexpress.com redirect to the real tenant, so the board token is
"<tenant host>:<site number>", e.g. "egug.fa.us2.oraclecloud.com:CX_1".
"""
from __future__ import annotations

import os

from ..http import get_json
from ..models import Job

API = ("https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
       "?onlyData=true&expand=requisitionList.secondaryLocations"
       "&finder=findReqs;siteNumber={site},keyword={keyword},limit={limit},offset={offset}")
PAGE = 200
MAX_PAGES = 3
# These sites are huge (AutoZone lists 12,000 requisitions), so search
# server-side for early-career wording instead of enumerating everything.
FAST = os.environ.get("PMINTERN_FAST") == "1"
KEYWORDS = (("intern", "co-op") if FAST
            else ("intern", "co-op", "campus", "rotational", "graduate"))
MAX_PAGES_FAST = 1


def _parse(board: str) -> tuple[str, str]:
    host, _, site = board.partition(":")
    if not host or not site:
        raise ValueError(f"oraclehcm board must be 'host:siteNumber', got {board!r}")
    return host, site


def fetch(board: str, company: str) -> list[Job]:
    host, site = _parse(board)
    jobs: dict[str, Job] = {}
    pages = MAX_PAGES_FAST if FAST else MAX_PAGES
    for keyword in KEYWORDS:
      for page in range(pages):
        data = get_json(API.format(host=host, site=site, keyword=keyword,
                                   limit=PAGE, offset=page * PAGE), timeout=40)
        block = (data.get("items") or [{}])[0]
        items = block.get("requisitionList") or []
        for item in items:
            job_id = str(item.get("Id") or "")
            if not job_id or job_id in jobs:
                continue
            locations = [item.get("PrimaryLocation") or ""]
            for secondary in item.get("secondaryLocations") or []:
                name = secondary.get("LocationName") or secondary.get("Name")
                if name:
                    locations.append(name)
            jobs[job_id] = Job(
                source="oraclehcm", company=company, board=board,
                external_id=job_id,
                title=(item.get("Title") or "").strip(),
                location=" / ".join(dict.fromkeys(x for x in locations if x)),
                url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}",
                posted_at=(item.get("PostedDate") or ""),
            )
        if len(items) < PAGE:
            break
    return list(jobs.values())
