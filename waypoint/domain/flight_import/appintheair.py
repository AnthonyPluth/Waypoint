"""App in the Air's export: one row per flight with the columns Date, Flight, From, To, Departure, Arrival, Airline, Seat
and Class, the airports as codes (or names with the code in brackets) and the times as times of day at the airports.

The layout is NOT confirmed: App in the Air publishes no description of its export and none was available to check, so
these columns are the ones its flights list shows, and the format is recognised only by that header. A column it names
differently is read as empty (a flight with no time or seat), never guessed at. The Notes column is never looked at."""
from __future__ import annotations

from collections.abc import Sequence

from .formats import Numbered, Proposed, Skipped, cell, clock_of, day_of, flight_number_of, places, text_of

SIGNATURE = {"date", "flight", "from", "to", "departure", "arrival"}


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
        out.append(Proposed(n, day, legs[0], legs[1], flight_number=flight_number_of(cell(row, "Flight")),
                            airline=text_of(cell(row, "Airline")), dep=clock_of(cell(row, "Departure"), day),
                            arr=clock_of(cell(row, "Arrival")), seat=text_of(cell(row, "Seat"), 10),
                            cabin=text_of(cell(row, "Class"))))
    return out
