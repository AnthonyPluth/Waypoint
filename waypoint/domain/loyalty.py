"""Loyalty and Known Traveler numbers: one membership per row, for a person (member or guest). Every signed-in member sees
and edits everyone's, so anyone can book for anyone (AGENTS.md, "IDs are for the household"). A number is encrypted at
rest (waypoint/storage/secretbox.py) and this is the only module in the domain that decrypts one. Listings carry only the
number's last four characters; the number itself comes from `reveal`, one membership at a time, so a page load never
holds every number. Numbers never go in a log, a report, a notification or an AI prompt."""
from __future__ import annotations

from typing import TypedDict

from sqlalchemy import delete, select, update

from ..storage import db, secretbox
from ..storage.models import LoyaltyId, Person

KINDS = ("airline", "hotel", "car", "known_traveler", "redress")
OTHER = "Other"
# The programs to choose from, for each kind (a fixed list: "Other" for any that isn't there).
PROGRAMS: dict[str, tuple[str, ...]] = {
    "airline": ("Alaska Mileage Plan", "American AAdvantage", "Delta SkyMiles", "JetBlue TrueBlue", "Southwest Rapid Rewards",
                "United MileagePlus", OTHER),
    "hotel": ("Hilton Honors", "Hyatt World of Hyatt", "IHG One Rewards", "Marriott Bonvoy", "Wyndham Rewards", OTHER),
    "car": ("Avis Preferred", "Enterprise Plus", "Hertz Gold Plus Rewards", "National Emerald Club", OTHER),
    "known_traveler": ("Global Entry", "NEXUS", "SENTRI", "TSA PreCheck", OTHER),
    "redress": ("DHS TRIP", OTHER),
}
MASK = "••••"


class Fields(TypedDict):
    """What a membership's form edits, already checked (waypoint/server/api/loyalty.py). `number` None: keep the one saved."""
    person_id: int
    kind: str
    program: str
    number: str | None
    tier: str | None
    expiry: str | None
    notes: str | None


class Listed(TypedDict):
    id: int
    person_id: int
    kind: str
    program: str
    masked: str            # MASK and the number's last four characters (all of it masked when it's that short)
    readable: bool         # false: Waypoint's key can't unlock it (a restore under another key); it has to be entered again
    tier: str | None
    expiry: str | None
    notes: str | None


class Conflict(TypedDict):
    """A person with two different numbers for one program (a claimed guest's and their own): both are kept, People flags it."""
    person_id: int
    kind: str
    program: str


class NoSuchPerson(Exception):
    """A membership names someone who isn't in People."""


class Duplicate(Exception):
    """The person already has a membership in that program (a second one in "Other" is fine: it can be any program)."""


class Unreadable(Exception):
    """The saved number can't be unlocked with Waypoint's current key."""


def mask(number: str) -> str:
    return MASK + number[-4:] if len(number) > 4 else MASK


def listed(row: LoyaltyId) -> Listed:
    try:
        masked, readable = mask(secretbox.decrypt(row.number) or ""), True
    except secretbox.SecretError:
        masked, readable = MASK, False
    return {"id": row.id, "person_id": row.person_id, "kind": row.kind, "program": row.program, "masked": masked,
            "readable": readable, "tier": row.tier, "expiry": row.expiry, "notes": row.notes}


def everyone(conn: db.Connection) -> list[Listed]:
    """Every membership, in a person's order of kinds (airline, hotel, car, Known Traveler, redress) and then by program."""
    rows = conn.orm.scalars(select(LoyaltyId)).all()
    order = {k: i for i, k in enumerate(KINDS)}
    return [listed(r) for r in sorted(rows, key=lambda r: (r.person_id, order.get(r.kind, len(order)), r.program.casefold(), r.id))]


def conflicts(conn: db.Connection) -> list[Conflict]:
    """The people with more than one different number for the same program. Only who and which program come out."""
    seen: dict[tuple[int, str, str], set[str]] = {}
    for row in conn.orm.scalars(select(LoyaltyId)).all():
        try:
            number = _plain(secretbox.decrypt(row.number) or "")
        except secretbox.SecretError:
            continue   # (a number this key can't unlock can't be compared)
        seen.setdefault((row.person_id, row.kind, row.program), set()).add(number)
    return [{"person_id": p, "kind": k, "program": g} for (p, k, g), numbers in sorted(seen.items()) if len(numbers) > 1]


def _person_exists(conn: db.Connection, person_id: int) -> bool:
    return conn.orm.scalar(select(Person.id).where(Person.id == person_id)) is not None


