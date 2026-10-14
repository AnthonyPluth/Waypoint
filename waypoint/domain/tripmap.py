from __future__ import annotations

import math
from typing import TypedDict, cast

from sqlalchemy import select

from ..storage import db, roads, states
from ..storage.geocode import Precision
from ..storage.models import Airport, Segment
from . import home, stats, trips
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
    home: home.HomePoint | None
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
MIN_RETRACE_SHARE = 0.5


def _drive(point: roads.Point, other: roads.Point) -> roads.Route | None:
    straight = roads.miles_between(point, other)
    if straight < MIN_ROAD_TRIP_MILES:
        return None
    found = roads.highways().route(point, other)
    if found is None or found.miles > MAX_DETOUR * straight:
        return None
    return found


def _section(line: roads.Route, point: roads.Point, other: roads.Point) -> roads.Route | None:
    if len(line.marks) != len(line.points):
        return None
    a, b = roads.locate(line.points, point), roads.locate(line.points, other)
    if a is None or b is None or max(a.gap, b.gap) > roads.MAX_LINK_MILES:
        return None
    forward = (a.index, a.share) <= (b.index, b.share)
    low, high = (a, b) if forward else (b, a)
    inner = line.points[low.index + 1:high.index + 1]
    walk = [low.point, *inner, high.point]
    marks = [line.marks[low.index + 1], *line.marks[low.index + 1:high.index + 1], line.marks[high.index + 1]]
    if not forward:
        walk, marks = walk[::-1], [marks[-1], *marks[:0:-1]]
    kept = [k for k in range(len(walk)) if k == 0 or walk[k] != walk[k - 1]]
    points = [walk[k] for k in kept]
    names = [marks[k] for k in kept]
    if len(names) > 1:
        names[0] = names[1]
    runs = [(names[k], roads.miles_between(points[k - 1], points[k])) for k in range(1, len(points))]
    miles = sum(miles for _, miles in runs)
    if miles <= 0 or miles < MIN_RETRACE_SHARE * roads.miles_between(point, other):
        return None
    return roads.Route(points, roads.long_runs(runs), miles, a.gap, b.gap, names)


def _retrace(followed: list[roads.Route], point: roads.Point, other: roads.Point) -> roads.Route | None:
    sections = [found for line in followed if (found := _section(line, point, other)) is not None]
    return min(sections, key=lambda r: r.start_link_miles + r.end_link_miles, default=None)


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
    followed: list[roads.Route] = []
    for first, second in _pairs(live, located):
        found = _retrace(followed, located[first], located[second])
        if found is None:
            found = _drive(located[first], located[second])
            if found is not None:
                followed.append(found)
        if found is not None:
            legs.append({"from_segment_id": first, "to_segment_id": second, "refs": found.refs, "points": _round(found.points)})
    nearby = roads.highways().near([line.points for line in followed]) if followed else []
    return {"legs": legs, "interstates": [{"ref": ref, "points": _round(line)} for ref, line in nearby]}


Layout = tuple[float, float]

PHONE_MAP: Layout = (600, 640)
WIDE_MAP: Layout = (960, 520)
MAP_PADDING: Layout = (100, 76)
MIN_MAP_SPAN = 10.0
VIEW_MARGIN = 1.1
ARC_STEPS = 24
POLE_LIMIT = 85.0


def _arc(a: roads.Point, b: roads.Point) -> list[roads.Point]:
    (lat1, lon1), (lat2, lon2) = (math.radians(a[0]), math.radians(a[1])), (math.radians(b[0]), math.radians(b[1]))
    start = (math.cos(lat1) * math.cos(lon1), math.cos(lat1) * math.sin(lon1), math.sin(lat1))
    end = (math.cos(lat2) * math.cos(lon2), math.cos(lat2) * math.sin(lon2), math.sin(lat2))
    angle = math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(start, end, strict=True)))))
    if angle < 1e-9 or math.pi - angle < 1e-9:
        return [a, b]
    out: list[roads.Point] = []
    for n in range(ARC_STEPS + 1):
        t = n / ARC_STEPS
        wa, wb = math.sin((1 - t) * angle) / math.sin(angle), math.sin(t * angle) / math.sin(angle)
        x, y, z = (wa * u + wb * v for u, v in zip(start, end, strict=True))
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out


def _reach(south: float, west: float, north: float, east: float, layout: Layout) -> tuple[float, float]:
    width, height = layout
    fit_w, fit_h = width - 2 * MAP_PADDING[0], height - 2 * MAP_PADDING[1]
    shrink = max(0.3, math.cos(math.radians((south + north) / 2)))
    across = max(east - west, MIN_MAP_SPAN) * shrink
    down = max(north - south, MIN_MAP_SPAN)
    per_degree = min(fit_w / across, fit_h / down)
    return width / per_degree / shrink, height / per_degree


def map_extent(waypoints: list[roads.Point], legs: list[RoadLeg], flights: list[tuple[roads.Point, roads.Point]]) -> states.Extent | None:
    seen = list(waypoints)
    seen += [(lat, lon) for leg in legs for lat, lon in leg["points"]]
    for a, b in flights:
        seen += _arc(a, b)
    if not seen:
        return None
    south, north = min(p[0] for p in seen), max(p[0] for p in seen)
    west, east = min(p[1] for p in seen), max(p[1] for p in seen)
    reaches = [_reach(south, west, north, east, layout) for layout in (PHONE_MAP, WIDE_MAP)]
    half_lon = max(r[0] for r in reaches) / 2 * VIEW_MARGIN
    half_lat = max(r[1] for r in reaches) / 2 * VIEW_MARGIN
    lat, lon = (south + north) / 2, (west + east) / 2
    return (max(-POLE_LIMIT, min(south, lat - half_lat)), max(-180.0, min(west, lon - half_lon)),
            min(POLE_LIMIT, max(north, lat + half_lat)), min(180.0, max(east, lon + half_lon)))


def state_lines(waypoints: list[roads.Point], legs: list[RoadLeg], flights: list[tuple[roads.Point, roads.Point]] | None = None) -> list[StateLine]:
    extent = map_extent(waypoints, legs, flights or [])
    if extent is None:
        return []
    return [{"points": _round(line)} for line in states.state_lines().within(extent)]


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
    airport_at = {a.code: (a.latitude, a.longitude) for a in found}
    flights = [(airport_at[o], airport_at[d]) for s in live if s["kind"] == "flight"
               for o, d in [((s["origin"] or "").strip().upper(), (s["destination"] or "").strip().upper())] if o in airport_at and d in airport_at]
    at_home = home.point(conn)
    road_trip = not any(s["kind"] in BREAKING_KINDS for s in live)
    waypoints = [(a.latitude, a.longitude) for a in found] + list(points.values()) + list(located.values())
    if at_home and road_trip:
        waypoints.append((at_home["latitude"], at_home["longitude"]))
    return {
        "home": at_home,
        "airports": [{"code": a.code, "city": a.city, "latitude": a.latitude, "longitude": a.longitude} for a in sorted(found, key=lambda a: a.code)],
        "cities": [{"city": c, "latitude": points[c][0], "longitude": points[c][1]} for c in sorted(points)],
        "stays": [{"segment_id": g.id, "latitude": g.latitude, "longitude": g.longitude, "precision": cast(Precision, g.geo_precision or "city")}
                  for g in stored if g.latitude is not None and g.longitude is not None],
        "roads": drives,
        "boundaries": state_lines(waypoints, drives["legs"], flights),
    }
