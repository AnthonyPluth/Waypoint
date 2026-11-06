from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict

from sqlalchemy import and_, delete, or_, select, update

from .. import oidc
from ..storage import db
from ..storage.models import Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, PhotoTripSync, Segment, SegmentRecipient, Trip, TripPerson, User
from . import people, photoqueue, photos, trippeople, visibility
from .visibility import Viewer

if TYPE_CHECKING:
    from .photomatch import SegmentPoint, TripWindow

State = Literal["shared", "declined", "ask", "none"]
SHARED: State = "shared"
DECLINED: State = "declined"
ASK: State = "ask"
NONE: State = "none"


STALE_SHARE = "The trip changed. Review who sees your photos under Your photos on this trip."
STALE_REMOVAL = "The trip changed since that photo was removed. Open the removed list again."
STALE_SETTING = "Your trips changed. Review them before sharing on all."


class Stale(Exception):
    pass


def _window_matches(conn: db.Connection, trip_id: int, window: Mapping[str, str]) -> bool:
    return photos.window_out(photos.trip_window(conn, trip_id)) == {"start": window.get("start"), "end": window.get("end")}


class Prefs(TypedDict):
    default_scope: photos.Scope
    share_all: bool


class Sharing(TypedDict):
    state: State
    scope: photos.Scope | None
    count: int
    removed_count: int
    removed: list[photos.TripPhoto]
    window: photos.WindowOut | None
    changed: float | None


class GrantedTrip(TypedDict):
    trip_id: int
    name: str
    start_date: str | None
    end_date: str | None
    state: Literal["shared", "declined"]
    scope: photos.Scope | None
    count: int
    removed_count: int


class PersonGrants(TypedDict):
    person_id: int
    prefs: Prefs
    trips: list[GrantedTrip]


class Grants(TypedDict):
    people: list[PersonGrants]


def lock(conn: db.Connection, person_id: int, trip_ids: Iterable[int]) -> dict[int, PhotoGrant]:
    return photos.lock_grants(conn, person_id, trip_ids)


def _lock_trip(conn: db.Connection, trip_id: int) -> bool:
    return int(conn.execute(update(Trip).where(Trip.id == trip_id).values(name=Trip.name)).rowcount) > 0


def _aboard_under_lock(conn: db.Connection, person_id: int, trip_id: int) -> bool:
    return _lock_trip(conn, trip_id) and person_id in trippeople.of(conn, [trip_id])[trip_id]


KEY = ["person_id", "trip_id"]


def _upsert_grant(conn: db.Connection, person_id: int, trip_id: int, scope: photos.Scope, by: str, now: float) -> None:
    db.upsert(conn, PhotoGrant, {"person_id": person_id, "trip_id": trip_id, "scope": scope, "revoked": None, "changed": now, "granted_by": by, "ask_again": False}, key=KEY)


def _write(conn: db.Connection, person_id: int, trip_id: int, scope: photos.Scope, by: str, now: float) -> None:
    lock(conn, person_id, [trip_id])
    _upsert_grant(conn, person_id, trip_id, scope, by, now)
    photoqueue.after_commit(conn, person_id, trip_id)


def _person_rows(conn: db.Connection, person_id: int, trip_ids: Sequence[int]) -> list[Photo]:
    on_trips = Photo.trip_id.in_(list(trip_ids)) if trip_ids else Photo.trip_id.is_(None)
    q = select(Photo).join(PhotoSource, PhotoSource.id == Photo.source_id) \
        .where(PhotoSource.person_id == person_id, or_(on_trips, and_(Photo.trip_id.is_(None), Photo.match.in_([photos.AMBIGUOUS, photos.HOME])))).order_by(Photo.id)
    return list(conn.orm.scalars(q).all())


def _re_place(conn: db.Connection, person_id: int, trip_ids: Sequence[int]) -> None:
    rows = _person_rows(conn, person_id, trip_ids)
    if not rows:
        return
    windows, at_home = photos.candidate_windows(conn, person_id), photos.home_in(conn)
    for row in rows:
        photos.re_place(conn, row, person_id, windows, home=at_home)


