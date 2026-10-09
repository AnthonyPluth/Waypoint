from __future__ import annotations

from collections.abc import Sequence

from .formats import Numbered, aircraft_of, Proposed, Skipped, cell, clock_of, day_of, flight_number_of, places, text_of

SIGNATURE = {"date", "from", "to", "canceled", "gatedeparture(scheduled)", "takeoff(scheduled)"}


def parse(rows: Sequence[Numbered]) -> list[Proposed | Skipped]:
    out: list[Proposed | Skipped] = []
    for n, row in rows:
        if cell(row, "Canceled").lower() == "true":
            out.append(Skipped(n, "This flight was cancelled, so it isn’t imported"))
            continue
        day = day_of(cell(row, "Date"))
        if day is None:
            out.append(Skipped(n, "The date isn’t a day like 2026-03-01"))
            continue
        legs = places(n, cell(row, "From"), cell(row, "To"))
        if isinstance(legs, Skipped):
            out.append(legs)
            continue
        dep = (clock_of(cell(row, "Gate Departure (Actual)"), day) or clock_of(cell(row, "Gate Departure (Scheduled)"), day)
               or clock_of(cell(row, "Take off (Actual)"), day) or clock_of(cell(row, "Take off (Scheduled)"), day))
        arr = (clock_of(cell(row, "Gate Arrival (Actual)")) or clock_of(cell(row, "Gate Arrival (Scheduled)"))
               or clock_of(cell(row, "Landing (Actual)")) or clock_of(cell(row, "Landing (Scheduled)")))
        airline = text_of(cell(row, "Airline"))
        number = flight_number_of(cell(row, "Flight")) or flight_number_of(f"{airline or ''}{cell(row, 'Flight')}")
        out.append(Proposed(n, day, legs[0], legs[1], flight_number=number, airline=airline, dep=dep, arr=arr,
                            seat=text_of(cell(row, "Seat"), 10), cabin=text_of(cell(row, "Cabin Class")),
                            aircraft=aircraft_of(cell(row, "Aircraft Type Name"))))
    return out
