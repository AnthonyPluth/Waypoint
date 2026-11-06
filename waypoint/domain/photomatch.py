from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from ..storage.models import Trip
from .stats import distance_km

MatchKind = Literal["place", "time", "far", "ambiguous", "home", "none"]
HomePrecision = Literal["address", "zip", "city"]
Point = tuple[float, float]

PAD = timedelta(hours=12)
HOME: dict[HomePrecision, float | None] = {"address": 2.0, "zip": 8.0, "city": None}
NEAR = 100.0
FAR = 400.0
MARGIN = 25.0
GAP = timedelta(hours=36)
CLUSTER = 5.0


@dataclass(frozen=True)
class PhotoIn:
    taken: datetime
    latitude: float | None
    longitude: float | None
    person_id: int

    @property
    def spot(self) -> Point | None:
        return (self.latitude, self.longitude) if self.latitude is not None and self.longitude is not None else None


@dataclass(frozen=True)
class SegmentPoint:
    segment_id: int
    kind: str
    start: datetime
    end: datetime
    latitude: float | None
    longitude: float | None
    to_latitude: float | None = None
    to_longitude: float | None = None
    timed: bool = True
    zone: str | None = None
    to_zone: str | None = None

    @property
    def origin(self) -> Point | None:
        return (self.latitude, self.longitude) if self.latitude is not None and self.longitude is not None else None

    @property
    def destination(self) -> Point | None:
        if self.to_latitude is not None and self.to_longitude is not None:
            return (self.to_latitude, self.to_longitude)
        return None if self.kind == "flight" else self.origin

    @property
    def places(self) -> list[Point]:
        return list(dict.fromkeys(p for p in (self.origin, self.destination) if p is not None))

    def gap(self, at: datetime) -> timedelta:
        if self.start <= at <= self.end:
            return timedelta(0)
        return self.start - at if at < self.start else at - self.end


@dataclass(frozen=True)
class TripWindow:
    trip_id: int
    start: datetime
    end: datetime
    points: tuple[SegmentPoint, ...]

    @property
    def length(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class HomeIn:
    latitude: float
    longitude: float
    precision: HomePrecision


@dataclass(frozen=True)
class Match:
    match: MatchKind
    trip_id: int | None = None
    segment_id: int | None = None
    distance_km: float | None = None


Nearest = tuple[float, SegmentPoint]


def window(trip: Trip, live_segments: Sequence[SegmentPoint]) -> TripWindow | None:
    if not live_segments:
        return None
    first = min(live_segments, key=lambda p: (p.start, p.segment_id))
    last = max(live_segments, key=lambda p: (p.end, -p.segment_id))
    start, end = first.start, last.end
    if trip.start_date and trip.end_date and not any(p.timed for p in live_segments):
        start = datetime.combine(date.fromisoformat(trip.start_date), time(0, 0), first.start.tzinfo)
        end = datetime.combine(date.fromisoformat(trip.end_date), time(23, 59), last.end.tzinfo)
    return TripWindow(trip.id, start.astimezone(UTC) - PAD, end.astimezone(UTC) + PAD, tuple(live_segments))


def _nearest(points: Sequence[SegmentPoint], at: datetime, spot: Point) -> Nearest | None:
    scored = [(distance_km(spot, place), p.gap(at), p.segment_id, p) for p in points for place in p.places]
    if not scored:
        return None
    distance, _, _, point = min(scored, key=lambda s: (s[0], s[1], s[2]))
    return distance, point


def _by_time(points: Sequence[SegmentPoint], at: datetime) -> SegmentPoint | None:
    return min(points, key=lambda p: (p.gap(at), p.end > at, p.segment_id), default=None)


def _shortest(windows: Sequence[TripWindow]) -> TripWindow | None:
    least = min(w.length for w in windows)
    shortest = [w for w in windows if w.length == least]
    return shortest[0] if len(shortest) == 1 else None


def _settled(scored: Sequence[tuple[TripWindow, Nearest | None]]) -> TripWindow | None:
    distances = sorted((near[0], w.trip_id, w) for w, near in scored if near is not None)
    if len(distances) < len(scored) or distances[1][0] - distances[0][0] < MARGIN:
        return None
    return distances[0][2]


def _timed_match(chosen: TripWindow, at: datetime) -> Match:
    point = _by_time(chosen.points, at)
    return Match("time", chosen.trip_id, point.segment_id if point else None, None)


def _kind(distance: float) -> MatchKind:
    return "place" if distance <= NEAR else "far" if distance > FAR else "time"


def settle(photo: PhotoIn, chosen: TripWindow | None) -> Match:
    if chosen is None:
        return Match("time")
    spot = photo.spot
    near = _nearest(chosen.points, photo.taken, spot) if spot is not None else None
    if near is None:
        return _timed_match(chosen, photo.taken)
    distance, point = near
    return Match(_kind(distance), chosen.trip_id, point.segment_id, distance)


def match(photo: PhotoIn, windows: Sequence[TripWindow], home: HomeIn | None) -> Match:
    at = photo.taken
    inside = [w for w in windows if w.start <= at <= w.end]
    if not inside:
        return Match("none")
    spot = photo.spot
    if spot is not None and home is not None:
        radius = HOME[home.precision]
        if radius is not None and distance_km(spot, (home.latitude, home.longitude)) <= radius:
            return Match("home")
    if spot is None:
        chosen = _shortest(inside)
        return _timed_match(chosen, at) if chosen else Match("ambiguous")
    nearest = {w.trip_id: _nearest(w.points, at, spot) for w in inside}
    winner = inside[0] if len(inside) == 1 else _settled([(w, nearest[w.trip_id]) for w in inside]) or _shortest(inside)
    if winner is None:
        return Match("ambiguous")
    near = nearest[winner.trip_id]
    if near is None:
        return _timed_match(winner, at)
    distance, point = near
    return Match(_kind(distance), winner.trip_id, point.segment_id, distance)
