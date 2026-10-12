from __future__ import annotations

import gzip
import heapq
import math
from collections import defaultdict
from itertools import pairwise
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = "roads.tsv.gz"
UNITS = 10_000
CELL_DEGREES = 0.25
EARTH_MILES = 3958.8
MAX_LINK_MILES = 30.0
MIN_RUN_MILES = 3.0
NETWORK_RINGS = 2
NETWORK_POINTS = 4000
NETWORK_FLAT_DEGREES = 0.01
ROUTE_FLAT_DEGREES = 0.004
START = -1
END = -2

Point = tuple[float, float]


def miles_between(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_MILES * math.asin(math.sqrt(h))


@dataclass(frozen=True)
class Edge:
    ref: str
    a: int
    b: int
    points: tuple[Point, ...]
    along: tuple[float, ...]

    @property
    def miles(self) -> float:
        return self.along[-1]


@dataclass(frozen=True)
class Snap:
    edge: int
    index: int
    point: Point
    offset: float
    link_miles: float


@dataclass(frozen=True)
class Arc:
    to: int
    miles: float
    ref: str
    points: list[Point]


@dataclass(frozen=True)
class Route:
    points: list[Point]
    refs: list[str]
    miles: float
    start_link_miles: float
    end_link_miles: float


class Graph:
    def __init__(self, edges: list[Edge]) -> None:
        self.edges = edges
        self.joined: dict[int, list[int]] = defaultdict(list)
        self.cells: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for i, edge in enumerate(edges):
            self.joined[edge.a].append(i)
            if edge.b != edge.a:
                self.joined[edge.b].append(i)
        self.main = frozenset(self._largest_network())
        for i, edge in enumerate(edges):
            for k in range(len(edge.points) - 1):
                (lat1, lon1), (lat2, lon2) = edge.points[k], edge.points[k + 1]
                for row in range(_cell(min(lat1, lat2)), _cell(max(lat1, lat2)) + 1):
                    for col in range(_cell(min(lon1, lon2)), _cell(max(lon1, lon2)) + 1):
                        self.cells[(row, col)].append((i, k))

    def _largest_network(self) -> list[int]:
        seen: set[int] = set()
        best: list[int] = []
        for first in range(len(self.edges)):
            if first in seen:
                continue
            seen.add(first)
            found, stack = [first], [first]
            while stack:
                edge = self.edges[stack.pop()]
                for node in (edge.a, edge.b):
                    for i in self.joined[node]:
                        if i not in seen:
                            seen.add(i)
                            found.append(i)
                            stack.append(i)
            if len(found) > len(best):
                best = found
        return sorted(best)

    def snap(self, point: Point, within: float = MAX_LINK_MILES) -> Snap | None:
        lat, lon = point
        reach = within / 69.0
        wide = reach / max(0.2, math.cos(math.radians(lat)))
        best: tuple[float, Snap] | None = None
        seen: set[tuple[int, int]] = set()
        for row in range(_cell(lat - reach), _cell(lat + reach) + 1):
            for col in range(_cell(lon - wide), _cell(lon + wide) + 1):
                for i, k in self.cells.get((row, col), ()):
                    if (i, k) in seen or i not in self.main:
                        continue
                    seen.add((i, k))
                    edge = self.edges[i]
                    near, share = _nearest_on(point, edge.points[k], edge.points[k + 1])
                    gap = miles_between(point, near)
                    if gap <= within and (best is None or gap < best[0]):
                        step = edge.along[k + 1] - edge.along[k]
                        best = (gap, Snap(i, k, near, edge.along[k] + share * step, gap))
        return best[1] if best else None

    def route(self, start: Point, end: Point, within: float = MAX_LINK_MILES) -> Route | None:
        a, b = self.snap(start, within), self.snap(end, within)
        if a is None or b is None:
            return None
        arcs = self._cheapest(a, b)
        if arcs is None:
            return None
        points: list[Point] = []
        for arc in arcs:
            points.extend(arc.points if not points or points[-1] != arc.points[0] else arc.points[1:])
        points = simplified(points, ROUTE_FLAT_DEGREES)
        return Route(points, _long_runs([(arc.ref, arc.miles) for arc in arcs]), sum(arc.miles for arc in arcs), a.link_miles, b.link_miles)

    def _cheapest(self, a: Snap, b: Snap) -> list[Arc] | None:
        ea, eb = self.edges[a.edge], self.edges[b.edge]
        extra: dict[int, list[Arc]] = defaultdict(list)
        extra[START] += [Arc(ea.a, a.offset, ea.ref, _reach(ea, a, True)), Arc(ea.b, ea.miles - a.offset, ea.ref, _reach(ea, a, False))]
        extra[eb.a].append(Arc(END, b.offset, eb.ref, _reach(eb, b, True)[::-1]))
        extra[eb.b].append(Arc(END, eb.miles - b.offset, eb.ref, _reach(eb, b, False)[::-1]))
        if a.edge == b.edge:
            extra[START].append(Arc(END, abs(a.offset - b.offset), ea.ref, _between(ea, a, b)))
        settled: dict[int, tuple[float, int | None, Arc | None]] = {}
        heap: list[tuple[float, int, int, int | None, Arc | None]] = [(0.0, 0, START, None, None)]
        tick = 0
        while heap:
            cost, _, node, came, arc = heapq.heappop(heap)
            if node in settled:
                continue
            settled[node] = (cost, came, arc)
            if node == END:
                break
            for step in [*extra.get(node, ()), *(self._arc(node, i) for i in self.joined.get(node, ()))]:
                if step.to not in settled:
                    tick += 1
                    heapq.heappush(heap, (cost + step.miles, tick, step.to, node, step))
        if END not in settled:
            return None
        arcs: list[Arc] = []
        back: int | None = END
        while back is not None:
            _, back, arc = settled[back]
            if arc is not None:
                arcs.append(arc)
        return arcs[::-1]

    def near(self, paths: list[list[Point]], rings: int = NETWORK_RINGS, budget: int = NETWORK_POINTS) -> list[tuple[str, list[Point]]]:
        seeds: set[tuple[int, int]] = set()
        for path in paths:
            for (lat1, lon1), (lat2, lon2) in zip(path, path[1:] or path, strict=False):
                steps = max(1, math.ceil(max(abs(lat2 - lat1), abs(lon2 - lon1)) / (CELL_DEGREES / 2)))
                for n in range(steps + 1):
                    seeds.add((_cell(lat1 + (lat2 - lat1) * n / steps), _cell(lon1 + (lon2 - lon1) * n / steps)))
        taken: set[int] = set()
        reached: set[tuple[int, int]] = set()
        out: list[tuple[str, list[Point]]] = []
        spent = 0
        for ring in range(rings + 1):
            ring_cells = {(r + dr, c + dc) for r, c in seeds for dr in range(-ring, ring + 1) for dc in range(-ring, ring + 1)} - reached
            reached |= ring_cells
            for i in sorted({i for cell in ring_cells for i, _ in self.cells.get(cell, ())} - taken):
                line = simplified(list(self.edges[i].points), NETWORK_FLAT_DEGREES)
                if spent + len(line) > budget:
                    continue
                taken.add(i)
                spent += len(line)
                out.append((self.edges[i].ref, line))
        return out

    def _arc(self, node: int, index: int) -> Arc:
        edge = self.edges[index]
        if edge.a == node:
            return Arc(edge.b, edge.miles, edge.ref, list(edge.points))
        return Arc(edge.a, edge.miles, edge.ref, list(reversed(edge.points)))


def simplified(points: list[Point], tolerance: float) -> list[Point]:
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


def _cell(value: float) -> int:
    return math.floor(value / CELL_DEGREES)


def _nearest_on(p: Point, a: Point, b: Point) -> tuple[Point, float]:
    scale = math.cos(math.radians(p[0]))
    ax, ay, bx, by, px, py = a[1] * scale, a[0], b[1] * scale, b[0], p[1] * scale, p[0]
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    share = 0.0 if span == 0 else min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / span))
    return (a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share), share