def _sweep_home(conn: db.Connection, person_id: int) -> None:
    windows = photos.candidate_windows(conn, person_id)
    q = select(Photo).join(PhotoSource, PhotoSource.id == Photo.source_id) \
        .where(PhotoSource.person_id == person_id, Photo.trip_id.is_(None), Photo.match == photos.HOME).order_by(Photo.id)
    for row in conn.orm.scalars(q).all():
        taken = photos.instant(row.taken_utc)
        if not any(w.start <= taken <= w.end for w in windows):
            conn.orm.delete(row)
    conn.orm.flush()


def _drop_derived(conn: db.Connection, person_id: int, trip_id: int) -> None:
    sources = select(PhotoSource.id).where(PhotoSource.person_id == person_id)
    conn.execute(delete(PhotoTripSync).where(PhotoTripSync.source_id.in_(sources), PhotoTripSync.trip_id == trip_id))
    _re_place(conn, person_id, [trip_id])
    _sweep_home(conn, person_id)


def _stop(conn: db.Connection, person_id: int, trip_id: int, by: str, now: float) -> None:
    lock(conn, person_id, [trip_id])
    db.upsert(conn, PhotoGrant, {"person_id": person_id, "trip_id": trip_id, "scope": photos.ONLY_ME, "revoked": now, "changed": now, "granted_by": by, "ask_again": False},
              key=KEY, update=["revoked", "changed", "granted_by", "ask_again"])
    _drop_derived(conn, person_id, trip_id)


def _end(conn: db.Connection, person_id: int, trip_id: int) -> None:
    lock(conn, person_id, [trip_id])
    conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == person_id, PhotoGrant.trip_id == trip_id))
    _drop_derived(conn, person_id, trip_id)


def _acting(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int) -> tuple[Trip, str] | None:
    if viewer.household or not photos.acts_for(conn, viewer, person_id):
        return None
    if not people.lock(conn, person_id) or not photos.acts_for(conn, viewer, person_id):
        return None
    trip, by = visibility.visible_trip(conn, viewer, trip_id), photos.viewer_sub(conn, viewer)
    return (trip, by) if trip is not None and by is not None else None


def lock_trips(conn: db.Connection, trip_ids: Iterable[int]) -> list[int]:
    return [trip_id for trip_id in sorted(set(trip_ids)) if _lock_trip(conn, trip_id)]


def lock_trips_of(conn: db.Connection, *person_ids: int) -> list[int]:
    return lock_trips(conn, {t for person_id in person_ids for t in _reachable(conn, person_id)})


def dated_trips(conn: db.Connection) -> list[int]:
    booked = select(Segment.trip_id)
    return list(conn.execute(select(Trip.id).where(Trip.start_date.is_not(None), Trip.end_date.is_not(None), Trip.id.not_in(booked)).order_by(Trip.id)).scalars())


def sharing(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int) -> Sharing:
    row = conn.orm.get(PhotoGrant, (person_id, trip_id))
    placed = photos.segment_points(conn, visibility.visible_segments(conn, viewer, [trip_id]))
    gone = [photos.photo_out(p, person, placed) for p, person in photos.removed(conn, viewer, trip_id) if person == person_id]
    count = sum(1 for _, person in photos.visible_rows(conn, viewer, trip_id) if person == person_id)
    state: State = NONE if row is None else DECLINED if row.revoked is not None else ASK if row.ask_again else SHARED
    return {"state": state, "scope": row.scope if row is not None and row.revoked is None else None,  # type: ignore[typeddict-item]
            "count": count, "removed_count": len(gone), "removed": gone, "window": photos.window_out(photos.trip_window(conn, trip_id)),
            "changed": row.changed if row is not None else None}


