"""Made-up data for previews and `make verify`: `run.py demo` fills an empty database with it. Nothing here is anyone's
real travel (AGENTS.md, "Personal data in the repo"): names, codes and numbers are invented, airports are real.

Each feature that stores something (people, trips) adds its own sample rows here, so `make verify` shows it."""
from __future__ import annotations

from sqlalchemy import func, select

from ..storage import db
from ..storage.models import LoyaltyId, Person, User
from . import loyalty, people

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


def seed(conn: db.Connection) -> int:
    """Fill an empty database with sample data. Returns how many rows it added."""
    before = _rows(conn)
    for sub, email, name, first in MEMBERS:
        db.insert_ignore(conn, User, {"sub": sub, "email": email, "name": name, "first_name": first, "last_seen": 0.0},
                         key=["sub"])
        people.ensure_member(conn, sub, name, first)
    for guest in GUESTS:
        people.add_guest(conn, guest)
    by_name = {p["display_name"]: p["id"] for p in people.everyone(conn)}
    for who, kind, program, number, tier, expiry, notes in MEMBERSHIPS:
        loyalty.add(conn, {"person_id": by_name[who], "kind": kind, "program": program, "number": number, "tier": tier,
                           "expiry": expiry, "notes": notes})
    return _rows(conn) - before


def _rows(conn: db.Connection) -> int:
    return sum(conn.orm.scalar(select(func.count()).select_from(m)) or 0 for m in (User, Person, LoyaltyId))
