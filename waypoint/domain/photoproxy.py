from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass, field

from ..providers import immich
from ..storage import db, photo_sources, secretbox
from ..storage.photo_sources import REFUSED
from . import photoqueue, photos, photosources
from .photos import Rendition
from .visibility import Viewer

RECHECK_SECONDS = 5.0
SNIFF_RANGE = f"bytes=0-{immich.SNIFF_BYTES - 1}"
KNOWN_TYPES = 1024
UNAVAILABLE = "Couldn’t get this picture from the photo library; try again later."
INLINE = "inline"
ATTACHMENT = "attachment"
RANGE_NOT_SATISFIABLE = 416

Body = Generator[bytes]


class Unavailable(Exception):
    pass


class Missing(Exception):
    pass


@dataclass(frozen=True)
class Served:
    photo_id: int
    asset_id: str
    asset_updated: str
    source_id: int
    demo: bool
    checked: float

    @property
    def revision(self) -> tuple[int, int, str, str]:
        return self.photo_id, self.source_id, self.asset_id, self.asset_updated


@dataclass(frozen=True)
class Picture:
    content_type: str
    data: bytes


@dataclass(frozen=True)
class Stream:
    status: int
    content_type: str
    disposition: str
    headers: dict[str, str] = field(default_factory=dict)
    body: Body | None = None


@dataclass(frozen=True)
class Library:
    source: immich.Source = field(repr=False)
    sealed: str | None = field(repr=False)


_known: dict[tuple[int, int, str, str], tuple[str, bool]] = {}
_lock = threading.Lock()


def find(conn: db.Connection, viewer: Viewer, photo_id: int) -> Served | None:
    found = photos.served(conn, viewer, photo_id)
    if found is None:
        return None
    photo = found[0]
    source = photo_sources.get(conn, photo.source_id)
    if source is None:
        return None
    return Served(photo.id, photo.asset_id, photo.asset_updated, source["id"], source["url"] == photoqueue.DEMO, time.monotonic())


def etag(served: Served, size: Rendition) -> str:
    photo_id, source_id, asset_id, asset_updated = served.revision
    digest = hashlib.sha256(f"{photo_id}:{source_id}:{asset_id}:{size}:{asset_updated}".encode()).hexdigest()[:32]
    return f'"{digest}"'


def _refuse(conn: db.Connection, served: Served, error: str, sealed: str | None) -> None:
    photo_sources.mark(conn, served.source_id, REFUSED, error, keep_off=True, sealed=sealed)
    conn.commit()


def _unlocked(conn: db.Connection, served: Served) -> Library | None:
    sealed = photo_sources.sealed_key(conn, served.source_id)
    try:
        source = photosources.unlock(conn, served.source_id)
    except secretbox.SecretError:
        _refuse(conn, served, photosources.KEY_LOST, sealed)
        return None
    return Library(source, sealed) if source is not None else None


def _ask[T](conn: db.Connection, served: Served, library: Library, ask: Callable[[], T]) -> T:
    try:
        return ask()
    except (immich.Refused, immich.NotConfigured) as e:
        _refuse(conn, served, str(e), library.sealed)
        raise Missing() from None
    except immich.NotAnImage:
        raise Missing() from None
    except immich.ImmichError:
        raise Unavailable(UNAVAILABLE) from None


def _gone(conn: db.Connection, served: Served, library: Library) -> None:
    try:
        if _ask(conn, served, library, lambda: immich.asset_exists(library.source, served.asset_id)):
            return
    except (Missing, Unavailable):
        return
    photos.forget(conn, served.photo_id, served.source_id, served.asset_id)
    conn.commit()


def rendition(conn: db.Connection, served: Served, size: Rendition) -> Picture | None:
    if served.demo:
        return Picture(*photos.placeholder(served.asset_id, size))
    library = _unlocked(conn, served)
    if library is None:
        return None
    try:
        got = _ask(conn, served, library, lambda: immich.thumbnail(library.source, served.asset_id, size))
    except Missing:
        return None
    if got is None:
        _gone(conn, served, library)
        return None
    return Picture(*got)


