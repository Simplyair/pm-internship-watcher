"""Decide whether a posting is a US/Canada product-management internship.

Two independent gates: the title must read as a PM internship, and the
location must plausibly be in the US or Canada. Ambiguity resolves toward
including the job -- a false positive costs one glance, a false negative
costs the posting.
"""
from __future__ import annotations

import re

# --- title: is this product management? ------------------------------------

# Unambiguous product-management wording. If one of these is present the role
# is PM, regardless of any weaker "product" words elsewhere in the title
# (e.g. "Product Management Intern - Product Innovation").
STRONG_PM = (
    r"\bproduct manage(?:r|ment|rs)\b",
    r"\bassociate product manager\b",
    r"\bproduct owner\b",
    r"\bapm\b",
    r"\bpm\b",
    r"\btpm\b",
)

# A bare "Product Intern" / "Product Internship" is how many startups label a
# PM internship. Requires the two words adjacent, so "Product Development
# Intern" and "Product Operations Intern" do not qualify.
SOFT_PM = (
    r"\bproduct intern(?:ship)?\b",
    r"\bproduct co-?op\b",
)

# Product-adjacent roles: not product management proper, but the same career
# track and worth seeing for named companies. "Program Manager" matters most --
# at Microsoft that title *is* the product role.
PRODUCT_ADJACENT = (
    r"\bprogram manage(?:r|ment)\b",
    r"\btechnical program manager\b",
    r"\bbusiness program manager\b",
    r"\bproduct operations?\b",
    r"\bproduct analyst\b",
    r"\bproduct analytics\b",
    r"\bproduct strategy\b",
    r"\bproduct marketing\b",
    r"\bproduct planner\b",
    r"\bproduct specialist\b",
    r"\bproduct development\b",
)

# Roles that contain "product" but are not product management. Checked first,
# so these veto even a strong match ("Product Marketing Manager Intern").
NOT_PM_HARD = (
    r"\bproduct marketing\b",
    r"\bproduct design(?:er)?\b",
    r"\bproduct engineer",
    r"\bproduct development engineer",
    r"\bproduct security\b",
    r"\bproduct support\b",
    r"\bproduct counsel\b",
    r"\bproduct quality\b",
    r"\bproduction\b",
    r"\b(?:full ?stack|front ?end|back ?end|hardware|mechanical|electrical|systems?|"
    r"test|quality|validation|manufacturing|process|packaging|firmware|asic|silicon)"
    r"\s+engineer",
    r"\bengineering intern",
    r"\bengineer intern",
    r"\bsoftware engineer",
    r"\bdata scientist\b",
    r"\bdata science\b",
    r"\bdata engineer\b",
    r"\bui/ux\b",
    r"\bux design",
    r"\bgraphic design",
    r"\brecruit",
    r"\bsales\b",
)

# --- title: is this an internship? -----------------------------------------

INTERN_PATTERNS = (
    r"\bintern\b",
    r"\binterns\b",
    r"\binternship\b",
    r"\bco-?op\b",
    r"\bsummer 20\d\d\b",
    r"\bfall 20\d\d\b",
    r"\bwinter 20\d\d\b",
    r"\bspring 20\d\d\b",
    r"\bundergraduate\b",
)  # deliberately no bare "student": it matches "PM, Student Loans" etc.

# Seniority markers that rule out an internship even if "intern" appears
# somewhere (e.g. "Manager, Internship Programs").
SENIOR_PATTERNS = (
    r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"\bprincipal\b",
    r"\bdirector\b", r"\bhead of\b", r"\bvp\b", r"\bvice president\b",
    r"\blead\b", r"\bmanager, intern", r"\bintern(?:ship)? program manager\b",
)

# --- location: US / Canada -------------------------------------------------

# Full names only. These were once .split() into single words, which made
# "island" (from "prince edward island") match "Long Island City" and
# "mexico" (from "new mexico") match "Mexico City". Phrases, not tokens.
US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
]

US_ABBREV = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()