def state_of(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int) -> Sharing | None:
    if viewer.household or not photos.acts_for(conn, viewer, person_id) or visibility.visible_trip(conn, viewer, trip_id) is None:
        return None
    return sharing(conn, viewer, person_id, trip_id)


def grant(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, scope: photos.Scope, now: float | None = None,
          window: Mapping[str, str] | None = None, expected_changed: float | None = None) -> Sharing | None:
    acting = _acting(conn, viewer, person_id, trip_id)
    if acting is None or scope not in photos.SCOPES:
        return None
    trip, by = acting
    if not _aboard_under_lock(conn, person_id, trip.id) or visibility.visible_trip(conn, viewer, trip.id) is None:
        return None
    if window is not None and not _window_matches(conn, trip.id, window):
        raise Stale(STALE_SHARE)
    row = lock(conn, person_id, [trip.id]).get(trip.id)
    if expected_changed is not None and (row is None or row.changed != expected_changed):
        raise Stale(STALE_SHARE)
    _write(conn, person_id, trip.id, scope, by, time.time() if now is None else now)
    return sharing(conn, viewer, person_id, trip.id)


def stop(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, now: float | None = None) -> Sharing | None:
    acting = _acting(conn, viewer, person_id, trip_id)
    if acting is None:
        return None
    trip, by = acting
    if not _lock_trip(conn, trip.id) or (conn.orm.get(PhotoGrant, (person_id, trip.id)) is None and person_id not in trippeople.of(conn, [trip.id])[trip.id]):
        return None
    _stop(conn, person_id, trip.id, by, time.time() if now is None else now)
    return sharing(conn, viewer, person_id, trip.id)


def decline(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, now: float | None = None) -> Sharing | None:
    acting = _acting(conn, viewer, person_id, trip_id)
    if acting is None:
        return None
    trip, _ = acting
    if not _lock_trip(conn, trip.id):
        return None
    row = lock(conn, person_id, [trip.id]).get(trip.id)
    if row is None or row.revoked is not None or not row.ask_again:
        return stop(conn, viewer, person_id, trip_id, now)
    row.ask_again = False
    conn.orm.flush()
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
    persons = sorted({person for _, person in found})
    if not all(people.lock(conn, person) for person in persons) or not _lock_trip(conn, trip_id):
        return None
    for person in persons:
        lock(conn, person, [trip_id])
    conn.orm.expire_all()
    fresh: list[tuple[Photo, int]] = []
    for photo, _ in found:
        row = photos.visible_photo(conn, viewer, photo.id)
        if row is None or row[0].trip_id != trip_id or not photos.acts_for(conn, viewer, row[1]):
            return None
        fresh.append(row)
    for photo, person in fresh:
        was = photo.trip_id if photo.decided_by == photos.OWNER else None
        db.insert_ignore(conn, PhotoExclusion, {"person_id": person, "asset_id": photo.asset_id, "trip_id": trip_id, "created": stamp, "was_trip_id": was},
                         key=["person_id", "asset_id", "trip_id"])
    for photo, person in fresh:
        if photos.re_place(conn, photo, person):
            photos.copy_placement(conn, photo, person)
    return sharing(conn, viewer, fresh[0][1], trip_id)


