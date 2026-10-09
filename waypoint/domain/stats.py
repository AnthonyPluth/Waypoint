from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal, TypedDict, cast

from sqlalchemy import func, select

from ..storage import db
from ..storage.models import Airline, Airport
from . import people, seatmaps, trips, visibility
from .chains import clean, hotel_chain
from .visibility import Viewer

EARTH_KM = 40075.0
MOON_KM = 384400.0
EARTH_RADIUS_KM = 6371.0088
FLIGHT_NUMBER = re.compile(r"\s*([A-Za-z0-9]{2})\s*\d{1,4}[A-Za-z]?\s*")
SEAT = re.compile(r"\s*\d{1,3}\s*([A-Za-z])\s*")
SeatPosition = Literal["window", "aisle", "middle", "unknown"]


@dataclass(frozen=True)
class Seg:
    kind: str
    start_local: str
    start_zone: str
    end_local: str
    end_zone: str
    origin: str | None
    destination: str | None
    provider: str | None
    details: Mapping[str, str] = field(default_factory=dict)
    ports: Sequence[trips.PortIn] = ()
    seats: Sequence[str] = ()
    trip_id: int | None = None


class Named(TypedDict):
    name: str
    count: int


class Place(TypedDict):
    name: str
    first_visit: str
    visits: int


class MapTrip(TypedDict):
    trip_id: int
    name: str
    start: str
    end: str


class AirportVisit(TypedDict):
    code: str
    name: str
    city: str | None
    country: str | None
    visits: int
    latitude: float | None
    longitude: float | None


class AirlineCount(TypedDict):
    code: str | None
    name: str
    flights: int


class RouteCount(TypedDict):
    a: str
    b: str
    flights: int
    distance_km: float | None
    a_latitude: float | None
    a_longitude: float | None
    b_latitude: float | None
    b_longitude: float | None
    trips: list[MapTrip]


class FlightRecord(TypedDict):
    origin: str
    destination: str
    distance_km: float
    start_local: str
    flight_number: str | None


class SeatShare(TypedDict):
    window: int
    aisle: int
    middle: int
    unknown: int


class FlightStats(TypedDict):
    count: int
    distance_km: float
    air_seconds: int
    airports: list[AirportVisit]
    airlines: list[AirlineCount]
    countries: list[Named]
    routes: list[RouteCount]
    cabins: list[Named]
    top_seat: str | None
    seat_positions: SeatShare
    longest: FlightRecord | None
    shortest: FlightRecord | None
    most_visited_airport: str | None
    busiest_month: str | None
    times_around_earth: float
    moon_fraction: float


class StayPlace(TypedDict):
    name: str
    stays: int
    nights: int


class StayRecord(TypedDict):
    hotel: str | None
    city: str | None
    nights: int
    start_local: str


class StayPin(TypedDict):
    city: str
    country: str | None
    latitude: float
    longitude: float
    stays: int
    nights: int
    trips: list[MapTrip]


class StayStats(TypedDict):
    nights: int
    chains: list[Named]
    cities: list[Named]
    countries: list[Named]
    count: int
    average_nights: float
    hotels: list[StayPlace]
    cities_by_nights: list[StayPlace]
    longest: StayRecord | None
    most_visited_hotel: StayPlace | None
    most_visited_city: StayPlace | None
    busiest_month: str | None
    pins: list[StayPin]


class CarStats(TypedDict):
    days: int
    companies: list[Named]


class CruiseStats(TypedDict):
    count: int
    nights: int
    sea_days: int
    ports: int
    lines: list[Named]


class PlaceStats(TypedDict):
    countries: list[Place]
    cities: list[Place]


