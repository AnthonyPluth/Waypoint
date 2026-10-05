"""Travel stats: what a person, or the household, has flown, stayed and driven, over the trips the viewer can see."""
from __future__ import annotations

from datetime import UTC, datetime

from ...domain import stats
from ...storage import db
from ...storage import settings_keys as sk
from ..common import ApiError
from ..contract import Stats
from .trips import viewer

YEARS = range(1900, 3000)


def api_stats(conn, q, _b) -> Stats:
    """GET /api/stats?person=<id|all>&year=<yyyy|all>: both default to all. A person who doesn't exist is a 404."""
    person, year = q.get("person", ["all"])[0], q.get("year", ["all"])[0]   # (a query’s values are lists)
    person_id = None
    if person != "all":
        if not (person.isascii() and person.isdigit() and len(person) < 10):
            raise ApiError("Send person as a person’s id or all")
        person_id = int(person)
    year_n = None
    if year != "all":
        if not (year.isascii() and year.isdigit() and int(year) in YEARS):
            raise ApiError("Send year as a four-digit year or all")
        year_n = int(year)
    found = stats.compute(conn, viewer(conn), person_id, year_n, datetime.now(UTC))
    if found is None:
        raise ApiError("No such person", 404)
    km = db.get_setting(conn, sk.DISTANCE_UNIT) == "km"
    return {"person": person_id, "year": year_n, "distance_unit": "km" if km else "mi", **found}
