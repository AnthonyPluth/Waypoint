"""Importing past flights from another app's CSV export (Settings → Import past flights): Flighty, myFlightRadar24,
OpenFlights or App in the Air.

`read` turns an uploaded file into what each row proposes, detecting the format from its header row; the parsers (one
module each) are pure functions from rows to proposed flights. `preview` marks each as new, already in Waypoint, or one
that can't be read, and `save` adds the ones the person confirms as segments (source "import"), grouped into trips as any
segment is. The file is read in memory and dropped: nothing here keeps it, logs a row or looks at a notes column, and
the confirm step sends back only the flights to save."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from . import appintheair, flighty, myflightradar24, openflights
from .formats import Numbered, Parser, Proposed, Skipped
from .save import FlightIn, PreviewRow, Saved, preview, save

__all__ = [
    "FORMATS",
    "MAX_ROWS",
    "FlightIn",
    "Parsed",
    "PreviewRow",
    "Proposed",
    "Saved",
    "Skipped",
    "Unreadable",
    "preview",
    "read",
    "save",
]

MAX_ROWS = 10_000
# Each format's name, the headers that identify it (normalised: case, spaces and underscores dropped) and its parser,
# in the order they're tried.
FORMATS: dict[str, tuple[frozenset[str], Parser]] = {
    "Flighty": (frozenset(flighty.SIGNATURE), flighty.parse),
    "myFlightRadar24": (frozenset(myflightradar24.SIGNATURE), myflightradar24.parse),
    "OpenFlights": (frozenset(openflights.SIGNATURE), openflights.parse),
    "App in the Air": (frozenset(appintheair.SIGNATURE), appintheair.parse),
}
SUPPORTED = "Flighty, myFlightRadar24, OpenFlights and App in the Air"


class Unreadable(ValueError):
    """The file can't be imported at all; the message says why (the API's 400)."""


@dataclass(frozen=True)
class Parsed:
    format: str
    rows: list[Proposed | Skipped]


def _normal(header: str) -> str:
    return "".join(c for c in header.casefold() if not c.isspace() and c != "_")


def read(data: bytes) -> Parsed:
    """The flights a CSV export proposes, one entry per row. Raises Unreadable for a file that isn't text or CSV, is empty,
    has no flights, has more than MAX_ROWS rows, or has headers that are none of the supported formats'."""
    if not data.strip():
        raise Unreadable("That file is empty.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Unreadable("That file isn’t a text (CSV) file. Export your flights as CSV and choose that.") from None
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        headers = next(reader)
        found = _format_of(headers)
        rows: list[Numbered] = []
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue
            if len(rows) >= MAX_ROWS:
                raise Unreadable(f"That file has more than {MAX_ROWS:,} rows. Split it into smaller files and import them one at a time.")
            rows.append((reader.line_num, {h.strip(): c.strip() for h, c in zip(headers, cells, strict=False)}))
    except csv.Error:
        raise Unreadable("That file isn’t a CSV file Waypoint can read.") from None
    if not rows:
        raise Unreadable("That file has a header row but no flights in it.")
    return Parsed(found, FORMATS[found][1](rows))


def _format_of(headers: list[str]) -> str:
    names = {_normal(h) for h in headers}
    for name, (signature, _) in FORMATS.items():
        if signature <= names:
            return name
    raise Unreadable(f"Waypoint can import CSV exports from {SUPPORTED}. This file’s columns don’t match any of them.")
