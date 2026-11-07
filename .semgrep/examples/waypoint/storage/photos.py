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
queried = conn.orm.query(Photo).all()

# ruleid: waypoint-photo-access
columns = conn.orm.query(Photo.id, Photo.trip_id).all()

# ruleid: waypoint-photo-access
created = insert(Photo)

# ruleid: waypoint-photo-access
ignored = db.insert_ignore(conn, Photo, rows)

# ruleid: waypoint-photo-access
added = conn.orm.add(Photo(asset_id=asset_id, source_id=source_id))

# ruleid: waypoint-photo-access
counted_where = select(func.count()).filter(Photo.trip_id == trip_id)

# ruleid: waypoint-photo-access
grouped = select(PhotoSource.id).group_by(Photo.source_id)

# ruleid: waypoint-photo-access
ordered = select(PhotoSource.id).order_by(Photo.taken_utc)

# ruleid: waypoint-photo-access
having = select(PhotoSource.id).group_by(PhotoSource.id).having(func.count(Photo.id) > 1)

# ruleid: waypoint-photo-access
distinct = select(PhotoSource.id).distinct(Photo.trip_id)

# ruleid: waypoint-photo-access
orm_filtered = conn.orm.query(PhotoSource).filter(Photo.source_id == PhotoSource.id).all()

# ruleid: waypoint-photo-access
row = Photo(asset_id=asset_id, source_id=source_id)
conn.orm.add(row)

# ruleid: waypoint-photo-access
rows = [Photo(asset_id=a, source_id=source_id) for a in assets]

# ok: waypoint-photo-access
sources = select(PhotoSource.id).where(PhotoSource.person_id == person_id)

# ok: waypoint-photo-access
granted = select(PhotoGrant.trip_id).where(PhotoGrant.person_id == person_id)
