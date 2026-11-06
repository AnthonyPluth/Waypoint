from __future__ import annotations

import heapq
import math
import time
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time as clock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Literal, TypedDict, cast

from sqlalchemy import ColumnElement, and_, false, or_, select

from ..storage import db, geocode
from ..storage.models import Airport, Person, Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, Segment, Trip, TripPerson
from . import home, photomatch, place_zones, trippeople, trips, visibility
from .photomatch import CLUSTER, GAP, NEAR, MatchKind, PhotoIn, Point, SegmentPoint, TripWindow, window
from .stats import EARTH_RADIUS_KM, distance_km
from .visibility import Viewer

Located = tuple[float, float, int]
LocationSource = Literal["exif", "inferred"]
Scope = Literal["only_me", "trip"]
Found = tuple[Photo, int]

SHOWN: tuple[MatchKind, ...] = ("place", "time", "far")
AMBIGUOUS: MatchKind = "ambiguous"
FAR: MatchKind = "far"
HOME: MatchKind = "home"
OWNER = "owner"
AUTO = "auto"
INFERRED: LocationSource = "inferred"
ONLY_ME: Scope = "only_me"
TRIP: Scope = "trip"
SCOPES: tuple[Scope, ...] = (ONLY_ME, TRIP)
MAX_CLUSTERS = 400
NOT_ON_TRIP = "Choose a trip you are on"
SHARE_FIRST = "Share your photos on that trip first"
PUT_BACK_FIRST = "Put the photo back on that trip first"
NOT_UNSETTLED = "Only a photo waiting under Needs a look can be left off"
NOT_IN_WINDOW = "That trip’s dates don’t cover this photo"


class OutsideWindow(Exception):
    pass


CHANGED = "Your trips changed meanwhile; try again"


class Changed(Exception):
    pass


class WindowOut(TypedDict):
    start: str
    end: str


def window_out(found: TripWindow | None) -> WindowOut | None:
    return {"start": found.start.isoformat(), "end": found.end.isoformat()} if found is not None else None
CELL = 0.1
COLUMNS = round(360 / CELL)
ROWS = round(180 / CELL)
KM_PER_DEGREE = 111.0


class TripPhoto(TypedDict):
    id: int
    person_id: int
    trip_id: int | None
    kind: Literal["image", "video"]
    taken_local: str
    zone: str | None
    latitude: float | None
    longitude: float | None
    location_source: LocationSource | None
    segment_id: int | None
    match: MatchKind
    distance_km: float | None
    cluster: int | None


class PhotoCluster(TypedDict):
    latitude: float
    longitude: float
    count: int
    first: str
    last: str
    cover: int
    inferred: bool


class PhotoCounts(TypedDict):
    total: int
    located: int
    inferred: int
    far: int


class PhotoPerson(TypedDict):
    person_id: int
    count: int


class TripPhotos(TypedDict):
    photos: list[TripPhoto]
    clusters: list[PhotoCluster]
    counts: PhotoCounts
    people: list[PhotoPerson]


class PhotoCandidate(TypedDict):
    id: int
    name: str


class ReviewPhoto(TripPhoto):
    candidates: list[PhotoCandidate]


class PhotoReview(TypedDict):
    photos: list[ReviewPhoto]


def _at(point: Point, segment_id: int) -> Located:
    return point[0], point[1], segment_id


def _anchor(point: SegmentPoint) -> Point | None:
    return point.origin if point.origin is not None else point.destination


def where_was(points: Sequence[SegmentPoint], instant: datetime) -> Located | None:
    active = [p for p in points if p.start <= instant <= p.end]
    if any(p.kind == "flight" for p in active):
        return None
    here = min((p for p in active if _anchor(p) is not None), key=lambda p: (p.end - p.start, p.segment_id), default=None)
    anchor = _anchor(here) if here is not None else None
    if here is not None and anchor is not None:
        return _at(anchor, here.segment_id)
    ended = max((p for p in points if p.end < instant <= p.end + GAP and p.destination is not None),
                key=lambda p: (p.end, -p.segment_id, p.start), default=None)
    if ended is not None and ended.destination is not None:
        return _at(ended.destination, ended.segment_id)
    upcoming = min((p for p in points if instant < p.start <= instant + GAP and p.origin is not None),
                   key=lambda p: (p.start, p.segment_id), default=None)
    if upcoming is not None and upcoming.origin is not None:
        return _at(upcoming.origin, upcoming.segment_id)
    return None


def _code(value: str | None) -> str:
    return (value or "").strip().upper()


