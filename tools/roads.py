from __future__ import annotations

import gzip
import math
import re
import struct
import sys
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import IO

OUT = Path(__file__).resolve().parent.parent / "waypoint" / "storage" / "roads.tsv.gz"

JUNCTION_DEGREES = 0.004
JOINT_DEGREES = 0.0005
SIMPLIFY_DEGREES = 0.001
UNITS = 10_000

Point = tuple[float, float]
Line = tuple[str, list[Point]]
Edge = tuple[str, int, int, list[Point]]

INTERSTATE_CLASSES = frozenset("1")
HIGHWAY_CLASSES = frozenset("123")
WANTED = ("SIGN1", "SIGNT1", "FCLASS", "STFIPS")
INTERSTATE_SIGN = re.compile(r"^I(H?)(\d{1,3})([CEW]?)$")
NUMBERED_SIGN = re.compile(r"^[US](\d{1,4})$")
STATES = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE",
    "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA",
    "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM",
    "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
}


def ref_of(kind: str, sign: str, state: str = "", fclass: str = "1") -> str | None:
    text = sign.strip().upper()
    if kind == "I":
        found = INTERSTATE_SIGN.match(text)
        return f"I-{found.group(1)}{found.group(2)}{found.group(3)}" if found and fclass in INTERSTATE_CLASSES else None
    found = NUMBERED_SIGN.match(text)
    if not found or fclass not in HIGHWAY_CLASSES or text[0] != kind:
        return None
    number = int(found.group(1))
    if kind == "U":
        return f"US-{number}"
    postal = STATES.get(state.zfill(2))
    return f"{postal}-{number}" if postal else None


def dbf_header(f: IO[bytes]) -> tuple[int, int, dict[str, tuple[int, int]]]:
    count, header, length = struct.unpack("<xxxxIHH", f.read(12))
    fields = f.read(header - 12)[20:]
    columns: dict[str, tuple[int, int]] = {}
    offset = 1
    for at in range(0, len(fields) - 1, 32):
        if fields[at] == 13:
            break
        size = fields[at + 16]
        columns[fields[at:at + 11].split(b"\0")[0].decode("ascii")] = (offset, size)
        offset += size
    return count, length, columns


def shape_parts(body: bytes) -> list[list[Point]]:
    if struct.unpack("<i", body[:4])[0] != 3:
        return []
    parts, total = struct.unpack("<ii", body[36:44])
    starts = [*struct.unpack(f"<{parts}i", body[44:44 + 4 * parts]), total]
    flat = struct.unpack(f"<{2 * total}d", body[44 + 4 * parts:44 + 4 * parts + 16 * total])
    return [[(flat[2 * j + 1], flat[2 * j]) for j in range(starts[k], starts[k + 1])] for k in range(parts)]


def shapes(f: IO[bytes]) -> Iterator[list[list[Point]]]:
    f.read(100)
    while len(header := f.read(8)) == 8:
        _, words = struct.unpack(">ii", header)
        yield shape_parts(f.read(words * 2))


def highways(archive: Path) -> list[Line]:
    found: list[Line] = []
    with zipfile.ZipFile(archive) as z:
        stem = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
        with z.open(f"{stem}.dbf") as table, z.open(f"{stem}.shp") as geometry:
            count, length, columns = dbf_header(table)
            for parts, record in zip(shapes(geometry), (table.read(length) for _ in range(count)), strict=False):
                values = {name: record[at:at + size].decode("latin-1").strip() for name, (at, size) in columns.items() if name in WANTED}
                ref = ref_of(values["SIGNT1"], values["SIGN1"], values["STFIPS"], values["FCLASS"])
                if ref:
                    found.extend((ref, part) for part in parts if len(part) >= 2)
    return found


def simplify(points: list[Point], tolerance: float) -> list[Point]:
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (y1, x1), (y2, x2) = points[first], points[last]
        dx, dy = x2 - x1, y2 - y1
        span = math.hypot(dx, dy)
        far, farthest = -1, -1.0
        for i in range(first + 1, last):
            y, x = points[i]
            gap = math.hypot(x - x1, y - y1) if span == 0 else abs(dx * (y - y1) - dy * (x - x1)) / span
            if gap > farthest:
                far, farthest = i, gap
        if farthest > tolerance:
            keep.add(far)
            stack += [(first, far), (far, last)]
    return [points[i] for i in sorted(keep)]


