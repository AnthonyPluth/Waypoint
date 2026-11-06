from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from typing import Literal, TypedDict

from sqlalchemy import and_, delete, or_, select, update

from .. import oidc
from ..storage import db
from ..storage.models import Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, PhotoTripSync, Trip, TripPerson, User
from . import people, photoqueue, photos, trippeople, visibility
from .photos import AMBIGUOUS, ONLY_ME, OWNER, SCOPES, Scope
from .visibility import Viewer

State = Literal["shared", "declined", "ask", "none"]
SHARED: State = "shared"
DECLINED: State = "declined"
NONE: State = "none"


class Prefs(TypedDict):
    default_scope: Scope
    share_all: bool


class Sharing(TypedDict):
    state: State
    scope: Scope | None
    count: int
    removed_count: int
    removed: list[photos.TripPhoto]


class GrantedTrip(TypedDict):
    trip_id: int
    name: str
    start_date: str | None
    end_date: str | None
    state: Literal["shared", "declined"]
    scope: Scope | None
    count: int
    removed_count: int


class PersonGrants(TypedDict):
    person_id: int
    prefs: Prefs
    trips: list[GrantedTrip]


class Grants(TypedDict):
    people: list[PersonGrants]


def lock(conn: db.Connection, person_id: int, trip_ids: Iterable[int]) -> dict[int, PhotoGrant]:
    ids = sorted(set(trip_ids))
    rows = conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.person_id == person_id, PhotoGrant.trip_id.in_(ids))
                            .order_by(PhotoGrant.trip_id).with_for_update()).all()
    return {r.trip_id: r for r in rows}


def _write(conn: db.Connection, person_id: int, trip_id: int, scope: Scope, by: str, now: float) -> None:
    row = lock(conn, person_id, [trip_id]).get(trip_id)
    if row is None:
        conn.orm.add(PhotoGrant(person_id=person_id, trip_id=trip_id, scope=scope, revoked=None, changed=now, granted_by=by))
    else:
        row.scope, row.revoked, row.changed, row.granted_by = scope, None, now, by
    conn.orm.flush()
    photoqueue.after_commit(conn, person_id, trip_id)


def _person_rows(conn: db.Connection, person_id: int, trip_ids: Sequence[int]) -> list[Photo]:
    on_trips = Photo.trip_id.in_(list(trip_ids)) if trip_ids else Photo.trip_id.is_(None)
    q = select(Photo).join(PhotoSource, PhotoSource.id == Photo.source_id) \
        .where(PhotoSource.person_id == person_id, or_(on_trips, and_(Photo.trip_id.is_(None), Photo.match == AMBIGUOUS))).order_by(Photo.id)
    return list(conn.orm.scalars(q).all())


def _re_place(conn: db.Connection, person_id: int, trip_ids: Sequence[int]) -> None:
    for row in _person_rows(conn, person_id, trip_ids):
        photos.re_place(conn, row, person_id)


def _drop_derived(conn: db.Connection, person_id: int, trip_id: int) -> None:
    sources = select(PhotoSource.id).where(PhotoSource.person_id == person_id)
    conn.execute(delete(PhotoTripSync).where(PhotoTripSync.source_id.in_(sources), PhotoTripSync.trip_id == trip_id))
    _re_place(conn, person_id, [trip_id])


def _stop(conn: db.Connection, person_id: int, trip_id: int, by: str, now: float) -> None:
    row = lock(conn, person_id, [trip_id]).get(trip_id)
    if row is None:
        conn.orm.add(PhotoGrant(person_id=person_id, trip_id=trip_id, scope=ONLY_ME, revoked=now, changed=now, granted_by=by))
    else:
        row.revoked, row.changed, row.granted_by = now, now, by
    conn.orm.flush()
    _drop_derived(conn, person_id, trip_id)


def _acting(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int) -> tuple[Trip, str] | None:
    if viewer.household or not photos.acts_for(conn, viewer, person_id):
        return None
    trip, by = visibility.visible_trip(conn, viewer, trip_id), photos.viewer_sub(conn, viewer)
    return (trip, by) if trip is not None and by is not None else None


def sharing(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int) -> Sharing:
    row = conn.orm.get(PhotoGrant, (person_id, trip_id))
    placed = photos.segment_points(conn, visibility.visible_segments(conn, viewer, [trip_id]))
    gone = [photos.photo_out(p, person, placed) for p, person in photos.removed(conn, viewer, trip_id) if person == person_id]
    count = sum(1 for _, person in photos.visible_rows(conn, viewer, trip_id) if person == person_id)
    state: State = NONE if row is None else SHARED if row.revoked is None else DECLINED
    return {"state": state, "scope": row.scope if row is not None and row.revoked is None else None,  # type: ignore[typeddict-item]
            "count": count, "removed_count": len(gone), "removed": gone}


