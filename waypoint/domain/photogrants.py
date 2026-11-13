from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict

from sqlalchemy import and_, delete, or_, select, update

from .. import oidc
from ..storage import db, photo_sources
from ..storage import settings_keys as sk
from ..storage.models import Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, PhotoTripSync, Segment, SegmentRecipient, Trip, TripPerson, User
from . import people, photoqueue, photos, trippeople, trips, visibility
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
NO_WINDOW = "Give the trip dates or a booking before sharing photos on it"
STALE_SOURCES = "Your libraries changed. Review them before sharing."
NEEDS_SNAPSHOT = 'Send the "window", "audience" and "sources" the confirmation showed'
NEEDS_VERSION = 'Send the "expected_changed" the confirmation showed'
NEEDS_SETTING_SNAPSHOT = 'Send the "windows", "audiences" and "sources" the confirmation showed'


class Stale(Exception):
    pass


Counter = Callable[[db.Connection, int, Sequence[int]], dict[int, int | None]]


def uncounted(_conn: db.Connection, _person_id: int, trip_ids: Sequence[int]) -> dict[int, int | None]:
    return dict.fromkeys(trip_ids)


def _window_matches(conn: db.Connection, trip_id: int, window: Mapping[str, str]) -> bool:
    return photos.window_out(photos.trip_window(conn, trip_id)) == {"start": window.get("start"), "end": window.get("end")}


class Prefs(TypedDict):
    default_scope: photos.Scope
    share_all: bool


class SourceVersion(TypedDict):
    id: int
    status: str


def sources_of(conn: db.Connection, person_id: int) -> list[SourceVersion]:
    rows = conn.execute(select(PhotoSource.id, PhotoSource.status).where(PhotoSource.person_id == person_id).order_by(PhotoSource.id)).fetchall()
    return [{"id": int(source_id), "status": str(status)} for source_id, status in rows]


def audience_of(conn: db.Connection, trip_id: int) -> list[int]:
    return sorted(trippeople.of(conn, [trip_id])[trip_id])


def _audience_matches(conn: db.Connection, trip_id: int, seen: Sequence[object]) -> bool:
    try:
        wanted = {int(str(p)) for p in seen}
    except (TypeError, ValueError):
        return False
    return wanted == set(audience_of(conn, trip_id))


def _sources_match(conn: db.Connection, person_id: int, seen: Sequence[Mapping[str, object]]) -> bool:
    try:
        wanted = {(int(str(s["id"])), str(s["status"])) for s in seen}
    except (KeyError, TypeError, ValueError):
        return False
    return wanted == {(s["id"], s["status"]) for s in sources_of(conn, person_id)}


class Sharing(TypedDict):
    state: State
    scope: photos.Scope | None
    count: int | None
    removed_count: int
    removed: list[photos.TripPhoto]
    window: photos.WindowOut | None
    changed: float | None
    audience: list[int]
    sources: list[SourceVersion]


class GrantedTrip(TypedDict):
    trip_id: int
    name: str
    start_date: str | None
    end_date: str | None
    state: Literal["shared", "declined", "none"]
    scope: photos.Scope | None
    count: int | None
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
    photoqueue.after_commit(conn, person_id, trip_id)


def _write(conn: db.Connection, person_id: int, trip_id: int, scope: photos.Scope, by: str, now: float) -> None:
    lock(conn, person_id, [trip_id])
    _upsert_grant(conn, person_id, trip_id, scope, by, now)


def _person_rows(conn: db.Connection, person_id: int, trip_ids: Sequence[int]) -> list[Photo]:
    on_trips = Photo.trip_id.in_(list(trip_ids)) if trip_ids else Photo.trip_id.is_(None)
    q = select(Photo).join(PhotoSource, PhotoSource.id == Photo.source_id) \
        .where(PhotoSource.person_id == person_id, or_(on_trips, and_(Photo.trip_id.is_(None), Photo.match.in_([photos.AMBIGUOUS, photos.HOME])))).order_by(Photo.id)
    return list(conn.orm.scalars(q).all())


