# waypoint/domain/booking_moves.py: moving bookings between trips, which only trips._relocate may do.
from sqlalchemy import update


def move(conn, seg, target):
    # ruleid: waypoint-booking-changes-trip
    conn.execute(update(Segment).where(Segment.id == seg.id).values(trip_id=target.id))
    # ruleid: waypoint-booking-changes-trip
    seg.trip_id = target.id
    # ok: waypoint-booking-changes-trip
    _relocate(conn, [seg.id], seg.trip_id, target)
    # ok: waypoint-booking-changes-trip
    conn.execute(update(Segment).where(Segment.id == seg.id).values(status="cancelled"))


def _relocate(conn, segment_ids, source_id, target):
    # ok: waypoint-booking-changes-trip
    conn.execute(update(Segment).where(Segment.id.in_(segment_ids)).values(trip_id=target.id))
