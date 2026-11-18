from __future__ import annotations

import itertools
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from functools import cache
from typing import TypedDict

from sqlalchemy import select

from ..storage import db, geocode, reference
from ..storage.models import Airport, DrivingRoute, Segment
from . import photos, place_zones, route_warming, stats, tripmap, trips, visibility
from .visibility import Viewer

UNSURE_MATCH = "far"
OWNER = "owner"
INFERRED = "inferred"
US = "US"


class PhotoCounts(TypedDict):
    total: int
    inferred: int


class KindCounts(TypedDict):
    flight: int
    hotel: int
    car: int
    train: int
    cruise: int
    parking: int
    visit: int


class TripSummary(TypedDict):
    days: int
    nights: int
    distance_km: float
    flight_km: float
    road_km: float
    road_estimated: bool
    states: list[str]
    countries: list[str]
    photos: PhotoCounts
    kinds: KindCounts


class PlacedPhoto(TypedDict):
    state: str | None
    country: str | None
    inferred: bool
    counts_place: bool


def _days(start: str | None, end: str | None) -> int:
    if not start or not end:
        return 0
    return max((date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days + 1, 0)


def _nights(live: Sequence[Segment]) -> int:
    spent: set[date] = set()
    for s in live:
        if s.kind in ("hotel", "cruise"):
            first, last = date.fromisoformat(s.start_local[:10]), date.fromisoformat(s.end_local[:10])
            spent |= {first + timedelta(days=n) for n in range((last - first).days)}
    return len(spent)


def _code(text: str | None) -> str:
    return (text or "").strip().upper()


def _one_per_flight(flights: Iterable[Segment]) -> list[Segment]:
    seen: set[tuple[str, str, str, str]] = set()
    legs: list[Segment] = []
    for s in flights:
        number = trips.flight_key(trips.decode_details(s.details).get("flight_number"))
        if number is not None:
            key = (number, s.start_local[:10], _code(s.origin), _code(s.destination))
            if key in seen:
                continue
            seen.add(key)
        legs.append(s)
    return legs


def _flight_km(conn: db.Connection, live: Sequence[Segment]) -> tuple[float, set[str]]:
    flights = _one_per_flight(s for s in live if s.kind == "flight")
    codes = {_code(p) for s in flights for p in (s.origin, s.destination)} - {""}
    known = {a.code: a for a in conn.orm.scalars(select(Airport).where(Airport.code.in_(sorted(codes)))).all()}
    total = 0.0
    for s in flights:
        here, there = known.get(_code(s.origin)), known.get(_code(s.destination))
        if here and there:
            total += stats.distance_km((here.latitude, here.longitude), (there.latitude, there.longitude))
    return total, {a.country for a in known.values()}


def _path_km(path: list[list[float]]) -> float:
    return sum(stats.distance_km((a[0], a[1]), (b[0], b[1])) for a, b in itertools.pairwise(path))


def _road_km(conn: db.Connection, viewer: Viewer, trip_id: int) -> tuple[float, bool]:
    trip, places = trips.get(conn, viewer, trip_id), tripmap.places(conn, viewer, trip_id)
    if trip is None or places is None:
        return 0.0, False
    stored = {(r.from_lat, r.from_lon, r.to_lat, r.to_lon): r for r in conn.orm.scalars(select(DrivingRoute).where(DrivingRoute.trip_id == trip_id))}
    total, estimated = 0.0, False
    for drive in route_warming.drives_of(trip, places):
        row = stored.get(route_warming.key_of(drive))
        path = json.loads(row.path) if row is not None else None
        if path:
            total += _path_km(path)
        else:
            total += stats.distance_km((drive[0], drive[1]), (drive[2], drive[3]))
            estimated = True
    return total, estimated


@cache
def _country_codes() -> dict[str, str]:
    known = {reference.place_key(name): code for code, name in reference.country_names().items()}
    known.update({reference.place_key(name): code for name, code in geocode.COUNTRIES.items()})
    known.update({reference.place_key("United States of America"): US})
    return known


def _country_of(text: str | None) -> tuple[str | None, str | None]:
    plain = " ".join((text or "").split())
    if not plain:
        return None, None
    code = plain.upper() if len(plain) == 2 and plain.upper() in reference.country_names() else _country_codes().get(reference.place_key(plain))
    if code is None:
        return None, plain
    return code, reference.country_names().get(code, plain)


def _state_name(text: str | None) -> str | None:
    plain = " ".join((text or "").split()).upper()
    if not plain:
        return None
    code = plain if plain in place_zones.STATE_NAMES else place_zones.US_NAMES.get(plain)
    return place_zones.state_name(code) if code else None


def _photos(conn: db.Connection, viewer: Viewer, trip_id: int) -> list[PlacedPhoto]:
    return [{"state": p.state, "country": p.country, "inferred": p.location_source == INFERRED, "counts_place": p.match != UNSURE_MATCH or p.decided_by == OWNER}
            for p, _ in photos.visible_rows(conn, viewer, trip_id)]


def _places(conn: db.Connection, live: Sequence[Segment], airport_countries: Iterable[str], photos: Sequence[PlacedPhoto]) -> tuple[list[str], list[str]]:
    names = reference.country_names()
    states: set[str] = set()
    countries: set[str] = {names.get(c, c) for c in airport_countries if c}
    stay_cities = {s.destination.strip().lower() for s in live if s.kind == "hotel" and s.destination and s.destination.strip()}
    countries |= {names.get(c, c) for c in stats.countries_of(conn, stay_cities).values()}
    for s in live:
        details = trips.decode_details(s.details)
        parsed = place_zones.parse(details.get("address"))
        if parsed.state and (state := place_zones.state_name(parsed.state)):
            states.add(state)
        if parsed.country:
            countries.add(names.get(parsed.country, parsed.country))
        if s.kind == "visit" and (nation := _code(s.destination)):
            countries.add(names.get(nation, nation))
            if nation == US and (state := _state_name(details.get(trips.STATE))):
                states.add(state)
    for photo in photos:
        if not photo["counts_place"]:
            continue
        code, country = _country_of(photo["country"])
        if country:
            countries.add(country)
        if code == US and (state := _state_name(photo["state"])):
            states.add(state)
    return sorted(states, key=str.casefold), sorted(countries, key=str.casefold)


def _kinds(live: Sequence[Segment]) -> KindCounts:
    found = Counter(s.kind for s in live)
    return {"flight": found["flight"], "hotel": found["hotel"], "car": found["car"], "train": found["train"],
            "cruise": found["cruise"], "parking": found["parking"], "visit": found["visit"]}


def summary(conn: db.Connection, viewer: Viewer, trip_id: int) -> TripSummary | None:
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return None
    booked = visibility.visible_segments(conn, viewer, [trip_id])
    live = [s for s in booked if s.status != "cancelled"]
    flight_km, airport_countries = _flight_km(conn, live)
    road_km, estimated = _road_km(conn, viewer, trip_id)
    photos = _photos(conn, viewer, trip_id)
    states, countries = _places(conn, live, airport_countries, photos)
    return {"days": _days(trip.start_date, trip.end_date) if live or not booked else 0, "nights": _nights(live),
            "distance_km": round(round(flight_km, 1) + round(road_km, 1), 1), "flight_km": round(flight_km, 1), "road_km": round(road_km, 1),
            "road_estimated": estimated, "states": states, "countries": countries,
            "photos": {"total": len(photos), "inferred": sum(1 for p in photos if p["inferred"])}, "kinds": _kinds(live)}
