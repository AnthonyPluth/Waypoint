from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, select

from ..storage import db
from ..storage.models import Segment, SegmentExclusion, SegmentTraveler, TripExclusion, TripPerson


def of(conn: db.Connection, trip_ids: Iterable[int]) -> dict[int, list[int]]:
    ids = list(dict.fromkeys(trip_ids))
    out: dict[int, list[int]] = {i: [] for i in ids}
    if ids:
        for row in conn.orm.scalars(select(TripPerson).where(TripPerson.trip_id.in_(ids)).order_by(TripPerson.id)).all():
            out[row.trip_id].append(row.person_id)
    return out


def excluded_from(conn: db.Connection, trip_ids: Iterable[int]) -> dict[int, set[int]]:
    ids = list(dict.fromkeys(trip_ids))
    out: dict[int, set[int]] = {i: set() for i in ids}
    if ids:
        for row in conn.orm.scalars(select(TripExclusion).where(TripExclusion.trip_id.in_(ids))).all():
            out[row.trip_id].add(row.person_id)
    return out


def excluded(conn: db.Connection, trip_id: int) -> set[int]:
    return excluded_from(conn, [trip_id])[trip_id]


def exclude(conn: db.Connection, trip_id: int, person_ids: Iterable[int]) -> None:
    for person_id in dict.fromkeys(person_ids):
        db.insert_ignore(conn, TripExclusion, {"trip_id": trip_id, "person_id": person_id}, key=["trip_id", "person_id"])


def restore(conn: db.Connection, trip_id: int, person_ids: Iterable[int]) -> None:
    wanted = list(dict.fromkeys(person_ids))
    if wanted:
        conn.execute(delete(TripExclusion).where(TripExclusion.trip_id == trip_id, TripExclusion.person_id.in_(wanted)))
        _uncut_in(conn, trip_id, wanted)


def cuts_on(conn: db.Connection, segment_ids: Iterable[int]) -> set[tuple[int, int]]:
    ids = list(dict.fromkeys(segment_ids))
    if not ids:
        return set()
    return {(row.segment_id, row.person_id)
            for row in conn.orm.scalars(select(SegmentExclusion).where(SegmentExclusion.segment_id.in_(ids))).all()}


def cut(conn: db.Connection, segment_ids: Iterable[int], person_ids: Iterable[int]) -> None:
    people = list(dict.fromkeys(person_ids))
    for segment_id in dict.fromkeys(segment_ids):
        for person_id in people:
            db.insert_ignore(conn, SegmentExclusion, {"segment_id": segment_id, "person_id": person_id}, key=["segment_id", "person_id"])


def uncut(conn: db.Connection, segment_ids: Iterable[int], person_ids: Iterable[int]) -> None:
    ids, people = list(dict.fromkeys(segment_ids)), list(dict.fromkeys(person_ids))
    if ids and people:
        conn.execute(delete(SegmentExclusion).where(SegmentExclusion.segment_id.in_(ids), SegmentExclusion.person_id.in_(people)))


def _uncut_in(conn: db.Connection, trip_id: int, person_ids: Sequence[int]) -> None:
    if person_ids:
        conn.execute(delete(SegmentExclusion).where(SegmentExclusion.person_id.in_(list(person_ids)),
                                                    SegmentExclusion.segment_id.in_(select(Segment.id).where(Segment.trip_id == trip_id))))


def add(conn: db.Connection, trip_id: int, person_ids: Iterable[int]) -> None:
    out = excluded(conn, trip_id)
    have = set(of(conn, [trip_id])[trip_id])
    joining = [p for p in dict.fromkeys(person_ids) if p not in have and p not in out]
    for person_id in joining:
        conn.orm.add(TripPerson(trip_id=trip_id, person_id=person_id))
    conn.orm.flush()
    _uncut_in(conn, trip_id, joining)


def put_back(conn: db.Connection, trip_id: int, person_ids: Iterable[int]) -> None:
    wanted = list(dict.fromkeys(person_ids))
    restore(conn, trip_id, wanted)
    add(conn, trip_id, wanted)


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
