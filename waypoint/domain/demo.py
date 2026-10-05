"""Made-up data for previews and `make verify`: `run.py demo` fills an empty database with it. Nothing here is anyone's
real travel (AGENTS.md, "Personal data in the repo"): names, codes and numbers are invented, airports are real.

Each feature that stores something (people, trips) adds its own sample rows here, so `make verify` shows it."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from ..storage import db, secretbox
from ..storage.models import LoyaltyId, Mailbox, Person, ReviewItem, Segment, SegmentTraveler, Trip, User
from . import loyalty, people, trips
from .mail import review
from .visibility import Viewer

# A household of two who have signed in (sub, email, name, first name), and two guests who haven't a login.
MEMBERS = [("demo-jane", "jane.doe@example.com", "Jane Doe", "Jane"),
           ("demo-sam", "sam.doe@example.com", "Sam Doe", "Sam")]
GUESTS: list[people.Fields] = [
    {"display_name": "Mia Doe", "first_name": "Mia", "legal_name": "Mia Rose Doe", "aliases": ["DOE/MIA MISS", "DOE/MIAROSE MISS"]},
    {"display_name": "Grandma Joan", "first_name": "Joan", "legal_name": "Joan Marie O’Hare", "aliases": ["OHARE/JOAN MRS"]},
]

# Made-up memberships: (person's display name, kind, program, number, tier, expiry, notes).
MEMBERSHIPS = [
    ("Jane Doe", "airline", "American AAdvantage", "DEMO1234567", "Gold", None, None),
    ("Jane Doe", "airline", "United MileagePlus", "DM987654", None, None, None),
    ("Jane Doe", "hotel", "Marriott Bonvoy", "DEMO55501234", "Platinum Elite", None, None),
    ("Jane Doe", "known_traveler", "TSA PreCheck", "TT0000012345", None, "2029-03-31", "Known Traveler Number"),
    ("Sam Doe", "airline", "Delta SkyMiles", "DEMO7654321", "Silver", None, None),
    ("Sam Doe", "car", "Hertz Gold Plus Rewards", "DEMO8800123", None, None, None),
    ("Sam Doe", "known_traveler", "Global Entry", "TT0000067890", None, "2028-11-15", None),
    ("Mia Doe", "known_traveler", "TSA PreCheck", "TT0000099999", None, None, None),
    ("Mia Doe", "redress", "DHS TRIP", "DEMO0001234", None, None, None),
]


# Four trips (and a fifth, read from an email, below), dated from today (so there is always a past one, one in progress and some to come): the family's two (Jane
# booked them for Jane, Sam and Mia: one last month, one under way), and one each for Jane and Sam alone, so each member
# sees three and the other's solo trip isn't among them (AGENTS.md, "You see the trips you're on").
def _at(today: date, days: int, clock: str) -> str:
    return f"{today + timedelta(days=days):%Y-%m-%d}T{clock}"


def _family_past(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "MCO", "start_local": _at(today, -41, "08:15"), "end_local": _at(today, -41, "11:20"),
         "confirmation": "RB3T6K", "provider": "Delta Air Lines", "details": {"flight_number": "DL 1412", "terminal": "4", "cabin": "Economy"}},
        {"kind": "hotel", "origin": "Lakeside Resort", "start_local": _at(today, -41, "15:00"), "end_local": _at(today, -36, "11:00"),
         "start_zone": "America/New_York", "end_zone": "America/New_York", "confirmation": "H41207", "provider": "Hilton",
         "details": {"address": "100 Lakeshore Drive, Orlando", "room": "Two queens"}},
        {"kind": "flight", "origin": "MCO", "destination": "JFK", "start_local": _at(today, -36, "17:40"), "end_local": _at(today, -36, "20:10"),
         "confirmation": "RB3T6K", "provider": "Delta Air Lines", "details": {"flight_number": "DL 2190"}},
    ]


def _family_now(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": _at(today, -2, "19:00"), "end_local": _at(today, -1, "07:10"),
         "confirmation": "KQ7M2X", "provider": "American Airlines", "details": {"flight_number": "AA 101", "terminal": "8", "cabin": "Economy"}},
        {"kind": "hotel", "origin": "Harbour Hotel", "start_local": _at(today, -1, "15:00"), "end_local": _at(today, 4, "10:00"),
         "start_zone": "Europe/London", "end_zone": "Europe/London", "confirmation": "H88231", "provider": "Marriott",
         "details": {"address": "1 Quay Street, London", "room": "Family room"}},
        {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": _at(today, 4, "11:30"), "end_local": _at(today, 4, "14:35"),
         "confirmation": "KQ7M2X", "provider": "American Airlines", "details": {"flight_number": "AA 102", "terminal": "3"}},
    ]


def _jane_alone(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "SFO", "start_local": _at(today, 20, "08:00"), "end_local": _at(today, 20, "11:20"),
         "confirmation": "PL4N9R", "provider": "United Airlines", "details": {"flight_number": "UA 311", "terminal": "7"}},
        {"kind": "car", "origin": "SFO airport", "destination": "SFO airport", "start_local": _at(today, 20, "12:30"), "end_local": _at(today, 22, "16:00"),
         "start_zone": "America/Los_Angeles", "end_zone": "America/Los_Angeles", "confirmation": "C7710", "provider": "Hertz",
         "details": {"car_class": "Midsize"}},
        {"kind": "flight", "origin": "SFO", "destination": "JFK", "start_local": _at(today, 22, "17:00"), "end_local": _at(today, 23, "01:35"),
         "confirmation": "PL4N9R", "provider": "United Airlines", "details": {"flight_number": "UA 318"}},
    ]


def _sam_alone(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "AKL", "start_local": _at(today, 45, "21:00"), "end_local": _at(today, 47, "06:30"),
         "confirmation": "ST2V7W", "provider": "Delta Air Lines", "details": {"flight_number": "DL 5"}},
    ]


# A flight Waypoint read from an email, for a traveller whose printed name nobody matches yet ("Who is this?" in Review).
def _read_from_email(today: date) -> trips.SegmentIn:
    return {"kind": "flight", "origin": "JFK", "destination": "ORD", "start_local": _at(today, 60, "07:00"), "end_local": _at(today, 60, "08:45"),
            "confirmation": "CH3K5P", "provider": "Example Air", "details": {"flight_number": "EX 410"}}

# The household's one connected mailbox, and two messages Waypoint couldn't read (sender's domain, days before today, why).
DEMO_MAILBOX = "jane.doe@gmail.example"
UNREAD: list[tuple[str, int, review.Reason]] = [("example-air.example", 21, "no_markup"), ("example-stays.example", 15, "incomplete")]


def _on(*ids: int | None) -> list[trips.TravelerIn]:
    return [{"person_id": i, "name": None} for i in ids]


def seed(conn: db.Connection, today: date | None = None) -> int:
    """Fill an empty database with sample data, its trips dated from `today` (this machine's, by default). Returns how many
    rows it added."""
    today = today or date.today()
    before = _rows(conn)
    for sub, email, name, first in MEMBERS:
        db.insert_ignore(conn, User, {"sub": sub, "email": email, "name": name, "first_name": first, "last_seen": 0.0},
                         key=["sub"])
        people.ensure_member(conn, sub, name, first)
    guests = [people.add_guest(conn, guest)["id"] for guest in GUESTS]
    jane, sam = (Viewer(people.person_for_sub(conn, sub)) for sub in ("demo-jane", "demo-sam"))
    for fields in (*_family_past(today), *_family_now(today)):
        trips.add_segment(conn, jane, {**fields, "travelers": _on(jane.person_id, sam.person_id, guests[0])})
    for fields in _jane_alone(today):
        trips.add_segment(conn, jane, {**fields, "travelers": _on(jane.person_id)})
    for fields in _sam_alone(today):
        trips.add_segment(conn, sam, {**fields, "travelers": _on(sam.person_id)})
    trips.add_segment(conn, jane, {**_read_from_email(today), "travelers": [{"person_id": None, "name": "RIVERA/ALEX MR"}]}, source="email")
    box = Mailbox(owner_sub="local", address=DEMO_MAILBOX, token=secretbox.encrypt("demo-not-a-token") or "", history_id="1",
                  status="connected", created=0.0, last_scan=None)
    conn.orm.add(box)
    conn.orm.flush()
    for domain, ago, reason in UNREAD:
        review.add(conn, box.id, f"demo-{domain}", domain, (today - timedelta(days=ago)).isoformat(), reason, 0.0)
    by_name = {p["display_name"]: p["id"] for p in people.everyone(conn)}
    for who, kind, program, number, tier, expiry, notes in MEMBERSHIPS:
        loyalty.add(conn, {"person_id": by_name[who], "kind": kind, "program": program, "number": number, "tier": tier,
                           "expiry": expiry, "notes": notes})
    return _rows(conn) - before


def _rows(conn: db.Connection) -> int:
    return sum(conn.orm.scalar(select(func.count()).select_from(m)) or 0
               for m in (User, Person, LoyaltyId, Trip, Segment, SegmentTraveler, Mailbox, ReviewItem))
