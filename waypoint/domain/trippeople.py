from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, select

from ..storage import db
from ..storage.models import Segment, SegmentTraveler, TripPerson


def of(conn: db.Connection, trip_ids: Iterable[int]) -> dict[int, list[int]]:
    ids = list(dict.fromkeys(trip_ids))
    out: dict[int, list[int]] = {i: [] for i in ids}
    if ids:
        for row in conn.orm.scalars(select(TripPerson).where(TripPerson.trip_id.in_(ids)).order_by(TripPerson.id)).all():
            out[row.trip_id].append(row.person_id)
    return out


def add(conn: db.Connection, trip_id: int, person_ids: Iterable[int]) -> None:
    have = set(of(conn, [trip_id])[trip_id])
    for person_id in dict.fromkeys(person_ids):
        if person_id not in have:
            conn.orm.add(TripPerson(trip_id=trip_id, person_id=person_id))
            have.add(person_id)
    conn.orm.flush()


def remove(conn: db.Connection, trip_id: int, person_ids: Sequence[int]) -> None:
    if person_ids:
        conn.execute(delete(TripPerson).where(TripPerson.trip_id == trip_id, TripPerson.person_id.in_(list(person_ids))))
        conn.orm.flush()


def clear(conn: db.Connection, trip_id: int) -> None:
    conn.execute(delete(TripPerson).where(TripPerson.trip_id == trip_id))
    conn.orm.flush()


def on_lists(conn: db.Connection, trip_id: int) -> list[int]:
    found = conn.orm.scalars(
        select(SegmentTraveler.person_id).join(Segment, Segment.id == SegmentTraveler.segment_id)
        .where(Segment.trip_id == trip_id, Segment.travelers_from_trip.is_(False), SegmentTraveler.person_id.is_not(None))
        .order_by(SegmentTraveler.id)).all()
    return list(dict.fromkeys(p for p in found if p is not None))


def keep_lists_inside(conn: db.Connection, trip_id: int) -> None:
    add(conn, trip_id, on_lists(conn, trip_id))
