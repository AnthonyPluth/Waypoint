"""Made-up data for previews and `make verify`: `run.py demo` fills an empty database with it. Nothing here is anyone's
real travel (AGENTS.md, "Personal data in the repo"): names, codes and numbers are invented, airports are real.

There's nothing to add yet: each feature that stores something (people, trips) adds its own sample rows here, so
`make verify` shows it."""
from __future__ import annotations

from ..storage import db


def seed(conn: db.Connection) -> int:
    """Fill an empty database with sample data. Returns how many rows it added."""
    return 0
