"""Travel stats: what a person (or the household) has flown, stayed and driven, worked out from the trips the viewer can
see. `build` is a pure function of the segments, the airports and the airlines it is given; `compute` loads them, only
through the visibility helper (waypoint/domain/visibility.py), so a viewer's stats never include a trip they can't see
(AGENTS.md, "You see the trips you're on"): a partner's view of your stats leaves out your solo trips.

What counts: segments that have finished (their end, at their own zone, is not after `now`) and aren't cancelled. A
calendar year is the segment's own local year (a flight's departure, at the departure airport); a stay's nights and a
rental's days are counted by their own local dates. A segment with several travellers counts once for the household and
once for each traveller asked about. Distances are kilometres (the page applies the household's unit). Times in the air
are the booked departure to the booked arrival, each at its own zone, so a flight across the date line or overnight
comes out right. An airport that isn't in the table still counts as a flight, an airport visit and a route, but has no
distance, country or coordinates."""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal, TypedDict

from sqlalchemy import func, select

from ..storage import db
from ..storage.models import Airline, Airport
from . import people, trips, visibility
from .visibility import Viewer

EARTH_KM = 40075.0        # around the equator
MOON_KM = 384400.0        # to the Moon
EARTH_RADIUS_KM = 6371.0088
FLIGHT_NUMBER = re.compile(r"\s*([A-Za-z0-9]{2})\s*\d{1,4}[A-Za-z]?\s*")
SEAT = re.compile(r"\s*\d{1,3}\s*([A-Za-z])\s*")
# The seats a letter places on the common single-aisle (A–F) and wide-body (A–K) layouts: A and the last letter of the row
# are by the window, the letters beside an aisle are aisle seats, the rest middle. A letter that isn't in a layout this
# rule knows (a digit-only seat, an I, anything past K) is "unknown".
SEAT_POSITIONS: dict[str, Literal["window", "aisle", "middle"]] = {
    "A": "window", "B": "middle", "C": "aisle", "D": "aisle", "E": "middle", "F": "window",
    "G": "aisle", "H": "aisle", "J": "middle", "K": "window"}
SeatPosition = Literal["window", "aisle", "middle", "unknown"]


@dataclass(frozen=True)
class Seg:
    """A segment as the stats read it (nothing of who is on it: `compute` picks the segments)."""
    kind: str
    start_local: str
    start_zone: str
    end_local: str
    end_zone: str
    origin: str | None
    destination: str | None
    provider: str | None
    details: Mapping[str, str] = field(default_factory=dict)
    ports: Sequence[trips.PortIn] = ()   # a cruise's ports of call
    seats: Sequence[str] = ()            # the seats of the travellers counted (a person's own; the household's, every traveller's), as typed


class Named(TypedDict):
    name: str
    count: int


class Place(TypedDict):
    name: str                  # a country's ISO code or a city's name
    first_visit: str           # the local date, YYYY-MM-DD
    visits: int


class AirportVisit(TypedDict):
    code: str
    name: str                  # the airport's name; the code when it isn't in the table
    city: str | None
    country: str | None
    visits: int                # each departure from it and arrival at it
    latitude: float | None
    longitude: float | None


class AirlineCount(TypedDict):
    code: str | None           # the IATA code in the flight number, when there is one
    name: str                  # the airline's name; the code for one that isn't in the table; the booking's provider without a number
    flights: int


class RouteCount(TypedDict):
    a: str                     # A–B and B–A are one route: the lower code first
    b: str
    flights: int
    distance_km: float | None
    a_latitude: float | None
    a_longitude: float | None
    b_latitude: float | None
    b_longitude: float | None


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
    busiest_month: str | None  # YYYY-MM, the month with the most departures
    times_around_earth: float
    moon_fraction: float


class StayPlace(TypedDict):
    name: str                  # a hotel's name or a city, as first written
    stays: int
    nights: int                # the nights spent there, each stay's own (overlapping stays each count theirs)


class StayRecord(TypedDict):
    hotel: str | None
    city: str | None
    nights: int
    start_local: str           # the local date and time of check-in


class StayStats(TypedDict):
    nights: int                # nights away in hotels, each night once however many stays overlap it
    chains: list[Named]        # stays by the booking's provider
    cities: list[Named]
    countries: list[Named]
    count: int                 # stays with at least one night (in the year asked about)
    average_nights: float      # nights per such stay, to a tenth
    hotels: list[StayPlace]    # by nights, then stays, then name
    cities_by_nights: list[StayPlace]
    longest: StayRecord | None
    most_visited_hotel: StayPlace | None   # most stays, then most nights
    most_visited_city: StayPlace | None
    busiest_month: str | None  # YYYY-MM, the month with the most nights away


class CarStats(TypedDict):
    days: int                  # days with a rental car out, each day once
    companies: list[Named]


class CruiseStats(TypedDict):
    count: int
    nights: int                # nights aboard, each night once however many cruises overlap it
    sea_days: int              # dates strictly between embarking and disembarking with no port of call that day, each once
    ports: int                 # different ports of call (by name)
    lines: list[Named]         # cruises by the booking's provider


