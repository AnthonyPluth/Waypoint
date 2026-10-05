"""Travel stats: what a person, or the household, has flown, stayed and driven, over the trips the viewer can see."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from ...domain import stats
from ...storage import db
from ...storage import settings_keys as sk
from ..common import ApiError
from ..contract import DistanceUnit, DistanceUnitBody, Stats
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
    return {"person": person_id, "year": year_n, "distance_unit": _unit(conn), **found}


def _unit(conn) -> Literal["mi", "km"]:
    return "km" if db.get_setting(conn, sk.DISTANCE_UNIT) == "km" else "mi"


def api_distance_unit(conn, _q, _b) -> DistanceUnit:
    """GET /api/distance-unit: miles unless the household chose kilometres."""
    return {"distance_unit": _unit(conn)}


def api_distance_unit_save(conn, _q, body: DistanceUnitBody) -> DistanceUnit:
    """POST /api/distance-unit: the household's unit for distances on the Stats page, "mi" or "km"."""
    unit = body.get("distance_unit")
    if unit not in ("mi", "km"):
        raise ApiError("Choose miles or kilometres")
    db.set_setting(conn, sk.DISTANCE_UNIT, unit)
    return {"distance_unit": unit}
