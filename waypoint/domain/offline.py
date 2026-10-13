from __future__ import annotations

from datetime import date, timedelta
from typing import TypedDict

from .. import dates
from ..storage import db, stored_mail
from . import trips, visibility
from .visibility import Viewer

LOOKAHEAD_DAYS = 7


class SegmentMessages(TypedDict):
    segment_id: int
    emails: list[stored_mail.Content]


class SavedTrip(TypedDict):
    trip: trips.TripOut
    messages: list[SegmentMessages]


class Saved(TypedDict):
    trips: list[SavedTrip]


MAX_TRIPS = 10


def _span(trip_start: str, trip_end: str | None) -> tuple[date, date]:
    start = dates.parse_day(trip_start)
    return start, dates.parse_day(trip_end) if trip_end else start


def saved_trip_ids(conn: db.Connection, viewer: Viewer, today: date) -> list[int]:
    dated = [(t.id, *_span(t.start_date, t.end_date)) for t in visibility.visible_trips(conn, viewer) if t.start_date]
    under_way = [tid for _end, _start, tid in sorted((end, start, tid) for tid, start, end in dated if start <= today <= end)]
    upcoming = sorted((start, tid) for tid, start, _end in dated if today < start)
    soon = [tid for start, tid in upcoming if start <= today + timedelta(days=LOOKAHEAD_DAYS)]
    chosen = under_way + soon
    nxt = upcoming[0][1] if upcoming else None
    if nxt is None or nxt in chosen[:MAX_TRIPS]:
        return chosen[:MAX_TRIPS]
    return [*chosen[:MAX_TRIPS - 1], nxt]


def _saved(conn: db.Connection, viewer: Viewer, trip_id: int) -> SavedTrip | None:
    trip = trips.get(conn, viewer, trip_id)
    if trip is None:
        return None
    messages: list[SegmentMessages] = []
    for segment in trip["segments"]:
        segment["gate_code"] = None
        emails = trips.emails_of(conn, viewer, segment["id"]) if segment["has_email"] else None
        if emails:
            messages.append({"segment_id": segment["id"], "emails": [{**e, "images": 0} for e in emails]})
    return {"trip": trip, "messages": messages}


def projection(conn: db.Connection, viewer: Viewer, today: date) -> Saved:
    found = (_saved(conn, viewer, tid) for tid in saved_trip_ids(conn, viewer, today))
    return {"trips": [s for s in found if s is not None]}
