from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, TypedDict, cast

from sqlalchemy import ColumnElement, or_, select

from ..storage import db, geocode
from ..storage.models import Airport, Photo, PhotoSource, Segment
from . import photomatch, trippeople, trips, visibility
from .photomatch import CLUSTER, GAP, MatchKind, PhotoIn, Point, SegmentPoint, TripWindow, window
from .stats import distance_km
from .visibility import Viewer

Located = tuple[float, float, int]
LocationSource = Literal["exif", "inferred"]

SHOWN: tuple[MatchKind, ...] = ("place", "time", "far")
LOOK: tuple[MatchKind, ...] = ("ambiguous", "far")
OWNER = "owner"
INFERRED: LocationSource = "inferred"
MAX_CLUSTERS = 400
NOT_ON_TRIP = "Choose a trip you are on"
CELL = 0.1


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
    hidden: bool


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
    hidden: int


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
                             arriving[0] if arriving else None, arriving[1] if arriving else None, timed)]
    if seg.kind == "train":
        return [SegmentPoint(seg.id, seg.kind, start, end, None, None, seg.latitude, seg.longitude, timed)]
    main = SegmentPoint(seg.id, seg.kind, start, end, seg.latitude, seg.longitude, timed=timed)
    if seg.kind != "cruise":
        return [main]
    calls: list[SegmentPoint] = []
    for port in ports:
        found = geocode.locate_port(port["name"])
        if found is None:
            continue
        arrive = trips.instant(port["arrive_local"], port["zone"]) if port["arrive_local"] else start
        depart = trips.instant(port["depart_local"], port["zone"]) if port["depart_local"] else end
        calls.append(SegmentPoint(seg.id, seg.kind, arrive, depart, found.latitude, found.longitude, timed=timed))
    if main.origin is None and calls:
        main = replace(main, latitude=calls[0].latitude, longitude=calls[0].longitude)
    return [main, *calls]


def candidate_windows(conn: db.Connection, person_id: int) -> list[TripWindow]:
    viewer = Viewer(person_id)
    seen = visibility.visible_trips(conn, viewer)
    aboard = trippeople.of(conn, [t.id for t in seen])
    mine = [t for t in seen if person_id in aboard[t.id]]
    if not mine:
        return []
    live = [s for s in visibility.visible_segments(conn, viewer, [t.id for t in mine]) if s.status != "cancelled"]
    codes = sorted({_code(c) for s in live if s.kind == "flight" for c in (s.origin, s.destination)} - {""})
    airport_at = {a.code: (a.latitude, a.longitude) for a in conn.orm.scalars(select(Airport).where(Airport.code.in_(codes))).all()}
    ports = trips.ports_of(conn, [s.id for s in live if s.kind == "cruise"])
    windows: list[TripWindow] = []
    for trip in mine:
        points = [p for s in live if s.trip_id == trip.id for p in _points(s, airport_at, ports.get(s.id, []))]
        found = window(trip, points)
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


def _owns(viewer: Viewer, person_id: int) -> bool:
    return viewer.household or viewer.person_id == person_id


def _zone(photo: Photo, segments: Mapping[int, Segment]) -> str | None:
    if photo.taken_offset is not None:
        return offset_label(photo.taken_offset)
    seg = segments.get(photo.segment_id) if photo.segment_id is not None else None
    if seg is None:
        return None
    return seg.end_zone if instant(photo.taken_utc) >= trips.instant(seg.end_local, seg.end_zone) else seg.start_zone


def _segments(conn: db.Connection, viewer: Viewer, trip_ids: Sequence[int]) -> dict[int, Segment]:
    ids = sorted({t for t in trip_ids})
    return {s.id: s for s in visibility.visible_segments(conn, viewer, ids)} if ids else {}


