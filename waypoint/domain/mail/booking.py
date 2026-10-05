"""What a booking read from an email is: the fields of one segment, none of the message's text. Shared by `extract.py` (schema.org
markup) and the vendor parsers in `parsers/`, which return the same thing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["flight", "hotel", "car", "train"]
Status = Literal["confirmed", "cancelled"]


@dataclass(frozen=True)
class Place:
    """Where a stay or a rental is, as far as the markup says: what finds its time zone."""
    city: str | None = None
    country: str | None = None


@dataclass(frozen=True)
class Passenger:
    name: str
    member_number: str | None = None   # a loyalty number printed on the booking (programMembership)


@dataclass(frozen=True)
class Booking:
    kind: Kind
    status: Status
    confirmation: str | None
    provider: str | None
    start: str                         # the time as written (ISO 8601, with or without an offset)
    end: str
    origin: str | None                 # a flight's airport code; a stay's or a rental's place, a station
    destination: str | None
    start_place: Place = Place()
    end_place: Place = Place()
    details: tuple[tuple[str, str], ...] = ()
    manage_url: str | None = None
    passengers: tuple[Passenger, ...] = ()


@dataclass(frozen=True)
class Parsed:
    """What a vendor parser found: its bookings, and how many it recognised but couldn't make into one (a missing time or place)."""
    bookings: tuple[Booking, ...] = ()
    unread: int = 0