def _re_place(conn: db.Connection, person_id: int, trip_ids: Sequence[int], keep_owner: bool = False) -> None:
    rows = _person_rows(conn, person_id, trip_ids)
    if not rows:
        return
    windows, at_home = photos.candidate_windows(conn, person_id), photos.home_in(conn)
    for row in rows:
        if not (keep_owner and row.decided_by == photos.OWNER and row.trip_id is not None):
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


def _drop_derived(conn: db.Connection, person_id: int, trip_id: int, keep_owner: bool = False) -> None:
    sources = select(PhotoSource.id).where(PhotoSource.person_id == person_id)
    conn.execute(delete(PhotoTripSync).where(PhotoTripSync.source_id.in_(sources), PhotoTripSync.trip_id == trip_id))
    _re_place(conn, person_id, [trip_id], keep_owner)
    _sweep_home(conn, person_id)


def _stop(conn: db.Connection, person_id: int, trip_id: int, by: str, now: float) -> None:
    lock(conn, person_id, [trip_id])
    db.upsert(conn, PhotoGrant, {"person_id": person_id, "trip_id": trip_id, "scope": photos.ONLY_ME, "revoked": now, "changed": now, "granted_by": by, "ask_again": False},
              key=KEY, update=["revoked", "changed", "granted_by", "ask_again"])
    _drop_derived(conn, person_id, trip_id, keep_owner=True)


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


def lock_home(conn: db.Connection) -> None:
    db.lock_setting(conn, sk.HOME)


def lock_trips(conn: db.Connection, trip_ids: Iterable[int]) -> list[int]:
    return [trip_id for trip_id in sorted(set(trip_ids)) if _lock_trip(conn, trip_id)]


def lock_trips_of(conn: db.Connection, *person_ids: int) -> list[int]:
    return lock_trips(conn, {t for person_id in person_ids for t in _reachable(conn, person_id)})


def home_changed(conn: db.Connection, dated: Iterable[int], before: Mapping[int, Before], now: float | None = None) -> None:
    known = list(dated)
    lock_trips(conn, known)
    fresh = [trip_id for trip_id in dated_trips(conn) if trip_id not in before]
    if fresh:
        aboard = trippeople.of(conn, fresh)
        before = {**before, **{trip_id: Before(None, frozenset(aboard[trip_id]), ()) for trip_id in fresh}}
    trips_changed(conn, [*known, *fresh], before, now)


def dated_trips(conn: db.Connection) -> list[int]:
    booked = select(Segment.trip_id)
    return list(conn.execute(select(Trip.id).where(Trip.start_date.is_not(None), Trip.end_date.is_not(None), Trip.id.not_in(booked)).order_by(Trip.id)).scalars())


def sharing(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, count: Counter = uncounted) -> Sharing:
    row = conn.orm.get(PhotoGrant, (person_id, trip_id))
    placed = photos.segment_points(conn, visibility.visible_segments(conn, viewer, [trip_id]))
    stamps = dict(conn.execute(select(PhotoExclusion.asset_id, PhotoExclusion.created)
                               .where(PhotoExclusion.person_id == person_id, PhotoExclusion.trip_id == trip_id)).fetchall())
    gone: list[photos.TripPhoto] = []
    for p, person in photos.removed(conn, viewer, trip_id):
        if person == person_id:
            out = photos.photo_out(p, person, placed)
            out["removed_at"] = stamps.get(p.asset_id)
            gone.append(out)
    state: State = NONE if row is None else DECLINED if row.revoked is not None else ASK if row.ask_again else SHARED
    counted = count(conn, person_id, [trip_id])[trip_id] if state == DECLINED else sum(1 for _, person in photos.visible_rows(conn, viewer, trip_id) if person == person_id)
    return {"state": state, "scope": row.scope if row is not None and row.revoked is None else None,  # type: ignore[typeddict-item]
            "count": counted, "removed_count": len(gone), "removed": gone, "window": photos.window_out(photos.trip_window(conn, trip_id)),
            "changed": row.changed if row is not None else None, "audience": audience_of(conn, trip_id), "sources": sources_of(conn, person_id)}