def put_back(conn: db.Connection, viewer: Viewer, trip_id: int, photo_id: int, created: float | None = None) -> Sharing | None:
    if viewer.household:
        return None
    found = next(((p, person) for p, person in photos.removed(conn, viewer, trip_id) if p.id == photo_id), None)
    if found is None:
        return None
    photo, person = found
    involved = sorted({t for t in (trip_id, photo.trip_id) if t is not None})
    if not people.lock(conn, person) or lock_trips(conn, involved) != involved:
        return None
    lock(conn, person, involved)
    conn.orm.expire_all()
    found = next(((p, person) for p, person in photos.removed(conn, viewer, trip_id) if p.id == photo_id), None)
    if found is None:
        return None
    photo, person = found
    exclusion = conn.orm.get(PhotoExclusion, (person, photo.asset_id, trip_id))
    if created is not None and (exclusion is None or exclusion.created != created):
        raise Stale(STALE_REMOVAL)
    was = exclusion.was_trip_id if exclusion is not None else None
    conn.execute(delete(PhotoExclusion).where(PhotoExclusion.person_id == person, PhotoExclusion.asset_id == photo.asset_id, PhotoExclusion.trip_id == trip_id))
    photoqueue.after_commit(conn, person, trip_id)
    conn.orm.expire_all()
    photo = conn.orm.get(Photo, photo.id) or photo
    if photo.decided_by == photos.OWNER and photo.trip_id not in (None, trip_id):
        return sharing(conn, viewer, person, trip_id)
    if was is not None and photos.window_holds(conn, was, photo) and was in photos.granted_trips(conn, person):
        photos.place_by_hand(conn, photo, person, was)
    elif photos.re_place(conn, photo, person):
        photos.copy_placement(conn, photo, person)
    return sharing(conn, viewer, person, trip_id)


def prefs_of(conn: db.Connection, person_id: int) -> Prefs:
    row = conn.orm.get(PhotoSharingPrefs, person_id)
    if row is None:
        return {"default_scope": photos.ONLY_ME, "share_all": False}
    return {"default_scope": row.default_scope, "share_all": row.share_all}  # type: ignore[typeddict-item]


def _setter(conn: db.Connection, sub: str | None) -> Viewer | None:
    person = people.person_for_sub(conn, sub) if sub else None
    return Viewer(person) if person is not None else None


def _unshared(conn: db.Connection, person_id: int, by: str) -> list[int]:
    setter = _setter(conn, by)
    if setter is None:
        return []
    seen = visibility.visible_trips(conn, setter)
    aboard = trippeople.of(conn, [t.id for t in seen])
    pending: list[int] = []
    for trip_id in sorted(t.id for t in seen if person_id in aboard[t.id]):
        if not _aboard_under_lock(conn, person_id, trip_id) or visibility.visible_trip(conn, setter, trip_id) is None:
            continue
        row = lock(conn, person_id, [trip_id]).get(trip_id)
        if row is None or row.revoked is not None:
            pending.append(trip_id)
    return pending


def _share_all(conn: db.Connection, person_id: int, by: str, scope: photos.Scope, now: float, pending: Sequence[int]) -> int:
    for trip_id in pending:
        _upsert_grant(conn, person_id, trip_id, scope, by, now)
    return len(pending)


def set_prefs(conn: db.Connection, viewer: Viewer, person_id: int, default_scope: photos.Scope | None, share_all: bool | None,
              now: float | None = None, windows: Mapping[str, Mapping[str, str]] | None = None) -> Prefs | None:
    if viewer.household or not photos.acts_for(conn, viewer, person_id):
        return None
    by = photos.viewer_sub(conn, viewer)
    if by is None or (default_scope is not None and default_scope not in photos.SCOPES):
        return None
    if not people.lock(conn, person_id) or not photos.acts_for(conn, viewer, person_id):
        return None
    stamp = time.time() if now is None else now
    found = conn.orm.get(PhotoSharingPrefs, person_id)
    was_on = found.share_all if found is not None else False
    pending = _unshared(conn, person_id, by) if share_all and not was_on else []
    if windows is not None and any(str(t) not in windows or not _window_matches(conn, t, windows[str(t)]) for t in pending):
        raise Stale(STALE_SETTING)
    db.insert_ignore(conn, PhotoSharingPrefs, {"person_id": person_id, "default_scope": photos.ONLY_ME, "share_all": False, "set_by": None, "share_all_since": None,
                                               "steward_sub": None}, key=["person_id"])
    row = conn.orm.get(PhotoSharingPrefs, person_id, with_for_update=True)
    if row is None or row.share_all != was_on:
        return None
    if default_scope is not None:
        row.default_scope = default_scope
    if share_all is not None:
        row.share_all = share_all
    if share_all is False:
        row.share_all_since = None
    if share_all and not was_on:
        row.set_by, row.share_all_since = by, stamp
        conn.orm.flush()
        _share_all(conn, person_id, by, row.default_scope, stamp, pending)  # type: ignore[arg-type]
    conn.orm.flush()
    return prefs_of(conn, person_id)


