from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from sqlalchemy import ColumnElement, delete, exists, func, select, true, update

from . import db, secretbox
from .models import Person, Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, User

Status = Literal["ok", "refused", "unreachable", "off"]
OK: Status = "ok"
REFUSED: Status = "refused"
UNREACHABLE: Status = "unreachable"
OFF: Status = "off"
STATUSES: tuple[Status, ...] = (OK, REFUSED, UNREACHABLE, OFF)
ON_A_TRIP = ("place", "time", "far")


class Stored(TypedDict):
    id: int
    person_id: int
    owner_sub: str
    url: str
    immich_user_id: str
    label: str | None
    status: Status
    last_sync: float | None
    last_error: str | None
    created: float


@dataclass(frozen=True)
class Unlocked:
    id: int
    url: str = field(repr=False)
    key: str = field(repr=False)
    user_id: str = field(repr=False)


COLUMNS = (PhotoSource.id, PhotoSource.person_id, PhotoSource.owner_sub, PhotoSource.url, PhotoSource.immich_user_id, PhotoSource.label,
           PhotoSource.status, PhotoSource.last_sync, PhotoSource.last_error, PhotoSource.created)


def _stored(row: dict) -> Stored:
    status = row["status"] if row["status"] in STATUSES else UNREACHABLE
    return {"id": int(row["id"]), "person_id": int(row["person_id"]), "owner_sub": str(row["owner_sub"]), "url": str(row["url"]),
            "immich_user_id": str(row["immich_user_id"]), "label": row["label"], "status": status, "last_sync": row["last_sync"],
            "last_error": row["last_error"], "created": float(row["created"])}


def list_all(conn: db.Connection) -> list[Stored]:
    return [_stored(r) for r in db.rows(conn.execute(select(*COLUMNS).order_by(PhotoSource.id)))]


def get(conn: db.Connection, source_id: int) -> Stored | None:
    row = conn.execute(select(*COLUMNS).where(PhotoSource.id == source_id)).fetchone()
    return _stored(dict(row)) if row is not None else None


def for_person(conn: db.Connection, person_id: int) -> list[Stored]:
    return [_stored(r) for r in db.rows(conn.execute(select(*COLUMNS).where(PhotoSource.person_id == person_id).order_by(PhotoSource.id)))]


def lock_person(conn: db.Connection, person_id: int) -> bool:
    return int(conn.execute(update(Person).where(Person.id == person_id).values(display_name=Person.display_name)).rowcount) > 0


def steward_of(conn: db.Connection, person_id: int) -> str | None:
    found = conn.execute(select(PhotoSharingPrefs.steward_sub).where(PhotoSharingPrefs.person_id == person_id)).scalar()
    return str(found) if found is not None else None


def set_steward(conn: db.Connection, person_id: int, sub: str) -> bool:
    db.insert_ignore(conn, PhotoSharingPrefs, {"person_id": person_id, "steward_sub": sub}, key=["person_id"])
    conn.execute(update(PhotoSharingPrefs).where(PhotoSharingPrefs.person_id == person_id, PhotoSharingPrefs.steward_sub.is_(None)).values(steward_sub=sub))
    return steward_of(conn, person_id) == sub


def trip_shared(conn: db.Connection, person_id: int) -> bool:
    return conn.execute(select(PhotoGrant.trip_id).where(PhotoGrant.person_id == person_id, PhotoGrant.scope == "trip", PhotoGrant.revoked.is_(None))
                        .limit(1)).fetchone() is not None


def save(conn: db.Connection, person_id: int, owner_sub: str, url: str, immich_user_id: str, key: str, label: str | None, now: float,
         status: Status = OK) -> int | None:
    values = {"person_id": person_id, "owner_sub": owner_sub, "url": url, "immich_user_id": immich_user_id, "api_key": secretbox.encrypt(key) or "",
              "label": label, "status": status, "last_sync": None, "last_error": None, "created": now}
    if db.insert_ignore(conn, PhotoSource, values, key=["person_id", "url", "immich_user_id"]).rowcount == 0:
        return None
    found = conn.execute(select(PhotoSource.id).where(PhotoSource.person_id == person_id, PhotoSource.url == url, PhotoSource.immich_user_id == immich_user_id,
                                                      PhotoSource.owner_sub == owner_sub)).scalar()
    return int(found) if found is not None else None