def _points(seg: Segment, airport_at: Mapping[str, Point], ports: Sequence[trips.PortIn]) -> list[SegmentPoint]:
    timed = not trips.untimed(trips.decode_details(seg.details))
    start, end = trips.instant(seg.start_local, seg.start_zone), trips.instant(seg.end_local, seg.end_zone)
    if seg.kind == "flight":
        leaving, arriving = airport_at.get(_code(seg.origin)), airport_at.get(_code(seg.destination))
        return [SegmentPoint(seg.id, seg.kind, start, end, leaving[0] if leaving else None, leaving[1] if leaving else None,
                             arriving[0] if arriving else None, arriving[1] if arriving else None, timed, seg.start_zone, seg.end_zone)]
    if seg.kind == "train":
        return [SegmentPoint(seg.id, seg.kind, start, end, None, None, seg.latitude, seg.longitude, timed, seg.start_zone, seg.end_zone)]
    main = SegmentPoint(seg.id, seg.kind, start, end, seg.latitude, seg.longitude, timed=timed, zone=seg.start_zone, to_zone=seg.end_zone)
    if seg.kind != "cruise":
        return [main]
    calls: list[SegmentPoint] = []
    for port in ports:
        found = geocode.locate_port(port["name"])
        if found is None:
            continue
        arrive = trips.instant(port["arrive_local"], port["zone"]) if port["arrive_local"] else start
        depart = trips.instant(port["depart_local"], port["zone"]) if port["depart_local"] else end
        calls.append(SegmentPoint(seg.id, seg.kind, arrive, depart, found.latitude, found.longitude, timed=timed, zone=port["zone"], to_zone=port["zone"]))
    if main.origin is None and calls:
        main = replace(main, latitude=calls[0].latitude, longitude=calls[0].longitude, borrowed=True)
    return [main, *calls]


def segment_points(conn: db.Connection, segments: Sequence[Segment]) -> dict[int, list[SegmentPoint]]:
    codes = sorted({_code(c) for s in segments if s.kind == "flight" for c in (s.origin, s.destination)} - {""})
    airport_at = {a.code: (a.latitude, a.longitude) for a in conn.orm.scalars(select(Airport).where(Airport.code.in_(codes))).all()} if codes else {}
    ports = trips.ports_of(conn, [s.id for s in segments if s.kind == "cruise"])
    return {s.id: _points(s, airport_at, ports.get(s.id, [])) for s in segments}


def granted_trips(conn: db.Connection, person_id: int) -> set[int]:
    return set(conn.execute(select(PhotoGrant.trip_id).where(PhotoGrant.person_id == person_id, PhotoGrant.revoked.is_(None))).scalars())


def excluded_trips(conn: db.Connection, person_id: int, asset_id: str) -> set[int]:
    return set(conn.execute(select(PhotoExclusion.trip_id).where(PhotoExclusion.person_id == person_id, PhotoExclusion.asset_id == asset_id)).scalars())


def candidate_windows(conn: db.Connection, person_id: int) -> list[TripWindow]:
    viewer = Viewer(person_id)
    granted = granted_trips(conn, person_id)
    seen = [t for t in visibility.visible_trips(conn, viewer) if t.id in granted]
    aboard = trippeople.of(conn, [t.id for t in seen])
    mine = [t for t in seen if person_id in aboard[t.id]]
    if not mine:
        return []
    booked = visibility.visible_segments(conn, viewer, [t.id for t in mine])
    live = [s for s in booked if s.status != "cancelled"]
    placed = segment_points(conn, live)
    windows: list[TripWindow] = []
    for trip in mine:
        points = [p for s in live if s.trip_id == trip.id for p in placed[s.id]]
        unbooked = not any(s.trip_id == trip.id for s in booked)
        found = window(trip, points) if points else _dated_window(conn, trip) if unbooked else None
        if found is not None:
            windows.append(found)
    return windows


