from __future__ import annotations

import hashlib
import itertools
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select

from .. import monitoring
from ..providers import mapkit
from ..storage import db
from ..storage.models import DrivingRoute
from . import driving_routes, home, maps, tripmap, trips
from .visibility import Viewer

HOUSEHOLD = Viewer(None, household=True)
SAME_PLACE_KM = 30.0
EARTH_KM = 6371.0
MAX_PER_RUN = 60
PAUSE_SECONDS = 3.0
Drive = tuple[float, float, float, float]
Key = tuple[int, int, int, int]
Fetch = Callable[[tuple[float, float], tuple[float, float]], list[list[float]] | None]


@dataclass
class Visit:
    name: str
    city: str
    code: str | None
    kind: str
    latitude: float
    longitude: float
    start: str
    end: str
    via: str | None
    exact: bool = False
    rental: bool = False


@dataclass
class Point:
    name: str
    latitude: float
    longitude: float
    kind: str = "place"
    code: str | None = None
    city: str | None = None
    exact: bool = False


def _key(text: str | None) -> str:
    return (text or "").strip().lower()


def _head(text: str) -> str:
    return text.split(",")[0].strip()


def _km(a: Point | Visit, b: Point | Visit) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    half = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b.longitude - a.longitude) / 2) ** 2
    return 2 * math.asin(min(1.0, math.sqrt(half))) * EARTH_KM


def _same_place(a: Point | Visit, b: Point | Visit) -> bool:
    if a.exact and b.exact:
        return _km(a, b) < SAME_PLACE_KM
    return _key(a.name) == _key(b.name) or _km(a, b) < SAME_PLACE_KM


def _same_stop(a: Visit, b: Visit) -> bool:
    if a.kind == "airport" and b.kind == "airport":
        return a.code == b.code
    if a.kind == b.kind or a.kind == "place" or b.kind == "place":
        return _same_place(a, b)
    return False


def _live(trip: trips.TripOut) -> list[trips.SegmentOut]:
    return [s for s in trip["segments"] if s["status"] != "cancelled"]


def _by_countries(trip: trips.TripOut) -> bool:
    live = [s for s in _live(trip) if s["kind"] != "parking"]
    return bool(live) and all(s["kind"] == "visit" for s in live)


def _is_road_trip(trip: trips.TripOut) -> bool:
    return not any(s["kind"] in ("flight", "train", "cruise") for s in _live(trip))


class _Finder:
    def __init__(self, places: tripmap.Places):
        self.airports = {a["code"].upper(): a for a in places["airports"]}
        self.cities = {_key(c["city"]): c for c in places["cities"]}
        self.airport_cities = {_key(a["city"]): a for a in places["airports"]}
        self.stored = {p["segment_id"]: p for p in places["stays"]}

    def airport(self, code: str | None) -> Point | None:
        found = self.airports.get((code or "").strip().upper())
        if found is None:
            return None
        return Point(found["city"], found["latitude"], found["longitude"], "airport", found["code"].upper())

    def city(self, text: str | None) -> Point | None:
        found: Any = None
        for table in (self.cities, self.airport_cities):
            found = table.get(_key(text))
            if found is None:
                found = table.get(_key(_head(text or "")))
            if found is not None:
                break
        return Point(_head(text), found["latitude"], found["longitude"]) if found is not None and text else None

    def stay(self, segment: trips.SegmentOut, text: str | None) -> Point | None:
        found = self.stored.get(segment["id"])
        if found is None:
            return None
        return Point(_head(text or "") or _head(segment["origin"] or "") or "Stay", found["latitude"], found["longitude"], exact=True)


