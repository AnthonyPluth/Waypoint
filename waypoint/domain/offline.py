from __future__ import annotations

import base64
from datetime import date, timedelta
from typing import TypedDict

from .. import dates
from ..storage import db, gate_codes, stored_mail
from ..storage.models import Airport
from . import airports, trips, visibility
from .visibility import Viewer

LOOKAHEAD_DAYS = 7
VERSION = 1


class SegmentMessages(TypedDict):
    segment_id: int
    emails: list[stored_mail.Content]


class SegmentPicture(TypedDict):
    segment_id: int
    type: str
    data: str


class AirportPoint(TypedDict):
    code: str
    latitude: float
    longitude: float


class SavedTrip(TypedDict):
    trip: trips.TripOut
    messages: list[SegmentMessages]
    codes: list[SegmentPicture]
    cities: dict[str, str]
    airports: list[AirportPoint]


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


def _pictures(conn: db.Connection, viewer: Viewer, trip: trips.TripOut) -> list[SegmentPicture]:
    found: list[SegmentPicture] = []
    for segment in trip["segments"]:
        code = segment["gate_code"]
        if segment["kind"] != gate_codes.KIND or segment["status"] == "cancelled" or code is None or code["state"] != "ready":
            continue
        image = trips.gate_code_of(conn, viewer, segment["id"])
        if image is not None:
            found.append({"segment_id": segment["id"], "type": image["type"], "data": base64.b64encode(image["data"]).decode("ascii")})
    return found


def _cities(conn: db.Connection, trip: trips.TripOut) -> dict[str, str]:
    codes = dict.fromkeys(code.strip().upper() for seg in trip["segments"] if seg["kind"] == "flight"
                          for code in (seg["origin"], seg["destination"]) if code and code.strip())
    found = ((code, airports.lookup(conn, code)) for code in codes)
    return {code: a["city"] for code, a in found if a is not None}


def _airports(conn: db.Connection, trip: trips.TripOut) -> list[AirportPoint]:
    codes = dict.fromkeys(seg["origin"].strip().upper() for seg in trip["segments"] if seg["kind"] == "car" and seg["origin"] and seg["origin"].strip())
    found = ((code, conn.orm.get(Airport, code)) for code in codes)
    return [{"code": code, "latitude": a.latitude, "longitude": a.longitude} for code, a in found if a is not None]


def _saved(conn: db.Connection, viewer: Viewer, trip_id: int, with_codes: bool) -> SavedTrip | None:
    trip = trips.get(conn, viewer, trip_id)
    if trip is None:
        return None
    codes = _pictures(conn, viewer, trip) if with_codes else []
    messages: list[SegmentMessages] = []
    for segment in trip["segments"]:
        if not with_codes:
            segment["gate_code"] = None
        emails = trips.emails_of(conn, viewer, segment["id"]) if segment["has_email"] else None
        if emails:
            messages.append({"segment_id": segment["id"], "emails": [{**e, "images": 0} for e in emails]})
    return {"trip": trip, "messages": messages, "codes": codes, "cities": _cities(conn, trip), "airports": _airports(conn, trip)}


def projection(conn: db.Connection, viewer: Viewer, today: date, with_codes: bool = False) -> Saved:
    found = (_saved(conn, viewer, tid, with_codes) for tid in saved_trip_ids(conn, viewer, today))
    return {"trips": [s for s in found if s is not None]}