def state_of(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, count: Counter = uncounted) -> Sharing | None:
    if viewer.household or not photos.acts_for(conn, viewer, person_id) or visibility.visible_trip(conn, viewer, trip_id) is None:
        return None
    return sharing(conn, viewer, person_id, trip_id, count)


def grant(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, scope: photos.Scope, now: float | None = None,
          window: Mapping[str, str] | None = None, expected_changed: float | None = None,
          sources: Sequence[Mapping[str, object]] | None = None, audience: Sequence[object] | None = None, strict: bool = False) -> Sharing | None:
    acting = _acting(conn, viewer, person_id, trip_id)
    if acting is None or scope not in photos.SCOPES:
        return None
    trip, by = acting
    if not _aboard_under_lock(conn, person_id, trip.id) or visibility.visible_trip(conn, viewer, trip.id) is None:
        return None
    if photos.trip_window(conn, trip.id) is None:
        raise trips.Invalid(NO_WINDOW)
    if strict and scope == photos.TRIP and (window is None or audience is None or sources is None):
        raise trips.Invalid(NEEDS_SNAPSHOT)
    if window is not None and not _window_matches(conn, trip.id, window):
        raise Stale(STALE_SHARE)
    if audience is not None and not _audience_matches(conn, trip.id, audience):
        raise Stale(STALE_SHARE)
    row = lock(conn, person_id, sorted(photos.granted_trips(conn, person_id) | {trip.id})).get(trip.id)
    if strict and scope == photos.TRIP and row is not None and expected_changed is None:
        raise trips.Invalid(NEEDS_VERSION)
    if expected_changed is not None and (row is None or row.changed != expected_changed):
        raise Stale(STALE_SHARE)
    if sources is not None and not _sources_match(conn, person_id, sources):
        raise Stale(STALE_SOURCES)
    _write(conn, person_id, trip.id, scope, by, time.time() if now is None else now)
    _re_place_automatic(conn, trip.id, person_id)
    return sharing(conn, viewer, person_id, trip.id)


def stop(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, now: float | None = None) -> Sharing | None:
    acting = _acting(conn, viewer, person_id, trip_id)
    if acting is None:
        return None
    trip, by = acting
    if not _lock_trip(conn, trip.id) or not _still_acting(conn, viewer, person_id, trip.id):
        return None
    if conn.orm.get(PhotoGrant, (person_id, trip.id)) is None and person_id not in trippeople.of(conn, [trip.id])[trip.id]:
        return None
    _stop(conn, person_id, trip.id, by, time.time() if now is None else now)
    return sharing(conn, viewer, person_id, trip.id)


def _still_acting(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int) -> bool:
    return photos.acts_for(conn, viewer, person_id) and visibility.visible_trip(conn, viewer, trip_id) is not None


def decline(conn: db.Connection, viewer: Viewer, person_id: int, trip_id: int, now: float | None = None) -> Sharing | None:
    acting = _acting(conn, viewer, person_id, trip_id)
    if acting is None:
        return None
    trip, _ = acting
    if not _lock_trip(conn, trip.id) or not _still_acting(conn, viewer, person_id, trip.id):
        return None
    row = lock(conn, person_id, [trip.id]).get(trip.id)
    if row is None or row.revoked is not None or not row.ask_again:
        return stop(conn, viewer, person_id, trip_id, now)
    row.ask_again, row.changed = False, time.time() if now is None else now
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
    for photo, person in found:
        row = photos.visible_photo(conn, viewer, photo.id)
        if row is None or row[0].trip_id != trip_id or row[1] != person or not photos.acts_for(conn, viewer, row[1]):
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
    if found is None or found[1] != person:
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


