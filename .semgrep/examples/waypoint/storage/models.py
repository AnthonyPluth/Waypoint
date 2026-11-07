# waypoint/storage/models.py is scanned like the rest of storage: only the table's mapping line carries a nosemgrep.
from sqlalchemy import select


class Photo:
    # ok: waypoint-photo-access
    __table__ = schema.photos  # nosemgrep: waypoint-photo-access -- the table's mapping, which is the one place models.py names it


class Elsewhere:
    # ruleid: waypoint-photo-access
    __table__ = schema.photos


# ruleid: waypoint-photo-access
listed = select(Photo.id)
