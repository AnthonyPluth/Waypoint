# A storage helper reads photo rows only through photos.visible, never with a query of its own.
from sqlalchemy import func, select

# ruleid: waypoint-photo-access
total = select(Photo.trip_id, func.count(Photo.id)).group_by(Photo.trip_id)

# ruleid: waypoint-photo-access
listed = select(Photo).where(Photo.source_id == source_id)

# ruleid: waypoint-photo-access
joined = select(PhotoSource.id).join(Photo, Photo.source_id == PhotoSource.id)

# ruleid: waypoint-photo-access
raw = conn.execute(text("select count(*) from photos where trip_id = :t"))

# ruleid: waypoint-photo-access
counted = select(func.count()).select_from(Photo)

# ruleid: waypoint-photo-access
filtered = select(func.count(PhotoSource.id)).where(Photo.source_id == PhotoSource.id)

# ruleid: waypoint-photo-access
nested = select(PhotoSource.id).where(PhotoSource.person_id == person_id, exists().where(Photo.source_id == PhotoSource.id))

# ruleid: waypoint-photo-access
created = insert(Photo)

# ruleid: waypoint-photo-access
ignored = db.insert_ignore(conn, Photo, rows)

# ruleid: waypoint-photo-access
added = conn.orm.add(Photo(asset_id=asset_id, source_id=source_id))

# ok: waypoint-photo-access
sources = select(PhotoSource.id).where(PhotoSource.person_id == person_id)

# ok: waypoint-photo-access
granted = select(PhotoGrant.trip_id).where(PhotoGrant.person_id == person_id)
