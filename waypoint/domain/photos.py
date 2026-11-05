from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from sqlalchemy import select

from ..storage import db, geocode
from ..storage.models import Airport, Segment
from . import trippeople, trips, visibility
from .photomatch import GAP, Point, SegmentPoint, TripWindow, window
from .visibility import Viewer

Located = tuple[float, float, int]


def _at(point: Point, segment_id: int) -> Located:
    return point[0], point[1], segment_id


def where_was(points: Sequence[SegmentPoint], instant: datetime) -> Located | None:
    active = [p for p in points if p.start <= instant <= p.end]
    if any(p.kind == "flight" for p in active):
        return None
    here = min((p for p in active if p.origin is not None), key=lambda p: (p.end - p.start, p.segment_id), default=None)
    if here is not None and here.origin is not None:
        return _at(here.origin, here.segment_id)
    ended = max((p for p in points if p.end < instant <= p.end + GAP and p.destination is not None),
                key=lambda p: (p.end, -p.segment_id), default=None)
    if ended is not None and ended.destination is not None:
        return _at(ended.destination, ended.segment_id)
    upcoming = min((p for p in points if instant < p.start <= instant + GAP and p.origin is not None),
                   key=lambda p: (p.start, p.segment_id), default=None)
    if upcoming is not None and upcoming.origin is not None:
        return _at(upcoming.origin, upcoming.segment_id)
    return None


def _code(value: str | None) -> str:
    return (value or "").strip().upper()


def _points(seg: Segment, airport_at: Mapping[str, Point], ports: Sequence[trips.PortIn]) -> list[SegmentPoint]:
    timed = not trips.untimed(trips.decode_details(seg.details))
    start, end = trips.instant(seg.start_local, seg.start_zone), trips.instant(seg.end_local, seg.end_zone)
    if seg.kind == "flight":
        leaving, arriving = airport_at.get(_code(seg.origin)), airport_at.get(_code(seg.destination))
        return [SegmentPoint(seg.id, seg.kind, start, end, leaving[0] if leaving else None, leaving[1] if leaving else None,
                             arriving[0] if arriving else None, arriving[1] if arriving else None, timed)]
    if seg.kind == "train":
        return [SegmentPoint(seg.id, seg.kind, start, end, None, None, seg.latitude, seg.longitude, timed)]
    main = SegmentPoint(seg.id, seg.kind, start, end, seg.latitude, seg.longitude, timed=timed)
    if seg.kind != "cruise":
        return [main]
    calls: list[SegmentPoint] = []
    for port in ports:
        found = geocode.locate_port(port["name"])
        if found is None:
            continue
        arrive = trips.instant(port["arrive_local"], port["zone"]) if port["arrive_local"] else start
        depart = trips.instant(port["depart_local"], port["zone"]) if port["depart_local"] else end
        calls.append(SegmentPoint(seg.id, seg.kind, arrive, depart, found.latitude, found.longitude, timed=timed))
    if main.origin is None and calls:
        main = replace(main, latitude=calls[0].latitude, longitude=calls[0].longitude)
    return [main, *calls]


def candidate_windows(conn: db.Connection, person_id: int) -> list[TripWindow]:
    viewer = Viewer(person_id)
    seen = visibility.visible_trips(conn, viewer)
    aboard = trippeople.of(conn, [t.id for t in seen])
    mine = [t for t in seen if person_id in aboard[t.id]]
    if not mine:
        return []
    live = [s for s in visibility.visible_segments(conn, viewer, [t.id for t in mine]) if s.status != "cancelled"]
    codes = sorted({_code(c) for s in live if s.kind == "flight" for c in (s.origin, s.destination)} - {""})
    airport_at = {a.code: (a.latitude, a.longitude) for a in conn.orm.scalars(select(Airport).where(Airport.code.in_(codes))).all()}
    ports = trips.ports_of(conn, [s.id for s in live if s.kind == "cruise"])
    windows: list[TripWindow] = []
    for trip in mine:
        points = [p for s in live if s.trip_id == trip.id for p in _points(s, airport_at, ports.get(s.id, []))]
        found = window(trip, points)
        if found is not None:
            windows.append(found)
    return windows
