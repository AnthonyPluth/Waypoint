from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from functools import cache
from typing import TypedDict

from sqlalchemy import false, or_, select

from ..storage import db, geocode, reference
from ..storage.models import Airport, Photo, PhotoSource, Segment
from . import place_zones, stats, tripmap, trips, visibility
from .visibility import Viewer

KM_PER_MILE = 1.609344
SHOWN_MATCHES = ("place", "time", "far")
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


def _road_km(live: Sequence[Segment]) -> tuple[float, bool]:
    located = {s.id: (s.latitude, s.longitude) for s in live if s.kind != "flight" and s.latitude is not None and s.longitude is not None}
    stops: list[tripmap.Stop] = [(s.id, s.kind, trips.instant(s.start_local, s.start_zone)) for s in live]
    total, estimated = 0.0, False
    for first, second, found in tripmap.drives(stops, located):
        if found is not None:
            total += (found.miles + found.start_link_miles + found.end_link_miles) * KM_PER_MILE
        else:
            total += stats.distance_km(located[first], located[second])
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
    own = PhotoSource.person_id == viewer.person_id if viewer.person_id is not None else false()
    rows = conn.execute(select(Photo.state, Photo.country, Photo.location_source, Photo.match, Photo.decided_by)
                        .join(PhotoSource, PhotoSource.id == Photo.source_id)
                        .where(Photo.trip_id == trip_id, or_(Photo.match.in_(SHOWN_MATCHES), Photo.decided_by == OWNER),
                               or_(Photo.hidden.is_(false()), own))).fetchall()
    return [{"state": state, "country": country, "inferred": source == INFERRED, "counts_place": match != UNSURE_MATCH or decided == OWNER}
            for state, country, source, match, decided in rows]


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
    road_km, estimated = _road_km(live)
    photos = _photos(conn, viewer, trip_id)
    states, countries = _places(conn, live, airport_countries, photos)
    return {"days": _days(trip.start_date, trip.end_date) if live or not booked else 0, "nights": _nights(live),
            "distance_km": round(round(flight_km, 1) + round(road_km, 1), 1), "flight_km": round(flight_km, 1), "road_km": round(road_km, 1),
            "road_estimated": estimated, "states": states, "countries": countries,
            "photos": {"total": len(photos), "inferred": sum(1 for p in photos if p["inferred"])}, "kinds": _kinds(live)}
