from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select

from .. import monitoring, oidc
from ..providers import immich
from ..storage import db, photo_sources, secretbox
from ..storage import settings_keys as sk
from ..storage.models import Photo, PhotoExclusion, PhotoTripSync
from ..storage.photo_sources import OK, REFUSED, UNREACHABLE, Stored
from . import home, photogrants, photos, photosources
from .photomatch import HomeIn, MatchKind, TripWindow

TIME_BUDGET = 600.0
FULL_RELIST_DAYS = 7
DAY = 86400.0
DEMO = "demo"
SYNCED = (OK, UNREACHABLE)
KINDS: tuple[MatchKind, ...] = ("place", "time", "far", "ambiguous", "home")
CHUNK = 500

_clock = time.monotonic
_lock = threading.Lock()
_running: set[int] = set()
_waiting: dict[int, set[int]] = {}
background = threading.Event()


class Provider(Protocol):
    def search(self, source: immich.Source, taken_after: datetime, taken_before: datetime, *, updated_after: datetime | None = None,
               page: int = 1) -> immich.Page: ...


@dataclass
class Summary:
    sources: int = 0
    pages: int = 0
    seen: int = 0
    new: int = 0
    matched: Counter[str] = field(default_factory=Counter)
    inferred: int = 0
    deleted: int = 0
    budget_hit: int = 0
    failed: int = 0

    def add(self, other: Summary) -> None:
        self.sources += other.sources
        self.pages += other.pages
        self.seen += other.seen
        self.new += other.new
        self.matched.update(other.matched)
        self.inferred += other.inferred
        self.deleted += other.deleted
        self.budget_hit += other.budget_hit
        self.failed += other.failed

    def line(self) -> str:
        kinds = ", ".join(f"{self.matched[k]} {k}" for k in KINDS)
        return (f"Photo sync: {self.sources} library(ies), {self.pages} page(s), {self.seen} photo(s) seen, {self.new} new, matched {kinds}, "
                f"{self.inferred} placed from the itinerary, {self.deleted} deleted, {self.budget_hit} stopped at the time budget, "
                f"{self.failed} failed.")


@dataclass
class _Run:
    conn: db.Connection
    source: Stored
    unlocked: immich.Source
    provider: Provider
    now: datetime
    deadline: float
    home: HomeIn | None
    windows: dict[int, TripWindow]
    summary: Summary

    @property
    def person(self) -> int:
        return self.source["person_id"]

    @property
    def source_id(self) -> int:
        return self.source["id"]


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def _home(conn: db.Connection) -> HomeIn | None:
    found = home.located(conn)
    if found is None:
        return None
    return HomeIn(found.latitude, found.longitude, "zip" if found.precision == "zip" else "city")


def _key(name: str, source_id: int) -> str:
    return f"{name}:{source_id}"


def _stamp(conn: db.Connection, name: str, source_id: int) -> float | None:
    raw = db.get_setting(conn, _key(name, source_id))
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _chunks(values: Sequence[str]) -> Iterable[list[str]]:
    for i in range(0, len(values), CHUNK):
        yield list(values[i:i + CHUNK])


