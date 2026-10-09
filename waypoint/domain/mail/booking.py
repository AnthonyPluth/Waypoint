from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["flight", "hotel", "car", "train", "cruise"]
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
class Port:
    name: str
    zone: str
    arrive_local: str | None
    depart_local: str | None


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
    start_zone: str | None = None
    end_zone: str | None = None
    ports: tuple[Port, ...] = ()


@dataclass(frozen=True)
class Parsed:
    bookings: tuple[Booking, ...] = ()
    unread: int = 0