def _out(photo: Photo, person_id: int, segments: Mapping[int, Segment]) -> TripPhoto:
    return {
        "id": photo.id, "person_id": person_id, "trip_id": photo.trip_id, "kind": cast(Literal["image", "video"], photo.kind),
        "taken_local": photo.taken_local, "zone": _zone(photo, segments),
        "latitude": photo.latitude, "longitude": photo.longitude, "location_source": cast(LocationSource | None, photo.location_source),
        "segment_id": photo.segment_id, "match": cast(MatchKind, photo.match), "distance_km": photo.distance_km,
        "cluster": None, "hidden": photo.hidden,
    }


def _rows(conn: db.Connection, *where: ColumnElement[bool]) -> list[tuple[Photo, int]]:
    q = select(Photo, PhotoSource.person_id).join(PhotoSource, PhotoSource.id == Photo.source_id).where(*where) \
        .order_by(Photo.taken_utc, Photo.id)
    return [(photo, person) for photo, person in conn.orm.execute(q).all()]


@dataclass(eq=False)
class _Cluster:
    latitude: float
    longitude: float
    count: int
    first_at: int
    last_at: int
    inferred: bool
    members: list[int]
    cell: tuple[int, int]
    index: int = -1

    def joined(self, other: _Cluster) -> None:
        total = self.count + other.count
        self.latitude = (self.latitude * self.count + other.latitude * other.count) / total
        self.longitude = (self.longitude * self.count + other.longitude * other.count) / total
        self.count = total
        self.first_at = min(self.first_at, other.first_at)
        self.last_at = max(self.last_at, other.last_at)
        self.inferred = self.inferred and other.inferred
        self.members += other.members


def _cell(point: Point) -> tuple[int, int]:
    return math.floor(point[0] / CELL), math.floor(point[1] / CELL)


def _near_cells(point: Point) -> list[tuple[int, int]]:
    row, col = _cell(point)
    stretch = math.cos(math.radians(point[0]))
    if stretch < 0.1:
        return []
    span = math.ceil(CLUSTER / 111.0 / CELL / stretch)
    return [(row + dr, col + dc) for dr in (-1, 0, 1) for dc in range(-span, span + 1)]


class _Grid:
    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.found: list[_Cluster] = []

    def first_within(self, point: Point) -> _Cluster | None:
        cells = _near_cells(point)
        indexes = sorted({i for c in cells for i in self.cells.get(c, ())}) if cells else range(len(self.found))
        for i in indexes:
            c = self.found[i]
            if distance_km(point, (c.latitude, c.longitude)) <= CLUSTER:
                return c
        return None

    def add(self, cluster: _Cluster) -> None:
        cluster.index = len(self.found)
        self.found.append(cluster)
        self.cells.setdefault(cluster.cell, []).append(cluster.index)

    def moved(self, cluster: _Cluster) -> None:
        cell = _cell((cluster.latitude, cluster.longitude))
        if cell != cluster.cell:
            self.cells[cluster.cell].remove(cluster.index)
            cluster.cell = cell
            self.cells.setdefault(cell, []).append(cluster.index)


def _merge_down(found: list[_Cluster]) -> list[_Cluster]:
    while len(found) > MAX_CLUSTERS:
        smallest = min(range(len(found)), key=lambda i: (found[i].count, found[i].first_at))
        s = found[smallest]
        nearest = min((i for i in range(len(found)) if i != smallest),
                      key=lambda i: (distance_km((s.latitude, s.longitude), (found[i].latitude, found[i].longitude)), found[i].first_at))
        found[nearest].joined(s)
        del found[smallest]
    return found


def clusters(rows: Sequence[TripPhoto]) -> list[PhotoCluster]:
    grid = _Grid()
    for index, row in enumerate(rows):
        row["cluster"] = None
        if row["latitude"] is None or row["longitude"] is None:
            continue
        point = (row["latitude"], row["longitude"])
        inferred = row["location_source"] == INFERRED
        joined = grid.first_within(point)
        if joined is None:
            grid.add(_Cluster(point[0], point[1], 1, index, index, inferred, [index], _cell(point)))
            continue
        joined.joined(_Cluster(point[0], point[1], 1, index, index, inferred, [index], _cell(point)))
        grid.moved(joined)
    found = sorted(_merge_down(grid.found), key=lambda c: c.first_at)
    for number, c in enumerate(found):
        for member in c.members:
            rows[member]["cluster"] = number
    return [{"latitude": c.latitude, "longitude": c.longitude, "count": c.count, "first": rows[c.first_at]["taken_local"],
             "last": rows[c.last_at]["taken_local"], "cover": rows[c.first_at]["id"], "inferred": c.inferred} for c in found]