class Stats(TypedDict):
    years: list[int]
    flights: FlightStats
    stays: StayStats
    cars: CarStats
    cruises: CruiseStats
    places: PlaceStats


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = ((math.radians(x), math.radians(y)) for x, y in (a, b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def seat_position(seat: str | None, details: Mapping[str, str] | None = None) -> SeatPosition:
    found = SEAT.fullmatch(seat or "")
    if not found:
        return "unknown"
    said = ((details or {}).get("seat_position") or "").strip().casefold()
    if said in ("window", "aisle", "middle"):
        return cast(SeatPosition, said)
    letter = found.group(1).upper()
    if letter == "A":
        return "window"
    cabin = cabin_group((details or {}).get("cabin") or "Economy")
    if cabin != "Economy":
        return "unknown"
    return seatmaps.position((details or {}).get("aircraft"), "economy", letter) or "unknown"


def _ranked(counts: Mapping[str, int]) -> list[Named]:
    return [{"name": n, "count": c} for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _finished(s: Seg, now: datetime) -> bool:
    return trips.instant(s.end_local, s.end_zone) <= now


def _days(s: Seg) -> list[date]:
    first, last = date.fromisoformat(s.start_local[:10]), date.fromisoformat(s.end_local[:10])
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def _nights(s: Seg) -> set[date]:
    first, last = date.fromisoformat(s.start_local[:10]), date.fromisoformat(s.end_local[:10])
    return {first + timedelta(days=i) for i in range((last - first).days)}


def _in(day: date, year: int | None) -> bool:
    return year is None or day.year == year


CABIN_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("First", ("first", "la premiere", "la première")),
    ("Business", ("business", "polaris", "delta one", "upper class", "club world", "club europe", "club class", "flagship", "mint")),
    ("Premium Economy", ("premium", "economy comfort", "economy extra", "comfort+", "comfort plus", "economy plus", "main cabin extra", "world traveller plus")),
    ("Economy", ("economy", "coach", "main", "basic", "standard", "saver", "tango", "wanna get away", "anytime", "light", "flex",
                 "blue", "classic", "value")),
)


def cabin_group(cabin: str) -> str:
    low = cabin.casefold()
    for group, words in CABIN_GROUPS:
        if any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low) for w in words):
            return group
    return cabin.title() if cabin.islower() or cabin.isupper() else cabin


def _flight_number(s: Seg) -> str | None:
    number = s.details.get("flight_number")
    return re.sub(r"\s+", "", number).upper() if number else None


def _airline_code(s: Seg) -> str | None:
    found = FLIGHT_NUMBER.fullmatch(s.details.get("flight_number") or "")
    return found.group(1).upper() if found else None


def _record(origin: str, destination: str, km: float, s: Seg) -> FlightRecord:
    return {"origin": origin, "destination": destination, "distance_km": round(km, 1), "start_local": s.start_local,
            "flight_number": _flight_number(s)}


