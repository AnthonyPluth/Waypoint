from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from ..storage import db, secretbox, stored_mail
from ..storage.models import (FlightStatus, LoyaltyId, Mailbox, Person, ReviewItem, Segment, SegmentMessage, SegmentPort, SegmentTraveler,
                              StoredMessage, Trip, User)
from . import loyalty, people, trips
from .mail import review
from .visibility import Viewer

MEMBERS = [("demo-jane", "jane.doe@example.com", "Jane Doe", "Jane"),
           ("demo-sam", "sam.doe@example.com", "Sam Doe", "Sam")]
GUESTS: list[people.Fields] = [
    {"display_name": "Mia Doe", "first_name": "Mia", "legal_name": "Mia Rose Doe", "aliases": ["DOE/MIA MISS", "DOE/MIAROSE MISS"]},
    {"display_name": "Grandma Joan", "first_name": "Joan", "legal_name": "Joan Marie O’Hare", "aliases": ["OHARE/JOAN MRS"]},
]

MEMBERSHIPS = [
    ("Jane Doe", "airline", "American AAdvantage", "DEMO1234567", None, None),
    ("Jane Doe", "airline", "United MileagePlus", "DM987654", None, None),
    ("Jane Doe", "hotel", "Marriott Bonvoy", "DEMO55501234", None, None),
    ("Jane Doe", "known_traveler", "TSA PreCheck", "TT0000012345", "2029-03-31", "Known Traveler Number"),
    ("Sam Doe", "airline", "Delta SkyMiles", "DEMO7654321", None, None),
    ("Sam Doe", "car", "Hertz Gold Plus Rewards", "DEMO8800123", None, None),
    ("Sam Doe", "known_traveler", "Global Entry", "TT0000067890", "2028-11-15", None),
    ("Mia Doe", "known_traveler", "TSA PreCheck", "TT0000099999", None, None),
    ("Mia Doe", "redress", "DHS TRIP", "DEMO0001234", None, None),
]


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
         "confirmation": "RB3T6K", "provider": "Delta Air Lines", "details": {"flight_number": "DL 2190", "cabin": "Economy", "seat": "22C"}},
    ]


def _family_now(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": _at(today, -2, "19:00"), "end_local": _at(today, -1, "07:10"),
         "confirmation": "KQ7M2X", "provider": "American Airlines", "details": {"flight_number": "AA 101", "terminal": "8", "cabin": "Economy"},
         "manage_url": "https://example.com/manage/KQ7M2X"},
        {"kind": "hotel", "origin": "Harbour Hotel", "start_local": _at(today, -1, "15:00"), "end_local": _at(today, 2, "10:00"),
         "start_zone": "Europe/London", "end_zone": "Europe/London", "confirmation": "H88231", "provider": "Marriott",
         "details": {"address": "1 Quay Street\nLondon E1 0AA", "room": "Family room", "phone": "+44 20 7946 0000"},
         "manage_url": "https://example.com/manage/H88231"},
        {"kind": "hotel", "origin": "Camden Guesthouse", "start_local": _at(today, 2, "15:00"), "end_local": _at(today, 4, "10:00"),
         "start_zone": "Europe/London", "end_zone": "Europe/London", "confirmation": "G20417", "provider": "Example Stays"},
        {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": _at(today, 4, "11:30"), "end_local": _at(today, 4, "14:35"),
         "confirmation": "KQ7M2X", "provider": "American Airlines", "details": {"flight_number": "AA 102", "terminal": "3"}},
    ]


def _family_last_year(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "SFO", "start_local": _at(today, -400, "07:30"), "end_local": _at(today, -400, "10:55"),
         "confirmation": "TV5N2B", "provider": "United Airlines", "details": {"flight_number": "UA 1205", "cabin": "Premium Economy", "seat": "14A"}},
        {"kind": "car", "origin": "SFO airport", "destination": "SFO airport", "start_local": _at(today, -400, "12:00"), "end_local": _at(today, -396, "12:00"),
         "start_zone": "America/Los_Angeles", "end_zone": "America/Los_Angeles", "confirmation": "C5521", "provider": "Hertz",
         "details": {"car_class": "SUV"}},
        {"kind": "hotel", "origin": "Bayview Inn", "destination": "San Francisco", "start_local": _at(today, -400, "15:00"), "end_local": _at(today, -396, "11:00"),
         "start_zone": "America/Los_Angeles", "end_zone": "America/Los_Angeles", "confirmation": "H70452", "provider": "Marriott",
         "details": {"room": "King"}},
        {"kind": "flight", "origin": "SFO", "destination": "JFK", "start_local": _at(today, -396, "13:00"), "end_local": _at(today, -396, "21:30"),
         "confirmation": "TV5N2B", "provider": "United Airlines", "details": {"flight_number": "UA 1210", "cabin": "Premium Economy", "seat": "14B"}},
    ]