def _held_by(source_id: int, owner: str | None) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return PhotoSource.id == source_id, PhotoSource.owner_sub == owner if owner is not None else true()


def set_key(conn: db.Connection, source_id: int, key: str, owner: str | None = None) -> bool:
    return int(conn.execute(update(PhotoSource).where(*_held_by(source_id, owner)).values(api_key=secretbox.encrypt(key) or "")).rowcount) > 0


def set_label(conn: db.Connection, source_id: int, label: str | None, owner: str | None = None) -> bool:
    return int(conn.execute(update(PhotoSource).where(*_held_by(source_id, owner)).values(label=label)).rowcount) > 0


def mark(conn: db.Connection, source_id: int, status: Status, error: str | None = None, synced: float | None = None,
         owner: str | None = None, *, keep_off: bool = False, sealed: str | None = None, was: tuple[Status, str | None] | None = None) -> bool:
    values: dict[str, object] = {"status": status, "last_error": error}
    if synced is not None:
        values["last_sync"] = synced
    paused = [PhotoSource.status != OFF] if keep_off else []
    same_key = [PhotoSource.api_key == sealed] if sealed is not None else []
    unchanged = [] if was is None else [PhotoSource.status == was[0], PhotoSource.last_error.is_(None) if was[1] is None else PhotoSource.last_error == was[1]]
    return int(conn.execute(update(PhotoSource).where(*_held_by(source_id, owner), *paused, *same_key, *unchanged).values(**values)).rowcount) > 0


def status(conn: db.Connection, source_id: int) -> Status | None:
    found = conn.execute(select(PhotoSource.status).where(PhotoSource.id == source_id)).scalar()
    return found if found in STATUSES else None


def sealed_key(conn: db.Connection, source_id: int) -> str | None:
    found = conn.execute(select(PhotoSource.api_key).where(PhotoSource.id == source_id)).scalar()
    return str(found) if found is not None else None


def remove(conn: db.Connection, source_id: int, owner: str | None = None) -> bool:
    return int(conn.execute(delete(PhotoSource).where(*_held_by(source_id, owner))).rowcount) > 0


def source_for_provider(conn: db.Connection, source_id: int) -> Unlocked | None:
    row = conn.execute(select(PhotoSource.id, PhotoSource.url, PhotoSource.api_key, PhotoSource.immich_user_id)
                       .where(PhotoSource.id == source_id)).fetchone()
    if row is None:
        return None
    return Unlocked(id=int(row["id"]), url=str(row["url"]), key=secretbox.decrypt(row["api_key"]) or "", user_id=str(row["immich_user_id"]))


def counts(conn: db.Connection) -> dict[int, tuple[int, int]]:
    removed = exists().where(PhotoExclusion.person_id == PhotoSource.person_id, PhotoExclusion.asset_id == Photo.asset_id,   # nosemgrep: waypoint-photo-access -- the per-source counts, which domain/photosources.py shows only to those who act for the source's person
                             PhotoExclusion.trip_id == Photo.trip_id)
    rows = conn.execute(select(Photo.source_id, func.count(Photo.id), func.count(Photo.trip_id.distinct()))   # nosemgrep: waypoint-photo-access -- the per-source counts, which domain/photosources.py shows only to those who act for the source's person
                        .join(PhotoSource, PhotoSource.id == Photo.source_id)
                        .where(Photo.trip_id.is_not(None), Photo.match.in_(ON_A_TRIP), ~removed).group_by(Photo.source_id)).fetchall()
    return {int(r[0]): (int(r[1]), int(r[2])) for r in rows}


def lock_owner(conn: db.Connection, sub: str) -> bool:
    return int(conn.execute(update(User).where(User.sub == sub).values(name=User.name)).rowcount) > 0
