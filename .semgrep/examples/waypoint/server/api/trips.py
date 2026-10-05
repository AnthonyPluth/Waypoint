# Handlers read trips and segments through the visibility helper, never by querying the tables.
from sqlalchemy import delete, select, update


def api_trip(conn, _q, _b, trip_id):
    # ruleid: waypoint-trip-visibility
    row = conn.execute(select(Trip).where(Trip.id == trip_id)).fetchone()
    # ruleid: waypoint-trip-visibility
    names = conn.execute(select(Trip.name, Segment.kind)).fetchall()
    # ruleid: waypoint-trip-visibility
    trip = conn.orm.get(Trip, trip_id)
    # ruleid: waypoint-trip-visibility
    conn.execute(update(Segment).where(Segment.trip_id == trip_id).values(status="cancelled"))
    # ruleid: waypoint-trip-visibility
    conn.execute(delete(Trip).where(Trip.id == trip_id))
    # ruleid: waypoint-trip-visibility
    rows = conn.execute(select(Person.id).join(Segment, Segment.trip_id == trip_id)).fetchall()
    # ruleid: waypoint-trip-visibility
    rows = conn.execute(select(Person.id).outerjoin(Trip, Trip.id == trip_id)).fetchall()
    # ruleid: waypoint-trip-visibility
    rows = conn.orm.query(Person).all()
    # ruleid: waypoint-trip-visibility
    other = aliased(Trip)
    # ruleid: waypoint-trip-visibility
    table = schema.trips
    # ruleid: waypoint-trip-visibility
    raw = "SELECT * FROM trips WHERE id = :id"
    # ruleid: waypoint-trip-visibility
    who = conn.execute(select(SegmentTraveler.person_id).where(SegmentTraveler.segment_id == trip_id)).fetchall()
    # ruleid: waypoint-trip-visibility
    legs = conn.orm.scalars(select(Segment).where(Segment.kind == "flight")).all()
    # ok: waypoint-trip-visibility
    trip = visibility.visible_trip(conn, viewer, trip_id)
    # ok: waypoint-trip-visibility
    mine = visibility.visible_trips(conn, viewer)
    # ok: waypoint-trip-visibility
    shown = trips.get(conn, viewer, trip_id)
    # ok: waypoint-trip-visibility
    label = "Trips you're on"
    # ok: waypoint-trip-visibility
    people = conn.execute(select(Person.id)).fetchall()
    return trip
