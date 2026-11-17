from __future__ import annotations

import json
import math
from typing import Any, TypedDict

from sqlalchemy import and_, or_, select

from ..storage import db
from ..storage.models import DrivingRoute
from . import tripmap
from .visibility import Viewer, visible_trips

SCALE = 10_000
MIN_POINTS = 2
MAX_POINTS = 10_000
MAX_PATH_BYTES = 400_000
MAX_DRIVES = 30
REPLACE_AFTER_SECONDS = 30 * 24 * 3600
ENDPOINT_REACH_DEGREES = 0.02
STOP_REACH_DEGREES = 0.001
PATH_DECIMALS = 6
MAX_TRIPS = 12
CARD_POINTS = 300


class Invalid(Exception):
    pass


class Place(TypedDict):
    latitude: float
    longitude: float


class CachedRoute(TypedDict):
    start: Place
    end: Place
    path: list[list[float]]


class TripRoutes(TypedDict):
    trip_id: int
    routes: list[CachedRoute]


Drive = tuple[float, float, float, float]


def _number(value: Any, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or not low <= value <= high:
        raise Invalid(f"The {what} must be a number between {low:g} and {high:g}")
    return float(value)


def _latitude(value: Any, what: str) -> float:
    return _number(value, -90, 90, what)


def _longitude(value: Any, what: str) -> float:
    return _number(value, -180, 180, what)


def place(value: Any, what: str) -> Place:
    if not isinstance(value, dict):
        raise Invalid(f"Send the {what} as latitude and longitude")
    return {"latitude": _latitude(value.get("latitude"), f"{what} latitude"), "longitude": _longitude(value.get("longitude"), f"{what} longitude")}


def drive_of(start: Any, end: Any) -> Drive:
    a, b = place(start, "start"), place(end, "end")
    if (round(a["latitude"] * SCALE), round(a["longitude"] * SCALE)) == (round(b["latitude"] * SCALE), round(b["longitude"] * SCALE)):
        raise Invalid("A drive needs two different places")
    return a["latitude"], a["longitude"], b["latitude"], b["longitude"]


def parse_drive(text: str) -> Drive:
    parts = text.split(",")
    if len(parts) != 4:
        raise Invalid("Send each drive as four numbers: start latitude, start longitude, end latitude, end longitude")
    try:
        lat1, lon1, lat2, lon2 = (float(p) for p in parts)
    except ValueError:
        raise Invalid("Send each drive as four numbers: start latitude, start longitude, end latitude, end longitude") from None
    return drive_of({"latitude": lat1, "longitude": lon1}, {"latitude": lat2, "longitude": lon2})


def parse_drives(texts: list[str]) -> list[Drive]:
    if not texts:
        raise Invalid("Send the drives to look up")
    if len(texts) > MAX_DRIVES:
        raise Invalid(f"Ask for at most {MAX_DRIVES} drives at a time")
    return [parse_drive(t) for t in texts]


def _key(drive: Drive) -> tuple[int, int, int, int]:
    lat1, lon1, lat2, lon2 = drive
    return round(lat1 * SCALE), round(lon1 * SCALE), round(lat2 * SCALE), round(lon2 * SCALE)


def clean_path(raw: Any, drive: Drive) -> list[list[float]]:
    if not isinstance(raw, list) or not MIN_POINTS <= len(raw) <= MAX_POINTS:
        raise Invalid(f"A route has {MIN_POINTS} to {MAX_POINTS} points")
    out: list[list[float]] = []
    for point in raw:
        if not isinstance(point, list) or len(point) != 2:
            raise Invalid("Each point of a route is a latitude and a longitude")
        out.append([round(_latitude(point[0], "route latitude"), PATH_DECIMALS), round(_longitude(point[1], "route longitude"), PATH_DECIMALS)])
    lat1, lon1, lat2, lon2 = drive
    if not _near(out[0], lat1, lon1, ENDPOINT_REACH_DEGREES) or not _near(out[-1], lat2, lon2, ENDPOINT_REACH_DEGREES):
        raise Invalid("The route doesn't start and end at the drive's places")
    if len(json.dumps(out, separators=(",", ":"))) > MAX_PATH_BYTES:
        raise Invalid("That route is too large")
    return out


def _near(point: list[float], latitude: float, longitude: float, reach: float) -> bool:
    return abs(point[0] - latitude) <= reach and abs(point[1] - longitude) <= reach


def _stops(places: tripmap.Places) -> list[tuple[float, float]]:
    found: list[tuple[float, float]] = [(a["latitude"], a["longitude"]) for a in places["airports"]]
    found += [(c["latitude"], c["longitude"]) for c in places["cities"]]
    found += [(s["latitude"], s["longitude"]) for s in places["stays"]]
    if places["home"] is not None:
        found.append((places["home"]["latitude"], places["home"]["longitude"]))
    return found


def _on_trip(stops: list[tuple[float, float]], drive: Drive) -> bool:
    lat1, lon1, lat2, lon2 = drive
    return (any(_near([lat, lon], lat1, lon1, STOP_REACH_DEGREES) for lat, lon in stops)
            and any(_near([lat, lon], lat2, lon2, STOP_REACH_DEGREES) for lat, lon in stops))


def cached(conn: db.Connection, viewer: Viewer, trip_id: int, texts: list[str], now: float) -> list[CachedRoute] | None:
    places = tripmap.places(conn, viewer, trip_id)
    if places is None:
        return None
    drives = parse_drives(texts)
    stops = _stops(places)
    wanted = {_key(d): d for d in drives if _on_trip(stops, d)}
    if not wanted:
        return []
    match = or_(*(and_(DrivingRoute.trip_id == trip_id, DrivingRoute.from_lat == a, DrivingRoute.from_lon == b, DrivingRoute.to_lat == c, DrivingRoute.to_lon == d) for a, b, c, d in wanted))
    out: list[CachedRoute] = []
    for row in conn.orm.scalars(select(DrivingRoute).where(match, DrivingRoute.stored > now - REPLACE_AFTER_SECONDS).order_by(DrivingRoute.from_lat, DrivingRoute.from_lon, DrivingRoute.to_lat, DrivingRoute.to_lon)):
        lat1, lon1, lat2, lon2 = wanted[(row.from_lat, row.from_lon, row.to_lat, row.to_lon)]
        out.append({"start": {"latitude": lat1, "longitude": lon1}, "end": {"latitude": lat2, "longitude": lon2}, "path": json.loads(row.path)})
    return out


def store(conn: db.Connection, viewer: Viewer, trip_id: int, start: Any, end: Any, raw_path: Any, now: float) -> bool | None:
    places = tripmap.places(conn, viewer, trip_id)
    if places is None:
        return None
    drive = drive_of(start, end)
    if not _on_trip(_stops(places), drive):
        raise Invalid("That isn't a drive of this trip")
    path = clean_path(raw_path, drive)
    from_lat, from_lon, to_lat, to_lon = _key(drive)
    have = conn.orm.get(DrivingRoute, (trip_id, from_lat, from_lon, to_lat, to_lon))
    if have is not None and now - have.stored < REPLACE_AFTER_SECONDS:
        return False
    db.upsert(conn, DrivingRoute, {"trip_id": trip_id, "from_lat": from_lat, "from_lon": from_lon, "to_lat": to_lat, "to_lon": to_lon,
                                   "path": json.dumps(path, separators=(",", ":")), "stored": now}, key=["trip_id", "from_lat", "from_lon", "to_lat", "to_lon"])
    return True


def parse_trips(texts: list[str]) -> list[int]:
    if not texts:
        raise Invalid("Send the trips to look up")
    if len(texts) > MAX_TRIPS:
        raise Invalid(f"Ask for at most {MAX_TRIPS} trips at a time")
    ids: list[int] = []
    for text in texts:
        if not text.isascii() or not text.isdigit() or len(text) > 12:
            raise Invalid("Send each trip as its number")
        ids.append(int(text))
    return ids


def _thin(path: list[list[float]], limit: int = CARD_POINTS) -> list[list[float]]:
    if len(path) <= limit:
        return path
    return [path[round(i * (len(path) - 1) / (limit - 1))] for i in range(limit)]


def cached_for_trips(conn: db.Connection, viewer: Viewer, texts: list[str], now: float) -> list[TripRoutes]:
    asked = set(parse_trips(texts))
    seen = sorted(t.id for t in visible_trips(conn, viewer) if t.id in asked)
    if not seen:
        return []
    rows = conn.orm.scalars(select(DrivingRoute).where(DrivingRoute.trip_id.in_(seen), DrivingRoute.stored > now - REPLACE_AFTER_SECONDS)
                            .order_by(DrivingRoute.trip_id, DrivingRoute.from_lat, DrivingRoute.from_lon, DrivingRoute.to_lat, DrivingRoute.to_lon))
    out: dict[int, TripRoutes] = {}
    for row in rows:
        found = out.setdefault(row.trip_id, {"trip_id": row.trip_id, "routes": []})
        found["routes"].append({"start": {"latitude": row.from_lat / SCALE, "longitude": row.from_lon / SCALE},
                                "end": {"latitude": row.to_lat / SCALE, "longitude": row.to_lon / SCALE}, "path": _thin(json.loads(row.path))})
    return list(out.values())