def _reach(edge: Edge, snap: Snap, towards_start: bool) -> list[Point]:
    if towards_start:
        return [snap.point, *reversed(edge.points[:snap.index + 1])]
    return [snap.point, *edge.points[snap.index + 1:]]


def _between(edge: Edge, a: Snap, b: Snap) -> list[Point]:
    low, high = (a, b) if (a.index, a.offset) <= (b.index, b.offset) else (b, a)
    points = [low.point, *edge.points[low.index + 1:high.index + 1], high.point]
    return points if low is a else points[::-1]


def _long_runs(runs: list[tuple[str, float]]) -> list[str]:
    names: list[str] = []
    totals: list[float] = []
    for ref, miles in runs:
        if names and names[-1] == ref:
            totals[-1] += miles
        else:
            names.append(ref)
            totals.append(miles)
    refs: list[str] = []
    for ref, miles in zip(names, totals, strict=True):
        if miles >= MIN_RUN_MILES and (not refs or refs[-1] != ref):
            refs.append(ref)
    return refs


def parse(rows: Iterable[str]) -> Graph:
    edges: list[Edge] = []
    for line in rows:
        columns = line.rstrip("\n").split("\t")
        if len(columns) < 4 or not columns[3].strip():
            continue
        numbers = [int(n) for n in columns[3].split()]
        lat, lon = numbers[0], numbers[1]
        points = [(lat / UNITS, lon / UNITS)]
        for k in range(2, len(numbers) - 1, 2):
            lat, lon = lat + numbers[k], lon + numbers[k + 1]
            points.append((lat / UNITS, lon / UNITS))
        if len(points) < 2:
            continue
        along = [0.0]
        for p, q in pairwise(points):
            along.append(along[-1] + miles_between(p, q))
        edges.append(Edge(columns[0], int(columns[1]), int(columns[2]), tuple(points), tuple(along)))
    return Graph(edges)


def load(name: str = FILE) -> Graph:
    with gzip.open(HERE / name, "rt", encoding="utf-8") as f:
        return parse(f)


@cache
def interstates() -> Graph:
    return load()
