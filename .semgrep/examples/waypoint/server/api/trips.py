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
    # ok: waypoint-trip-visibility
    trip = visibility.trip(conn, person, trip_id)
    # ok: waypoint-trip-visibility
    people = conn.execute(select(Person.id)).fetchall()
    return trip
