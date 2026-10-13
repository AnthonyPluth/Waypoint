from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Any

from .. import pmtiles, tls

TIMEOUT = 60
TRIES = 5
CHUNK = 16 * 1024 * 1024
PIECE = 256 * 1024
MAX_DIRECTORY = 64 * 1024 * 1024
MAX_DEPTH = 4
MAX_ZOOM = 9
LEAF_SIZES = (4096, 8192, 16384, 32768, 65536)
KEY = re.compile(r"^\d{8}\.pmtiles$")
USER_AGENT = "Waypoint (https://github.com/AnthonyPluth/Waypoint; self-hosted travel app)"


@dataclass(frozen=True)
class Hosts:
    builds: str = "https://build-metadata.protomaps.dev/builds.json"
    files: str = "https://build.protomaps.com/"
    allow_http: bool = False


HOSTS = Hosts()


class Unavailable(Exception):
    pass


Progress = Callable[[int, int], None]


def _request(url: str, start: int, end: int | None = None) -> urllib.request.Request:
    span = f"bytes={start}-{'' if end is None else end}"
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": span, "Accept-Encoding": "identity"})


def _open(req: urllib.request.Request) -> Any:
    try:
        return tls.urlopen(req, timeout=TIMEOUT, allow_http=HOSTS.allow_http)
    except urllib.error.HTTPError as e:
        e.close()
        raise Unavailable(f"Protomaps answered HTTP {e.code}") from None
    except (urllib.error.URLError, *tls.NETWORK_ERRORS):
        raise Unavailable("Protomaps couldn't be reached") from None


def _read(url: str, start: int, length: int) -> bytes:
    if length <= 0:
        return b""
    for attempt in range(TRIES):
        try:
            with _open(_request(url, start, start + length - 1)) as resp:
                data: bytes = resp.read(length + 1)
            if resp.status == 206 and len(data) == length:
                return data
            raise Unavailable("Protomaps sent the wrong part of the file")
        except (Unavailable, *tls.NETWORK_ERRORS):
            if attempt == TRIES - 1:
                raise Unavailable("Protomaps couldn't be reached") from None
            time.sleep(2 ** attempt)
    raise Unavailable("Protomaps couldn't be reached")


def latest_build() -> str:
    try:
        with _open(urllib.request.Request(HOSTS.builds, headers={"User-Agent": USER_AGENT})) as resp:
            listing = json.loads(resp.read(8 * 1024 * 1024))
        keys: list[str] = sorted(item["key"] for item in listing if isinstance(item, dict) and isinstance(item.get("key"), str) and KEY.match(item["key"]))
    except (ValueError, TypeError, *tls.NETWORK_ERRORS):
        raise Unavailable("Protomaps' list of builds couldn't be read") from None
    if not keys:
        raise Unavailable("Protomaps' list of builds had no map in it")
    return keys[-1]


def build_url(key: str) -> str:
    if not KEY.match(key):
        raise Unavailable("That isn't a Protomaps build")
    return HOSTS.files + key


@dataclass(frozen=True)
class Plan:
    prefix: bytes
    runs: tuple[tuple[int, int], ...]
    data_length: int

    @property
    def total(self) -> int:
        return len(self.prefix) + self.data_length


def _directory(url: str, header: pmtiles.Header, offset: int, length: int) -> list[pmtiles.Entry]:
    if length > MAX_DIRECTORY:
        raise Unavailable("Protomaps' file has a directory that is too large")
    try:
        return pmtiles.read_directory(_read(url, offset, length), header.internal_compression)
    except (pmtiles.FormatError, OSError, EOFError) as e:
        raise Unavailable("Protomaps' file couldn't be read") from e


def _collect(url: str, header: pmtiles.Header, entries: list[pmtiles.Entry], limit: int, depth: int = 0) -> list[pmtiles.Entry]:
    found: list[pmtiles.Entry] = []
    for e in entries:
        if e.tile_id >= limit:
            break
        if e.run_length:
            found.append(e)
        elif depth < MAX_DEPTH:
            found += _collect(url, header, _directory(url, header, header.leaf_offset + e.offset, e.length), limit, depth + 1)
    return found


def _layout(entries: list[pmtiles.Entry], compression: int) -> tuple[bytes, bytes]:
    for size in LEAF_SIZES:
        leaves = b""
        pointers: list[pmtiles.Entry] = []
        for at in range(0, len(entries), size):
            part = pmtiles.write_directory(entries[at:at + size], compression)
            pointers.append(pmtiles.Entry(entries[at].tile_id, len(leaves), len(part), 0))
            leaves += part
        root = pmtiles.write_directory(pointers, compression)
        if len(root) <= pmtiles.ROOT_LIMIT:
            return root, leaves
    raise Unavailable("Protomaps' file has too many tiles to index")