def joined(conn: db.Connection, person_id: int, trip_id: int, now: float | None = None) -> bool:
    row = conn.orm.get(PhotoSharingPrefs, person_id)
    if row is None or not row.share_all or row.set_by is None:
        return False
    setter = _setter(conn, row.set_by)
    if setter is None or not _aboard_under_lock(conn, person_id, trip_id) or visibility.visible_trip(conn, setter, trip_id) is None:
        return False
    found = lock(conn, person_id, [trip_id]).get(trip_id)
    if found is not None and (found.revoked is None or row.share_all_since is None or found.revoked >= row.share_all_since):
        return False
    _write(conn, person_id, trip_id, row.default_scope, row.set_by, time.time() if now is None else now)  # type: ignore[arg-type]
    return True


def _lost_sight(conn: db.Connection, trip_id: int) -> list[PhotoGrant]:
    active = conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.trip_id == trip_id, PhotoGrant.revoked.is_(None)).order_by(PhotoGrant.person_id)).all()
    gone = []
    for g in active:
        setter = _setter(conn, g.granted_by)
        if setter is None or visibility.visible_trip(conn, setter, trip_id) is None:
            gone.append(g)
    return gone


def _gone(conn: db.Connection, trip_id: int) -> list[int]:
    aboard = set(trippeople.of(conn, [trip_id])[trip_id])
    holders = conn.execute(select(PhotoGrant.person_id).where(PhotoGrant.trip_id == trip_id).order_by(PhotoGrant.person_id)).scalars()
    return [p for p in holders if p not in aboard]


def reconcile(conn: db.Connection, trip_id: int, now: float | None = None) -> int:
    stamp = time.time() if now is None else now
    ended = [(p, trip_id) for p in _gone(conn, trip_id)]
    for person, trip in ended:
        _end(conn, person, trip)
    lost = [(g.person_id, g.trip_id) for g in _lost_sight(conn, trip_id)]
    for person, trip in lost:
        _end(conn, person, trip)
    return len(ended) + len(lost) + sum(1 for person in trippeople.of(conn, [trip_id])[trip_id] if joined(conn, person, trip_id, stamp))


def reconcile_all(conn: db.Connection, now: float | None = None) -> int:
    standing = select(PhotoSharingPrefs.person_id).where(PhotoSharingPrefs.share_all.is_(True))
    trip_ids = set(conn.execute(select(TripPerson.trip_id).where(TripPerson.person_id.in_(standing))).scalars())
    trip_ids |= set(conn.execute(select(PhotoGrant.trip_id).where(PhotoGrant.revoked.is_(None))).scalars())
    return sum(reconcile(conn, trip_id, now) for trip_id in sorted(trip_ids))


def left(conn: db.Connection, person_id: int, trip_id: int) -> None:
    _end(conn, person_id, trip_id)


def _grew(before: TripWindow | None, after: TripWindow | None) -> bool:
    return after is not None and (before is None or after.start < before.start or after.end > before.end)


def _shrank(before: TripWindow | None, after: TripWindow | None) -> bool:
    return before is not None and (after is None or after.start > before.start or after.end < before.end)


def _photo_people(conn: db.Connection, trip_id: int) -> set[int]:
    granted = set(conn.execute(select(PhotoGrant.person_id).where(PhotoGrant.trip_id == trip_id)).scalars())
    placed = set(conn.execute(select(PhotoSource.person_id).join(Photo, Photo.source_id == PhotoSource.id).where(Photo.trip_id == trip_id)).scalars())
    return granted | placed


class Before(NamedTuple):
    window: TripWindow | None
    people: frozenset[int]
    points: tuple[SegmentPoint, ...]