def _eligible(conn: db.Connection, person_id: int, by: str) -> list[int]:
    setter = _setter(conn, by)
    if setter is None:
        return []
    seen = visibility.visible_trips(conn, setter)
    aboard = trippeople.of(conn, [t.id for t in seen])
    mine = sorted(t.id for t in seen if person_id in aboard[t.id])
    active = set(conn.execute(select(PhotoGrant.trip_id).where(PhotoGrant.person_id == person_id, PhotoGrant.trip_id.in_(mine), PhotoGrant.revoked.is_(None))).scalars())
    return [t for t in mine if t not in active and photos.trip_window(conn, t) is not None]


def _not_yet_shared(conn: db.Connection, person_id: int, by: str) -> list[int]:
    setter = _setter(conn, by)
    if setter is None:
        return []
    held = lock_trips(conn, _eligible(conn, person_id, by))
    still = [t for t in held if person_id in trippeople.of(conn, [t])[t] and visibility.visible_trip(conn, setter, t) is not None]
    rows = lock(conn, person_id, sorted(photos.granted_trips(conn, person_id) | set(still)))
    return [t for t in still if t not in rows or rows[t].revoked is not None]


def _share_all(conn: db.Connection, person_id: int, by: str, scope: photos.Scope, now: float, pending: Sequence[int]) -> int:
    for trip_id in pending:
        _upsert_grant(conn, person_id, trip_id, scope, by, now)
    for trip_id in pending:
        _re_place_automatic(conn, trip_id, person_id)
    return len(pending)


def set_prefs(conn: db.Connection, viewer: Viewer, person_id: int, default_scope: photos.Scope | None, share_all: bool | None,
              now: float | None = None, windows: Mapping[str, Mapping[str, str]] | None = None,
              sources: Sequence[Mapping[str, object]] | None = None, audiences: Mapping[str, Sequence[object]] | None = None,
              strict: bool = False) -> Prefs | None:
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
    effective = default_scope if default_scope is not None else found.default_scope if found is not None else photos.ONLY_ME
    if strict and share_all and not was_on and effective == photos.TRIP and (windows is None or audiences is None or sources is None):
        raise trips.Invalid(NEEDS_SETTING_SNAPSHOT)
    pending = _not_yet_shared(conn, person_id, by) if share_all and not was_on else []
    if windows is not None and any(str(t) not in windows or not _window_matches(conn, t, windows[str(t)]) for t in pending):
        raise Stale(STALE_SETTING)
    if audiences is not None and any(str(t) not in audiences or not _audience_matches(conn, t, audiences[str(t)]) for t in pending):
        raise Stale(STALE_SETTING)
    if sources is not None and share_all and not was_on and not _sources_match(conn, person_id, sources):
        raise Stale(STALE_SOURCES)
    db.insert_ignore(conn, PhotoSharingPrefs, {"person_id": person_id, "default_scope": photos.ONLY_ME, "share_all": False, "set_by": None, "share_all_since": None,
                                               "steward_sub": None}, key=["person_id"])
    row = conn.orm.get(PhotoSharingPrefs, person_id, with_for_update=True)
    if row is None or row.share_all != was_on:
        return None
    if share_all and not was_on and _eligible(conn, person_id, by) != pending:
        raise Stale(STALE_SETTING)
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


def _prefs_row(conn: db.Connection, person_id: int, for_update: bool = False) -> PhotoSharingPrefs | None:
    q = select(PhotoSharingPrefs).where(PhotoSharingPrefs.person_id == person_id).execution_options(populate_existing=True)
    return conn.orm.scalars(q.with_for_update() if for_update else q).first()


