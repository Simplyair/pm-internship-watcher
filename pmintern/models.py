"""The Job record shared across sources, matching, storage, and alerting."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class Job:
    source: str           # "greenhouse" | "lever" | "ashby"
    company: str          # display name
    board: str            # board token used to fetch it
    external_id: str      # id as given by the ATS
    title: str
    location: str
    url: str
    posted_at: str = ""   # ISO8601 if the board tells us, else ""
    department: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable dedupe key. Survives title edits and URL tracking params."""
        raw = f"{self.source}:{self.board}:{self.external_id}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def __str__(self) -> str:
        return f"{self.company} — {self.title} ({self.location})"