def state_of(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int) -> Sharing | None:
    if viewer.household or not photos.acts_for(conn, viewer, person_id) or visibility.visible_trip(conn, viewer, trip_id) is None:
        return None
    return sharing(conn, viewer, person_id, trip_id)


def grant(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, scope: Scope, now: float | None = None) -> Sharing | None:
    acting = _acting(conn, viewer, person_id, trip_id)
    if acting is None or scope not in SCOPES:
        return None
    trip, by = acting
    if person_id not in trippeople.of(conn, [trip.id])[trip.id]:
        return None
    _write(conn, person_id, trip.id, scope, by, time.time() if now is None else now)
    return sharing(conn, viewer, person_id, trip.id)


def stop(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, now: float | None = None) -> Sharing | None:
    acting = _acting(conn, viewer, person_id, trip_id)
    if acting is None:
        return None
    trip, by = acting
    if conn.orm.get(PhotoGrant, (person_id, trip.id)) is None and person_id not in trippeople.of(conn, [trip.id])[trip.id]:
        return None
    _stop(conn, person_id, trip.id, by, time.time() if now is None else now)
    return sharing(conn, viewer, person_id, trip.id)


def exclude(conn: db.Connection, viewer: Viewer, trip_id: int, photo_ids: Sequence[int], now: float | None = None) -> Sharing | None:
    if viewer.household or visibility.visible_trip(conn, viewer, trip_id) is None or not photo_ids:
        return None
    found: list[tuple[Photo, int]] = []
    for photo_id in dict.fromkeys(photo_ids):
        row = photos.visible_photo(conn, viewer, photo_id)
        if row is None or row[0].trip_id != trip_id or not photos.acts_for(conn, viewer, row[1]):
            return None
        found.append(row)
    stamp = time.time() if now is None else now
    for person in sorted({person for _, person in found}):
        lock(conn, person, [trip_id])
    for photo, person in found:
        db.insert_ignore(conn, PhotoExclusion, {"person_id": person, "asset_id": photo.asset_id, "trip_id": trip_id, "created": stamp},
                         key=["person_id", "asset_id", "trip_id"])
    for photo, person in found:
        photos.re_place(conn, photo, person)
    return sharing(conn, viewer, found[0][1], trip_id)


def put_back(conn: db.Connection, viewer: Viewer, trip_id: int, photo_id: int) -> Sharing | None:
    if viewer.household:
        return None
    found = next(((p, person) for p, person in photos.removed(conn, viewer, trip_id) if p.id == photo_id), None)
    if found is None:
        return None
    photo, person = found
    lock(conn, person, [trip_id])
    conn.execute(delete(PhotoExclusion).where(PhotoExclusion.person_id == person, PhotoExclusion.asset_id == photo.asset_id, PhotoExclusion.trip_id == trip_id))
    if not (photo.decided_by == OWNER and photo.trip_id not in (None, trip_id)):
        photos.re_place(conn, photo, person)
    photoqueue.after_commit(conn, person, trip_id)
    return sharing(conn, viewer, person, trip_id)


def prefs_of(conn: db.Connection, person_id: int) -> Prefs:
    row = conn.orm.get(PhotoSharingPrefs, person_id)
    if row is None:
        return {"default_scope": ONLY_ME, "share_all": False}
    return {"default_scope": row.default_scope, "share_all": row.share_all}  # type: ignore[typeddict-item]


def _setter(conn: db.Connection, sub: str | None) -> Viewer | None:
    person = people.person_for_sub(conn, sub) if sub else None
    return Viewer(person) if person is not None else None


def _share_all(conn: db.Connection, person_id: int, by: str, scope: Scope, now: float) -> int:
    setter = _setter(conn, by)
    if setter is None:
        return 0
    seen = visibility.visible_trips(conn, setter)
    aboard = trippeople.of(conn, [t.id for t in seen])
    mine = [t.id for t in seen if person_id in aboard[t.id]]
    rows = lock(conn, person_id, mine)
    written = 0
    for trip_id in mine:
        row = rows.get(trip_id)
        if row is None or row.revoked is not None:
            _write(conn, person_id, trip_id, scope, by, now)
            written += 1
    return written