def joined(conn: db.Connection, person_id: int, trip_id: int, now: float | None = None) -> bool:
    if not _aboard_under_lock(conn, person_id, trip_id) or photos.trip_window(conn, trip_id) is None:
        return False
    found = lock(conn, person_id, [trip_id]).get(trip_id)
    row = _prefs_row(conn, person_id, for_update=True)
    if row is None or not row.share_all or row.set_by is None:
        return False
    setter = _setter(conn, row.set_by)
    if setter is None or visibility.visible_trip(conn, setter, trip_id) is None:
        return False
    if found is not None and (found.revoked is None or row.share_all_since is None or found.revoked >= row.share_all_since):
        return False
    _upsert_grant(conn, person_id, trip_id, row.default_scope, row.set_by, time.time() if now is None else now)  # type: ignore[arg-type]
    _re_place_automatic(conn, trip_id, person_id)
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
    held = lock_trips(conn, trip_ids)
    lock_grants_for(conn, held)
    return sum(reconcile(conn, trip_id, now) for trip_id in held)


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


def _active(conn: db.Connection, trip_id: int) -> list[PhotoGrant]:
    return list(conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.trip_id == trip_id, PhotoGrant.revoked.is_(None)).order_by(PhotoGrant.person_id)).all())


def lock_grants_for(conn: db.Connection, trip_ids: Iterable[int]) -> None:
    ids = sorted(set(trip_ids))
    aboard = trippeople.of(conn, ids)
    involved = {person for trip_id in ids for person in _photo_people(conn, trip_id) | set(aboard[trip_id])}
    for person in sorted(involved):
        lock(conn, person, sorted(photos.granted_trips(conn, person) | set(ids)))


def _re_place_shrunk(conn: db.Connection, trip_id: int, after: TripWindow | None) -> None:
    for person in sorted(_photo_people(conn, trip_id)):
        windows = photos.candidate_windows(conn, person)
        for row in _person_rows(conn, person, [trip_id]):
            held = after is not None and after.start <= photos.instant(row.taken_utc) <= after.end
            if not (row.decided_by == photos.OWNER and held):
                photos.re_place(conn, row, person, windows)


def _rows_near(conn: db.Connection, person_id: int, trip_id: int, found: TripWindow | None) -> list[Photo]:
    near = Photo.trip_id == trip_id
    if found is not None:
        near = or_(near, and_(Photo.taken_utc >= (found.start - timedelta(days=1)).isoformat(), Photo.taken_utc <= (found.end + timedelta(days=1)).isoformat()))
    q = select(Photo).join(PhotoSource, PhotoSource.id == Photo.source_id).where(PhotoSource.person_id == person_id, near).order_by(Photo.id)
    return [row for row in conn.orm.scalars(q).all()
            if row.trip_id == trip_id or (found is not None and found.start <= photos.instant(row.taken_utc) <= found.end)]


def _re_place_automatic(conn: db.Connection, trip_id: int, person_id: int | None = None) -> None:
    found = photos.trip_window(conn, trip_id)
    for g in _active(conn, trip_id):
        if person_id is not None and g.person_id != person_id:
            continue
        windows = photos.candidate_windows(conn, g.person_id)
        for row in _rows_near(conn, g.person_id, trip_id, found):
            inside = found is not None and found.start <= photos.instant(row.taken_utc) <= found.end
            if row.decided_by == photos.OWNER:
                if row.trip_id == trip_id and not inside:
                    photos.re_place(conn, row, g.person_id, windows)
            elif row.match != photos.HOME:
                photos.re_place(conn, row, g.person_id, windows)


def _ask_again(conn: db.Connection, trip_id: int, now: float) -> None:
    for g in _active(conn, trip_id):
        lock(conn, g.person_id, [trip_id])
        if g.scope == photos.TRIP:
            g.scope, g.ask_again = photos.ONLY_ME, True
        g.changed = now
    conn.orm.flush()