class PlaceStats(TypedDict):
    countries: list[Place]     # flights' and hotels' together, earliest first
    cities: list[Place]


class Stats(TypedDict):
    years: list[int]           # the years with something finished, newest first, whatever year was asked about
    flights: FlightStats
    stays: StayStats
    cars: CarStats
    cruises: CruiseStats
    places: PlaceStats


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The great-circle distance between two (latitude, longitude) points."""
    (la1, lo1), (la2, lo2) = ((math.radians(x), math.radians(y)) for x, y in (a, b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def seat_position(seat: str | None) -> SeatPosition:
    found = SEAT.fullmatch(seat or "")
    return SEAT_POSITIONS.get(found.group(1).upper(), "unknown") if found else "unknown"


def _ranked(counts: Mapping[str, int]) -> list[Named]:
    return [{"name": n, "count": c} for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _finished(s: Seg, now: datetime) -> bool:
    return trips.instant(s.end_local, s.end_zone) <= now


def _days(s: Seg) -> list[date]:
    """The local dates a stay or rental touches, first to last."""
    first, last = date.fromisoformat(s.start_local[:10]), date.fromisoformat(s.end_local[:10])
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def _nights(s: Seg) -> set[date]:
    """The nights of a stay: each local date from check-in up to, not including, check-out."""
    first, last = date.fromisoformat(s.start_local[:10]), date.fromisoformat(s.end_local[:10])
    return {first + timedelta(days=i) for i in range((last - first).days)}


def _in(day: date, year: int | None) -> bool:
    return year is None or day.year == year


CABIN_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("First", ("first", "la premiere", "la première")),
    ("Business", ("business", "polaris", "delta one", "upper class", "club world", "club europe", "club class", "flagship", "mint")),
    ("Premium Economy", ("premium", "comfort+", "comfort plus", "economy plus", "main cabin extra", "world traveller plus")),
    ("Economy", ("economy", "coach", "main", "basic", "standard", "saver", "tango", "wanna get away", "anytime", "light", "flex",
                 "blue", "classic", "value")),
)


def cabin_group(cabin: str) -> str:
    """The cabin a fare name or a cabin as an email wrote it belongs to: First, Business, Premium Economy or Economy
    ("Main Basic", "Tango Plus" and "Wanna Get Away" are fares in economy), by the words in it. A name that holds none of the
    words stays as written, so an unfamiliar one still shows."""
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


def _flights(flights: Sequence[Seg], known: Mapping[str, Airport], airlines: Mapping[str, str]) -> FlightStats:
    total_km, air = 0.0, 0.0
    visits: Counter[str] = Counter()
    carriers: Counter[tuple[str | None, str]] = Counter()
    routes: Counter[tuple[str, str]] = Counter()
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
        visits.update((origin, destination))
        routes[(min(origin, destination), max(origin, destination))] += 1
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
        # Each counted traveller's own seat; a booking with none of theirs has its booking seat, once.
        own = [t for t in (re.sub(r"\s+", "", x).upper() for x in s.seats) if t]
        booking = re.sub(r"\s+", "", s.details.get("seat") or "").upper()
        for seat in own or ([booking] if booking else [""]):
            if seat:
                seats[seat] += 1
            positions[seat_position(seat)] += 1
    airports_out: list[AirportVisit] = []
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
                           "b_latitude": b.latitude if b else None, "b_longitude": b.longitude if b else None})
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


def _stays(stays: Sequence[Seg], year: int | None, city_countries: Mapping[str, str]) -> StayStats:
    nights: set[date] = set()
    chains: Counter[str] = Counter()
    cities: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    for s in stays:
        spent_in_year = {d for d in _nights(s) if _in(d, year)}
        nights |= spent_in_year
        if year is not None and not spent_in_year:
            continue
        if s.provider:
            chains[s.provider] += 1
        if s.destination:
            cities[s.destination] += 1
            if (country := city_countries.get(s.destination.strip().lower())):
                countries[country] += 1
    return {"nights": len(nights), "chains": _ranked(chains), "cities": _ranked(cities), "countries": _ranked(countries),
            **_stay_figures(stays, year)}  # type: ignore[typeddict-item]


def _place_list(found: Mapping[str, list[int]], names: Mapping[str, str]) -> list[StayPlace]:
    return sorted(({"name": names[k], "stays": v[0], "nights": v[1]} for k, v in found.items()),
                  key=lambda p: (-p["nights"], -p["stays"], p["name"].casefold()))


def _most_visited(places: Sequence[StayPlace]) -> StayPlace | None:
    return min(places, key=lambda p: (-p["stays"], -p["nights"], p["name"].casefold()), default=None)


def _stay_figures(stays: Sequence[Seg], year: int | None) -> dict[str, object]:
    """What the stats say of the stays that have a night (in the year): how many, the average, the hotels and cities by nights,
    the longest, and the busiest month. Hotels and cities are matched by name without case or extra spaces."""
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
        if out and s.provider:
            companies[s.provider] += 1
    return {"days": len(days), "companies": _ranked(companies)}


def _port_days(port: trips.PortIn) -> set[date]:
    """The local dates the ship is at a port: from its arrival's date to its departure's (either alone is one day)."""
    days = [date.fromisoformat(t[:10]) for t in (port["arrive_local"], port["depart_local"]) if t]
    return {days[0] + timedelta(days=i) for i in range((max(days) - min(days)).days + 1)} if days else set()


def _cruises(cruises: Sequence[Seg], year: int | None) -> CruiseStats:
    nights: set[date] = set()
    sea: set[date] = set()
    ports: set[str] = set()
    lines: Counter[str] = Counter()
    for s in cruises:
        aboard = {d for d in _nights(s) if _in(d, year)}
        nights |= aboard
        in_port = set().union(*(_port_days(p) for p in s.ports)) if s.ports else set()
        first = date.fromisoformat(s.start_local[:10])
        sea |= {d for d in _nights(s) if d > first and d not in in_port and _in(d, year)}
        if not aboard:
            continue
        ports |= {p["name"].strip().casefold() for p in s.ports
                  if year is None or not (days := _port_days(p)) or any(_in(d, year) for d in days)}
        if s.provider:
            lines[s.provider] += 1
    counted = [s for s in cruises if any(_in(d, year) for d in _nights(s))]
    return {"count": len(counted), "nights": len(nights), "sea_days": len(sea), "ports": len(ports), "lines": _ranked(lines)}


def _places(flights: Sequence[Seg], stays: Sequence[Seg], known: Mapping[str, Airport],
            city_countries: Mapping[str, str]) -> PlaceStats:
    countries: dict[str, list[str]] = {}
    cities: dict[str, list[str]] = {}

    def seen(into: dict[str, list[str]], name: str, day: str) -> None:
        into.setdefault(name, []).append(day)
    for s in flights:
        for code, local in ((s.origin, s.start_local), (s.destination, s.end_local)):
            a = known.get((code or "").upper())
            if a:
                seen(countries, a.country, local[:10])
                seen(cities, a.city, local[:10])
    for s in stays:
        if s.destination:
            seen(cities, s.destination.strip(), s.start_local[:10])
            if (country := city_countries.get(s.destination.strip().lower())):
                seen(countries, country, s.start_local[:10])

    def listed(found: dict[str, list[str]]) -> list[Place]:
        return sorted(({"name": n, "first_visit": min(days), "visits": len(set(days))} for n, days in found.items()),
                      key=lambda p: (p["first_visit"], p["name"]))
    return {"countries": listed(countries), "cities": listed(cities)}


def _years(live: Sequence[Seg]) -> list[int]:
    """The years that have something to count: a flight's departure year, the years a stay's nights or a rental's days fall in."""
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
          city_countries: Mapping[str, str], *, now: datetime, year: int | None = None) -> Stats:
    """The stats of these segments: the finished, uncancelled ones (`segments` already holds only what the person wanted
    counted), in `year` (a calendar year at the places themselves) or for ever. `now` is an aware moment."""
    live = [s for s in segments if _finished(s, now)]
    flights = [s for s in live if s.kind == "flight" and (year is None or int(s.start_local[:4]) == year)]
    stays = [s for s in live if s.kind == "hotel"]
    cars = [s for s in live if s.kind == "car"]
    cruises = [s for s in live if s.kind == "cruise"]
    stays_in = [s for s in stays if year is None or any(_in(d, year) for d in _nights(s))]
    return {"years": _years(live), "flights": _flights(flights, known, airlines), "stays": _stays(stays_in, year, city_countries),
            "cars": _cars(cars, year), "cruises": _cruises(cruises, year), "places": _places(flights, stays_in, known, city_countries)}


def compute(conn: db.Connection, viewer: Viewer, person_id: int | None, year: int | None, now: datetime) -> Stats | None:
    """The stats of `person_id` (None: the whole household) over what `viewer` can see. None when there is no such person."""
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
                trips.decode_details(s.details), ports.get(s.id, []), seats_of.get(s.id, [])) for s in segments]
    codes = {(p or "").upper() for s in seen if s.kind == "flight" for p in (s.origin, s.destination)}
    known = {a.code: a for a in conn.orm.scalars(select(Airport).where(Airport.code.in_(sorted(codes)))).all()}
    prefixes = {c for s in seen if s.kind == "flight" and (c := _airline_code(s))}
    names = dict(conn.execute(select(Airline.code, Airline.name).where(Airline.code.in_(sorted(prefixes)))).fetchall())
    stay_cities = {s.destination.strip().lower() for s in seen if s.kind == "hotel" and s.destination}
    return build(seen, known, names, _countries_of(conn, stay_cities), now=now, year=year)


def _countries_of(conn: db.Connection, cities: set[str]) -> dict[str, str]:
    """The country of each of these cities (lower case): the one with the most airports in a city of that name (London is
    the United Kingdom's, not Ontario's), none when two tie."""
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
