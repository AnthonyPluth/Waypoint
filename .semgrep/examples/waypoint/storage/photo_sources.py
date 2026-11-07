# waypoint/storage/photo_sources.py: the per-source counts that domain/photosources.py shows only to those who act for the person.
from sqlalchemy import func, select

# ok: waypoint-photo-access
rows = select(Photo.source_id, func.count(Photo.id)).group_by(Photo.source_id)  # nosemgrep: waypoint-photo-access -- the per-source counts

# ruleid: waypoint-photo-access
unjustified = select(Photo.source_id, func.count(Photo.id)).group_by(Photo.source_id)