def trips_changed(conn: db.Connection, trip_ids: Iterable[int], before: Mapping[int, Before] | None = None, now: float | None = None) -> None:
    stamp = time.time() if now is None else now
    settled: list[tuple[int, Before, TripWindow | None]] = []
    held = lock_trips(conn, trip_ids)
    lock_grants_for(conn, held)
    for trip_id in held:
        aboard = set(trippeople.of(conn, [trip_id])[trip_id])
        was = before.get(trip_id) if before is not None else None
        after = photos.trip_window(conn, trip_id) if was is not None else None
        if was is not None and (aboard - was.people or _grew(was.window, after)):
            _ask_again(conn, trip_id, stamp)
        for person in sorted(_photo_people(conn, trip_id) - aboard):
            left(conn, person, trip_id)
        reconcile(conn, trip_id, stamp)
        if photos.trip_window(conn, trip_id) is None:
            for g in _active(conn, trip_id):
                _end(conn, g.person_id, trip_id)
        if was is not None:
            settled.append((trip_id, was, after))
    for trip_id, was, after in settled:
        if _shrank(was.window, after):
            _re_place_shrunk(conn, trip_id, after)
        if was.points != photos.trip_points(conn, trip_id) or was.window != after:
            _re_place_automatic(conn, trip_id)


def split(conn: db.Connection, original: int, new: int) -> None:
    for e in conn.orm.scalars(select(PhotoExclusion).where(PhotoExclusion.trip_id == original).order_by(PhotoExclusion.person_id, PhotoExclusion.asset_id)).all():
        db.insert_ignore(conn, PhotoExclusion, {"person_id": e.person_id, "asset_id": e.asset_id, "trip_id": new, "created": e.created, "was_trip_id": None},
                         key=["person_id", "asset_id", "trip_id"])
    conn.orm.flush()


def merged(conn: db.Connection, kept: int, gone: int) -> None:
    for e in conn.orm.scalars(select(PhotoExclusion).where(PhotoExclusion.trip_id == gone).order_by(PhotoExclusion.person_id, PhotoExclusion.asset_id)).all():
        db.insert_ignore(conn, PhotoExclusion, {"person_id": e.person_id, "asset_id": e.asset_id, "trip_id": kept, "created": e.created,
                                                "was_trip_id": kept if e.was_trip_id == gone else e.was_trip_id},
                         key=["person_id", "asset_id", "trip_id"])
    trip_deleted(conn, gone)


def trip_deleted(conn: db.Connection, trip_id: int) -> None:
    if not _lock_trip(conn, trip_id):
        return
    granted = set(conn.execute(select(PhotoGrant.person_id).where(PhotoGrant.trip_id == trip_id)).scalars())
    placed = set(conn.execute(select(PhotoSource.person_id).join(Photo, Photo.source_id == PhotoSource.id).where(Photo.trip_id == trip_id)).scalars())
    lock_grants_for(conn, [trip_id])
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
    lapsed = sorted(((g.person_id, g.trip_id, g.granted_by) for g in every if g.granted_by in gone), key=lambda g: g[:2])
    settings = sorted({p.person_id for p in standing if p.set_by in gone} | {p.person_id for p in stewarded if p.steward_sub in gone})
    for sub in sorted(gone):
        photo_sources.lock_owner(conn, sub)
    for person in sorted({person for person, _, _ in lapsed} | set(settings)):
        people.lock(conn, person)
    lock_trips(conn, [trip for _, trip, _ in lapsed])
    gone = {s for s in sorted(gone) if _lapsed(conn, s, stamp)}
    for person, trip, by in lapsed:
        conn.orm.expire_all()
        held = lock(conn, person, [trip]).get(trip)
        if held is None or held.granted_by != by or by not in gone:
            continue
        if held.revoked is None:
            _end(conn, person, trip)
        else:
            conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == person, PhotoGrant.trip_id == trip, PhotoGrant.granted_by == by))
        ended += 1
    for person in settings:
        row = _prefs_row(conn, person, for_update=True)
        if row is None:
            continue
        if row.share_all and row.set_by in gone:
            row.share_all, row.share_all_since = False, None
            ended += 1
        if row.steward_sub in gone:
            row.steward_sub = None
            ended += 1
    conn.orm.flush()
    return ended


