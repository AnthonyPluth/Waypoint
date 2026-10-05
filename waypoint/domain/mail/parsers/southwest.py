"""Southwest Airlines (southwest.com, mail from luv.southwest.com): confirmation, change and cancellation emails, which carry
no schema.org markup, read from their text. Pure: the HTML and text in, bookings out.

The layout it reads, one leg after another (the times are the airports' wall-clock times; the airline's emails give no zones):

    Confirmation #: K7QW2N
    Passenger: JANE DOE
    Rapid Rewards #: 55512340011
    Flight 1234 Mon, Nov 16, 2026
    Dallas (Love Field), TX (DAL) 8:05 AM
    Houston (Hobby), TX (HOU) 9:10 AM (+1 day)

A change email is the same layout with the new times; one that says the trip "has been canceled" is read the same way and each
leg comes out cancelled. A leg whose lines don't fit is counted unread rather than guessed at."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from ..booking import Booking, Parsed, Passenger
from ._text import lines

PROVIDER = "Southwest Airlines"
MAX_LEGS = 50
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
CONFIRMATION = re.compile(r"confirmation\s*(?:#|number|code)?\s*:?\s*([A-Z0-9]{6})", re.IGNORECASE)
PASSENGER = re.compile(r"passenger(?: \d{1,2})?\s*:\s*(\S.{0,80})", re.IGNORECASE)
MEMBER = re.compile(r"rapid rewards(?: account)?\s*(?:#|number)?\s*:?\s*(\d{6,15})", re.IGNORECASE)
LEG = re.compile(r"flight\s+#?(\d{1,4})\b\D{0,12}([A-Za-z]{3}) (\d{1,2}), (\d{4})", re.IGNORECASE)
STOP = re.compile(r"\(([A-Z]{3})\)\s+(\d{1,2}):(\d{2}) ?([AP])M(?: \(\+(\d) day\))?", re.IGNORECASE)
CANCELLED = re.compile(r"\b(?:has|have|was|were) been cancell?ed\b|\bcancell?ation confirmation\b", re.IGNORECASE)


def _clock(hour: int, minute: int, meridiem: str) -> time | None:
    if not (1 <= hour <= 12 and minute < 60):
        return None
    return time(hour % 12 + (12 if meridiem.upper() == "P" else 0), minute)


def _leg(code: str | None, status: str, first: re.Match[str], dep: re.Match[str], arr: re.Match[str],
         passengers: tuple[Passenger, ...]) -> Booking | None:
    month = MONTHS.get(first[2].lower())
    if month is None:
        return None
    try:
        day = date(int(first[4]), month, int(first[3]))
    except ValueError:
        return None
    left, right = _clock(int(dep[2]), int(dep[3]), dep[4]), _clock(int(arr[2]), int(arr[3]), arr[4])
    if left is None or right is None or not code:
        return None
    start = datetime.combine(day, left)
    end = datetime.combine(day + timedelta(days=int(arr[5] or 0)), right)
    return Booking("flight", "cancelled" if status == "cancelled" else "confirmed", code, PROVIDER,
                   start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), dep[1].upper(), arr[1].upper(),
                   details=(("flight_number", f"WN {first[1]}"),), passengers=passengers)


def parse(html: str, text: str) -> Parsed:
    rows = lines(html, text)
    code = next((m[1].upper() for r in rows if (m := CONFIRMATION.fullmatch(r))), None)
    names = [m[1].strip() for r in rows if (m := PASSENGER.fullmatch(r))]
    number = next((m[1] for r in rows if (m := MEMBER.fullmatch(r))), None)
    # A membership number on a booking for one traveller is theirs; with several, whose it is isn't said.
    passengers = tuple(Passenger(n, number if len(names) == 1 else None) for n in names)
    status = "cancelled" if any(CANCELLED.search(r) for r in rows) else "confirmed"
    found: list[Booking] = []
    unread = 0
    for i, row in enumerate(rows):
        first = LEG.match(row)
        if first is None:
            continue
        if len(found) + unread >= MAX_LEGS:
            break
        dep = STOP.search(rows[i + 1]) if i + 1 < len(rows) else None
        arr = STOP.search(rows[i + 2]) if i + 2 < len(rows) else None
        made = _leg(code, status, first, dep, arr, passengers) if dep and arr else None
        if made is None:
            unread += 1
        elif made not in found:
            found.append(made)
    return Parsed(tuple(found), unread)
