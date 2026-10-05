"""OpenFlights' export (My Flights → Export on openflights.org): one row per flight with the columns Date, From, To,
Flight_Number, Airline, Distance, Duration, Seat, Seat_Type, Class, Reason, Plane, Registration, Trip, Note and the site's
ids. The airports are IATA or ICAO codes, the date may carry a time of day (the departure's), the duration is HH:MM and the
class a letter (Y, P, C or F). It has no arrival time. The Note column is never looked at.

The columns are from the layout OpenFlights documents for its CSV import and export; no export from the site was available
to check them against."""
from __future__ import annotations

from collections.abc import Sequence

from .formats import Numbered, Proposed, Skipped, cell, clock_of, day_of, flight_number_of, places, text_of

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
                            seat=text_of(cell(row, "Seat"), 10), cabin=CLASSES.get(cabin.upper(), text_of(cabin))))
    return out