def _flights(flights: Sequence[Seg], known: Mapping[str, Airport], airlines: Mapping[str, str], trip_names: Mapping[int, str]) -> FlightStats:
    total_km, air = 0.0, 0.0
    arrivals: Counter[str] = Counter()
    departures: Counter[str] = Counter()
    carriers: Counter[tuple[str | None, str]] = Counter()
    routes: Counter[tuple[str, str]] = Counter()
    route_trips: dict[tuple[str, str], list[MapTrip]] = {}
    cabins: Counter[str] = Counter()
    seats: Counter[str] = Counter()
    months: Counter[str] = Counter()
    positions: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    longest: tuple[float, FlightRecord] | None = None
    shortest: tuple[float, FlightRecord] | None = None
    for s in flights:
        origin, destination = (s.origin or "").upper(), (s.destination or "").upper()
        air += (trips.instant(s.end_local, s.end_zone) - trips.instant(s.start_local, s.start_zone)).total_seconds()
        months[s.start_local[:7]] += 1
        departures[origin] += 1
        arrivals[destination] += 1
        route = (min(origin, destination), max(origin, destination))
        routes[route] += 1
        if (ref := _map_trip(s, trip_names)):
            route_trips.setdefault(route, []).append(ref)
        here, there = known.get(origin), known.get(destination)
        countries.update(a.country for a in (here, there) if a)
        if here and there:
            km = distance_km((here.latitude, here.longitude), (there.latitude, there.longitude))
            total_km += km
            record = _record(origin, destination, km, s)
            if longest is None or km > longest[0]:
                longest = (km, record)
            if shortest is None or km < shortest[0]:
                shortest = (km, record)
        code = _airline_code(s)
        if code:
            carriers[(code, airlines.get(code, code))] += 1
        elif s.provider:
            carriers[(None, s.provider)] += 1
        cabin = (s.details.get("cabin") or "").strip()
        if cabin:
            cabins[cabin_group(cabin)] += 1
        own = [t for t in (re.sub(r"\s+", "", x).upper() for x in s.seats) if t]
        booking = re.sub(r"\s+", "", s.details.get("seat") or "").upper()
        without_position = {k: v for k, v in s.details.items() if k != "seat_position"}
        for seat in own or ([booking] if booking else [""]):
            if seat:
                seats[seat] += 1
            positions[seat_position(seat, s.details if seat == booking or (not booking and len(own) == 1) else without_position)] += 1
    airports_out: list[AirportVisit] = []
    visits = {code: max(arrivals[code], departures[code]) for code in arrivals.keys() | departures.keys()}
    for code, n in sorted(visits.items(), key=lambda kv: (-kv[1], kv[0])):
        a = known.get(code)
        airports_out.append({"code": code, "name": a.name if a else code, "city": a.city if a else None,
                             "country": a.country if a else None, "visits": n,
                             "latitude": a.latitude if a else None, "longitude": a.longitude if a else None})
    routes_out: list[RouteCount] = []
    for (a_code, b_code), n in sorted(routes.items(), key=lambda kv: (-kv[1], kv[0])):
        a, b = known.get(a_code), known.get(b_code)
        routes_out.append({"a": a_code, "b": b_code, "flights": n,
                           "distance_km": round(distance_km((a.latitude, a.longitude), (b.latitude, b.longitude)), 1) if a and b else None,
                           "a_latitude": a.latitude if a else None, "a_longitude": a.longitude if a else None,
                           "b_latitude": b.latitude if b else None, "b_longitude": b.longitude if b else None,
                           "trips": sorted(route_trips.get((a_code, b_code), []), key=lambda t: (t["start"], t["trip_id"]))})
    top_seat = min(seats.items(), key=lambda kv: (-kv[1], kv[0]))[0] if seats else None
    busiest = min(months.items(), key=lambda kv: (-kv[1], kv[0]))[0] if months else None
    return {
        "count": len(flights), "distance_km": round(total_km, 1), "air_seconds": int(air),
        "airports": airports_out,
        "airlines": [{"code": c, "name": n, "flights": k} for (c, n), k in sorted(carriers.items(), key=lambda kv: (-kv[1], kv[0][1]))],
        "countries": _ranked(countries), "routes": routes_out, "cabins": _ranked(cabins), "top_seat": top_seat,
        "seat_positions": {"window": positions["window"], "aisle": positions["aisle"], "middle": positions["middle"],
                           "unknown": positions["unknown"]},
        "longest": longest[1] if longest else None, "shortest": shortest[1] if shortest else None,
        "most_visited_airport": airports_out[0]["code"] if airports_out else None, "busiest_month": busiest,
        "times_around_earth": round(total_km / EARTH_KM, 3), "moon_fraction": round(total_km / MOON_KM, 4),
    }


def _map_trip(s: Seg, trip_names: Mapping[int, str]) -> MapTrip | None:
    if s.trip_id is None or s.trip_id not in trip_names:
        return None
    return {"trip_id": s.trip_id, "name": trip_names[s.trip_id], "start": s.start_local[:10], "end": s.end_local[:10]}


def _stay_pins(stays: Sequence[Seg], year: int | None, city_countries: Mapping[str, str], city_points: Mapping[str, tuple[float, float]],
               trip_names: Mapping[int, str]) -> list[StayPin]:
    found: dict[str, StayPin] = {}
    for s in stays:
        spent = {d for d in _nights(s) if _in(d, year)}
        key = (s.destination or "").strip().lower()
        if not spent or key not in city_points:
            continue
        pin = found.setdefault(key, {"city": (s.destination or "").strip(), "country": city_countries.get(key),
                                     "latitude": city_points[key][0], "longitude": city_points[key][1], "stays": 0, "nights": 0, "trips": []})
        pin["stays"] += 1
        pin["nights"] += len(spent)
        if (ref := _map_trip(s, trip_names)):
            pin["trips"].append(ref)
    for pin in found.values():
        pin["trips"].sort(key=lambda t: (t["start"], t["trip_id"]))
    return sorted(found.values(), key=lambda p: (-p["nights"], -p["stays"], p["city"].casefold()))