def set_prefs(conn: db.Connection, viewer: Viewer, person_id: int, default_scope: Scope | None, share_all: bool | None,
              now: float | None = None) -> Prefs | None:
    if viewer.household or not photos.acts_for(conn, viewer, person_id):
        return None
    by = photos.viewer_sub(conn, viewer)
    if by is None or (default_scope is not None and default_scope not in SCOPES):
        return None
    row = conn.orm.get(PhotoSharingPrefs, person_id)
    if row is None:
        row = PhotoSharingPrefs(person_id=person_id, default_scope=ONLY_ME, share_all=False, set_by=None)
        conn.orm.add(row)
    was_on = row.share_all
    if default_scope is not None:
        row.default_scope = default_scope
    if share_all is not None:
        row.share_all = share_all
    if share_all and not was_on:
        row.set_by = by
        conn.orm.flush()
        _share_all(conn, person_id, by, row.default_scope, time.time() if now is None else now)  # type: ignore[arg-type]
    conn.orm.flush()
    return prefs_of(conn, person_id)


def joined(conn: db.Connection, person_id: int, trip_id: int, now: float | None = None) -> bool:
    row = conn.orm.get(PhotoSharingPrefs, person_id)
    if row is None or not row.share_all or row.set_by is None:
        return False
    setter = _setter(conn, row.set_by)
    if setter is None or visibility.visible_trip(conn, setter, trip_id) is None:
        return False
    if lock(conn, person_id, [trip_id]):
        return False
    _write(conn, person_id, trip_id, row.default_scope, row.set_by, time.time() if now is None else now)  # type: ignore[arg-type]
    return True


def _unseen(conn: db.Connection, trip_id: int) -> list[PhotoGrant]:
    gone: list[PhotoGrant] = []
    for g in conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.trip_id == trip_id, PhotoGrant.revoked.is_(None)).order_by(PhotoGrant.person_id)).all():
        setter = _setter(conn, g.granted_by)
        if setter is not None and visibility.visible_trip(conn, setter, trip_id) is None:
            gone.append(g)
    return gone


def reconcile(conn: db.Connection, trip_id: int, now: float | None = None) -> int:
    stamp = time.time() if now is None else now
    for g in _unseen(conn, trip_id):
        left(conn, g.person_id, trip_id)
    return sum(1 for person in trippeople.of(conn, [trip_id])[trip_id] if joined(conn, person, trip_id, stamp))


def reconcile_all(conn: db.Connection, now: float | None = None) -> int:
    standing = select(PhotoSharingPrefs.person_id).where(PhotoSharingPrefs.share_all.is_(True))
    trip_ids = set(conn.execute(select(TripPerson.trip_id).where(TripPerson.person_id.in_(standing))).scalars())
    trip_ids |= set(conn.execute(select(PhotoGrant.trip_id).where(PhotoGrant.revoked.is_(None))).scalars())
    return sum(reconcile(conn, trip_id, now) for trip_id in sorted(trip_ids))


def left(conn: db.Connection, person_id: int, trip_id: int) -> None:
    lock(conn, person_id, [trip_id])
    conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == person_id, PhotoGrant.trip_id == trip_id))
    _drop_derived(conn, person_id, trip_id)


def _photo_people(conn: db.Connection, trip_id: int) -> set[int]:
    granted = set(conn.execute(select(PhotoGrant.person_id).where(PhotoGrant.trip_id == trip_id)).scalars())
    placed = set(conn.execute(select(PhotoSource.person_id).join(Photo, Photo.source_id == PhotoSource.id).where(Photo.trip_id == trip_id)).scalars())
    return granted | placed


def trips_changed(conn: db.Connection, trip_ids: Iterable[int], now: float | None = None) -> None:
    stamp = time.time() if now is None else now
    for trip_id in [t for t in sorted(set(trip_ids)) if conn.orm.get(Trip, t) is not None]:
        aboard = set(trippeople.of(conn, [trip_id])[trip_id])
        for person in sorted(_photo_people(conn, trip_id) - aboard):
            left(conn, person, trip_id)
        reconcile(conn, trip_id, stamp)


def merged(conn: db.Connection, kept: int, gone: int) -> None:
    for e in conn.orm.scalars(select(PhotoExclusion).where(PhotoExclusion.trip_id == gone).order_by(PhotoExclusion.person_id, PhotoExclusion.asset_id)).all():
        db.insert_ignore(conn, PhotoExclusion, {"person_id": e.person_id, "asset_id": e.asset_id, "trip_id": kept, "created": e.created},
                         key=["person_id", "asset_id", "trip_id"])
    trip_deleted(conn, gone)


