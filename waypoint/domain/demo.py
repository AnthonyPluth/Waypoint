"""Made-up data for previews and `make verify`: `run.py demo` fills an empty database with it. Nothing here is anyone's
real travel (AGENTS.md, "Personal data in the repo"): names, codes and numbers are invented, airports are real.

Each feature that stores something (people, trips) adds its own sample rows here, so `make verify` shows it."""
from __future__ import annotations

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


# Three trips: the family's (Jane booked it for Jane, Sam and Mia) and one each for Jane and Sam alone, so each member sees
# two and the other's solo trip isn't among them (AGENTS.md, "You see the trips you're on").
FAMILY: list[trips.SegmentIn] = [
    {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-11-20T19:00", "end_local": "2026-11-21T07:10",
     "confirmation": "KQ7M2X", "provider": "Example Air", "details": {"flight_number": "EX 101", "terminal": "7", "cabin": "Economy"}},
    {"kind": "hotel", "origin": "Harbour Hotel", "start_local": "2026-11-21T15:00", "end_local": "2026-11-27T10:00",
     "start_zone": "Europe/London", "end_zone": "Europe/London", "confirmation": "H88231",
     "details": {"address": "1 Quay Street, London", "room": "Family room"}},
    {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": "2026-11-27T11:30", "end_local": "2026-11-27T14:35",
     "confirmation": "KQ7M2X", "provider": "Example Air", "details": {"flight_number": "EX 102"}},
]
JANE_ALONE: list[trips.SegmentIn] = [
    {"kind": "flight", "origin": "JFK", "destination": "SFO", "start_local": "2026-12-08T08:00", "end_local": "2026-12-08T11:20",
     "confirmation": "PL4N9R", "provider": "Example Air", "details": {"flight_number": "EX 311"}},
    {"kind": "flight", "origin": "SFO", "destination": "JFK", "start_local": "2026-12-10T17:00", "end_local": "2026-12-11T01:35",
     "confirmation": "PL4N9R", "provider": "Example Air", "details": {"flight_number": "EX 318"}},
]
SAM_ALONE: list[trips.SegmentIn] = [
    {"kind": "flight", "origin": "JFK", "destination": "AKL", "start_local": "2027-01-14T21:00", "end_local": "2027-01-16T06:30",
     "confirmation": "ST2V7W", "provider": "Example Air", "details": {"flight_number": "EX 5"}},
]


# A flight Waypoint read from an email, for a traveller whose printed name nobody matches yet ("Who is this?" in Review).
READ_FROM_EMAIL: trips.SegmentIn = {
    "kind": "flight", "origin": "JFK", "destination": "ORD", "start_local": "2027-02-03T07:00", "end_local": "2027-02-03T08:45",
    "confirmation": "CH3K5P", "provider": "Example Air", "details": {"flight_number": "EX 410"}}

# The household's one connected mailbox, and two messages Waypoint couldn't read (sender's domain, day, why).
DEMO_MAILBOX = "jane.doe@gmail.example"
UNREAD: list[tuple[str, str, review.Reason]] = [("example-air.example", "2026-09-14", "no_markup"),
                                                  ("example-stays.example", "2026-09-20", "incomplete")]


def _on(*ids: int | None) -> list[trips.TravelerIn]:
    return [{"person_id": i, "name": None} for i in ids]


def seed(conn: db.Connection) -> int:
    """Fill an empty database with sample data. Returns how many rows it added."""
    before = _rows(conn)
    for sub, email, name, first in MEMBERS:
        db.insert_ignore(conn, User, {"sub": sub, "email": email, "name": name, "first_name": first, "last_seen": 0.0},
                         key=["sub"])
        people.ensure_member(conn, sub, name, first)
    guests = [people.add_guest(conn, guest)["id"] for guest in GUESTS]
    jane, sam = (Viewer(people.person_for_sub(conn, sub)) for sub in ("demo-jane", "demo-sam"))
    for fields in FAMILY:
        trips.add_segment(conn, jane, {**fields, "travelers": _on(jane.person_id, sam.person_id, guests[0])})
    for fields in JANE_ALONE:
        trips.add_segment(conn, jane, {**fields, "travelers": _on(jane.person_id)})
    for fields in SAM_ALONE:
        trips.add_segment(conn, sam, {**fields, "travelers": _on(sam.person_id)})
    trips.add_segment(conn, jane, {**READ_FROM_EMAIL, "travelers": [{"person_id": None, "name": "RIVERA/ALEX MR"}]}, source="email")
    box = Mailbox(owner_sub="local", address=DEMO_MAILBOX, token=secretbox.encrypt("demo-not-a-token") or "", history_id="1",
                  status="connected", created=0.0, last_scan=1_790_000_000.0)
    conn.orm.add(box)
    conn.orm.flush()
    for domain, day, reason in UNREAD:
        review.add(conn, box.id, f"demo-{domain}", domain, day, reason, 0.0)
    by_name = {p["display_name"]: p["id"] for p in people.everyone(conn)}
    for who, kind, program, number, tier, expiry, notes in MEMBERSHIPS:
        loyalty.add(conn, {"person_id": by_name[who], "kind": kind, "program": program, "number": number, "tier": tier,
                           "expiry": expiry, "notes": notes})
    return _rows(conn) - before


def _rows(conn: db.Connection) -> int:
    return sum(conn.orm.scalar(select(func.count()).select_from(m)) or 0
               for m in (User, Person, LoyaltyId, Trip, Segment, SegmentTraveler, Mailbox, ReviewItem))
