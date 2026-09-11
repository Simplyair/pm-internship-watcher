"""Career sites that publish a plain URL sitemap with the job title in the slug.

Some Radancy-style sites (TELUS) expose only a `<urlset>` sitemap, not the RSS
feed Scotiabank serves. The job pages themselves are JavaScript-rendered, but
the URL carries everything needed to filter:

    /job/Toronto-Manager-Area-Sales-ON-M5J-2V5/601253817/
         ^city  ^title              ^prov ^postal   ^id

Titles recovered this way are approximate -- hyphens become spaces and the city
stays glued to the front -- but they are accurate enough to match against, and
every alert carries the real link. The board token is the sitemap URL.
"""
from __future__ import annotations

import re
import urllib.parse

from ..http import get_text
from ..models import Job

LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.S)
# Two shapes in the wild:
#   TELUS: /job/Toronto-Manager-Area-Sales-ON-M5J-2V5/601253817/
#   RBI:   /job/R3306/Sr-Director-Software-Engineering-Burger-King
JOB_RE = re.compile(r"/job/([^/]+)/(\d{4,})/?$")
JOB_RE_ID_FIRST = re.compile(r"/job/([A-Z]*\d{3,}[A-Z0-9]*)/([^/]+)/?$")
# Some slugs name the country instead of a province code.
COUNTRY_RE = re.compile(r"\b(canada|united states|usa|us)\b", re.I)
# ...and some name only a city ("Undergraduate Summer Internship Program Toronto").
CA_CITY_RE = re.compile(
    r"\b(toronto|vancouver|montreal|montr[eé]al|ottawa|waterloo|kitchener|calgary|"
    r"edmonton|mississauga|burnaby|halifax|winnipeg|victoria|markham|oakville|"
    r"quebec city|qu[eé]bec)\b", re.I)
PROVINCE = ("ON QC BC AB MB SK NS NB NL PE YT NT NU").split()
STATE = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
         "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV "
         "WI WY DC").split()
# trailing "-ON" or "-ON-M5J-2V5"
TAIL_RE = re.compile(
    r"[\s-](" + "|".join(PROVINCE + STATE) + r")(?:[\s-][A-Z0-9]{3}[\s-]?[A-Z0-9]{3})?\s*$"
)


def fetch(board: str, company: str) -> list[Job]:
    body = get_text(board, timeout=60)
    jobs = []
    for loc in LOC_RE.findall(body):
        url = loc.replace("&amp;", "&").strip()
        path = urllib.parse.urlparse(url).path
        match = JOB_RE.search(path)
        if match:
            slug, external_id = match.group(1), match.group(2)
        else:
            match = JOB_RE_ID_FIRST.search(path)
            if not match:
                continue
            external_id, slug = match.group(1), match.group(2)
        text = urllib.parse.unquote(slug).replace("&amp;", "&").replace("-", " ").strip()

        location = ""
        tail = TAIL_RE.search(text)
        if tail:
            code = tail.group(1)
            location = (f"{code}, Canada" if code in PROVINCE else f"{code}, USA")
            text = text[: tail.start()].strip()
        else:
            # No province code; fall back to a country named in the slug.
            country = COUNTRY_RE.search(text)
            city = CA_CITY_RE.search(text)
            if country:
                location = ("Canada" if country.group(1).lower() == "canada"
                            else "United States")
            elif city:
                location = f"{city.group(1).title()}, Canada"

        jobs.append(Job(source="jobsitemap", company=company, board=board,
                        external_id=external_id, title=text,
                        location=location, url=url))
    return jobs