def node_lines(lines: list[Line], junction: float = JUNCTION_DEGREES, joint: float = JOINT_DEGREES) -> list[Edge]:
    grid: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)

    def cell(p: Point) -> tuple[int, int]:
        return math.floor(p[0] / junction), math.floor(p[1] / junction)

    for li, (_, part) in enumerate(lines):
        for vi, p in enumerate(part):
            grid[cell(p)].append((li, vi))
    parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find(x: tuple[int, int]) -> tuple[int, int]:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    cuts: dict[int, set[int]] = defaultdict(set)
    for li, (_, part) in enumerate(lines):
        for vi in (0, len(part) - 1):
            p = part[vi]
            row, col = cell(p)
            nearest: dict[int, tuple[float, int]] = {}
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    for lj, vj in grid.get((row + dr, col + dc), ()):
                        if lj == li:
                            continue
                        q = lines[lj][1][vj]
                        gap = max(abs(p[0] - q[0]), abs(p[1] - q[1]))
                        if gap <= (joint if lines[lj][0] == lines[li][0] else junction) and (lj not in nearest or gap < nearest[lj][0]):
                            nearest[lj] = (gap, vj)
            for lj, (_, vj) in nearest.items():
                cuts[lj].add(vj)
                parent[find((li, vi))] = find((lj, vj))
    ids: dict[tuple[int, int], int] = {}
    edges: list[Edge] = []
    for li, (ref, part) in enumerate(lines):
        stops = sorted({0, len(part) - 1} | cuts.get(li, set()))
        for first, last in pairwise(stops):
            a = ids.setdefault(find((li, first)), len(ids))
            b = ids.setdefault(find((li, last)), len(ids))
            edges.append((ref, a, b, part[first:last + 1]))
    return edges


def chain_edges(edges: list[Edge]) -> list[Edge]:
    touching: dict[int, list[int]] = defaultdict(list)
    for i, (_, a, b, _) in enumerate(edges):
        touching[a].append(i)
        touching[b].append(i)
    alive = dict(enumerate(edges))
    for node, at in list(touching.items()):
        if len(at) != 2 or at[0] == at[1] or at[0] not in alive or at[1] not in alive:
            continue
        (ref1, a1, b1, p1), (ref2, a2, b2, p2) = alive[at[0]], alive[at[1]]
        if ref1 != ref2 or a1 == b1 or a2 == b2:
            continue
        left, right = (p1 if b1 == node else p1[::-1]), (p2 if a2 == node else p2[::-1])
        far1, far2 = (a1 if b1 == node else b1), (b2 if a2 == node else a2)
        merged = (ref1, far1, far2, left + right[1:])
        new = at[0]
        del alive[at[1]]
        alive[new] = merged
        for end in (far1, far2):
            touching[end] = [new if j == at[1] else j for j in touching[end]]
    return list(alive.values())


def thin(edges: list[Edge], tolerance: float = SIMPLIFY_DEGREES) -> list[Edge]:
    out = []
    for ref, a, b, points in edges:
        piece = simplify(points, tolerance)
        if len(piece) >= 2 and (a != b or len(piece) > 2):
            out.append((ref, a, b, piece))
    return out


def encode(edges: list[Edge]) -> str:
    rows = []
    for ref, a, b, points in sorted(edges, key=lambda e: (e[0], e[3][0], e[3][-1])):
        scaled = [(round(lat * UNITS), round(lon * UNITS)) for lat, lon in points]
        numbers = [*scaled[0]]
        for (lat1, lon1), (lat2, lon2) in pairwise(scaled):
            numbers += [lat2 - lat1, lon2 - lon1]
        rows.append(f"{ref}\t{a}\t{b}\t{' '.join(map(str, numbers))}\n")
    return "".join(rows)


def build(lines: list[Line]) -> list[Edge]:
    return thin(chain_edges(node_lines(lines)))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: roads.py NHS_2025-08-08.zip", file=sys.stderr)
        return 2
    edges = build(highways(Path(argv[1])))
    with OUT.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="", compresslevel=9) as z:
        z.write(encode(edges).encode("utf-8"))
    print(f"{len(edges)} road pieces -> {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
