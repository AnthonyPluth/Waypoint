from __future__ import annotations

from collections.abc import Sequence

from .formats import Numbered, aircraft_of, Proposed, Skipped, cell, clock_of, day_of, flight_number_of, places, text_of

SIGNATURE = {"date", "from", "to", "flightnumber", "distance", "fromoid"}
CLASSES = {"Y": "Economy", "P": "Premium economy", "C": "Business", "F": "First"}


def parse(rows: Sequence[Numbered]) -> list[Proposed | Skipped]:
    out: list[Proposed | Skipped] = []
    for n, row in rows:
        when = cell(row, "Date")
        day = day_of(when)
        if day is None:
            out.append(Skipped(n, "The date isn’t a day like 2026-03-01"))
            continue
        legs = places(n, cell(row, "From"), cell(row, "To"))
        if isinstance(legs, Skipped):
            out.append(legs)
            continue
        cabin = cell(row, "Class")
        out.append(Proposed(n, day, legs[0], legs[1], flight_number=flight_number_of(cell(row, "Flight_Number")),
                            airline=text_of(cell(row, "Airline")), dep=clock_of(when, day), arr=None,
                            seat=text_of(cell(row, "Seat"), 10), cabin=CLASSES.get(cabin.upper(), text_of(cabin)),
                            aircraft=aircraft_of(cell(row, "Plane"))))
    return out