def instant(taken_utc: str) -> datetime:
    parsed = datetime.fromisoformat(taken_utc)
    return (parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def offset_label(minutes: int) -> str:
    if minutes == 0:
        return "UTC"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{'+' if minutes > 0 else '−'}{hours:02d}:{rest:02d}"


def viewer_sub(conn: db.Connection, viewer: Viewer) -> str | None:
    if viewer.person_id is None:
        return None
    sub = conn.execute(select(Person.user_sub).where(Person.id == viewer.person_id)).scalar()
    return str(sub) if sub is not None else None


def persons_of(conn: db.Connection, viewer: Viewer) -> list[int]:
    if viewer.person_id is None:
        return []
    sub = viewer_sub(conn, viewer)
    if sub is None:
        return [viewer.person_id]
    stewarded = conn.execute(select(PhotoSharingPrefs.person_id).join(Person, Person.id == PhotoSharingPrefs.person_id)
                             .where(Person.user_sub.is_(None), PhotoSharingPrefs.steward_sub == sub)).scalars()
    return [viewer.person_id, *sorted(p for p in stewarded if p != viewer.person_id)]


def acts_for(conn: db.Connection, viewer: Viewer, person_id: int) -> bool:
    return person_id in persons_of(conn, viewer)


def _with_me(viewer_person: int) -> ColumnElement[bool]:
    return select(TripPerson.trip_id).where(TripPerson.trip_id == Photo.trip_id, TripPerson.person_id == viewer_person).exists()


def _granted(persons: Sequence[int], viewer_person: int) -> ColumnElement[bool]:
    return select(PhotoGrant.person_id).where(PhotoGrant.person_id == PhotoSource.person_id, PhotoGrant.trip_id == Photo.trip_id, PhotoGrant.revoked.is_(None),
                                              or_(and_(PhotoGrant.scope == TRIP, _with_me(viewer_person)), PhotoSource.person_id.in_(list(persons)))).exists()


def lock_grants(conn: db.Connection, person_id: int, trip_ids: Iterable[int]) -> dict[int, PhotoGrant]:
    ids = sorted(set(trip_ids))
    rows = conn.orm.scalars(select(PhotoGrant).where(PhotoGrant.person_id == person_id, PhotoGrant.trip_id.in_(ids))
                            .order_by(PhotoGrant.trip_id).with_for_update()).all()
    return {r.trip_id: r for r in rows}


def canonical_ids(conn: db.Connection, keys: Iterable[tuple[int, str]]) -> set[int]:
    wanted = set(keys)
    if not wanted:
        return set()
    q = select(Photo.id, Photo.source_id, Photo.asset_id, PhotoSource.person_id, PhotoSource.status).join(PhotoSource, PhotoSource.id == Photo.source_id) \
        .where(PhotoSource.person_id.in_(sorted({p for p, _ in wanted})), Photo.asset_id.in_(sorted({a for _, a in wanted})))
    best: dict[tuple[int, str], tuple[tuple[bool, int, int], int]] = {}
    for photo_id, source_id, asset_id, person, status in conn.execute(q).fetchall():
        key = (person, asset_id)
        if key not in wanted:
            continue
        rank = (status != "ok", source_id, photo_id)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, photo_id)
    return {photo_id for _, photo_id in best.values()}


def _canonical(conn: db.Connection, rows: Sequence[Found]) -> list[Found]:
    keep = canonical_ids(conn, {(person, photo.asset_id) for photo, person in rows})
    return [(photo, person) for photo, person in rows if photo.id in keep]