def trip_deleted(conn: db.Connection, trip_id: int) -> None:
    granted = set(conn.execute(select(PhotoGrant.person_id).where(PhotoGrant.trip_id == trip_id)).scalars())
    placed = set(conn.execute(select(PhotoSource.person_id).join(Photo, Photo.source_id == PhotoSource.id).where(Photo.trip_id == trip_id)).scalars())
    for person in sorted(granted | placed):
        lock(conn, person, [trip_id])
    conn.execute(delete(PhotoGrant).where(PhotoGrant.trip_id == trip_id))
    conn.execute(delete(PhotoExclusion).where(PhotoExclusion.trip_id == trip_id))
    conn.execute(delete(PhotoTripSync).where(PhotoTripSync.trip_id == trip_id))
    for person in sorted(granted | placed):
        _re_place(conn, person, [trip_id])


def _lapsed(conn: db.Connection, sub: str, now: float) -> bool:
    email = conn.execute(select(User.email).where(User.sub == sub)).scalar()
    return oidc.access_lapsed(conn, sub, email, now) is not None


def end_lapsed(conn: db.Connection, now: float | None = None) -> int:
    stamp = time.time() if now is None else now
    active = list(conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.revoked.is_(None)).order_by(PhotoGrant.person_id, PhotoGrant.trip_id)).all())
    standing = list(conn.orm.scalars(select(PhotoSharingPrefs).where(PhotoSharingPrefs.share_all.is_(True))).all())
    subs = {g.granted_by for g in active} | {p.set_by for p in standing if p.set_by}
    gone = {s for s in sorted(subs) if _lapsed(conn, s, stamp)}
    ended = 0
    for g in [g for g in active if g.granted_by in gone]:
        _stop(conn, g.person_id, g.trip_id, g.granted_by, stamp)
        ended += 1
    for p in [p for p in standing if p.set_by in gone]:
        p.share_all = False
        ended += 1
    conn.orm.flush()
    return ended


def claim(conn: db.Connection, guest_id: int, member_id: int, sub: str) -> None:
    have = select(PhotoGrant.trip_id).where(PhotoGrant.person_id == member_id)
    conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == guest_id, PhotoGrant.trip_id.in_(have)))
    conn.execute(update(PhotoGrant).where(PhotoGrant.person_id == guest_id).values(person_id=member_id, granted_by=sub))
    for e in conn.orm.scalars(select(PhotoExclusion).where(PhotoExclusion.person_id == guest_id)).all():
        db.insert_ignore(conn, PhotoExclusion, {"person_id": member_id, "asset_id": e.asset_id, "trip_id": e.trip_id, "created": e.created},
                         key=["person_id", "asset_id", "trip_id"])
    if conn.orm.get(PhotoSharingPrefs, member_id) is None:
        conn.execute(update(PhotoSharingPrefs).where(PhotoSharingPrefs.person_id == guest_id)
                     .values(person_id=member_id, set_by=sub if conn.orm.get(PhotoSharingPrefs, guest_id) is not None else None))
    urls = select(PhotoSource.url).where(PhotoSource.person_id == member_id)
    conn.execute(update(PhotoSource).where(PhotoSource.person_id == guest_id, PhotoSource.url.not_in(urls)).values(person_id=member_id, owner_sub=sub))
    conn.orm.expire_all()


def grants(conn: db.Connection, viewer: Viewer) -> Grants:
    if viewer.household:
        return {"people": []}
    out: list[PersonGrants] = []
    seen = {t.id: t for t in visibility.visible_trips(conn, viewer)}
    for person in photos.persons_of(conn, viewer):
        rows = conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.person_id == person, PhotoGrant.trip_id.in_(list(seen))).order_by(PhotoGrant.trip_id)).all()
        listed: list[GrantedTrip] = []
        for row in rows:
            trip, state = seen[row.trip_id], sharing(conn, viewer, person, row.trip_id)
            listed.append({"trip_id": trip.id, "name": trip.name, "start_date": trip.start_date, "end_date": trip.end_date,
                           "state": "shared" if row.revoked is None else "declined", "scope": state["scope"],
                           "count": state["count"], "removed_count": state["removed_count"]})
        listed.sort(key=lambda t: (t["start_date"] is None, t["start_date"] or "", t["trip_id"]))
        out.append({"person_id": person, "prefs": prefs_of(conn, person), "trips": listed})
    return {"people": out}