def _visits(trip: trips.TripOut, places: tripmap.Places) -> list[Visit]:
    finder = _Finder(places)
    countries = _by_countries(trip)
    live = [s for s in _live(trip) if s["kind"] != "parking" and (s["kind"] != "visit" or countries)]
    if countries:
        live.sort(key=lambda s: (s["start_local"], s["end_local"], s["id"]))
    else:
        live.sort(key=lambda s: (trips.instant(s["start_local"], s["start_zone"]), s["id"]))
    flies = any(s["kind"] == "flight" for s in live)
    out: list[Visit] = []

    def add(p: Point | None, start: str, end: str, via: str | None, rental: bool = False) -> None:
        if p is not None:
            out.append(Visit(p.name, p.city or p.name, p.code, p.kind, p.latitude, p.longitude, start, end, via, p.exact, rental))

    def first(*found: Point | None) -> Point | None:
        return next((p for p in found if p is not None), None)

    for s in live:
        kind, origin, destination = s["kind"], s["origin"], s["destination"]
        if kind == "flight":
            add(finder.airport(origin), s["start_local"], s["start_local"], None)
            add(finder.airport(destination), s["end_local"], s["end_local"], "flight")
        elif kind == "visit":
            add(finder.stay(s, destination or ""), s["start_local"], s["end_local"], None)
        elif kind == "hotel":
            found = first(finder.stay(s, destination), finder.city(destination))
            if found is not None:
                found = Point(_head(origin or "") or found.name, found.latitude, found.longitude, "stay", None, found.name, found.exact)
            add(found, s["start_local"], s["end_local"], None)
        elif kind == "car":
            if not flies:
                at = destination if destination is not None else origin
                add(first(finder.stay(s, at), finder.city(destination), finder.city(origin)), s["start_local"], s["end_local"], None, True)
        elif kind == "train":
            add(finder.city(origin), s["start_local"], s["start_local"], None)
            add(first(finder.stay(s, destination), finder.city(destination)), s["end_local"], s["end_local"], "train")
        else:
            add(first(finder.stay(s, origin), finder.city(origin)), s["start_local"], s["start_local"], None)
            for port in s["itinerary"]:
                arrive = port.get("arrive_local") or s["start_local"]
                add(finder.city(port["name"]), arrive, port.get("depart_local") or port.get("arrive_local") or s["end_local"], "cruise")
            back = finder.stay(s, destination) if destination and _key(destination) == _key(origin) else None
            add(first(back, finder.city(destination)), s["end_local"], s["end_local"], "cruise")
    return [v for v in out if not v.rental or not any(not o.rental and _same_place(v, o) for o in out)]


def stops_of(trip: trips.TripOut, places: tripmap.Places) -> list[Visit]:
    merged: list[Visit] = []
    for v in _visits(trip, places):
        last = merged[-1] if merged else None
        if last is not None and _same_stop(last, v):
            upgrade = last.kind == "place" and v.kind != "place"
            start, end, via = last.start, last.end, last.via
            if upgrade:
                last.__dict__.update(v.__dict__)
            last.start = start if start < v.start else v.start
            last.end = end if end > v.end else v.end
            last.via = via if via is not None else v.via
        else:
            merged.append(Visit(**v.__dict__))
    home = places["home"]
    if home is not None and merged and _is_road_trip(trip):
        first, last = merged[0], merged[-1]
        at = Visit(home["city"], home["city"], None, "home", home["latitude"], home["longitude"], "", "", None)
        if not _same_place(at, first):
            merged.insert(0, Visit(**{**at.__dict__, "start": first.start, "end": first.start}))
        if not _same_place(at, last):
            merged.append(Visit(**{**at.__dict__, "start": last.end, "end": last.end}))
    return merged


def drives_in(stops: list[Visit]) -> list[Drive]:
    return [(a.latitude, a.longitude, b.latitude, b.longitude) for a, b in itertools.pairwise(stops)
            if b.via is None and (a.latitude != b.latitude or a.longitude != b.longitude)]


def drives_of(trip: trips.TripOut, places: tripmap.Places) -> list[Drive]:
    return drives_in(stops_of(trip, places))


def key_of(drive: Drive) -> Key:
    lat1, lon1, lat2, lon2 = drive
    scale = driving_routes.SCALE
    return round(round(lat1, 4) * scale), round(round(lon1, 4) * scale), round(round(lat2, 4) * scale), round(round(lon2, 4) * scale)


