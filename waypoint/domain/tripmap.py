from __future__ import annotations

from typing import TypedDict

from sqlalchemy import select

from ..storage import db
from ..storage.models import Airport
from . import stats, trips
from .visibility import Viewer


class AirportPoint(TypedDict):
    code: str
    city: str
    latitude: float
    longitude: float


class CityPoint(TypedDict):
    city: str
    latitude: float
    longitude: float


class Places(TypedDict):
    airports: list[AirportPoint]
    cities: list[CityPoint]


def _names(segment: trips.SegmentOut) -> set[str]:
    named = [segment["origin"], segment["destination"], *(port["name"] for port in segment["itinerary"])]
    wanted = {name.strip().lower() for name in named if name and name.strip()}
    return wanted | {name.split(",")[0].strip() for name in wanted if "," in name}


def places(conn: db.Connection, viewer: Viewer, trip_id: int) -> Places | None:
    trip = trips.get(conn, viewer, trip_id)
    if trip is None:
        return None
    live = [s for s in trip["segments"] if s["status"] != "cancelled"]
    codes = {(p or "").strip().upper() for s in live if s["kind"] == "flight" for p in (s["origin"], s["destination"])}
    cities: set[str] = set()
    for s in live:
        if s["kind"] in ("hotel", "car", "train", "cruise"):
            cities |= _names(s)
    found = conn.orm.scalars(select(Airport).where(Airport.code.in_(sorted(codes)))).all()
    points = stats.points_of(conn, stats.countries_of(conn, cities))
    return {
        "airports": [{"code": a.code, "city": a.city, "latitude": a.latitude, "longitude": a.longitude} for a in sorted(found, key=lambda a: a.code)],
        "cities": [{"city": c, "latitude": points[c][0], "longitude": points[c][1]} for c in sorted(points)],
    }