CA_PROVINCES = [
    "ontario", "quebec", "québec", "alberta", "manitoba", "saskatchewan",
    "british columbia", "nova scotia", "new brunswick", "newfoundland",
    "labrador", "prince edward island", "yukon", "nunavut",
    "northwest territories",
]

CA_ABBREV = "ON QC BC AB MB SK NS NB NL PE PEI YT NT NU".split()

US_CITIES = (
    "new york san francisco seattle austin boston chicago los angeles "
    "san jose mountain view palo alto menlo park sunnyvale santa clara "
    "cupertino redmond bellevue denver boulder atlanta miami dallas houston "
    "philadelphia pittsburgh detroit minneapolis phoenix portland san diego "
    "washington dc arlington bay area silicon valley nyc sf"
).split(", ") + [
    "new york", "san francisco", "los angeles", "san jose", "mountain view",
    "palo alto", "menlo park", "santa clara", "san diego", "bay area",
    "silicon valley", "salt lake city", "kansas city", "ann arbor",
]

CA_CITIES = [
    "toronto", "vancouver", "montreal", "montréal", "ottawa", "waterloo",
    "kitchener", "calgary", "edmonton", "mississauga", "burnaby", "victoria",
    "halifax", "winnipeg", "quebec city", "markham", "hamilton", "london, on",
]

# Countries that mean "not North America" unless a US/CA token also appears.
FOREIGN = [
    "united kingdom", "london, uk", "london, england", "england", "scotland",
    "ireland", "dublin", "germany", "berlin", "munich", "france", "paris",
    "spain", "madrid", "barcelona", "portugal", "lisbon", "netherlands",
    "amsterdam", "belgium", "brussels", "switzerland", "zurich", "geneva",
    "sweden", "stockholm", "norway", "oslo", "denmark", "copenhagen",
    "finland", "helsinki", "poland", "warsaw", "krakow", "czech", "prague",
    "austria", "vienna", "italy", "milan", "rome", "greece", "athens",
    "romania", "bucharest", "hungary", "budapest", "ukraine", "israel",
    "tel aviv", "india", "bangalore", "bengaluru", "hyderabad", "mumbai",
    "delhi", "gurgaon", "pune", "chennai", "noida", "china", "beijing",
    "shanghai", "shenzhen", "hong kong", "taiwan", "taipei", "japan",
    "tokyo", "korea", "seoul", "singapore", "malaysia", "kuala lumpur",
    "indonesia", "jakarta", "philippines", "manila", "vietnam", "hanoi",
    "thailand", "bangkok", "australia", "sydney", "melbourne", "new zealand",
    "brazil", "sao paulo", "são paulo", "mexico city", "argentina",
    "buenos aires", "chile", "santiago", "colombia", "bogota", "peru",
    "lima", "south africa", "cape town", "nigeria", "lagos", "kenya",
    "nairobi", "egypt", "cairo", "dubai", "abu dhabi", "uae", "saudi",
    "riyadh", "qatar", "doha", "turkey", "istanbul", "emea", "apac",
    "latam", "asia", "europe",
]

NA_PHRASES = [
    "united states", "u.s.", "u.s.a", "usa", "us-remote", "remote - us",
    "remote (us)", "remote, us", "canada", "canadian", "north america",
    "remote - canada", "remote (canada)", "us or canada",
]


def _matches_any(text: str, patterns) -> bool:
    return any(re.search(p, text) for p in patterns)


def _contains_word(text: str, words) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def is_pm_title(title: str) -> bool:
    """True only for product *management* roles.

    Three tiers: a disqualifying word rules the title out; explicit product
    management wording rules it in; a bare "Product Intern" also counts, since
    that is how many startups label the same job. Everything else -- product
    development, product operations, product analyst -- is not PM.
    """
    low = title.lower()
    if _matches_any(low, NOT_PM_HARD):
        return False
    if _matches_any(low, STRONG_PM):
        return True
    return _matches_any(low, SOFT_PM)