def snapshot(conn: db.Connection, trip_ids: Iterable[int]) -> dict[int, Before]:
    ids = list(dict.fromkeys(trip_ids))
    aboard = trippeople.of(conn, ids)
    return {trip_id: Before(photos.trip_window(conn, trip_id), frozenset(aboard[trip_id]), photos.trip_points(conn, trip_id)) for trip_id in ids}


def _re_place_automatic(conn: db.Connection, trip_id: int) -> None:
    found = photos.trip_window(conn, trip_id)
    for g in conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.trip_id == trip_id, PhotoGrant.revoked.is_(None)).order_by(PhotoGrant.person_id)).all():
        lock(conn, g.person_id, sorted(photos.granted_trips(conn, g.person_id) | {trip_id}))
        q = select(Photo).join(PhotoSource, PhotoSource.id == Photo.source_id).where(PhotoSource.person_id == g.person_id).order_by(Photo.id)
        for row in conn.orm.scalars(q).all():
            inside = found is not None and found.start <= photos.instant(row.taken_utc) <= found.end
            if row.decided_by != photos.OWNER and (inside or row.trip_id == trip_id):
                photos.re_place(conn, row, g.person_id)


def _ask_again(conn: db.Connection, trip_id: int, now: float) -> None:
    active = conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.trip_id == trip_id, PhotoGrant.revoked.is_(None), PhotoGrant.scope == photos.TRIP)
                              .order_by(PhotoGrant.person_id)).all()
    for g in active:
        lock(conn, g.person_id, [trip_id])
        g.scope, g.ask_again, g.changed = photos.ONLY_ME, True, now
    conn.orm.flush()


def trips_changed(conn: db.Connection, trip_ids: Iterable[int], before: Mapping[int, Before] | None = None, now: float | None = None) -> None:
    stamp = time.time() if now is None else now
    for trip_id in [t for t in sorted(set(trip_ids)) if _lock_trip(conn, t)]:
        aboard = set(trippeople.of(conn, [trip_id])[trip_id])
        was = before.get(trip_id) if before is not None else None
        after = photos.trip_window(conn, trip_id) if was is not None else None
        if was is not None and (aboard - was.people or _grew(was.window, after)):
            _ask_again(conn, trip_id, stamp)
        for person in sorted(_photo_people(conn, trip_id) - aboard):
            left(conn, person, trip_id)
        reconcile(conn, trip_id, stamp)
        if was is not None and _shrank(was.window, after):
            for g in conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.trip_id == trip_id, PhotoGrant.revoked.is_(None)).order_by(PhotoGrant.person_id)).all():
                lock(conn, g.person_id, [trip_id])
                for row in _person_rows(conn, g.person_id, [trip_id]):
                    held = after is not None and after.start <= photos.instant(row.taken_utc) <= after.end
                    if not (row.decided_by == photos.OWNER and held):
                        photos.re_place(conn, row, g.person_id)
        if was is not None and was.points != photos.trip_points(conn, trip_id):
            _re_place_automatic(conn, trip_id)


def split(conn: db.Connection, original: int, new: int) -> None:
    for e in conn.orm.scalars(select(PhotoExclusion).where(PhotoExclusion.trip_id == original).order_by(PhotoExclusion.person_id, PhotoExclusion.asset_id)).all():
        db.insert_ignore(conn, PhotoExclusion, {"person_id": e.person_id, "asset_id": e.asset_id, "trip_id": new, "created": e.created, "was_trip_id": None},
                         key=["person_id", "asset_id", "trip_id"])
    conn.orm.flush()


def merged(conn: db.Connection, kept: int, gone: int) -> None:
    for e in conn.orm.scalars(select(PhotoExclusion).where(PhotoExclusion.trip_id == gone).order_by(PhotoExclusion.person_id, PhotoExclusion.asset_id)).all():
        db.insert_ignore(conn, PhotoExclusion, {"person_id": e.person_id, "asset_id": e.asset_id, "trip_id": kept, "created": e.created, "was_trip_id": None},
                         key=["person_id", "asset_id", "trip_id"])
    trip_deleted(conn, gone)


