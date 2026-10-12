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
RINGS = 10
BUDGET = 1500

Point = tuple[float, float]


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

    def near(self, paths: list[list[Point]], rings: int = RINGS, budget: int = BUDGET) -> list[list[Point]]:
        seeds: set[tuple[int, int]] = set()
        for path in paths:
            for (lat1, lon1), (lat2, lon2) in zip(path, path[1:] or path, strict=False):
                steps = max(1, math.ceil(max(abs(lat2 - lat1), abs(lon2 - lon1)) / (CELL_DEGREES / 2)))
                for n in range(steps + 1):
                    seeds.add((_cell(lat1 + (lat2 - lat1) * n / steps), _cell(lon1 + (lon2 - lon1) * n / steps)))
        reached: set[tuple[int, int]] = set()
        chosen: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for ring in range(rings + 1):
            ring_cells = {(r + dr, c + dc) for r, c in seeds for dr in range(-ring, ring + 1) for dc in range(-ring, ring + 1)} - reached
            reached |= ring_cells
            chosen += sorted({hit for cell in ring_cells for hit in self.cells.get(cell, ())} - seen)
            seen.update(chosen)
        taken: dict[int, set[int]] = defaultdict(set)
        for i, k in chosen[:budget]:
            taken[i].add(k)
        return self._runs(taken)

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
