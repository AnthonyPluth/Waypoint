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


class Saved(TypedDict):
    trip: trips.TripOut | None
    messages: list[SegmentMessages]


def _span(trip_start: str, trip_end: str | None) -> tuple[date, date]:
    start = dates.parse_day(trip_start)
    return start, dates.parse_day(trip_end) if trip_end else start


def current_trip_id(conn: db.Connection, viewer: Viewer, today: date) -> int | None:
    dated = [(t.id, *_span(t.start_date, t.end_date)) for t in visibility.visible_trips(conn, viewer) if t.start_date]
    under_way = sorted((end, start, tid) for tid, start, end in dated if start <= today <= end)
    if under_way:
        return under_way[0][2]
    soon = sorted((start, tid) for tid, start, _end in dated if today < start <= today + timedelta(days=LOOKAHEAD_DAYS))
    return soon[0][1] if soon else None


def projection(conn: db.Connection, viewer: Viewer, today: date) -> Saved:
    trip_id = current_trip_id(conn, viewer, today)
    trip = trips.get(conn, viewer, trip_id) if trip_id is not None else None
    if trip is None:
        return {"trip": None, "messages": []}
    messages: list[SegmentMessages] = []
    for segment in trip["segments"]:
        emails = trips.emails_of(conn, viewer, segment["id"]) if segment["has_email"] else None
        if emails:
            messages.append({"segment_id": segment["id"], "emails": emails})
    return {"trip": trip, "messages": messages}