def _once(data: bytes) -> Body:
    yield data


def _open(conn: db.Connection, served: Served, library: Library, byte_range: str | None) -> immich.Original:
    got = _ask(conn, served, library, lambda: immich.open_original(library.source, served.asset_id, byte_range=byte_range))
    if got is None:
        _gone(conn, served, library)
        raise Missing()
    return got


def _prefix(original: immich.Original) -> bytes:
    data = b""
    while len(data) < immich.SNIFF_BYTES:
        try:
            chunk = original.read()
        except immich.ImmichError:
            raise Unavailable(UNAVAILABLE) from None
        if not chunk:
            break
        data += chunk
    return data


def _typed(served: Served, data: bytes) -> tuple[str, bool]:
    found = immich.original_type(data)
    if found is None:
        raise Missing()
    with _lock:
        if len(_known) >= KNOWN_TYPES:
            _known.clear()
        _known[served.revision] = found
    return found


def _still_served(viewer: Viewer, served: Served) -> bool:
    with db.session() as conn:
        found = photos.served(conn, viewer, served.photo_id)
        return found is not None and (found[0].id, found[0].source_id, found[0].asset_id, found[0].asset_updated) == served.revision


def _body(viewer: Viewer, served: Served, original: immich.Original, prefix: bytes) -> Body:
    checked = served.checked
    pending = prefix
    try:
        while True:
            if not pending:
                try:
                    pending = original.read()
                except immich.ImmichError:
                    return
                if not pending:
                    return
            if time.monotonic() - checked >= RECHECK_SECONDS:
                if not _still_served(viewer, served):
                    return
                checked = time.monotonic()
            yield pending
            pending = b""
    finally:
        original.close()


def _stream(viewer: Viewer, served: Served, original: immich.Original, kind: tuple[str, bool], prefix: bytes) -> Stream:
    content_type, inline = kind
    headers: dict[str, str] = {}
    if original.content_range:
        headers["Content-Range"] = original.content_range
    if original.accept_ranges:
        headers["Accept-Ranges"] = original.accept_ranges
    if original.status == RANGE_NOT_SATISFIABLE:
        original.close()
        return Stream(original.status, content_type, INLINE if inline else ATTACHMENT, headers)
    if original.content_length is not None:
        headers["Content-Length"] = str(original.content_length)
    return Stream(original.status, content_type, INLINE if inline else ATTACHMENT, headers, _body(viewer, served, original, prefix))


def _whole(conn: db.Connection, viewer: Viewer, served: Served, library: Library) -> Stream:
    original = _open(conn, served, library, None)
    try:
        prefix = _prefix(original)
        kind = _typed(served, prefix)
    except (Missing, Unavailable):
        original.close()
        raise
    return _stream(viewer, served, original, kind, prefix)


def _ranged(conn: db.Connection, viewer: Viewer, served: Served, library: Library, asked: str) -> Stream:
    known = _known.get(served.revision)
    if known is None:
        with _open(conn, served, library, SNIFF_RANGE) as probe:
            known = _typed(served, _prefix(probe))
    return _stream(viewer, served, _open(conn, served, library, asked), known, b"")


def original(conn: db.Connection, viewer: Viewer, served: Served, byte_range: str | None) -> Stream | None:
    if served.demo:
        content_type, data = photos.placeholder(served.asset_id, "preview")
        return Stream(200, content_type, INLINE, {"Content-Length": str(len(data))}, _once(data))
    library = _unlocked(conn, served)
    if library is None:
        return None
    asked = immich.single_range(byte_range)
    try:
        return _whole(conn, viewer, served, library) if asked is None else _ranged(conn, viewer, served, library, asked)
    except Missing:
        return None