def _exclusions(conn: db.Connection, person: int, asset_ids: Sequence[str]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for part in _chunks(sorted(set(asset_ids))):
        for asset_id, trip_id in conn.execute(select(PhotoExclusion.asset_id, PhotoExclusion.trip_id)
                                              .where(PhotoExclusion.person_id == person, PhotoExclusion.asset_id.in_(part))).fetchall():
            out.setdefault(str(asset_id), set()).add(int(trip_id))
    return out


def _rows(conn: db.Connection, source_id: int, asset_ids: Sequence[str] | None = None) -> list[Photo]:
    if asset_ids is None:
        return list(conn.orm.scalars(select(Photo).where(Photo.source_id == source_id).order_by(Photo.id)).all())
    found: list[Photo] = []
    for part in _chunks(sorted(set(asset_ids))):
        found.extend(conn.orm.scalars(select(Photo).where(Photo.source_id == source_id, Photo.asset_id.in_(part))).all())
    return found


def _inside(windows: Iterable[TripWindow], taken: datetime) -> list[TripWindow]:
    return [w for w in windows if w.start <= taken <= w.end]


def _left_off(photo: Photo, windows: Iterable[TripWindow], left_out: set[int]) -> bool:
    inside = _inside(windows, photos.instant(photo.taken_utc))
    return photo.match == photos.AMBIGUOUS and photo.trip_id is None and bool(inside) and all(w.trip_id in left_out for w in inside)


def _tally(run: _Run, photo: Photo) -> None:
    run.summary.matched[photo.match] += 1
    if photo.location_source == photos.INFERRED:
        run.summary.inferred += 1


def _syncs(conn: db.Connection, source_id: int) -> dict[int, PhotoTripSync]:
    return {s.trip_id: s for s in conn.orm.scalars(select(PhotoTripSync).where(PhotoTripSync.source_id == source_id)).all()}


def _prepare(run: _Run, restart: bool) -> None:
    conn = run.conn
    conn.orm.expire_all()
    owned = _rows(conn, run.source_id)
    photogrants.lock(conn, run.person, set(run.windows) | {p.trip_id for p in owned if p.trip_id is not None})
    syncs = _syncs(conn, run.source_id)
    changed = False
    for trip_id, stale in syncs.items():
        if trip_id not in run.windows:
            conn.orm.delete(stale)
            changed = True
    for trip_id, w in run.windows.items():
        row = syncs.get(trip_id)
        start, end = _iso(w.start), _iso(w.end)
        if row is None:
            conn.orm.add(PhotoTripSync(source_id=run.source_id, trip_id=trip_id, window_start=start, window_end=end,
                                       cursor=None, resume_page=None, fetch_started=None, synced=None))
            changed = True
        elif (row.window_start, row.window_end) != (start, end) or restart:
            changed = changed or (row.window_start, row.window_end) != (start, end)
            row.window_start, row.window_end, row.cursor, row.resume_page, row.fetch_started = start, end, None, None, None
    conn.orm.flush()
    windows = list(run.windows.values())
    excluded = _exclusions(conn, run.person, [p.asset_id for p in owned])
    for p in owned:
        left_out = excluded.get(p.asset_id, set())
        taken_away = (p.trip_id is None and p.match not in (photos.AMBIGUOUS, "home")) or (p.trip_id is not None and p.trip_id not in run.windows)
        moved = changed and p.decided_by != photos.OWNER and not _left_off(p, windows, left_out)
        if (taken_away or moved) and not photos.re_place(conn, p, run.person, windows, left_out, run.home):
            run.summary.deleted += 1
    conn.commit()


def _upsert(run: _Run, asset: immich.Asset, row: Photo | None, windows: list[TripWindow], left_out: set[int]) -> None:
    conn = run.conn
    run.summary.seen += 1
    if row is None:
        if not _inside(windows, photos.instant(asset.taken_utc)):
            return
        row = Photo(source_id=run.source_id, asset_id=asset.id, trip_id=None, segment_id=None, match="none", distance_km=None,
                    decided_by=photos.AUTO, latitude=None, longitude=None, location_source=None)
        conn.orm.add(row)
        run.summary.new += 1
    row.asset_updated, row.kind, row.taken_utc, row.taken_local = asset.updated_at, asset.kind, asset.taken_utc, asset.taken_local
    row.taken_offset, row.state, row.country, row.seen = asset.taken_offset, asset.state, asset.country, run.now.timestamp()
    if asset.latitude is not None and asset.longitude is not None:
        row.latitude, row.longitude, row.location_source = asset.latitude, asset.longitude, "exif"
    elif row.location_source == "exif":
        row.latitude, row.longitude, row.location_source = None, None, None
    conn.orm.flush()
    kept = next((w for w in windows if w.trip_id == row.trip_id), None) if row.decided_by == photos.OWNER and row.trip_id not in left_out else None
    if kept is not None:
        photos.keep_on(row, run.person, kept)
        conn.orm.flush()
    elif not photos.re_place(conn, row, run.person, windows, left_out, run.home):
        run.summary.deleted += 1
        return
    _tally(run, row)


def _write(run: _Run, trip_id: int, got: immich.Page) -> bool:
    conn = run.conn
    conn.orm.expire_all()
    grants = photogrants.lock(conn, run.person, run.windows)
    live = {t for t, g in grants.items() if g.revoked is None}
    row = conn.orm.get(PhotoTripSync, (run.source_id, trip_id))
    if trip_id not in live or row is None:
        conn.commit()
        return False
    windows = [w for t, w in run.windows.items() if t in live]
    assets = list({a.id: a for a in got.assets}.values())
    existing = {p.asset_id: p for p in _rows(conn, run.source_id, [a.id for a in assets])}
    excluded = _exclusions(conn, run.person, [a.id for a in assets])
    for asset in assets:
        _upsert(run, asset, existing.get(asset.id), windows, excluded.get(asset.id, set()))
    if got.next_page is None:
        row.cursor, row.resume_page, row.fetch_started, row.synced = row.fetch_started, None, None, run.now.timestamp()
    else:
        row.resume_page = got.next_page
    conn.commit()
    return True


def _traverse(run: _Run, trip_id: int) -> bool:
    conn = run.conn
    row = conn.orm.get(PhotoTripSync, (run.source_id, trip_id))
    if row is None:
        return True
    if row.fetch_started is None:
        row.fetch_started, row.resume_page = _iso(run.now), None
        conn.commit()
    after = photos.instant(row.cursor) if row.cursor else None
    page = row.resume_page or 1
    window = run.windows[trip_id]
    while True:
        got = run.provider.search(run.unlocked, window.start, window.end, updated_after=after, page=page)
        run.summary.pages += 1
        if not _write(run, trip_id, got) or got.next_page is None:
            return True
        page = got.next_page
        if _clock() >= run.deadline:
            return False


def _finish_relist(run: _Run, started: float) -> None:
    conn = run.conn
    conn.orm.expire_all()
    photogrants.lock(conn, run.person, run.windows)
    windows = list(run.windows.values())
    for p in _rows(conn, run.source_id):
        if p.seen < started and _inside(windows, photos.instant(p.taken_utc)):
            conn.orm.delete(p)
            run.summary.deleted += 1
    db.set_setting(conn, _key(sk.PHOTOS_LAST_RELIST, run.source_id), repr(run.now.timestamp()))
    db.set_setting(conn, _key(sk.PHOTOS_RELIST_STARTED, run.source_id), None)
    conn.commit()


def _relist(conn: db.Connection, source_id: int, now: datetime, full: bool) -> tuple[float | None, bool]:
    last = _stamp(conn, sk.PHOTOS_LAST_RELIST, source_id)
    if not full and last is not None and now.timestamp() - last < FULL_RELIST_DAYS * DAY:
        return None, False
    started = _stamp(conn, sk.PHOTOS_RELIST_STARTED, source_id)
    if started is not None:
        return started, False
    db.set_setting(conn, _key(sk.PHOTOS_RELIST_STARTED, source_id), repr(now.timestamp()))
    conn.commit()
    return now.timestamp(), True


def _order(conn: db.Connection, source_id: int, trip_ids: list[int]) -> list[int]:
    syncs = _syncs(conn, source_id)
    return sorted(trip_ids, key=lambda t: (syncs[t].cursor is not None and syncs[t].fetch_started is None if t in syncs else False, t))


def _failed(conn: db.Connection, source: Stored, error: immich.ImmichError) -> None:
    conn.rollback()
    if isinstance(error, immich.Refused | immich.NotConfigured):
        photo_sources.mark(conn, source["id"], REFUSED, str(error))
    elif isinstance(error, immich.RateLimited):
        photo_sources.mark(conn, source["id"], source["status"], source["last_error"] or str(error))
    else:
        kept = source["last_error"] if source["status"] == UNREACHABLE and source["last_error"] else str(error)
        photo_sources.mark(conn, source["id"], UNREACHABLE, kept)
    conn.commit()


def run(conn: db.Connection, source_id: int, provider: Provider, now: datetime, *, full: bool = False, trips: set[int] | None = None) -> Summary:
    summary = Summary()
    source = photo_sources.get(conn, source_id)
    if not oidc.enabled() or source is None or source["status"] not in SYNCED or source["url"] == DEMO:
        return summary
    summary.sources = 1
    try:
        unlocked = photosources.unlock(conn, source_id)
    except secretbox.SecretError:
        photo_sources.mark(conn, source_id, REFUSED, photosources.KEY_LOST)
        conn.commit()
        summary.failed = 1
        return summary
    if unlocked is None:
        return summary
    windows = {w.trip_id: w for w in photos.candidate_windows(conn, source["person_id"])}
    job = _Run(conn, source, unlocked, provider, now, _clock() + TIME_BUDGET, _home(conn), windows, summary)
    started, fresh = _relist(conn, source_id, now, full) if trips is None else (None, False)
    _prepare(job, fresh)
    finished = True
    try:
        for n, trip_id in enumerate(_order(conn, source_id, [t for t in windows if trips is None or t in trips])):
            if (n and _clock() >= job.deadline) or not _traverse(job, trip_id):
                finished = False
                break
    except immich.ImmichError as e:
        _failed(conn, source, e)
        summary.failed = 1
        return summary
    if not finished:
        summary.budget_hit = 1
        return summary
    if trips is None:
        if started is not None:
            _finish_relist(job, started)
        photo_sources.mark(conn, source_id, OK, None, now.timestamp())
        conn.commit()
    return summary


def _claim(source_id: int) -> bool:
    with _lock:
        if source_id in _running:
            return False
        _running.add(source_id)
        return True


def _release(source_id: int) -> set[int] | None:
    with _lock:
        waiting = _waiting.pop(source_id, None)
        if waiting is None:
            _running.discard(source_id)
        return waiting


def running(source_id: int) -> bool:
    with _lock:
        return source_id in _running


def _sync(source_id: int, now: datetime, full: bool, trips: set[int] | None) -> Summary:
    total = Summary()
    while True:
        try:
            with db.session() as conn:
                total.add(run(conn, source_id, immich, now, full=full, trips=trips))
        except Exception as e:
            total.failed += 1
            monitoring.report(e, values=False)
        trips, full, now = _release(source_id), False, datetime.now(UTC)
        if trips is None:
            return total


def sync_all(now: datetime, full: bool = False) -> Summary:
    total = Summary()
    if not oidc.enabled():
        return total
    with db.session() as conn:
        photogrants.reconcile_all(conn, now.timestamp())
    with db.session() as conn:
        ids = [s["id"] for s in photo_sources.list_all(conn) if s["status"] in SYNCED and s["url"] != DEMO]
    for source_id in ids:
        if _claim(source_id):
            total.add(_sync(source_id, now, full, None))
    if total.sources:
        monitoring.log(total.line())
    return total


def _now_in_thread(source_id: int, trips: set[int] | None) -> None:
    summary = _sync(source_id, datetime.now(UTC), False, trips)
    if summary.sources:
        monitoring.log(summary.line())


def start(source_id: int, trips: set[int] | None = None) -> bool:
    if not background.is_set() or not oidc.enabled():
        return False
    with _lock:
        if source_id in _running:
            if trips is not None:
                _waiting.setdefault(source_id, set()).update(trips)
            return False
        _running.add(source_id)
    threading.Thread(target=_now_in_thread, args=(source_id, trips), daemon=True, name="photo-sync-now").start()
    return True


def queue(person_id: int, trip_id: int) -> None:
    if not background.is_set():
        return
    try:
        with db.session() as conn:
            ids = [s["id"] for s in photo_sources.for_person(conn, person_id) if s["status"] in SYNCED and s["url"] != DEMO]
    except Exception as e:
        monitoring.report(e, values=False)
        return
    for source_id in ids:
        start(source_id, {trip_id})


def after_commit(conn: db.Connection, person_id: int, trip_id: int) -> None:
    conn.after_commit(lambda: queue(person_id, trip_id))