def _stays(stays: Sequence[Seg], year: int | None, city_countries: Mapping[str, str], city_points: Mapping[str, tuple[float, float]],
           trip_names: Mapping[int, str]) -> StayStats:
    nights: set[date] = set()
    chains: Counter[str] = Counter()
    cities: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    for s in stays:
        spent_in_year = {d for d in _nights(s) if _in(d, year)}
        nights |= spent_in_year
        if year is not None and not spent_in_year:
            continue
        if (chain := hotel_chain(s.provider, s.origin)):
            chains[chain] += 1
        if s.destination:
            cities[s.destination] += 1
            if (country := city_countries.get(s.destination.strip().lower())):
                countries[country] += 1
    return {"nights": len(nights), "chains": _ranked(chains), "cities": _ranked(cities), "countries": _ranked(countries),
            "pins": _stay_pins(stays, year, city_countries, city_points, trip_names),
            **_stay_figures(stays, year)}  # type: ignore[typeddict-item]


def _place_list(found: Mapping[str, list[int]], names: Mapping[str, str]) -> list[StayPlace]:
    return sorted(({"name": names[k], "stays": v[0], "nights": v[1]} for k, v in found.items()),
                  key=lambda p: (-p["nights"], -p["stays"], p["name"].casefold()))


def _most_visited(places: Sequence[StayPlace]) -> StayPlace | None:
    return min(places, key=lambda p: (-p["stays"], -p["nights"], p["name"].casefold()), default=None)


def _stay_figures(stays: Sequence[Seg], year: int | None) -> dict[str, object]:
    hotels: dict[str, list[int]] = {}
    cities: dict[str, list[int]] = {}
    hotel_names: dict[str, str] = {}
    city_names: dict[str, str] = {}
    months: Counter[str] = Counter()
    longest: StayRecord | None = None
    total = count = 0
    for s in stays:
        spent = {d for d in _nights(s) if _in(d, year)}
        if not spent:
            continue
        count += 1
        total += len(spent)
        months.update(f"{d.year}-{d.month:02d}" for d in spent)
        for name, found, names in ((s.origin, hotels, hotel_names), (s.destination, cities, city_names)):
            key = " ".join((name or "").split()).casefold()
            if key:
                names.setdefault(key, " ".join((name or "").split()))
                seen = found.setdefault(key, [0, 0])
                seen[0] += 1
                seen[1] += len(spent)
        if longest is None or len(spent) > longest["nights"]:
            longest = {"hotel": s.origin, "city": s.destination, "nights": len(spent), "start_local": s.start_local}
    hotel_list, city_list = _place_list(hotels, hotel_names), _place_list(cities, city_names)
    busiest = min(months, key=lambda m: (-months[m], m), default=None)
    return {"count": count, "average_nights": round(total / count, 1) if count else 0.0, "hotels": hotel_list,
            "cities_by_nights": city_list, "longest": longest, "most_visited_hotel": _most_visited(hotel_list),
            "most_visited_city": _most_visited(city_list), "busiest_month": busiest}


def _cars(cars: Sequence[Seg], year: int | None) -> CarStats:
    days: set[date] = set()
    companies: Counter[str] = Counter()
    for s in cars:
        out = {d for d in _days(s) if _in(d, year)}
        days |= out
        if out and (company := clean(s.provider)):
            companies[company] += 1
    return {"days": len(days), "companies": _ranked(companies)}


