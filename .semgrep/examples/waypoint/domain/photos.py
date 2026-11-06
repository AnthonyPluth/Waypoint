# waypoint/domain/photos.py: the one module whose Photo queries are the access predicate (visible, unsettled, removed).
from sqlalchemy import select

# ok: waypoint-photo-access
rows = select(Photo, PhotoSource.person_id).join(PhotoSource, PhotoSource.id == Photo.source_id).where(visible(conn, viewer))

# ok: waypoint-photo-access
left_out = select(PhotoExclusion.asset_id).where(PhotoExclusion.asset_id == Photo.asset_id).exists()
