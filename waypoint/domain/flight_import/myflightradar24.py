from __future__ import annotations

from collections.abc import Sequence

from .formats import Numbered, Proposed, Skipped, cell, clock_of, day_of, flight_number_of, places, text_of

SIGNATURE = {"date", "flightnumber", "from", "to", "deptime", "arrtime"}
_CLASSES = {"1": "Economy", "2": "Business", "3": "First", "4": "Premium economy", "5": "Private"}


def parse(rows: Sequence[Numbered]) -> list[Proposed | Skipped]:
    out: list[Proposed | Skipped] = []
    for n, row in rows:
        day = day_of(cell(row, "Date"))
        if day is None:
            out.append(Skipped(n, "The date isn’t a day like 2026-03-01"))
            continue
        legs = places(n, cell(row, "From"), cell(row, "To"))
        if isinstance(legs, Skipped):
            out.append(legs)
            continue
        out.append(Proposed(n, day, legs[0], legs[1], flight_number=flight_number_of(cell(row, "Flight number")),
                            airline=text_of(cell(row, "Airline")), dep=clock_of(cell(row, "Dep time"), day),
                            arr=clock_of(cell(row, "Arr time")), seat=text_of(cell(row, "Seat number"), 10),
                            cabin=_CLASSES.get(cell(row, "Flight class"), text_of(cell(row, "Flight class")))))
    return out

