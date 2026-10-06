from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, false, or_, select, true

from ..storage import db
from ..storage.models import Segment, SegmentRecipient, SegmentTraveler, Trip


@dataclass(frozen=True)
class Viewer:
    person_id: int | None
    household: bool = False


def can_see(viewer: Viewer) -> ColumnElement[bool]:
    if viewer.household:
        return true()
    if viewer.person_id is None:
        return false()
    me = viewer.person_id
    travelling = select(Segment.trip_id).join(SegmentTraveler, SegmentTraveler.segment_id == Segment.id) \
        .where(SegmentTraveler.person_id == me)
    booked_a_segment = select(Segment.trip_id).where(Segment.booked_by == me)
    received = select(Segment.trip_id).join(SegmentRecipient, SegmentRecipient.segment_id == Segment.id) \
        .where(SegmentRecipient.person_id == me)
    return or_(Trip.booked_by == me, Trip.id.in_(travelling), Trip.id.in_(booked_a_segment), Trip.id.in_(received))


def visible_trips(conn: db.Connection, viewer: Viewer) -> list[Trip]:
    return list(conn.orm.scalars(select(Trip).where(can_see(viewer))
                                 .order_by(Trip.start_date.is_(None), Trip.start_date, Trip.id)).all())


def visible_trip(conn: db.Connection, viewer: Viewer, trip_id: int) -> Trip | None:
    return conn.orm.scalars(select(Trip).where(Trip.id == trip_id, can_see(viewer))).first()


def visible_segments(conn: db.Connection, viewer: Viewer, trip_ids: Sequence[int] | None = None) -> list[Segment]:
    q = select(Segment).join(Trip, Trip.id == Segment.trip_id).where(can_see(viewer))
    if trip_ids is not None:
        q = q.where(Segment.trip_id.in_(list(trip_ids)))
    return list(conn.orm.scalars(q.order_by(Segment.id)).all())


def visible_segment(conn: db.Connection, viewer: Viewer, segment_id: int) -> Segment | None:
    return conn.orm.scalars(select(Segment).join(Trip, Trip.id == Segment.trip_id)
                            .where(Segment.id == segment_id, can_see(viewer))).first()


def visible_travelers(conn: db.Connection, viewer: Viewer, segment_ids: Sequence[int]) -> list[SegmentTraveler]:
    return list(conn.orm.scalars(
        select(SegmentTraveler).join(Segment, Segment.id == SegmentTraveler.segment_id)
        .join(Trip, Trip.id == Segment.trip_id).where(can_see(viewer), SegmentTraveler.segment_id.in_(list(segment_ids)))
        .order_by(SegmentTraveler.id)).all())


def visible_traveler(conn: db.Connection, viewer: Viewer, traveler_id: int) -> SegmentTraveler | None:
    return conn.orm.scalars(
        select(SegmentTraveler).join(Segment, Segment.id == SegmentTraveler.segment_id)
        .join(Trip, Trip.id == Segment.trip_id).where(can_see(viewer), SegmentTraveler.id == traveler_id)).first()


def visible_unmatched(conn: db.Connection, viewer: Viewer) -> list[SegmentTraveler]:
    return list(conn.orm.scalars(
        select(SegmentTraveler).join(Segment, Segment.id == SegmentTraveler.segment_id)
        .join(Trip, Trip.id == Segment.trip_id).where(can_see(viewer), SegmentTraveler.person_id.is_(None))
        .order_by(SegmentTraveler.id)).all())


def household_segments(conn: db.Connection, kind: str) -> list[Segment]:
    return list(conn.orm.scalars(select(Segment).where(Segment.kind == kind, Segment.confirmation.is_not(None))
                                 .order_by(Segment.id)).all())


def note_recipient(conn: db.Connection, viewer: Viewer, segment: Segment) -> bool:
    if viewer.household or viewer.person_id is None or visible_segment(conn, viewer, segment.id) is not None:
        return False
    db.insert_ignore(conn, SegmentRecipient, {"segment_id": segment.id, "person_id": viewer.person_id},
                     key=["segment_id", "person_id"])
    return True