def _holds(conn: db.Connection, fields: Fields, *, besides: int | None = None) -> bool:
    """Whether the person has a membership (other than `besides`) in this program."""
    if fields["program"] == OTHER:
        return False
    found = select(LoyaltyId.id).where(LoyaltyId.person_id == fields["person_id"], LoyaltyId.kind == fields["kind"],
                                        LoyaltyId.program == fields["program"])
    if besides is not None:
        found = found.where(LoyaltyId.id != besides)
    return conn.orm.scalar(found.limit(1)) is not None


def add(conn: db.Connection, fields: Fields) -> Listed:
    """Save a membership. Raises NoSuchPerson, Duplicate (they have one in that program), and ValueError when there is no number."""
    if not _person_exists(conn, fields["person_id"]):
        raise NoSuchPerson()
    if _holds(conn, fields):
        raise Duplicate()
    if not fields["number"]:
        raise ValueError("a new membership needs a number")
    row = LoyaltyId(person_id=fields["person_id"], kind=fields["kind"], program=fields["program"],
                    number=secretbox.encrypt(fields["number"]) or "", tier=fields["tier"], expiry=fields["expiry"],
                    notes=fields["notes"])
    conn.orm.add(row)
    conn.orm.flush()
    return listed(row)


def edit(conn: db.Connection, loyalty_id: int, fields: Fields) -> Listed | None:
    """Change a membership (the number only when one is given). None: there's no such membership. Raises NoSuchPerson, and
    Duplicate when it would move to a program the person already has (one left in the program it was in, as a person who was
    given two by claiming a guest has, can still be edited)."""
    if not _person_exists(conn, fields["person_id"]):
        raise NoSuchPerson()
    current = conn.orm.get(LoyaltyId, loyalty_id)
    moved = current is not None and (current.person_id, current.kind, current.program) != (fields["person_id"], fields["kind"], fields["program"])
    if moved and _holds(conn, fields, besides=loyalty_id):
        raise Duplicate()
    values = {"person_id": fields["person_id"], "kind": fields["kind"], "program": fields["program"],
              "tier": fields["tier"], "expiry": fields["expiry"], "notes": fields["notes"]}
    if fields["number"]:
        values["number"] = secretbox.encrypt(fields["number"])
    if conn.execute(update(LoyaltyId).where(LoyaltyId.id == loyalty_id).values(**values)).rowcount == 0:
        return None
    conn.orm.expire_all()
    row = conn.orm.get(LoyaltyId, loyalty_id)
    return listed(row) if row else None


def remove(conn: db.Connection, loyalty_id: int) -> bool:
    return conn.execute(delete(LoyaltyId).where(LoyaltyId.id == loyalty_id)).rowcount > 0


def reveal(conn: db.Connection, loyalty_id: int) -> str | None:
    """One membership's number, in the clear. None: there's no such membership. Raises Unreadable."""
    row = conn.orm.get(LoyaltyId, loyalty_id)
    if row is None:
        return None
    try:
        return secretbox.decrypt(row.number) or ""
    except secretbox.SecretError as e:
        raise Unreadable() from e


def _plain(number: str) -> str:
    return "".join(number.split()).replace("-", "").casefold()


def person_for_number(conn: db.Connection, number: str) -> int | None:
    """The person who has this loyalty or Known Traveler number (as printed on a booking), so a booking is matched to them
    by it. None when no one does, or when the number is on more than one person. The numbers stay in here: only who
    they belong to comes out."""
    wanted = _plain(number)
    if not wanted:
        return None
    found: set[int] = set()
    for row in conn.orm.scalars(select(LoyaltyId)).all():
        try:
            saved = secretbox.decrypt(row.number) or ""
        except secretbox.SecretError:
            continue   # (a number this key can't unlock can't match)
        if _plain(saved) == wanted:
            found.add(row.person_id)
    return found.pop() if len(found) == 1 else None


def known_numbers(conn: db.Connection) -> list[str]:
    """Every number saved, as typed, so the optional AI fallback can strip exactly these from what it sends (they never go
    to it: AGENTS.md, "IDs are for the household"). Stays in memory; nothing here is shown, kept or logged."""
    found: list[str] = []
    for row in conn.orm.scalars(select(LoyaltyId)).all():
        try:
            found.append(secretbox.decrypt(row.number) or "")
        except secretbox.SecretError:
            continue
    return [n for n in found if n.strip()]
