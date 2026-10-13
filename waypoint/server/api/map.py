from __future__ import annotations

import re
from collections.abc import Generator

from ...domain import basemap
from ...storage import mapfile
from ..common import ApiError, Response, _current, own_session
from ..contract import MapStatus

RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
MAX_SPAN = 32 * 1024 * 1024
PIECE = 1024 * 1024
NOT_READY = "The detailed map isn't ready"
CACHE = "private, max-age=3600"


def api_map(conn, _q, _b) -> MapStatus:
    return basemap.status()


def _whole(size: int) -> Generator[bytes]:
    at = 0
    while at < size:
        piece = mapfile.read(at, min(PIECE, size - at))
        if not piece:
            return
        at += len(piece)
        yield piece


@own_session
def api_map_tiles(_conn, _q, _b) -> Response:
    size = mapfile.size()
    if size is None or not mapfile.usable():
        raise ApiError(NOT_READY, 404)
    header = getattr(_current, "range", None)
    if not header:
        return Response(b"", "application/octet-stream", headers={"Accept-Ranges": "bytes", "Content-Length": str(size)}, cache=CACHE, stream=_whole(size))
    found = RANGE.match(header.strip())
    if not found or (not found.group(1) and not found.group(2)):
        raise ApiError("That byte range can't be served", 416)
    first, last = found.groups()
    start = max(0, size - int(last)) if not first else int(first)
    end = size - 1 if not first or not last else min(int(last), size - 1)
    if start >= size or end < start or end - start + 1 > MAX_SPAN:
        raise ApiError("That byte range can't be served", 416)
    body = mapfile.read(start, end - start + 1)
    if len(body) != end - start + 1:
        raise ApiError(NOT_READY, 404)
    return Response(body, "application/octet-stream", status=206, cache=CACHE,
                    headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{size}"})
