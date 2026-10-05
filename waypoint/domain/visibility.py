"""Who sees which trips (AGENTS.md, "You see the trips you're on"): a trip is visible to the people travelling on any of its
segments, to whoever booked it (the trip, or any of its segments) and to whoever got the confirmation of one of its
bookings in their own mailbox (`segment_recipients`); nobody else, by any route. A segment is visible with its trip. This module is the only way trips and segments are read for a request: Semgrep's
`waypoint-trip-visibility` keeps `select(Trip…)` and the rest out of waypoint/server/, so a route goes through these
functions, and a trip or segment that isn't visible is answered as one that doesn't exist (a 404).

`viewer` is the person asking. Without sign-in (on your own machine, where everyone is the one local household) the
viewer is the household, which sees every trip."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, false, or_, select, true

from ..storage import db
from ..storage.models import Segment, SegmentRecipient, SegmentTraveler, Trip


@dataclass(frozen=True)
class Viewer:
    person_id: int | None   # None: signed in as someone with no person row, who sees only what's nobody's
    household: bool = False  # no sign-in: the local household, which sees everything


def can_see(viewer: Viewer) -> ColumnElement[bool]:
    """The condition on `Trip` that the viewer can see the trip."""
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
    """The viewer's trips, by start date (undated last)."""
    return list(conn.orm.scalars(select(Trip).where(can_see(viewer))
                                 .order_by(Trip.start_date.is_(None), Trip.start_date, Trip.id)).all())


def visible_trip(conn: db.Connection, viewer: Viewer, trip_id: int) -> Trip | None:
    """The trip, or None when there's none by that id or the viewer can't see it."""
    return conn.orm.scalars(select(Trip).where(Trip.id == trip_id, can_see(viewer))).first()


def visible_segments(conn: db.Connection, viewer: Viewer, trip_ids: Sequence[int] | None = None) -> list[Segment]:
    """The segments of the viewer's trips (of these trips, when given), by id."""
    q = select(Segment).join(Trip, Trip.id == Segment.trip_id).where(can_see(viewer))
    if trip_ids is not None:
        q = q.where(Segment.trip_id.in_(list(trip_ids)))
    return list(conn.orm.scalars(q.order_by(Segment.id)).all())


def visible_segment(conn: db.Connection, viewer: Viewer, segment_id: int) -> Segment | None:
    """The segment, or None when there's none by that id or its trip isn't the viewer's."""
    return conn.orm.scalars(select(Segment).join(Trip, Trip.id == Segment.trip_id)
                            .where(Segment.id == segment_id, can_see(viewer))).first()


def visible_travelers(conn: db.Connection, viewer: Viewer, segment_ids: Sequence[int]) -> list[SegmentTraveler]:
    """Who is on these segments, for those among them the viewer can see."""
    return list(conn.orm.scalars(
        select(SegmentTraveler).join(Segment, Segment.id == SegmentTraveler.segment_id)
        .join(Trip, Trip.id == Segment.trip_id).where(can_see(viewer), SegmentTraveler.segment_id.in_(list(segment_ids)))
        .order_by(SegmentTraveler.id)).all())


def visible_traveler(conn: db.Connection, viewer: Viewer, traveler_id: int) -> SegmentTraveler | None:
    """Someone on a segment, or None when there's none by that id or the segment's trip isn't the viewer's."""
    return conn.orm.scalars(
        select(SegmentTraveler).join(Segment, Segment.id == SegmentTraveler.segment_id)
        .join(Trip, Trip.id == Segment.trip_id).where(can_see(viewer), SegmentTraveler.id == traveler_id)).first()


def visible_unmatched(conn: db.Connection, viewer: Viewer) -> list[SegmentTraveler]:
    """The travellers on the viewer's segments who are only a name as printed on the booking, not yet a person."""
    return list(conn.orm.scalars(
        select(SegmentTraveler).join(Segment, Segment.id == SegmentTraveler.segment_id)
        .join(Trip, Trip.id == Segment.trip_id).where(can_see(viewer), SegmentTraveler.person_id.is_(None))
        .order_by(SegmentTraveler.id)).all())


def household_segments(conn: db.Connection, kind: str) -> list[Segment]:
    """Every segment of this kind that has a confirmation code, whoever sees it. For the mail scan alone, to find the booking a
    copy of an email is about when it's already on a trip the mailbox's owner isn't on; what it finds is never shown on its
    own (`note_recipient` is what lets the owner see it), and nothing in waypoint/server/ calls it."""
    return list(conn.orm.scalars(select(Segment).where(Segment.kind == kind, Segment.confirmation.is_not(None))
                                 .order_by(Segment.id)).all())


def note_recipient(conn: db.Connection, viewer: Viewer, segment: Segment) -> bool:
    """The viewer got this booking's confirmation in their own mailbox, so they see its trip from now on: the email is
    already theirs, but the whole trip becomes visible to them (every segment and traveller on it, as for a traveller), so it
    rests on the match being right. Does nothing when they see the trip already (or aren't someone who
    can be noted). True when it noted them."""
    if viewer.household or viewer.person_id is None or visible_segment(conn, viewer, segment.id) is not None:
        return False
    db.insert_ignore(conn, SegmentRecipient, {"segment_id": segment.id, "person_id": viewer.person_id},
                     key=["segment_id", "person_id"])
    return True