def _narrower(mine: PhotoGrant, theirs: PhotoGrant, now: float) -> None:
    was = (mine.scope, mine.revoked)
    if theirs.revoked is not None:
        mine.revoked = theirs.revoked if mine.revoked is None else max(mine.revoked, theirs.revoked)
    elif mine.revoked is None and theirs.scope == photos.ONLY_ME:
        mine.scope = photos.ONLY_ME
    mine.changed = max(mine.changed, theirs.changed, now) if (mine.scope, mine.revoked) != was else max(mine.changed, theirs.changed)


def claim(conn: db.Connection, guest_id: int, member_id: int, sub: str, now: float | None = None) -> None:
    stamp = time.time() if now is None else now
    mine = {g.trip_id: g for g in conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.person_id == member_id).order_by(PhotoGrant.trip_id)).all()}
    closed: list[int] = []
    for theirs in conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.person_id == guest_id, PhotoGrant.trip_id.in_(list(mine))).order_by(PhotoGrant.trip_id)).all():
        kept = mine[theirs.trip_id]
        open_before = kept.revoked is None or theirs.revoked is None
        _narrower(kept, theirs, stamp)
        if open_before and kept.revoked is not None:
            closed.append(kept.trip_id)
    conn.orm.flush()
    conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == guest_id, PhotoGrant.trip_id.in_(list(mine))))
    conn.execute(update(PhotoGrant).where(PhotoGrant.person_id == guest_id).values(person_id=member_id, granted_by=sub))
    _claim_exclusions(conn, guest_id, member_id)
    if conn.orm.get(PhotoSharingPrefs, member_id) is None:
        conn.execute(update(PhotoSharingPrefs).where(PhotoSharingPrefs.person_id == guest_id).values(person_id=member_id, set_by=sub, steward_sub=None))
    _claim_sources(conn, guest_id, member_id, sub)
    conn.orm.expire_all()
    reachable = _reachable(conn, member_id)
    lock_grants_for(conn, sorted(set(reachable) | set(closed)))
    for trip_id in closed:
        _drop_derived(conn, member_id, trip_id)
    for trip_id in reachable:
        reconcile(conn, trip_id)


def _claim_exclusions(conn: db.Connection, guest_id: int, member_id: int) -> None:
    theirs = list(conn.orm.scalars(select(PhotoExclusion).where(PhotoExclusion.person_id == guest_id)
                                   .order_by(PhotoExclusion.asset_id, PhotoExclusion.trip_id)).all())
    for e in theirs:
        mine = conn.orm.get(PhotoExclusion, (member_id, e.asset_id, e.trip_id))
        if mine is None:
            conn.orm.add(PhotoExclusion(person_id=member_id, asset_id=e.asset_id, trip_id=e.trip_id, created=e.created, was_trip_id=e.was_trip_id))
        elif mine.was_trip_id is None and e.was_trip_id is not None:
            mine.created, mine.was_trip_id = e.created, e.was_trip_id
    conn.orm.flush()


def _merge_source(conn: db.Connection, theirs: PhotoSource, mine: PhotoSource) -> None:
    kept = {p.asset_id: p for p in conn.orm.scalars(select(Photo).where(Photo.source_id == mine.id)).all()}
    placed: list[tuple[Photo, int | None]] = []
    moved: list[Photo] = []
    for p in conn.orm.scalars(select(Photo).where(Photo.source_id == theirs.id).order_by(Photo.id)).all():
        twin = kept.get(p.asset_id)
        if twin is None:
            p.source_id = mine.id
            if p.decided_by == photos.OWNER:
                moved.append(p)
            continue
        if p.decided_by == photos.OWNER and twin.decided_by != photos.OWNER:
            placed.append((twin, p.trip_id))
        conn.orm.delete(p)
    synced = {s.trip_id: s for s in conn.orm.scalars(select(PhotoTripSync).where(PhotoTripSync.source_id == mine.id)).all()}
    for s in conn.orm.scalars(select(PhotoTripSync).where(PhotoTripSync.source_id == theirs.id)).all():
        if s.trip_id in synced:
            _merge_sync(synced[s.trip_id], s)
            conn.orm.delete(s)
        else:
            s.source_id, s.relist_gen = mine.id, None
    conn.orm.flush()
    conn.orm.delete(theirs)
    conn.orm.flush()
    for twin, trip_id in placed:
        photos.place_by_hand(conn, twin, mine.person_id, trip_id)
    for p in moved:
        photos.copy_placement(conn, p, mine.person_id)


