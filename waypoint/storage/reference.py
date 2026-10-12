from __future__ import annotations

import gzip
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _rows(name: str) -> list[list[str]]:
    with gzip.open(HERE / name, "rt", encoding="utf-8") as f:
        return [line.rstrip("\n").split("\t") for line in f if line.strip()]


@cache
def airport_zones() -> dict[str, str]:
    return {row[0]: row[4] for row in _rows("airports.tsv.gz") if len(row) >= 5 and row[4]}


@cache
def airport_states() -> dict[str, str]:
    return {row[1]: row[2] for row in _rows("regions.tsv.gz") if len(row) >= 3 and row[0] == "A" and row[2]}


@cache
def country_names() -> dict[str, str]:
    return {row[1]: row[2] for row in _rows("regions.tsv.gz") if len(row) >= 3 and row[0] == "C" and row[2]}


@cache
def airline_names() -> dict[str, str]:
    return {row[0]: row[2] for row in _rows("airlines.tsv.gz") if len(row) >= 3 and row[0] and row[2]}


@cache
def airport_places() -> tuple[tuple[str, str, str], ...]:
    return tuple((row[2], row[3], row[4]) for row in _rows("airports.tsv.gz") if len(row) >= 5 and row[2] and row[4])
