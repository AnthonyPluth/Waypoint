from __future__ import annotations

import gzip
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = "states.tsv.gz"
UNITS = 10_000
CELL_DEGREES = 0.5
BUDGET = 1500
THIN_FROM = 0.02

Point = tuple[float, float]
Extent = tuple[float, float, float, float]


@dataclass(frozen=True)
class Border:
    a: str
    b: str
    points: tuple[Point, ...]


def _cell(value: float) -> int:
    return math.floor(value / CELL_DEGREES)


class Borders:
    def __init__(self, borders: list[Border]) -> None:
        self.borders = borders
        self.cells: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for i, border in enumerate(borders):
            for k in range(len(border.points) - 1):
                (lat1, lon1), (lat2, lon2) = border.points[k], border.points[k + 1]
                for row in range(_cell(min(lat1, lat2)), _cell(max(lat1, lat2)) + 1):
                    for col in range(_cell(min(lon1, lon2)), _cell(max(lon1, lon2)) + 1):
                        self.cells[(row, col)].append((i, k))

    def within(self, extent: Extent, budget: int = BUDGET) -> list[list[Point]]:
        south, west, north, east = extent
        taken: dict[int, set[int]] = defaultdict(set)
        for row in range(_cell(south), _cell(north) + 1):
            for col in range(_cell(west), _cell(east) + 1):
                for i, k in self.cells.get((row, col), ()):
                    taken[i].add(k)
        return thin(self._runs(taken), budget)

    def _runs(self, taken: dict[int, set[int]]) -> list[list[Point]]:
        out: list[list[Point]] = []
        for i in sorted(taken):
            points = self.borders[i].points
            run: list[Point] = []
            last = -2
            for k in sorted(taken[i]):
                if k != last + 1 and run:
                    out.append(run)
                    run = []
                if not run:
                    run.append(points[k])
                run.append(points[k + 1])
                last = k
            if run:
                out.append(run)
        return out


def steps(lines: list[list[Point]]) -> int:
    return sum(len(line) - 1 for line in lines)


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


def thin(lines: list[list[Point]], budget: int) -> list[list[Point]]:
    tolerance = THIN_FROM
    while steps(lines) > budget and any(len(line) > 2 for line in lines):
        lines = [simplify(line, tolerance) for line in lines]
        tolerance *= 2
    return lines


def parse(rows: Iterable[str]) -> Borders:
    borders: list[Border] = []
    for line in rows:
        columns = line.rstrip("\n").split("\t")
        if len(columns) < 3 or not columns[2].strip():
            continue
        numbers = [int(n) for n in columns[2].split()]
        lat, lon = numbers[0], numbers[1]
        points = [(lat / UNITS, lon / UNITS)]
        for k in range(2, len(numbers) - 1, 2):
            lat, lon = lat + numbers[k], lon + numbers[k + 1]
            points.append((lat / UNITS, lon / UNITS))
        if len(points) >= 2:
            borders.append(Border(columns[0], columns[1], tuple(points)))
    return Borders(borders)


def load(name: str = FILE) -> Borders:
    with gzip.open(HERE / name, "rt", encoding="utf-8") as f:
        return parse(f)


@cache
def state_lines() -> Borders:
    return load()