def _merge_sync(kept: PhotoTripSync, gone: PhotoTripSync) -> None:
    same_window = (kept.window_start, kept.window_end) == (gone.window_start, gone.window_end)
    kept.cursor = min(kept.cursor, gone.cursor) if same_window and kept.cursor and gone.cursor else None
    kept.resume_after, kept.fetch_started, kept.relist_gen = None, None, None


def _library(source: PhotoSource) -> tuple[str, str]:
    return photo_sources.address(source.url), source.immich_user_id


def _claim_sources(conn: db.Connection, guest_id: int, member_id: int, sub: str) -> None:
    mine = {_library(s): s for s in conn.orm.scalars(select(PhotoSource).where(PhotoSource.person_id == member_id)).all()}
    kept: list[int] = []
    for theirs in conn.orm.scalars(select(PhotoSource).where(PhotoSource.person_id == guest_id).order_by(PhotoSource.id)).all():
        twin = mine.get(_library(theirs))
        if twin is None:
            theirs.person_id, theirs.owner_sub = member_id, sub
            mine[_library(theirs)] = theirs
            kept.append(theirs.id)
        else:
            _merge_source(conn, theirs, twin)
    conn.orm.flush()
    if kept:
        q = select(Photo).where(Photo.source_id.in_(kept), Photo.decided_by == photos.OWNER).order_by(Photo.id)
        for row in conn.orm.scalars(q).all():
            photos.copy_placement(conn, row, member_id)


def _reachable(conn: db.Connection, person_id: int) -> list[int]:
    listed = select(TripPerson.trip_id).where(TripPerson.person_id == person_id)
    booked = select(Trip.id).where(Trip.booked_by == person_id)
    booked_a_segment = select(Segment.trip_id).where(Segment.booked_by == person_id)
    received = select(Segment.trip_id).join(SegmentRecipient, SegmentRecipient.segment_id == Segment.id).where(SegmentRecipient.person_id == person_id)
    found: set[int] = set()
    for q in (listed, booked, booked_a_segment, received):
        found |= set(conn.execute(q).scalars())
    return sorted(found)


def grants(conn: db.Connection, viewer: Viewer, count: Counter = uncounted) -> Grants:
    if viewer.household:
        return {"people": []}
    out: list[PersonGrants] = []
    seen = {t.id: t for t in visibility.visible_trips(conn, viewer)}
    aboard = trippeople.of(conn, list(seen))
    for person in photos.persons_of(conn, viewer):
        rows = {g.trip_id: g for g in conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.person_id == person, PhotoGrant.trip_id.in_(list(seen)))).all()}
        unshared = sorted(t for t in seen if (t in rows and rows[t].revoked is not None) or (t not in rows and person in aboard[t]))
        counted = count(conn, person, unshared)
        listed: list[GrantedTrip] = []
        for trip_id in sorted(set(rows) | set(unshared)):
            row, counts = rows.get(trip_id), counted.get(trip_id)
            if (row is None or row.revoked is not None) and counts == 0:
                continue
            trip, state = seen[trip_id], sharing(conn, viewer, person, trip_id)
            shown: Literal["shared", "declined", "none"] = "none" if row is None else "shared" if row.revoked is None else "declined"
            listed.append({"trip_id": trip.id, "name": trip.name, "start_date": trip.start_date, "end_date": trip.end_date, "state": shown,
                           "scope": state["scope"], "count": state["count"] if shown == "shared" else counts, "removed_count": state["removed_count"]})
        listed.sort(key=lambda t: (t["start_date"] is None, t["start_date"] or "", t["trip_id"]))
        out.append({"person_id": person, "prefs": prefs_of(conn, person), "trips": listed})
    return {"people": out}