def for_trip(conn: db.Connection, viewer: Viewer, trip_id: int) -> TripPhotos | None:
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return None
    rows = [(p, person) for p, person in _rows(conn, Photo.trip_id == trip.id, Photo.match.in_(SHOWN)) if not p.hidden or _owns(viewer, person)]
    segments = _segments(conn, viewer, [trip.id])
    photos = [_out(p, person, segments) for p, person in rows]
    found = clusters(photos)
    by_person = Counter(person for _, person in rows)
    return {
        "photos": photos, "clusters": found,
        "counts": {"total": len(photos), "located": sum(p["location_source"] == "exif" for p in photos),
                   "inferred": sum(p["location_source"] == INFERRED for p in photos), "far": sum(p["match"] == "far" for p in photos),
                   "hidden": sum(p["hidden"] for p in photos)},
        "people": [{"person_id": person, "count": by_person[person]} for person in sorted(by_person)],
    }


def needs_a_look(conn: db.Connection, viewer: Viewer) -> PhotoReview:
    if viewer.person_id is None and not viewer.household:
        return {"photos": []}
    whose = [] if viewer.household else [PhotoSource.person_id == viewer.person_id]
    rows = _rows(conn, *whose, Photo.match.in_(LOOK), or_(Photo.decided_by.is_(None), Photo.decided_by != OWNER))
    windows = {person: candidate_windows(conn, person) for person in sorted({person for _, person in rows})}
    names = {t.id: t.name for t in visibility.visible_trips(conn, viewer)}
    segments = _segments(conn, viewer, [p.trip_id for p, _ in rows if p.trip_id is not None])
    photos: list[ReviewPhoto] = []
    for p, person in rows:
        taken = instant(p.taken_utc)
        candidates: list[PhotoCandidate] = [{"id": w.trip_id, "name": names[w.trip_id]} for w in windows[person]
                                            if w.start <= taken <= w.end and w.trip_id in names]
        photos.append({**_out(p, person, segments), "candidates": candidates})
    return {"photos": photos}


def _place(photo: Photo, person: int, chosen: TripWindow | None) -> None:
    taken = instant(photo.taken_utc)
    gps = photo.location_source == "exif"
    placed = photomatch.settle(PhotoIn(taken, photo.latitude if gps else None, photo.longitude if gps else None, person), chosen)
    photo.match, photo.segment_id, photo.distance_km = placed.match, placed.segment_id, placed.distance_km
    photo.decided_by = OWNER
    if gps:
        return
    here = where_was(chosen.points, taken) if chosen is not None else None
    photo.latitude, photo.longitude = (here[0], here[1]) if here else (None, None)
    photo.location_source = INFERRED if here else None


def decide(conn: db.Connection, viewer: Viewer, photo_id: int, trip_id: int | None, hidden: bool | None) -> TripPhoto | None:
    found = _rows(conn, Photo.id == photo_id)
    if not found or not _owns(viewer, found[0][1]):
        return None
    photo, person = found[0]
    if trip_id is not None:
        trip = visibility.visible_trip(conn, viewer, trip_id)
        if trip is None or person not in trippeople.of(conn, [trip.id])[trip.id]:
            raise trips.Invalid(NOT_ON_TRIP)
        photo.trip_id = trip.id
        _place(photo, person, next((w for w in candidate_windows(conn, person) if w.trip_id == trip.id), None))
    if hidden is not None:
        photo.hidden = hidden
    conn.orm.flush()
    return _out(photo, person, _segments(conn, viewer, [photo.trip_id] if photo.trip_id is not None else []))
