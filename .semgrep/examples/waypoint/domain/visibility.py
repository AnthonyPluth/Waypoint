# waypoint/domain/visibility.py: the helper every trip and segment query goes through (domain code isn't server code).
from sqlalchemy import select

# ok: waypoint-trip-visibility
trips = select(Trip).where(Trip.id.in_(visible_ids))

# ok: waypoint-trip-visibility
listed = select(TripPerson.trip_id).where(TripPerson.person_id == me)