def trip_deleted(conn: db.Connection, trip_id: int) -> None:
    if not _lock_trip(conn, trip_id):
        return
    granted = set(conn.execute(select(PhotoGrant.person_id).where(PhotoGrant.trip_id == trip_id)).scalars())
    placed = set(conn.execute(select(PhotoSource.person_id).join(Photo, Photo.source_id == PhotoSource.id).where(Photo.trip_id == trip_id)).scalars())
    for person in sorted(granted | placed):
        lock(conn, person, [trip_id])
    conn.execute(delete(PhotoGrant).where(PhotoGrant.trip_id == trip_id))
    conn.execute(delete(PhotoExclusion).where(PhotoExclusion.trip_id == trip_id))
    conn.execute(delete(PhotoTripSync).where(PhotoTripSync.trip_id == trip_id))
    for person in sorted(granted | placed):
        _re_place(conn, person, [trip_id])
        _sweep_home(conn, person)


def _lapsed(conn: db.Connection, sub: str, now: float) -> bool:
    email = conn.execute(select(User.email).where(User.sub == sub)).scalar()
    return oidc.access_lapsed(conn, sub, email, now) is not None


def end_lapsed(conn: db.Connection, now: float | None = None) -> int:
    stamp = time.time() if now is None else now
    every = list(conn.orm.scalars(select(PhotoGrant).order_by(PhotoGrant.person_id, PhotoGrant.trip_id)).all())
    standing = list(conn.orm.scalars(select(PhotoSharingPrefs).where(PhotoSharingPrefs.share_all.is_(True))).all())
    stewarded = list(conn.orm.scalars(select(PhotoSharingPrefs).where(PhotoSharingPrefs.steward_sub.is_not(None))).all())
    subs = {g.granted_by for g in every} | {p.set_by for p in standing if p.set_by} | {p.steward_sub for p in stewarded if p.steward_sub}
    gone = {s for s in sorted(subs) if _lapsed(conn, s, stamp)}
    ended = 0
    lapsed = sorted(((g.trip_id, g.person_id, g.granted_by) for g in every if g.granted_by in gone), key=lambda g: g[:2])
    lock_trips(conn, [trip for trip, _, _ in lapsed])
    for trip, person, by in lapsed:
        conn.orm.expire_all()
        held = lock(conn, person, [trip]).get(trip)
        if held is None or held.granted_by != by:
            continue
        if held.revoked is None:
            _end(conn, person, trip)
        else:
            conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == person, PhotoGrant.trip_id == trip, PhotoGrant.granted_by == by))
        ended += 1
    for p in [p for p in standing if p.set_by in gone]:
        p.share_all, p.share_all_since = False, None
        ended += 1
    for p in [p for p in stewarded if p.steward_sub in gone]:
        p.steward_sub = None
        ended += 1
    conn.orm.flush()
    return ended


def _narrower(mine: PhotoGrant, theirs: PhotoGrant) -> None:
    if theirs.revoked is not None:
        mine.revoked = theirs.revoked if mine.revoked is None else max(mine.revoked, theirs.revoked)
    elif mine.revoked is None and theirs.scope == photos.ONLY_ME:
        mine.scope = photos.ONLY_ME
    mine.changed = max(mine.changed, theirs.changed)