def _family_two_years_ago(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "CDG", "start_local": _at(today, -800, "18:30"), "end_local": _at(today, -799, "08:00"),
         "confirmation": "WM8D4P", "provider": "Air France", "details": {"flight_number": "AF 7", "cabin": "Business", "seat": "3D"}},
        {"kind": "hotel", "origin": "Hôtel du Parc", "destination": "Paris", "start_local": _at(today, -799, "15:00"), "end_local": _at(today, -793, "11:00"),
         "start_zone": "Europe/Paris", "end_zone": "Europe/Paris", "confirmation": "H12984", "provider": "Hilton",
         "details": {"room": "Double"}},
        {"kind": "flight", "origin": "CDG", "destination": "JFK", "start_local": _at(today, -793, "11:15"), "end_local": _at(today, -793, "13:50"),
         "confirmation": "WM8D4P", "provider": "Air France", "details": {"flight_number": "AF 8", "cabin": "Business", "seat": "3F"}},
    ]


def _port(name: str, zone: str, day: int, arrive: str | None, leave: str | None, today: date) -> trips.PortIn:
    return {"name": name, "zone": zone, "arrive_local": _at(today, day, arrive) if arrive else None,
            "depart_local": _at(today, day, leave) if leave else None}


def _cruises(today: date) -> list[trips.SegmentIn]:
    new_york, bahamas, cayman = "America/New_York", "America/Nassau", "America/Cayman"
    return [
        {"kind": "cruise", "origin": "Miami", "destination": "Miami", "start_local": _at(today, -250, "16:30"), "end_local": _at(today, -243, "07:00"),
         "start_zone": new_york, "end_zone": new_york, "confirmation": "CR48210", "provider": "Example Cruise Line",
         "details": {"ship": "Example Voyager", "room": "Balcony 9214", "deck": "9"},
         "itinerary": [_port("Nassau", bahamas, -249, "08:00", "17:00", today), _port("Grand Cayman", cayman, -246, "07:00", "16:00", today),
                       _port("Cozumel", "America/Cancun", -245, "08:00", "17:00", today)]},
        {"kind": "cruise", "origin": "Seattle", "destination": "Seattle", "start_local": _at(today, 75, "16:00"), "end_local": _at(today, 82, "06:30"),
         "start_zone": "America/Los_Angeles", "end_zone": "America/Los_Angeles", "confirmation": "CR90377", "provider": "Example Cruise Line",
         "details": {"ship": "Example Explorer", "room": "Oceanview 6118", "deck": "6", "address": "2001 Terminal Way\nSeattle, WA 98100"},
         "itinerary": [_port("Juneau", "America/Juneau", 78, "07:00", "18:00", today), _port("Skagway", "America/Juneau", 79, "07:00", "20:00", today),
                       _port("Victoria", "America/Vancouver", 81, "18:00", "23:00", today)]},
    ]


def _joan(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": _at(today, -2, "19:00"), "end_local": _at(today, -1, "07:10"),
         "confirmation": "MW5T9Z", "provider": "American Airlines", "details": {"flight_number": "AA 101", "terminal": "8", "cabin": "Economy"},
         "manage_url": "https://example.com/manage/MW5T9Z"},
        {"kind": "hotel", "origin": "Camden Guesthouse", "start_local": _at(today, 2, "15:00"), "end_local": _at(today, 4, "10:00"),
         "start_zone": "Europe/London", "end_zone": "Europe/London", "confirmation": "G20417", "provider": "Example Stays"},
        {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": _at(today, 4, "11:30"), "end_local": _at(today, 4, "14:35"),
         "confirmation": "MW5T9Z", "provider": "American Airlines", "details": {"flight_number": "AA 102", "terminal": "3"},
         "manage_url": "https://example.com/manage/MW5T9Z"},
    ]