def _home_zone(conn: db.Connection) -> ZoneInfo:
    found = home.read(conn)
    address = ", ".join(part for part in (found["city"], " ".join(p for p in (found["state"], found["zip"]) if p), found["country"]) if part) if found["saved"] else ""
    try:
        return ZoneInfo(place_zones.zone_for_address(conn, address) or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _dated_window(conn: db.Connection, trip: Trip) -> TripWindow | None:
    if not trip.start_date or not trip.end_date:
        return None
    zone = _home_zone(conn)
    start = datetime.combine(datetime.fromisoformat(trip.start_date).date(), clock(0, 0), zone)
    end = datetime.combine(datetime.fromisoformat(trip.end_date).date(), clock(23, 59), zone)
    return TripWindow(trip.id, start.astimezone(UTC) - photomatch.PAD, end.astimezone(UTC) + photomatch.PAD, ())


def trip_window(conn: db.Connection, trip_id: int) -> TripWindow | None:
    trip = conn.orm.get(Trip, trip_id)
    if trip is None:
        return None
    booked = list(conn.orm.scalars(select(Segment).where(Segment.trip_id == trip.id).order_by(Segment.id)).all())
    live = [s for s in booked if s.status != "cancelled"]
    if not live:
        return _dated_window(conn, trip) if not booked else None
    placed = segment_points(conn, live)
    return window(trip, [p for s in live for p in placed[s.id]])


def trip_points(conn: db.Connection, trip_id: int) -> tuple[SegmentPoint, ...]:
    live = [s for s in conn.orm.scalars(select(Segment).where(Segment.trip_id == trip_id).order_by(Segment.id)).all() if s.status != "cancelled"]
    placed = segment_points(conn, live)
    return tuple(p for s in live for p in placed[s.id])


def window_holds(conn: db.Connection, trip_id: int, photo: Photo) -> bool:
    found = trip_window(conn, trip_id)
    return found is not None and found.start <= instant(photo.taken_utc) <= found.end


def _excluded() -> ColumnElement[bool]:
    return select(PhotoExclusion.asset_id).where(PhotoExclusion.person_id == PhotoSource.person_id, PhotoExclusion.asset_id == Photo.asset_id,
                                                 PhotoExclusion.trip_id == Photo.trip_id).exists()


def _aboard() -> ColumnElement[bool]:
    return select(TripPerson.trip_id).where(TripPerson.trip_id == Photo.trip_id, TripPerson.person_id == PhotoSource.person_id).exists()


def visible(conn: db.Connection, viewer: Viewer) -> ColumnElement[bool]:
    if viewer.person_id is None:
        return false()
    return and_(Photo.trip_id.is_not(None), Photo.match.in_(SHOWN), visibility.can_see(viewer), _granted(persons_of(conn, viewer), viewer.person_id), ~_excluded(),
                _aboard())


def _query(conn: db.Connection, viewer: Viewer, *where: ColumnElement[bool]) -> list[Found]:
    q = select(Photo, PhotoSource.person_id).join(PhotoSource, PhotoSource.id == Photo.source_id).join(Trip, Trip.id == Photo.trip_id) \
        .where(visible(conn, viewer), *where)
    return _canonical(conn, sorted(((photo, person) for photo, person in conn.orm.execute(q).all()), key=lambda found: (instant(found[0].taken_utc), found[0].id)))


def visible_rows(conn: db.Connection, viewer: Viewer, trip_id: int | None = None) -> list[Found]:
    return _query(conn, viewer, *([Photo.trip_id == trip_id] if trip_id is not None else []))


def visible_photo(conn: db.Connection, viewer: Viewer, photo_id: int) -> Found | None:
    found = _query(conn, viewer, Photo.id == photo_id)
    return found[0] if found else None


def _candidates(conn: db.Connection, photo: Photo, person: int, windows: Sequence[TripWindow], seen: set[int] | None = None) -> list[TripWindow]:
    taken = instant(photo.taken_utc)
    left_out = excluded_trips(conn, person, photo.asset_id)
    return [w for w in windows if w.start <= taken <= w.end and w.trip_id not in left_out and (seen is None or w.trip_id in seen)]


def _seen(conn: db.Connection, viewer: Viewer) -> set[int]:
    return {t.id for t in visibility.visible_trips(conn, viewer)}


def _with_candidates(conn: db.Connection, viewer: Viewer, rows: Sequence[Found]) -> list[tuple[Photo, int, list[TripWindow]]]:
    seen = _seen(conn, viewer)
    windows = {person: candidate_windows(conn, person) for person in sorted({person for _, person in rows})}
    found = [(p, person, _candidates(conn, p, person, windows[person], seen)) for p, person in rows]
    return [(p, person, candidates) for p, person, candidates in found if candidates]


def unsettled(conn: db.Connection, viewer: Viewer, photo_id: int | None = None) -> list[tuple[Photo, int, list[TripWindow]]]:
    persons = persons_of(conn, viewer)
    if not persons:
        return []
    where = [PhotoSource.person_id.in_(persons), Photo.match == AMBIGUOUS, Photo.trip_id.is_(None), or_(Photo.decided_by.is_(None), Photo.decided_by != OWNER)]
    rows = [row for row in _rows(conn, *where) if photo_id is None or row[0].id == photo_id]
    return _with_candidates(conn, viewer, rows)


def removed(conn: db.Connection, viewer: Viewer, trip_id: int) -> list[Found]:
    persons = persons_of(conn, viewer)
    if not persons or visibility.visible_trip(conn, viewer, trip_id) is None:
        return []
    left_out = select(PhotoExclusion.asset_id).where(PhotoExclusion.person_id == PhotoSource.person_id, PhotoExclusion.asset_id == Photo.asset_id,
                                                     PhotoExclusion.trip_id == trip_id).exists()
    found = trip_window(conn, trip_id)
    if found is None:
        return []
    return [(p, person) for p, person in _rows(conn, PhotoSource.person_id.in_(persons), left_out) if found.start <= instant(p.taken_utc) <= found.end]


def _zone_by_place(points: Sequence[SegmentPoint], at: datetime, spot: Point) -> str | None:
    ends = [(distance_km(spot, place), p.gap(at), p.segment_id, order, n, zone) for order, p in enumerate(points) if not p.borrowed
            for n, (place, zone) in enumerate(((p.origin, p.zone), (p.destination, p.to_zone))) if place is not None]
    nearest = min(ends, default=None)
    return nearest[5] if nearest is not None and nearest[0] <= NEAR else None


def _zone_by_time(points: Sequence[SegmentPoint], at: datetime) -> str | None:
    active = min((p for p in points if p.start <= at < p.end), key=lambda p: (p.end - p.start, p.start), default=None)
    if active is not None:
        return active.zone
    ended = max((p for p in points if p.end <= at), key=lambda p: (p.end, p.start), default=None)
    if ended is not None:
        return ended.to_zone
    upcoming = min((p for p in points if p.start > at), key=lambda p: (p.start, p.end), default=None)
    return upcoming.zone if upcoming is not None else None


def _zone(photo: Photo, placed: Mapping[int, Sequence[SegmentPoint]]) -> str | None:
    if photo.taken_offset is not None:
        return offset_label(photo.taken_offset)
    points = placed.get(photo.segment_id, ()) if photo.segment_id is not None else ()
    if not points:
        return None
    at = instant(photo.taken_utc)
    if photo.location_source == "exif" and photo.latitude is not None and photo.longitude is not None:
        return _zone_by_place(points, at, (photo.latitude, photo.longitude)) or _zone_by_time(points, at)
    return _zone_by_time(points, at)


def _placed(conn: db.Connection, viewer: Viewer, trip_ids: Sequence[int]) -> dict[int, list[SegmentPoint]]:
    ids = sorted(set(trip_ids))
    return segment_points(conn, visibility.visible_segments(conn, viewer, ids)) if ids else {}


def photo_out(photo: Photo, person_id: int, placed: Mapping[int, Sequence[SegmentPoint]]) -> TripPhoto:
    return {
        "id": photo.id, "person_id": person_id, "trip_id": photo.trip_id, "kind": cast(Literal["image", "video"], photo.kind),
        "taken_local": photo.taken_local, "zone": _zone(photo, placed),
        "latitude": photo.latitude, "longitude": photo.longitude, "location_source": cast(LocationSource | None, photo.location_source),
        "segment_id": photo.segment_id, "match": cast(MatchKind, photo.match), "distance_km": photo.distance_km,
        "cluster": None,
    }


def _rows(conn: db.Connection, *where: ColumnElement[bool]) -> list[Found]:
    q = select(Photo, PhotoSource.person_id).join(PhotoSource, PhotoSource.id == Photo.source_id).where(*where)
    return _canonical(conn, sorted(((photo, person) for photo, person in conn.orm.execute(q).all()), key=lambda found: (instant(found[0].taken_utc), found[0].id)))


def _wrapped(longitude: float) -> float:
    if -180.0 <= longitude < 180.0:
        return longitude
    turned = (longitude + 180.0) % 360.0 - 180.0
    return turned if turned < 180.0 else -180.0


@dataclass(eq=False)
class _Cluster:
    latitude: float
    longitude: float
    count: int
    first_at: int
    last_at: int
    inferred: bool
    members: list[int]
    cell: tuple[int, int] = (0, 0)
    index: int = -1
    alive: bool = True

    def joined(self, other: _Cluster) -> None:
        total = self.count + other.count
        self.latitude = (self.latitude * self.count + other.latitude * other.count) / total
        self.longitude = _wrapped(self.longitude + _wrapped(other.longitude - self.longitude) * other.count / total)
        self.count = total
        self.first_at = min(self.first_at, other.first_at)
        self.last_at = max(self.last_at, other.last_at)
        self.inferred = self.inferred and other.inferred
        self.members += other.members


def _cell(point: Point) -> tuple[int, int]:
    return min(math.floor(point[0] / CELL), ROWS // 2 - 1), math.floor(point[1] / CELL) % COLUMNS


def _span(latitude: float) -> int:
    stretch = math.cos(math.radians(min(abs(latitude) + CELL, 90.0)))
    return COLUMNS // 2 if stretch < 1e-9 else min(COLUMNS // 2, math.ceil(CLUSTER / KM_PER_DEGREE / CELL / stretch))


def _ring(cell: tuple[int, int], span: int, ring: int) -> Iterator[tuple[int, int]]:
    row, col = cell
    if ring == 0:
        yield cell
        return
    width, inner = min(ring * span, COLUMNS // 2), min((ring - 1) * span, COLUMNS // 2)
    across = range(-width, width + 1) if 2 * width + 1 < COLUMNS else range(COLUMNS)
    for dr in (-ring, ring):
        if -ROWS // 2 <= row + dr < ROWS // 2:
            for dc in across:
                yield row + dr, (col + dc) % COLUMNS
    if width > inner:
        sides = [*range(-width, -inner), *range(inner + 1, width + 1)]
        for dr in range(max(1 - ring, -ROWS // 2 - row), min(ring, ROWS // 2 - row)):
            for dc in sides:
                yield row + dr, (col + dc) % COLUMNS


def _cap(point: Point, radius_km: float) -> tuple[range, range]:
    reach = math.degrees(radius_km / EARTH_RADIUS_KM)
    rows = range(max(-ROWS // 2, math.floor((point[0] - reach) / CELL)), min(ROWS // 2, math.floor((point[0] + reach) / CELL) + 1))
    if abs(point[0]) + reach >= 90.0:
        return rows, range(COLUMNS)
    half = math.degrees(math.asin(min(1.0, math.sin(math.radians(reach)) / math.cos(math.radians(point[0])))))
    width = min(COLUMNS // 2, math.ceil(half / CELL) + 1)
    return rows, range(-width, width + 1) if 2 * width + 1 < COLUMNS else range(COLUMNS)


Closest = tuple[float, int, "_Cluster"]


class _Grid:
    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.found: list[_Cluster] = []
        self.alive = 0

    def _in(self, cells: Iterator[tuple[int, int]]) -> set[int]:
        return {i for c in cells for i in self.cells.get(c, ())}

    def first_within(self, point: Point) -> _Cluster | None:
        cell, span = _cell(point), _span(point[0])
        for i in sorted(self._in(_ring(cell, span, 0)) | self._in(_ring(cell, span, 1))):
            c = self.found[i]
            if distance_km(point, (c.latitude, c.longitude)) <= CLUSTER:
                return c
        return None

    def _closest(self, cluster: _Cluster, indexes: set[int], best: Closest) -> Closest:
        here = (cluster.latitude, cluster.longitude)
        for i in indexes:
            other = self.found[i]
            if other is not cluster:
                best = min(best, (distance_km(here, (other.latitude, other.longitude)), other.first_at, other))
        return best

    def _every(self, cluster: _Cluster, best: Closest) -> _Cluster:
        return self._closest(cluster, {i for i, c in enumerate(self.found) if c.alive}, best)[2]

    def nearest(self, cluster: _Cluster) -> _Cluster:
        best: Closest = (math.inf, 0, cluster)
        ring = looked = 0
        while best[0] == math.inf:
            cells = list(_ring(cluster.cell, _span(abs(cluster.latitude) + ring * CELL), ring))
            looked += len(cells)
            if looked > self.alive:
                return self._every(cluster, best)
            best = self._closest(cluster, self._in(iter(cells)), best)
            ring += 1
        rows, across = _cap((cluster.latitude, cluster.longitude), best[0])
        if len(rows) * len(across) > self.alive:
            return self._every(cluster, best)
        col = cluster.cell[1]
        return self._closest(cluster, self._in((r, (col + dc) % COLUMNS) for r in rows for dc in across), best)[2]

    def add(self, cluster: _Cluster) -> None:
        cluster.index, cluster.cell = len(self.found), _cell((cluster.latitude, cluster.longitude))
        self.found.append(cluster)
        self.cells.setdefault(cluster.cell, []).append(cluster.index)
        self.alive += 1

    def moved(self, cluster: _Cluster) -> None:
        cell = _cell((cluster.latitude, cluster.longitude))
        if cell != cluster.cell:
            self.cells[cluster.cell].remove(cluster.index)
            cluster.cell = cell
            self.cells.setdefault(cell, []).append(cluster.index)

    def remove(self, cluster: _Cluster) -> None:
        self.cells[cluster.cell].remove(cluster.index)
        cluster.alive = False
        self.alive -= 1


def _merge_down(grid: _Grid) -> list[_Cluster]:
    queue = [(c.count, c.first_at, c.index) for c in grid.found]
    heapq.heapify(queue)
    while grid.alive > MAX_CLUSTERS:
        count, _, index = heapq.heappop(queue)
        smallest = grid.found[index]
        if not smallest.alive or smallest.count != count:
            continue
        into = grid.nearest(smallest)
        into.joined(smallest)
        grid.remove(smallest)
        grid.moved(into)
        heapq.heappush(queue, (into.count, into.first_at, into.index))
    return [c for c in grid.found if c.alive]


def clusters(rows: Sequence[TripPhoto]) -> list[PhotoCluster]:
    grid = _Grid()
    for index, row in enumerate(rows):
        row["cluster"] = None
        if row["latitude"] is None or row["longitude"] is None:
            continue
        point = (row["latitude"], _wrapped(row["longitude"]))
        inferred = row["location_source"] == INFERRED
        joined = grid.first_within(point)
        if joined is None:
            grid.add(_Cluster(point[0], point[1], 1, index, index, inferred, [index]))
            continue
        joined.joined(_Cluster(point[0], point[1], 1, index, index, inferred, [index]))
        grid.moved(joined)
    found = sorted(_merge_down(grid), key=lambda c: c.first_at)
    for number, c in enumerate(found):
        for member in c.members:
            rows[member]["cluster"] = number
    return [{"latitude": c.latitude, "longitude": c.longitude, "count": c.count, "first": rows[c.first_at]["taken_local"],
             "last": rows[c.last_at]["taken_local"], "cover": rows[c.first_at]["id"], "inferred": c.inferred} for c in found]


def for_trip(conn: db.Connection, viewer: Viewer, trip_id: int) -> TripPhotos | None:
    trip = visibility.visible_trip(conn, viewer, trip_id) if not viewer.household else None
    if trip is None:
        return None
    rows = visible_rows(conn, viewer, trip.id)
    placed = _placed(conn, viewer, [trip.id])
    photos = [photo_out(p, person, placed) for p, person in rows]
    found = clusters(photos)
    by_person = Counter(person for _, person in rows)
    return {
        "photos": photos, "clusters": found,
        "counts": {"total": len(photos), "located": sum(p["location_source"] == "exif" for p in photos),
                   "inferred": sum(p["location_source"] == INFERRED for p in photos), "far": sum(p["match"] == FAR for p in photos)},
        "people": [{"person_id": person, "count": by_person[person]} for person in sorted(by_person)],
    }


def _far_rows(conn: db.Connection, viewer: Viewer) -> list[tuple[Photo, int, list[TripWindow]]]:
    persons = persons_of(conn, viewer)
    rows = _query(conn, viewer, PhotoSource.person_id.in_(persons), Photo.match == FAR, or_(Photo.decided_by.is_(None), Photo.decided_by != OWNER))
    return _with_candidates(conn, viewer, rows)


def needs_a_look(conn: db.Connection, viewer: Viewer) -> PhotoReview:
    if viewer.person_id is None:
        return {"photos": []}
    rows = sorted([*_far_rows(conn, viewer), *unsettled(conn, viewer)], key=lambda found: (instant(found[0].taken_utc), found[0].id))
    names = {t.id: t.name for t in visibility.visible_trips(conn, viewer)}
    placed = _placed(conn, viewer, [p.trip_id for p, _, _ in rows if p.trip_id is not None])
    photos: list[ReviewPhoto] = []
    for p, person, windows in rows:
        candidates: list[PhotoCandidate] = [{"id": w.trip_id, "name": names[w.trip_id]} for w in windows if w.trip_id in names]
        photos.append({**photo_out(p, person, placed), "candidates": candidates})
    return {"photos": photos}


def _shot(photo: Photo, person: int) -> PhotoIn:
    gps = photo.location_source == "exif"
    return PhotoIn(instant(photo.taken_utc), photo.latitude if gps else None, photo.longitude if gps else None, person)


def _apply(photo: Photo, placed: photomatch.Match, chosen: TripWindow | None, decided: str) -> None:
    photo.match, photo.segment_id, photo.distance_km = placed.match, placed.segment_id, placed.distance_km
    photo.decided_by = decided
    if photo.location_source == "exif":
        return
    here = where_was(chosen.points, instant(photo.taken_utc)) if chosen is not None else None
    photo.latitude, photo.longitude = (here[0], here[1]) if here else (None, None)
    photo.location_source = INFERRED if here else None


def _place(photo: Photo, person: int, chosen: TripWindow | None) -> None:
    _apply(photo, photomatch.settle(_shot(photo, person), chosen), chosen, OWNER)


def re_place(conn: db.Connection, photo: Photo, person: int) -> bool:
    shot = _shot(photo, person)
    inside = [w for w in candidate_windows(conn, person) if w.start <= shot.taken <= w.end]
    left_out = excluded_trips(conn, person, photo.asset_id)
    candidates = [w for w in inside if w.trip_id not in left_out]
    placed = photomatch.match(shot, candidates, None)
    if placed.match == "none":
        removed_from = sorted((w for w in inside if w.trip_id in left_out), key=lambda w: w.trip_id)
        if not removed_from:
            conn.orm.delete(photo)
            conn.orm.flush()
            return False
        photo.trip_id = removed_from[0].trip_id
        _apply(photo, photomatch.settle(shot, removed_from[0]), removed_from[0], AUTO)
        conn.orm.flush()
        return True
    chosen = next((w for w in candidates if w.trip_id == placed.trip_id), None)
    photo.trip_id = placed.trip_id
    _apply(photo, placed, chosen, AUTO)
    conn.orm.flush()
    return True


def _own_photo(conn: db.Connection, viewer: Viewer, photo_id: int) -> Found | None:
    found = visible_photo(conn, viewer, photo_id) or next(((p, person) for p, person, _ in unsettled(conn, viewer, photo_id)), None)
    return found if found is not None and acts_for(conn, viewer, found[1]) else None


def _settled_under_lock(conn: db.Connection, viewer: Viewer, photo_id: int, trip_id: int | None) -> tuple[Found, set[int]] | None:
    found = _own_photo(conn, viewer, photo_id)
    if found is None:
        return None
    person = found[1]
    locked = granted_trips(conn, person) | {t for t in (found[0].trip_id, trip_id) if t is not None}
    lock_grants(conn, person, sorted(locked))
    conn.orm.expire_all()
    found = _own_photo(conn, viewer, photo_id)
    if found is None or (found[0].trip_id is not None and found[0].trip_id not in locked):
        return None
    return found, locked


def _same_asset(conn: db.Connection, photo: Photo, person: int) -> list[Photo]:
    q = select(Photo).join(PhotoSource, PhotoSource.id == Photo.source_id) \
        .where(PhotoSource.person_id == person, Photo.asset_id == photo.asset_id, Photo.id != photo.id).order_by(Photo.id)
    return list(conn.orm.scalars(q).all())


def copy_placement(conn: db.Connection, photo: Photo, person: int) -> None:
    chosen = next((w for w in candidate_windows(conn, person) if w.trip_id == photo.trip_id), None) if photo.trip_id is not None else None
    for twin in _same_asset(conn, photo, person):
        twin.trip_id = photo.trip_id
        if photo.decided_by == OWNER:
            _place(twin, person, chosen)
        else:
            _apply(twin, photomatch.settle(_shot(twin, person), chosen) if chosen is not None else photomatch.Match(cast(MatchKind, photo.match)), chosen, AUTO)
    conn.orm.flush()


def place_by_hand(conn: db.Connection, photo: Photo, person: int, trip_id: int) -> None:
    photo.trip_id = trip_id
    _place(photo, person, next((w for w in candidate_windows(conn, person) if w.trip_id == trip_id), None))
    copy_placement(conn, photo, person)


def decide(conn: db.Connection, viewer: Viewer, photo_id: int, trip_id: int | None, excluded: bool | None) -> TripPhoto | None:
    settled = _settled_under_lock(conn, viewer, photo_id, trip_id) if not viewer.household else None
    if settled is None:
        return None
    (photo, person), locked = settled
    if trip_id is not None:
        trip = visibility.visible_trip(conn, viewer, trip_id)
        if trip is None or person not in trippeople.of(conn, [trip.id])[trip.id]:
            raise trips.Invalid(NOT_ON_TRIP)
        if trip.id not in granted_trips(conn, person):
            raise trips.Invalid(SHARE_FIRST)
        if trip.id in excluded_trips(conn, person, photo.asset_id):
            raise trips.Invalid(PUT_BACK_FIRST)
        if not window_holds(conn, trip.id, photo):
            raise OutsideWindow(NOT_IN_WINDOW)
        place_by_hand(conn, photo, person, trip.id)
    if excluded:
        if photo.match != AMBIGUOUS or photo.trip_id is not None:
            raise trips.Invalid(NOT_UNSETTLED)
        fresh = next(((p, c) for p, _, c in unsettled(conn, viewer, photo_id)), None)
        if fresh is None:
            return None
        photo, candidates = fresh
        if any(w.trip_id not in locked for w in candidates):
            raise Changed(CHANGED)
        for w in candidates:
            db.insert_ignore(conn, PhotoExclusion, {"person_id": person, "asset_id": photo.asset_id, "trip_id": w.trip_id, "created": time.time(), "was_trip_id": None},
                             key=["person_id", "asset_id", "trip_id"])
    conn.orm.flush()
    return photo_out(photo, person, _placed(conn, viewer, [photo.trip_id] if photo.trip_id is not None else []))
