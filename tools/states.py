from __future__ import annotations

import gzip
import math
import struct
import sys
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import IO

OUT = Path(__file__).resolve().parent.parent / "waypoint" / "storage" / "states.tsv.gz"

SIMPLIFY_DEGREES = 0.012
UNITS = 10_000
POLYGON = 5

Point = tuple[float, float]
Edge = tuple[Point, Point]
Border = tuple[str, str, list[Point]]


def dbf_codes(f: IO[bytes]) -> list[str]:
    count, header, length = struct.unpack("<xxxxIHH", f.read(12))
    fields = f.read(header - 12)[20:]
    offset = 1
    where: tuple[int, int] | None = None
    for at in range(0, len(fields) - 1, 32):
        if fields[at] == 13:
            break
        size = fields[at + 16]
        if fields[at:at + 11].split(b"\0")[0] == b"STUSPS":
            where = (offset, size)
        offset += size
    if where is None:
        raise ValueError("no STUSPS column")
    start, size = where
    return [f.read(length)[start:start + size].decode("ascii").strip() for _ in range(count)]


def shape_rings(body: bytes) -> list[list[Point]]:
    if struct.unpack("<i", body[:4])[0] != POLYGON:
        return []
    parts, total = struct.unpack("<ii", body[36:44])
    starts = [*struct.unpack(f"<{parts}i", body[44:44 + 4 * parts]), total]
    flat = struct.unpack(f"<{2 * total}d", body[44 + 4 * parts:44 + 4 * parts + 16 * total])
    return [[(flat[2 * j + 1], flat[2 * j]) for j in range(starts[k], starts[k + 1])] for k in range(parts)]


def shapes(f: IO[bytes]) -> Iterator[list[list[Point]]]:
    f.read(100)
    while len(header := f.read(8)) == 8:
        _, words = struct.unpack(">ii", header)
        yield shape_rings(f.read(words * 2))


def states(archive: Path) -> dict[str, list[list[Point]]]:
    found: dict[str, list[list[Point]]] = {}
    with zipfile.ZipFile(archive) as z:
        stem = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
        with z.open(f"{stem}.dbf") as table, z.open(f"{stem}.shp") as geometry:
            codes = dbf_codes(table)
            for code, rings in zip(codes, shapes(geometry), strict=True):
                found[code] = rings
    return found


def shared_edges(rings_by_state: dict[str, list[list[Point]]]) -> dict[Edge, set[str]]:
    owners: dict[Edge, set[str]] = defaultdict(set)
    for code, rings in rings_by_state.items():
        for ring in rings:
            for p, q in pairwise(ring):
                if p != q:
                    owners[(p, q) if p <= q else (q, p)].add(code)
    return {edge: who for edge, who in owners.items() if len(who) == 2}


def chains(edges: list[Edge]) -> list[list[Point]]:
    touching: dict[Point, list[Point]] = defaultdict(list)
    for p, q in edges:
        touching[p].append(q)
        touching[q].append(p)
    used: set[Edge] = set()
    out: list[list[Point]] = []

    def walk(start: Point, first: Point) -> list[Point]:
        line = [start, first]
        used.add((start, first) if start <= first else (first, start))
        while len(touching[line[-1]]) == 2:
            here, before = line[-1], line[-2]
            step = next(n for n in touching[here] if n != before)
            key = (here, step) if here <= step else (step, here)
            if key in used:
                break
            used.add(key)
            line.append(step)
        return line

    for node in sorted(touching):
        if len(touching[node]) == 2:
            continue
        for first in sorted(touching[node]):
            key = (node, first) if node <= first else (first, node)
            if key not in used:
                out.append(walk(node, first))
    for node in sorted(touching):
        for first in sorted(touching[node]):
            key = (node, first) if node <= first else (first, node)
            if key not in used:
                out.append(walk(node, first))
    return out


def simplify(points: list[Point], tolerance: float) -> list[Point]:
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (y1, x1), (y2, x2) = points[first], points[last]
        scale = math.cos(math.radians((y1 + y2) / 2))
        dx, dy = (x2 - x1) * scale, y2 - y1
        span = math.hypot(dx, dy)
        far, farthest = -1, -1.0
        for i in range(first + 1, last):
            y, x = points[i]
            gap = math.hypot((x - x1) * scale, y - y1) if span == 0 else abs(dx * (y - y1) - dy * (x - x1) * scale) / span
            if gap > farthest:
                far, farthest = i, gap
        if farthest > tolerance:
            keep.add(far)
            stack += [(first, far), (far, last)]
    return [points[i] for i in sorted(keep)]


def build(rings_by_state: dict[str, list[list[Point]]], tolerance: float = SIMPLIFY_DEGREES) -> list[Border]:
    by_pair: dict[tuple[str, str], list[Edge]] = defaultdict(list)
    for edge, who in shared_edges(rings_by_state).items():
        a, b = sorted(who)
        by_pair[(a, b)].append(edge)
    borders: list[Border] = []
    for (a, b), edges in by_pair.items():
        for line in chains(edges):
            piece = simplify(line, tolerance)
            if len(piece) >= 2 and piece[0] != piece[-1]:
                borders.append((a, b, piece))
    return borders


def encode(borders: list[Border]) -> str:
    rows = []
    for a, b, points in sorted(borders, key=lambda x: (x[0], x[1], x[2][0], x[2][-1])):
        scaled = [(round(lat * UNITS), round(lon * UNITS)) for lat, lon in points]
        numbers = [*scaled[0]]
        for (lat1, lon1), (lat2, lon2) in pairwise(scaled):
            numbers += [lat2 - lat1, lon2 - lon1]
        rows.append(f"{a}\t{b}\t{' '.join(map(str, numbers))}\n")
    return "".join(rows)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: states.py cb_2024_us_state_5m.zip", file=sys.stderr)
        return 2
    borders = build(states(Path(argv[1])))
    with OUT.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="", compresslevel=9) as z:
        z.write(encode(borders).encode("utf-8"))
    print(f"{len(borders)} state lines -> {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