def _jane_alone(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "SFO", "start_local": _at(today, 20, "08:00"), "end_local": _at(today, 20, "11:20"),
         "confirmation": "PL4N9R", "provider": "United Airlines", "details": {"flight_number": "UA 311", "terminal": "7"}},
        {"kind": "car", "origin": "SFO airport", "destination": "SFO airport", "start_local": _at(today, 20, "12:30"), "end_local": _at(today, 22, "16:00"),
         "start_zone": "America/Los_Angeles", "end_zone": "America/Los_Angeles", "confirmation": "C7710", "provider": "Hertz",
         "details": {"car_class": "Midsize", "address": "1 Rental Way, San Francisco", "phone": "+1 415 555 0100"}},
        {"kind": "flight", "origin": "SFO", "destination": "JFK", "start_local": _at(today, 22, "17:00"), "end_local": _at(today, 23, "01:35"),
         "confirmation": "PL4N9R", "provider": "United Airlines", "details": {"flight_number": "UA 318"}},
    ]


def _sam_alone(today: date) -> list[trips.SegmentIn]:
    return [
        {"kind": "flight", "origin": "JFK", "destination": "AKL", "start_local": _at(today, 45, "21:00"), "end_local": _at(today, 47, "06:30"),
         "confirmation": "ST2V7W", "provider": "Delta Air Lines", "details": {"flight_number": "DL 5"}},
    ]


def _flight_status(today: date) -> dict[str, str]:
    return {
        "flight_number": "AA102", "date": f"{today + timedelta(days=4):%Y-%m-%d}", "state": "delayed", "origin": "LHR", "destination": "JFK",
        "dep_scheduled": _at(today, 4, "11:30"), "dep_estimated": _at(today, 4, "12:20"), "dep_zone": "Europe/London",
        "dep_terminal": "3", "dep_gate": "A12", "arr_scheduled": _at(today, 4, "14:35"), "arr_estimated": _at(today, 4, "15:25"),
        "arr_zone": "America/New_York", "arr_terminal": "8",
    }

def _read_from_email(today: date) -> trips.SegmentIn:
    return {"kind": "flight", "origin": "JFK", "destination": "ORD", "start_local": _at(today, 60, "07:00"), "end_local": _at(today, 60, "08:45"),
            "confirmation": "CH3K5P", "provider": "Example Air", "details": {"flight_number": "EX 410"}}

def _held_stay(today: date) -> trips.SegmentIn:
    return {"kind": "hotel", "origin": "Quay Street Lodge", "destination": None, "start_local": _at(today, 90, "15:00"), "end_local": _at(today, 95, "10:00"),
            "start_zone": "Europe/London", "end_zone": "Europe/London"}


def _message(domain: str, days_ago: int, today: date, subject: str, lines: tuple[str, ...]) -> stored_mail.Content:
    return {"subject": subject, "sender_domain": domain, "received": (today - timedelta(days=days_ago)).isoformat(), "text": "\n".join(lines),
            "html": "".join(f"<p>{line}</p>" for line in lines), "truncated": False}


SUBJECTS = {"example-air.example": "Your itinerary", "example-stays.example": "Your reservation", "example-cruises.example": "Your cruise booking"}

DEMO_MAILBOX = "jane.doe@gmail.example"
UNREAD: list[tuple[str, int, review.Reason]] = [("example-air.example", 21, "no_markup"), ("example-stays.example", 15, "incomplete")]
DEMO_SHARED_MAILBOX = "sam.doe@gmail.example"
SHARED_UNREAD: list[tuple[str, int, review.Reason]] = [("example-cruises.example", 9, "no_markup")]


FAMILY_SEATS = {"DL 1412": ("22A", "22B", "22C"), "AA 101": ("31A", "31B", "31C")}


def _on(*ids: int | None, seats: tuple[str, ...] = ()) -> list[trips.TravelerIn]:
    out: list[trips.TravelerIn] = [{"person_id": i, "name": None} for i in ids]
    for traveler, seat in zip(out, seats, strict=False):
        traveler["seat"] = seat
    return out