def claim(conn: db.Connection, guest_id: int, member_id: int, sub: str) -> None:
    mine = {g.trip_id: g for g in conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.person_id == member_id).order_by(PhotoGrant.trip_id)).all()}
    closed: list[int] = []
    for theirs in conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.person_id == guest_id, PhotoGrant.trip_id.in_(list(mine))).order_by(PhotoGrant.trip_id)).all():
        kept = mine[theirs.trip_id]
        active = kept.revoked is None
        _narrower(kept, theirs)
        if active and kept.revoked is not None:
            closed.append(kept.trip_id)
    conn.orm.flush()
    conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == guest_id, PhotoGrant.trip_id.in_(list(mine))))
    conn.execute(update(PhotoGrant).where(PhotoGrant.person_id == guest_id).values(person_id=member_id, granted_by=sub))
    for e in conn.orm.scalars(select(PhotoExclusion).where(PhotoExclusion.person_id == guest_id)).all():
        db.insert_ignore(conn, PhotoExclusion, {"person_id": member_id, "asset_id": e.asset_id, "trip_id": e.trip_id, "created": e.created, "was_trip_id": e.was_trip_id},
                         key=["person_id", "asset_id", "trip_id"])
    if conn.orm.get(PhotoSharingPrefs, member_id) is None:
        conn.execute(update(PhotoSharingPrefs).where(PhotoSharingPrefs.person_id == guest_id).values(person_id=member_id, set_by=sub, steward_sub=None))
    _claim_sources(conn, guest_id, member_id, sub)
    conn.orm.expire_all()
    if closed:
        lock(conn, member_id, closed)
    for trip_id in closed:
        _drop_derived(conn, member_id, trip_id)
    for trip_id in _reachable(conn, member_id):
        reconcile(conn, trip_id)


def _merge_source(conn: db.Connection, theirs: PhotoSource, mine: PhotoSource) -> None:
    kept = {p.asset_id: p for p in conn.orm.scalars(select(Photo).where(Photo.source_id == mine.id)).all()}
    placed: list[tuple[Photo, int | None]] = []
    for p in conn.orm.scalars(select(Photo).where(Photo.source_id == theirs.id).order_by(Photo.id)).all():
        twin = kept.get(p.asset_id)
        if twin is None:
            p.source_id = mine.id
            continue
        if p.decided_by == photos.OWNER and twin.decided_by != photos.OWNER:
            placed.append((twin, p.trip_id))
        conn.orm.delete(p)
    synced = {s.trip_id for s in conn.orm.scalars(select(PhotoTripSync).where(PhotoTripSync.source_id == mine.id)).all()}
    for s in conn.orm.scalars(select(PhotoTripSync).where(PhotoTripSync.source_id == theirs.id)).all():
        if s.trip_id in synced:
            conn.orm.delete(s)
        else:
            s.source_id = mine.id
    conn.orm.flush()
    conn.orm.delete(theirs)
    conn.orm.flush()
    for twin, trip_id in placed:
        photos.place_by_hand(conn, twin, mine.person_id, trip_id)


def _claim_sources(conn: db.Connection, guest_id: int, member_id: int, sub: str) -> None:
    mine = {(s.url, s.immich_user_id): s for s in conn.orm.scalars(select(PhotoSource).where(PhotoSource.person_id == member_id)).all()}
    for theirs in conn.orm.scalars(select(PhotoSource).where(PhotoSource.person_id == guest_id).order_by(PhotoSource.id)).all():
        twin = mine.get((theirs.url, theirs.immich_user_id))
        if twin is None:
            theirs.person_id, theirs.owner_sub = member_id, sub
            mine[(theirs.url, theirs.immich_user_id)] = theirs
        else:
            _merge_source(conn, theirs, twin)
    conn.orm.flush()


def _reachable(conn: db.Connection, person_id: int) -> list[int]:
    listed = select(TripPerson.trip_id).where(TripPerson.person_id == person_id)
    booked = select(Trip.id).where(Trip.booked_by == person_id)
    booked_a_segment = select(Segment.trip_id).where(Segment.booked_by == person_id)
    received = select(Segment.trip_id).join(SegmentRecipient, SegmentRecipient.segment_id == Segment.id).where(SegmentRecipient.person_id == person_id)
    found: set[int] = set()
    for q in (listed, booked, booked_a_segment, received):
        found |= set(conn.execute(q).scalars())
    return sorted(found)


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
