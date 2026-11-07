# waypoint/domain/tripstats.py: a trip's summary counts the photos the viewer may see, through photos.visible_rows, never its own query.
from sqlalchemy import delete, select, update

# ruleid: waypoint-photo-access
rows = select(Photo).where(Photo.trip_id == trip_id)

# ruleid: waypoint-photo-access
states = select(Photo.state, Photo.country).where(Photo.trip_id == trip_id)

# ruleid: waypoint-photo-access
joined = select(PhotoSource.person_id).join(Photo, Photo.source_id == PhotoSource.id)

# ruleid: waypoint-photo-access
row = conn.orm.get(Photo, photo_id)

# ruleid: waypoint-photo-access
conn.execute(update(Photo).where(Photo.id == photo_id).values(trip_id=None))

# ruleid: waypoint-photo-access
conn.execute(delete(Photo).where(Photo.trip_id == trip_id))

# ruleid: waypoint-photo-access
table = schema.photos

# ok: waypoint-photo-access
placed = photos.visible_rows(conn, viewer, trip_id)
