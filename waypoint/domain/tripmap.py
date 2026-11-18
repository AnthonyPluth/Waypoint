from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple, TypedDict, cast

from sqlalchemy import select

from ..storage import db
from ..storage.geocode import Precision
from ..storage.models import Airport, Segment
from . import home, stats, trips
from .visibility import Viewer

Point = tuple[float, float]


class AirportPoint(TypedDict):
    code: str
    city: str
    latitude: float
    longitude: float


class CityPoint(TypedDict):
    city: str
    latitude: float
    longitude: float


class StayPoint(TypedDict):
    segment_id: int
    latitude: float
    longitude: float
    precision: Precision


class Places(TypedDict):
    home: home.HomePoint | None
    airports: list[AirportPoint]
    cities: list[CityPoint]
    stays: list[StayPoint]


def _names(segment: trips.SegmentOut) -> set[str]:
    named = [segment["origin"], segment["destination"], *(port["name"] for port in segment["itinerary"])]
    wanted = {name.strip().lower() for name in named if name and name.strip()}
    return wanted | {name.split(",")[0].strip() for name in wanted if "," in name}


class _Located(NamedTuple):
    live: list[trips.SegmentOut]
    airports: Sequence[Airport]
    stays: Sequence[Segment]
    cities: dict[str, Point]
    home: home.HomePoint | None


def _locate(conn: db.Connection, viewer: Viewer, trip_id: int) -> _Located | None:
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
    stored = conn.orm.scalars(select(Segment).where(Segment.id.in_([s["id"] for s in live if s["kind"] != "flight"]),
                                                    Segment.latitude.is_not(None), Segment.longitude.is_not(None)).order_by(Segment.id)).all()
    points = stats.points_of(conn, stats.countries_of(conn, cities))
    return _Located(live, found, stored, points, home.point(conn))


def stop_points(conn: db.Connection, viewer: Viewer, trip_id: int) -> list[Point] | None:
    at = _locate(conn, viewer, trip_id)
    if at is None:
        return None
    found: list[Point] = [(a.latitude, a.longitude) for a in sorted(at.airports, key=lambda a: a.code)]
    found += [at.cities[c] for c in sorted(at.cities)]
    found += [(g.latitude, g.longitude) for g in at.stays if g.latitude is not None and g.longitude is not None]
    if at.home is not None:
        found.append((at.home["latitude"], at.home["longitude"]))
    return found


def places(conn: db.Connection, viewer: Viewer, trip_id: int) -> Places | None:
    at = _locate(conn, viewer, trip_id)
    if at is None:
        return None
    return {
        "home": at.home,
        "airports": [{"code": a.code, "city": a.city, "latitude": a.latitude, "longitude": a.longitude} for a in sorted(at.airports, key=lambda a: a.code)],
        "cities": [{"city": c, "latitude": at.cities[c][0], "longitude": at.cities[c][1]} for c in sorted(at.cities)],
        "stays": [{"segment_id": g.id, "latitude": g.latitude, "longitude": g.longitude, "precision": cast(Precision, g.geo_precision or "city")}
                  for g in at.stays if g.latitude is not None and g.longitude is not None],
    }