def _cruises(cruises: Sequence[Seg], year: int | None) -> CruiseStats:
    nights: set[date] = set()
    sea: set[date] = set()
    ports: set[str] = set()
    lines: Counter[str] = Counter()
    for s in cruises:
        aboard = {d for d in _nights(s) if _in(d, year)}
        nights |= aboard
        in_port = set().union(*(trips.port_days(p) for p in s.ports)) if s.ports else set()
        first = date.fromisoformat(s.start_local[:10])
        sea |= {d for d in _nights(s) if d > first and d not in in_port and _in(d, year)}
        if not aboard:
            continue
        ports |= {p["name"].strip().casefold() for p in s.ports
                  if year is None or not (days := trips.port_days(p)) or any(_in(d, year) for d in days)}
        if s.provider:
            lines[s.provider] += 1
    counted = [s for s in cruises if any(_in(d, year) for d in _nights(s))]
    return {"count": len(counted), "nights": len(nights), "sea_days": len(sea), "ports": len(ports), "lines": _ranked(lines)}


Span = tuple[date, date]


def _visit_count(spans: Iterable[Span]) -> int:
    groups, reach = 0, None
    for start, end in sorted(spans):
        if reach is None or start > reach + timedelta(days=1):
            groups += 1
        reach = end if reach is None else max(reach, end)
    return groups


def _places(flights: Sequence[Seg], stays: Sequence[Seg], known: Mapping[str, Airport],
            city_countries: Mapping[str, str]) -> PlaceStats:
    countries: dict[str, list[str]] = {}
    cities: dict[str, list[str]] = {}
    came: dict[str, dict[str, list[Span]]] = {"country": {}, "city": {}}
    went: dict[str, dict[str, list[Span]]] = {"country": {}, "city": {}}
    stayed: dict[str, dict[str, list[Span]]] = {"country": {}, "city": {}}

    def seen(into: dict[str, list[str]], name: str, day: str) -> None:
        into.setdefault(name, []).append(day)

    def note(into: dict[str, dict[str, list[Span]]], kind: str, name: str, first: str, last: str) -> None:
        into[kind].setdefault(name, []).append((date.fromisoformat(first[:10]), date.fromisoformat(last[:10])))
    for s in flights:
        there, here = known.get((s.destination or "").upper()), known.get((s.origin or "").upper())
        for a, local in ((here, s.start_local), (there, s.end_local)):
            if a:
                seen(countries, a.country, local[:10])
                seen(cities, a.city, local[:10])
        for kind in ("country", "city"):
            if there and (not here or getattr(here, kind) != getattr(there, kind)):
                note(came, kind, getattr(there, kind), s.end_local, s.end_local)
            if here and (not there or getattr(here, kind) != getattr(there, kind)):
                note(went, kind, getattr(here, kind), s.start_local, s.start_local)
    for s in stays:
        if s.destination:
            city = s.destination.strip()
            seen(cities, city, s.start_local[:10])
            note(stayed, "city", city, s.start_local, s.end_local)
            if (country := city_countries.get(city.lower())):
                seen(countries, country, s.start_local[:10])
                note(stayed, "country", country, s.start_local, s.end_local)

    def visits(kind: str, name: str) -> int:
        arrivals, departures = came[kind].get(name, []), went[kind].get(name, [])
        flown = arrivals if _visit_count(arrivals) >= _visit_count(departures) else departures
        return max(_visit_count([*flown, *stayed[kind].get(name, [])]), 1)

    def listed(found: dict[str, list[str]], kind: str) -> list[Place]:
        return sorted(({"name": n, "first_visit": min(days), "visits": visits(kind, n)}
                       for n, days in found.items()), key=lambda p: (p["first_visit"], p["name"]))
    return {"countries": listed(countries, "country"), "cities": listed(cities, "city")}


def _years(live: Sequence[Seg]) -> list[int]:
    found: set[int] = set()
    for s in live:
        if s.kind == "flight":
            found.add(int(s.start_local[:4]))
        elif s.kind == "hotel":
            found.update(d.year for d in _nights(s))
        elif s.kind == "car":
            found.update(d.year for d in _days(s))
        elif s.kind == "cruise":
            found.update(d.year for d in _nights(s))
    return sorted(found, reverse=True)