def plan(url: str, max_zoom: int = MAX_ZOOM) -> Plan:
    try:
        header = pmtiles.parse_header(_read(url, 0, pmtiles.HEADER_LENGTH))
        if header.internal_compression not in (pmtiles.NO_COMPRESSION, pmtiles.GZIP):
            raise pmtiles.FormatError("unsupported compression")
    except pmtiles.FormatError as e:
        raise Unavailable("Protomaps' file couldn't be read") from e
    limit = pmtiles.zoom_end(max_zoom)
    found = _collect(url, header, _directory(url, header, header.root_offset, header.root_length), limit)
    if not found:
        raise Unavailable("Protomaps' file had no tiles")
    found.sort(key=lambda e: e.tile_id)
    unique = sorted({(e.offset, e.length) for e in found})
    moved: dict[tuple[int, int], int] = {}
    runs: list[tuple[int, int]] = []
    out = 0
    for offset, length in unique:
        moved[(offset, length)] = out
        at = header.data_offset + offset
        if runs and runs[-1][0] + runs[-1][1] == at:
            runs[-1] = (runs[-1][0], runs[-1][1] + length)
        else:
            runs.append((at, length))
        out += length
    entries = [pmtiles.Entry(e.tile_id, moved[(e.offset, e.length)], e.length, min(e.run_length, limit - e.tile_id)) for e in found]
    root, leaves = _layout(entries, header.internal_compression)
    metadata = _read(url, header.metadata_offset, header.metadata_length)
    metadata_offset = pmtiles.HEADER_LENGTH + len(root)
    leaf_offset = metadata_offset + len(metadata)
    data_offset = leaf_offset + len(leaves)
    new = replace(header, root_offset=pmtiles.HEADER_LENGTH, root_length=len(root), metadata_offset=metadata_offset,
                  metadata_length=len(metadata), leaf_offset=leaf_offset, leaf_length=len(leaves), data_offset=data_offset,
                  data_length=out, addressed_tiles=sum(e.run_length for e in entries), tile_entries=len(entries),
                  tile_contents=len(unique), clustered=1, min_zoom=min(header.min_zoom, max_zoom), max_zoom=max_zoom)
    return Plan(pmtiles.build_header(new) + root + metadata + leaves, tuple(runs), out)


def _stream(url: str, start: int, length: int, sink: IO[bytes], progress: Callable[[int], None]) -> None:
    done = 0
    attempts = 0
    while done < length:
        before = done
        try:
            with _open(_request(url, start + done, start + length - 1)) as resp:
                if resp.status != 206:
                    raise Unavailable("Protomaps sent the wrong part of the file")
                while piece := resp.read(min(PIECE, length - done)):
                    sink.write(piece)
                    done += len(piece)
                    progress(len(piece))
        except (Unavailable, *tls.NETWORK_ERRORS):
            pass
        if done == before:
            attempts += 1
            if attempts >= TRIES:
                raise Unavailable("Protomaps couldn't be reached")
            time.sleep(2 ** attempts)
        else:
            attempts = 0
    sink.flush()


def _resume(part: Path, prefix: bytes) -> int:
    try:
        with part.open("rb") as f:
            if f.read(len(prefix)) != prefix:
                return 0
        return max(0, part.stat().st_size - len(prefix))
    except OSError:
        return 0


def extract(url: str, dest: Path, progress: Progress | None = None, max_zoom: int = MAX_ZOOM) -> None:
    wanted = plan(url, max_zoom)
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    done = min(_resume(part, wanted.prefix), wanted.data_length)
    mode = "r+b" if part.exists() and done else "wb"
    with part.open(mode) as sink:
        if mode == "wb":
            sink.write(wanted.prefix)
            done = 0
        sink.seek(len(wanted.prefix) + done)
        sink.truncate()
        have = len(wanted.prefix) + done
        report = progress or (lambda *_: None)

        def advance(n: int) -> None:
            nonlocal have
            have += n
            report(have, wanted.total)

        report(have, wanted.total)
        skip = done
        for offset, length in wanted.runs:
            if skip >= length:
                skip -= length
                continue
            start, remaining = offset + skip, length - skip
            skip = 0
            while remaining:
                step = min(CHUNK, remaining)
                _stream(url, start, step, sink, advance)
                start += step
                remaining -= step
        os.fsync(sink.fileno())
    os.replace(part, dest)
