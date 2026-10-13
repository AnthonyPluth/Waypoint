from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass

MAGIC = b"PMTiles"
VERSION = 3
HEADER_LENGTH = 127
ROOT_LIMIT = 16384 - HEADER_LENGTH
NO_COMPRESSION = 1
GZIP = 2


class FormatError(ValueError):
    pass


@dataclass(frozen=True)
class Header:
    root_offset: int
    root_length: int
    metadata_offset: int
    metadata_length: int
    leaf_offset: int
    leaf_length: int
    data_offset: int
    data_length: int
    addressed_tiles: int
    tile_entries: int
    tile_contents: int
    clustered: int
    internal_compression: int
    tile_compression: int
    tile_type: int
    min_zoom: int
    max_zoom: int
    min_lon: int
    min_lat: int
    max_lon: int
    max_lat: int
    center_zoom: int
    center_lon: int
    center_lat: int


_BOUNDS = struct.Struct("<4iBii")


def parse_header(raw: bytes) -> Header:
    if len(raw) < HEADER_LENGTH or raw[:7] != MAGIC:
        raise FormatError("not a PMTiles file")
    if raw[7] != VERSION:
        raise FormatError(f"PMTiles version {raw[7]} is not supported")
    numbers = struct.unpack("<8Q3Q", raw[8:8 + 88])
    single = struct.unpack("<6B", raw[96:102])
    bounds = _BOUNDS.unpack(raw[102:102 + _BOUNDS.size])
    return Header(*numbers, *single, *bounds)


def build_header(h: Header) -> bytes:
    body = struct.pack("<8Q3Q", h.root_offset, h.root_length, h.metadata_offset, h.metadata_length, h.leaf_offset,
                       h.leaf_length, h.data_offset, h.data_length, h.addressed_tiles, h.tile_entries, h.tile_contents)
    body += struct.pack("<6B", h.clustered, h.internal_compression, h.tile_compression, h.tile_type, h.min_zoom, h.max_zoom)
    body += _BOUNDS.pack(h.min_lon, h.min_lat, h.max_lon, h.max_lat, h.center_zoom, h.center_lon, h.center_lat)
    return MAGIC + bytes([VERSION]) + body


@dataclass(frozen=True)
class Entry:
    tile_id: int
    offset: int
    length: int
    run_length: int


def _varint(data: bytes, at: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if at >= len(data) or shift > 63:
            raise FormatError("a directory ends in the middle of a number")
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, at
        shift += 7


def _put(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def decompress(data: bytes, compression: int) -> bytes:
    if compression == NO_COMPRESSION:
        return data
    if compression == GZIP:
        return gzip.decompress(data)
    raise FormatError(f"compression {compression} is not supported")


def read_directory(raw: bytes, compression: int) -> list[Entry]:
    data = decompress(raw, compression)
    count, at = _varint(data, 0)
    ids: list[int] = []
    last = 0
    for _ in range(count):
        step, at = _varint(data, at)
        last += step
        ids.append(last)
    runs = []
    for _ in range(count):
        run, at = _varint(data, at)
        runs.append(run)
    lengths = []
    for _ in range(count):
        length, at = _varint(data, at)
        lengths.append(length)
    entries: list[Entry] = []
    for i in range(count):
        value, at = _varint(data, at)
        offset = entries[-1].offset + entries[-1].length if value == 0 and i > 0 else value - 1
        entries.append(Entry(ids[i], offset, lengths[i], runs[i]))
    return entries


def write_directory(entries: list[Entry], compression: int = GZIP) -> bytes:
    out = bytearray(_put(len(entries)))
    last = 0
    for e in entries:
        out += _put(e.tile_id - last)
        last = e.tile_id
    for e in entries:
        out += _put(e.run_length)
    for e in entries:
        out += _put(e.length)
    for i, e in enumerate(entries):
        out += _put(0 if i > 0 and e.offset == entries[i - 1].offset + entries[i - 1].length else e.offset + 1)
    data = bytes(out)
    return gzip.compress(data, mtime=0) if compression == GZIP else data


def zoom_end(zoom: int) -> int:
    return (4 ** (zoom + 1) - 1) // 3


def _rotate(n: int, x: int, y: int, rx: int, ry: int) -> tuple[int, int]:
    if ry == 0:
        if rx == 1:
            x, y = n - 1 - x, n - 1 - y
        x, y = y, x
    return x, y


def tile_id(z: int, x: int, y: int) -> int:
    if z > 31 or not (0 <= x < 1 << z and 0 <= y < 1 << z):
        raise FormatError("a tile outside the world")
    base = zoom_end(z - 1) if z else 0
    d = 0
    s = (1 << z) >> 1
    while s > 0:
        rx = 1 if x & s else 0
        ry = 1 if y & s else 0
        d += s * s * ((3 * rx) ^ ry)
        x, y = _rotate(1 << z, x, y, rx, ry)
        s >>= 1
    return base + d


def tile_zxy(tid: int) -> tuple[int, int, int]:
    z = 0
    while tid >= zoom_end(z):
        z += 1
    d = tid - (zoom_end(z - 1) if z else 0)
    x = y = 0
    s = 1
    while s < 1 << z:
        rx = 1 & (d // 2)
        ry = 1 & (d ^ rx)
        x, y = _rotate(s, x, y, rx, ry)
        x += s * rx
        y += s * ry
        d //= 4
        s <<= 1
    return z, x, y
