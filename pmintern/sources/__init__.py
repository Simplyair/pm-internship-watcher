"""Job board adapters. Each exposes fetch(board, company) -> list[Job]."""
from __future__ import annotations

from . import ashby, greenhouse, lever, simplify, workday

ADAPTERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "simplify": simplify.fetch,
    "workday": workday.fetch,
}


def fetch(source: str, board: str, company: str):
    try:
        adapter = ADAPTERS[source]
    except KeyError:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(ADAPTERS)}")
    return adapter(board, company)