def is_internship_title(title: str) -> bool:
    """True if the title reads as an internship/co-op and not a senior role."""
    low = title.lower()
    if _matches_any(low, SENIOR_PATTERNS):
        return False
    return _matches_any(low, INTERN_PATTERNS)


def location_region(location: str) -> str:
    """Classify a location string as 'us', 'ca', 'na', 'foreign', or 'unknown'."""
    if not location or not location.strip():
        return "unknown"
    low = location.lower()

    has_ca = (
        "canada" in low
        or _contains_word(low, CA_CITIES)
        or _contains_word(low, CA_PROVINCES)
        or any(re.search(rf",\s*{ab}\b", location) for ab in CA_ABBREV)
    )
    has_us = (
        any(phrase in low for phrase in ("united states", "usa", "u.s."))
        or _contains_word(low, US_CITIES)
        or _contains_word(low, US_STATES)
        or any(re.search(rf",\s*{ab}\b", location) for ab in US_ABBREV)
    )
    if has_us and has_ca:
        return "na"
    if has_ca:
        return "ca"
    if has_us:
        return "us"
    if any(phrase in low for phrase in NA_PHRASES):
        return "na"
    if any(country in low for country in FOREIGN):
        return "foreign"
    if "remote" in low:
        # Bare "Remote" with no country -- usually US-based. Keep it.
        return "unknown"
    return "unknown"


def is_north_america(location: str) -> bool:
    return location_region(location) != "foreign"


def matches(job, *, require_location: bool = True) -> bool:
    """Full filter: a PM internship posted in (or plausibly in) the US/Canada."""
    if not is_pm_title(job.title) or not is_internship_title(job.title):
        return False
    if require_location and not is_north_america(job.location):
        return False
    return True


# The adjacency path has its own, narrower veto. Engineering and design are
# genuinely different tracks, but marketing / operations / analyst ARE the
# adjacency being asked for, so they must not be vetoed here.
NOT_ADJACENT = (
    r"\bproduct engineer",
    r"\bproduct development engineer",
    r"\bproduct design(?:er)?\b",
    r"\bproduct security\b",
    r"\bproduct quality\b",
    r"\bproduct counsel\b",
    r"\bproduction\b",
    r"\b(?:full ?stack|front ?end|back ?end|hardware|mechanical|electrical|systems?|"
    r"test|quality|validation|manufacturing|process|packaging|firmware|asic|silicon)"
    r"\s+engineer",
    r"\bengineering intern",
    r"\bengineer intern",
    r"\bsoftware engineer",
    r"\bdata scientist\b",
    r"\bdata science\b",
    r"\bdata engineer\b",
    r"\bui/ux\b",
    r"\bux design",
    r"\bgraphic design",
    r"\brecruit",
)


def is_adjacent_title(title: str) -> bool:
    """Product management *or* the roles next to it (ops, analyst, program)."""
    low = title.lower()
    if _matches_any(low, NOT_ADJACENT):
        return False
    return (_matches_any(low, STRONG_PM) or _matches_any(low, SOFT_PM)
            or _matches_any(low, PRODUCT_ADJACENT))


def matches_watchlist(job, watchlist) -> bool:
    """Extra, per-company widening layered on top of the default filter.

    Each entry is {"company": ..., "regions": [...], "titles": [...]}.
    With "titles" the entry matches those keywords instead of the
    product-adjacent set -- for programs that carry no product wording at all,
    like RBI's "Generalist" internship. Strictly additive: never removes a
    default match.
    """
    if not watchlist:
        return False
    company = (job.company or "").lower()
    for entry in watchlist:
        name = (entry.get("company") or "").lower()
        if not name or name not in company:
            continue
        if not is_internship_title(job.title):
            continue
        keywords = entry.get("titles")
        if keywords:
            low = job.title.lower()
            if not any(k.lower() in low for k in keywords):
                continue
        elif not is_adjacent_title(job.title):
            continue
        regions = entry.get("regions")
        if regions and location_region(job.location) not in set(regions) | {"na"}:
            continue
        return True
    return False
