from __future__ import annotations

from typing import TypedDict, cast

from sqlalchemy import select

from ..storage import db, roads, states
from ..storage.geocode import Precision
from ..storage.models import Airport, Segment
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


class StayPoint(TypedDict):
    segment_id: int
    latitude: float
    longitude: float
    precision: Precision


class RoadLeg(TypedDict):
    from_segment_id: int
    to_segment_id: int
    refs: list[str]
    points: list[list[float]]


class RoadLine(TypedDict):
    ref: str
    points: list[list[float]]


class Roads(TypedDict):
    legs: list[RoadLeg]
    interstates: list[RoadLine]


class StateLine(TypedDict):
    points: list[list[float]]


class Places(TypedDict):
    airports: list[AirportPoint]
    cities: list[CityPoint]
    stays: list[StayPoint]
    roads: Roads
    boundaries: list[StateLine]


def _names(segment: trips.SegmentOut) -> set[str]:
    named = [segment["origin"], segment["destination"], *(port["name"] for port in segment["itinerary"])]
    wanted = {name.strip().lower() for name in named if name and name.strip()}
    return wanted | {name.split(",")[0].strip() for name in wanted if "," in name}


MIN_ROAD_TRIP_MILES = 50.0
MAX_DETOUR = 2.5
ROAD_KINDS = ("hotel", "car")
BREAKING_KINDS = ("flight", "train", "cruise")


def _drive(point: roads.Point, other: roads.Point) -> roads.Route | None:
    straight = roads.miles_between(point, other)
    if straight < MIN_ROAD_TRIP_MILES:
        return None
    found = roads.interstates().route(point, other)
    if found is None or found.miles > MAX_DETOUR * straight:
        return None
    return found


def _pairs(live: list[trips.SegmentOut], located: dict[int, roads.Point]) -> list[tuple[int, int]]:
    ordered = sorted(live, key=lambda s: (trips.instant(s["start_local"], s["start_zone"]), s["id"]))
    pairs: list[tuple[int, int]] = []
    last: int | None = None
    for s in ordered:
        if s["kind"] in BREAKING_KINDS:
            last = None
        elif s["kind"] in ROAD_KINDS:
            if s["id"] not in located:
                last = None
                continue
            if last is not None:
                pairs.append((last, s["id"]))
            last = s["id"]
    return pairs


def _round(points: list[roads.Point]) -> list[list[float]]:
    return [[round(lat, 3), round(lon, 3)] for lat, lon in points]


def road_legs(live: list[trips.SegmentOut], located: dict[int, roads.Point]) -> Roads:
    legs: list[RoadLeg] = []
    followed: list[list[roads.Point]] = []
    for first, second in _pairs(live, located):
        found = _drive(located[first], located[second])
        if found is not None:
            legs.append({"from_segment_id": first, "to_segment_id": second, "refs": found.refs, "points": _round(found.points)})
            followed.append(found.points)
    nearby = roads.interstates().near(followed) if followed else []
    return {"legs": legs, "interstates": [{"ref": ref, "points": _round(line)} for ref, line in nearby]}


def state_lines(waypoints: list[roads.Point], legs: list[RoadLeg]) -> list[StateLine]:
    paths: list[list[roads.Point]] = [[p] for p in waypoints]
    paths += [[(lat, lon) for lat, lon in leg["points"]] for leg in legs]
    if not paths:
        return []
    return [{"points": _round(line)} for line in states.state_lines().near(paths)]


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
    stored = conn.orm.scalars(select(Segment).where(Segment.id.in_([s["id"] for s in live if s["kind"] != "flight"]),
                                                    Segment.latitude.is_not(None), Segment.longitude.is_not(None)).order_by(Segment.id)).all()
    located = {g.id: (g.latitude, g.longitude) for g in stored if g.latitude is not None and g.longitude is not None}
    points = stats.points_of(conn, stats.countries_of(conn, cities))
    drives = road_legs(live, located)
    waypoints = [(a.latitude, a.longitude) for a in found] + list(points.values()) + list(located.values())
    return {
        "airports": [{"code": a.code, "city": a.city, "latitude": a.latitude, "longitude": a.longitude} for a in sorted(found, key=lambda a: a.code)],
        "cities": [{"city": c, "latitude": points[c][0], "longitude": points[c][1]} for c in sorted(points)],
        "stays": [{"segment_id": g.id, "latitude": g.latitude, "longitude": g.longitude, "precision": cast(Precision, g.geo_precision or "city")}
                  for g in stored if g.latitude is not None and g.longitude is not None],
        "roads": drives,
        "boundaries": state_lines(waypoints, drives["legs"]),
    }