def seed(conn: db.Connection, today: date | None = None) -> int:
    today = today or date.today()
    before = _rows(conn)
    for sub, email, name, first in MEMBERS:
        db.insert_ignore(conn, User, {"sub": sub, "email": email, "name": name, "first_name": first, "last_seen": 0.0},
                         key=["sub"])
        people.ensure_member(conn, sub, name, first)
    guests = [people.add_guest(conn, guest)["id"] for guest in GUESTS]
    jane, sam = (Viewer(people.person_for_sub(conn, sub)) for sub in ("demo-jane", "demo-sam"))
    now_trip = None
    for fields in (*_family_two_years_ago(today), *_family_last_year(today), *_family_past(today), *_family_now(today)):
        seats = FAMILY_SEATS.get((fields.get("details") or {}).get("flight_number", ""), ())
        added = trips.add_segment(conn, jane, {**fields, "travelers": _on(jane.person_id, sam.person_id, guests[0], seats=seats)})
        now_trip = added["trip_id"] if added and (fields.get("details") or {}).get("flight_number") == "AA 102" else now_trip
    for fields in _cruises(today):
        trips.add_segment(conn, jane, {**fields, "travelers": _on(jane.person_id, sam.person_id)})
    for fields in _joan(today):
        trips.add_segment(conn, jane, {**fields, "travelers": _on(guests[1])}, now_trip)
    for fields in _jane_alone(today):
        trips.add_segment(conn, jane, {**fields, "travelers": _on(jane.person_id)})
    for fields in _sam_alone(today):
        trips.add_segment(conn, sam, {**fields, "travelers": _on(sam.person_id)})
    from_email = trips.add_segment(conn, jane, {**_read_from_email(today), "travelers": [{"person_id": None, "name": "RIVERA/ALEX MR"}]}, source="email")
    held_ids = [added["id"] for added in (trips.add_segment(conn, jane, {**_held_stay(today), "travelers": _on(jane.person_id)}) for _ in range(2)) if added]
    box = Mailbox(owner_sub="local", address=DEMO_MAILBOX, token=secretbox.encrypt("demo-not-a-token") or "", history_id="1",
                  status="connected", created=0.0, last_scan=None)
    conn.orm.add(box)
    conn.orm.flush()
    for domain, ago, reason in UNREAD:
        review.add(conn, box.id, f"demo-{domain}", domain, (today - timedelta(days=ago)).isoformat(), reason, 0.0)
        stored_mail.put(conn, box.id, f"demo-{domain}", _message(domain, ago, today, f"{SUBJECTS[domain]}: made-up details",
                                                                 ("Hello Jane,", "These are made-up details for the demo.", "Confirmation: DEMO42")), 0.0)
    review.add(conn, box.id, "demo-held-stay", "example-stays.example", (today - timedelta(days=4)).isoformat(), "match", 0.0,
               [({**_held_stay(today), "confirmation": "DEMO77", "provider": "Example Stays"}, held_ids)])
    stored_mail.put(conn, box.id, "demo-held-stay", _message("example-stays.example", 4, today, "Your stay: Quay Street Lodge",
                                                             ("Hello Jane,", "Your stay at Quay Street Lodge is booked.", "Confirmation: DEMO77")), 0.0)
    if from_email:
        stored_mail.put(conn, box.id, "demo-read-from-email", _message("example-air.example", 60, today, "Your itinerary: flight EX 410",
                                                                       ("Hello,", "Your flight EX 410 leaves New York (JFK) at 7:00 am.", "Confirmation: CH3K5P")), 0.0)
        stored_mail.link(conn, from_email["id"], box.id, "demo-read-from-email")
    shared = Mailbox(owner_sub="demo-sam", address=DEMO_SHARED_MAILBOX, token=secretbox.encrypt("demo-not-a-token") or "", history_id="1",
                     status="connected", created=0.0, last_scan=None, share_review=True)
    conn.orm.add(shared)
    conn.orm.flush()
    for domain, ago, reason in SHARED_UNREAD:
        review.add(conn, shared.id, f"demo-{domain}", domain, (today - timedelta(days=ago)).isoformat(), reason, 0.0)
        stored_mail.put(conn, shared.id, f"demo-{domain}", _message(domain, ago, today, f"{SUBJECTS[domain]}: made-up details",
                                                                    ("Hello,", "These are made-up details for the demo.")), 0.0)
    by_name = {p["display_name"]: p["id"] for p in people.everyone(conn)}
    for who, kind, program, number, expiry, notes in MEMBERSHIPS:
        loyalty.add(conn, {"person_id": by_name[who], "kind": kind, "program": program, "number": number,
                           "expiry": expiry, "notes": notes})
    db.upsert(conn, FlightStatus, {**_flight_status(today), "fetched_at": datetime.now(UTC).timestamp()}, key=["flight_number", "date"])
    return _rows(conn) - before


def _rows(conn: db.Connection) -> int:
    return sum(conn.orm.scalar(select(func.count()).select_from(m)) or 0
               for m in (User, Person, LoyaltyId, Trip, Segment, SegmentPort, SegmentTraveler, FlightStatus, Mailbox, ReviewItem, StoredMessage, SegmentMessage))