def build(segments: Iterable[Seg], known: Mapping[str, Airport], airlines: Mapping[str, str],
          city_countries: Mapping[str, str], *, now: datetime, year: int | None = None,
          city_points: Mapping[str, tuple[float, float]] | None = None, trip_names: Mapping[int, str] | None = None) -> Stats:
    city_points, trip_names = city_points or {}, trip_names or {}
    live = [s for s in segments if _finished(s, now)]
    flights = [s for s in live if s.kind == "flight" and (year is None or int(s.start_local[:4]) == year)]
    stays = [s for s in live if s.kind == "hotel"]
    cars = [s for s in live if s.kind == "car"]
    cruises = [s for s in live if s.kind == "cruise"]
    stays_in = [s for s in stays if year is None or any(_in(d, year) for d in _nights(s))]
    return {"years": _years(live), "flights": _flights(flights, known, airlines, trip_names),
            "stays": _stays(stays_in, year, city_countries, city_points, trip_names),
            "cars": _cars(cars, year), "cruises": _cruises(cruises, year), "places": _places(flights, stays_in, known, city_countries)}


def compute(conn: db.Connection, viewer: Viewer, person_id: int | None, year: int | None, now: datetime) -> Stats | None:
    if person_id is not None and people.get(conn, person_id) is None:
        return None
    segments = [s for s in visibility.visible_segments(conn, viewer) if s.status != "cancelled"]
    travelling = visibility.visible_travelers(conn, viewer, [s.id for s in segments])
    if person_id is not None:
        on = {t.segment_id for t in travelling if t.person_id == person_id}
        segments = [s for s in segments if s.id in on]
    seats_of: dict[int, list[str]] = {}
    for t in travelling:
        if t.seat and (person_id is None or t.person_id == person_id):
            seats_of.setdefault(t.segment_id, []).append(t.seat)
    ports = trips.ports_of(conn, [s.id for s in segments if s.kind == "cruise"])
    seen = [Seg(s.kind, s.start_local, s.start_zone, s.end_local, s.end_zone, s.origin, s.destination, s.provider,
                trips.decode_details(s.details), ports.get(s.id, []), seats_of.get(s.id, []), s.trip_id) for s in segments]
    codes = {(p or "").upper() for s in seen if s.kind == "flight" for p in (s.origin, s.destination)}
    known = {a.code: a for a in conn.orm.scalars(select(Airport).where(Airport.code.in_(sorted(codes)))).all()}
    prefixes = {c for s in seen if s.kind == "flight" and (c := _airline_code(s))}
    names = dict(conn.execute(select(Airline.code, Airline.name).where(Airline.code.in_(sorted(prefixes)))).fetchall())
    stay_cities = {s.destination.strip().lower() for s in seen if s.kind == "hotel" and s.destination}
    countries = _countries_of(conn, stay_cities)
    trip_names = {t.id: t.name for t in visibility.visible_trips(conn, viewer)}
    return build(seen, known, names, countries, now=now, year=year, city_points=_points_of(conn, countries), trip_names=trip_names)


def _points_of(conn: db.Connection, countries: Mapping[str, str]) -> dict[str, tuple[float, float]]:
    if not countries:
        return {}
    found: dict[str, list[tuple[float, float]]] = {}
    for city, country, lat, lon in conn.execute(select(func.lower(Airport.city), Airport.country, Airport.latitude, Airport.longitude)
                                                .where(func.lower(Airport.city).in_(sorted(countries)))):
        if countries.get(city) == country:
            found.setdefault(city, []).append((lat, lon))
    return {c: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) for c, pts in found.items()}


def _countries_of(conn: db.Connection, cities: set[str]) -> dict[str, str]:
    if not cities:
        return {}
    found: dict[str, Counter[str]] = {}
    for city, country in conn.execute(select(func.lower(Airport.city), Airport.country).where(func.lower(Airport.city).in_(sorted(cities)))):
        found.setdefault(city, Counter())[country] += 1
    out: dict[str, str] = {}
    for city, counts in found.items():
        ranked = counts.most_common(2)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            out[city] = ranked[0][0]
    return out
