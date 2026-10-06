from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["flight", "hotel", "car", "train"]
Status = Literal["confirmed", "cancelled"]


@dataclass(frozen=True)
class Place:
    city: str | None = None
    country: str | None = None


@dataclass(frozen=True)
class Passenger:
    name: str
    member_number: str | None = None


@dataclass(frozen=True)
class Booking:
    kind: Kind
    status: Status
    confirmation: str | None
    provider: str | None
    start: str
    end: str
    origin: str | None
    destination: str | None
    start_place: Place = Place()
    end_place: Place = Place()
    details: tuple[tuple[str, str], ...] = ()
    manage_url: str | None = None
    passengers: tuple[Passenger, ...] = ()
    clock_times: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Parsed:
    bookings: tuple[Booking, ...] = ()
    unread: int = 0