def thin(path: list[list[float]], limit: int = driving_routes.MAX_POINTS) -> list[list[float]]:
    if len(path) <= limit:
        return path
    return [path[round(i * (len(path) - 1) / (limit - 1))] for i in range(limit)]


@dataclass
class Missing:
    trip_id: int
    drive: Drive
    stops: list[tuple[float, float]]


@dataclass
class Memory:
    gave_up: set[Key] = field(default_factory=set)
    settled: dict[int, str] = field(default_factory=dict)


@dataclass
class Outcome:
    fetched: int = 0
    left: bool = False
    stop: bool = False
    refused: bool = False


def _fingerprint(trip: trips.TripOut, at_home: Any) -> str:
    return hashlib.sha256(json.dumps([trip, at_home], sort_keys=True, default=str).encode()).hexdigest()


def missing(conn: db.Connection, today: date, memory: Memory) -> list[Missing]:
    found: list[Missing] = []
    all_trips = [t for t in reversed(trips.listing(conn, HOUSEHOLD)) if t["end_date"] and t["end_date"] < today.isoformat()]
    stored: dict[int, set[Key]] = {}
    for row in conn.orm.scalars(select(DrivingRoute).where(DrivingRoute.trip_id.in_([t["id"] for t in all_trips]))):
        stored.setdefault(row.trip_id, set()).add((row.from_lat, row.from_lon, row.to_lat, row.to_lon))
    at_home = home.point(conn)
    for trip in all_trips:
        mark = _fingerprint(trip, at_home)
        if memory.settled.get(trip["id"]) == mark:
            continue
        try:
            places = tripmap.places(conn, HOUSEHOLD, trip["id"])
            stops = stops_of(trip, places) if places is not None else []
        except Exception as e:
            monitoring.report(e, values=False)
            continue
        have = stored.get(trip["id"], set())
        seen: set[Key] = set()
        known = [(s.latitude, s.longitude) for s in stops]
        for drive in drives_in(stops):
            k = key_of(drive)
            if k not in have and k not in memory.gave_up and k not in seen:
                seen.add(k)
                found.append(Missing(trip["id"], drive, known))
        if not seen:
            memory.settled[trip["id"]] = mark
    return found


def run(today: date, fetch: Fetch, pause: Callable[[float], bool], memory: Memory, now: Callable[[], float],
        limit: int | None = None, delay: float | None = None) -> Outcome:
    limit = MAX_PER_RUN if limit is None else limit
    delay = PAUSE_SECONDS if delay is None else delay
    outcome = Outcome()
    with db.session() as conn:
        todo = missing(conn, today, memory)
    asked: dict[Key, list[list[float]] | None] = {}
    calls = 0
    for item in todo:
        k = key_of(item.drive)
        if k not in asked:
            if calls >= limit:
                outcome.left = True
                break
            if calls and pause(delay):
                outcome.stop = True
                break
            calls += 1
            lat1, lon1, lat2, lon2 = item.drive
            try:
                asked[k] = fetch((lat1, lon1), (lat2, lon2))
            except mapkit.Refused:
                outcome.refused = outcome.stop = True
                break
            except mapkit.ServerError:
                outcome.stop = True
                break
            if asked[k] is None:
                memory.gave_up.add(k)
        path = asked[k]
        if path is None:
            continue
        lat1, lon1, lat2, lon2 = item.drive
        try:
            with db.session() as conn:
                saved = driving_routes.store_for(conn, item.trip_id, item.stops, {"latitude": round(lat1, 4), "longitude": round(lon1, 4)},
                                                 {"latitude": round(lat2, 4), "longitude": round(lon2, 4)}, thin(path), now())
        except driving_routes.Invalid:
            memory.gave_up.add(k)
            continue
        if saved:
            outcome.fetched += 1
    return outcome


def client() -> Fetch | None:
    creds = maps.credentials() if maps.enabled() else None
    if creds is None:
        return None
    directions = mapkit.Directions(creds)
    return lambda start, end: directions.route(start, end, time.time())
