from __future__ import annotations

from typing import TypedDict

from sqlalchemy import delete, select, update

from ..storage import db, secretbox
from ..storage.models import LoyaltyId, Person

KINDS = ("airline", "hotel", "car", "known_traveler", "redress")
OTHER = "Other"
EXPIRES = ("known_traveler", "redress")
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
    person_id: int
    kind: str
    program: str
    number: str | None
    expiry: str | None
    notes: str | None


class Listed(TypedDict):
    id: int
    person_id: int
    kind: str
    program: str
    masked: str
    readable: bool
    expiry: str | None
    notes: str | None


class Conflict(TypedDict):
    person_id: int
    kind: str
    program: str


class NoSuchPerson(Exception):
    pass


class Duplicate(Exception):
    pass


class Unreadable(Exception):
    pass


def mask(number: str) -> str:
    return MASK + number[-4:] if len(number) > 4 else MASK


def listed(row: LoyaltyId) -> Listed:
    try:
        masked, readable = mask(secretbox.decrypt(row.number) or ""), True
    except secretbox.SecretError:
        masked, readable = MASK, False
    return {"id": row.id, "person_id": row.person_id, "kind": row.kind, "program": row.program, "masked": masked,
            "readable": readable, "expiry": row.expiry, "notes": row.notes}


def everyone(conn: db.Connection) -> list[Listed]:
    rows = conn.orm.scalars(select(LoyaltyId)).all()
    order = {k: i for i, k in enumerate(KINDS)}
    return [listed(r) for r in sorted(rows, key=lambda r: (r.person_id, order.get(r.kind, len(order)), r.program.casefold(), r.id))]


def conflicts(conn: db.Connection) -> list[Conflict]:
    seen: dict[tuple[int, str, str], set[str]] = {}
    for row in conn.orm.scalars(select(LoyaltyId)).all():
        try:
            number = _plain(secretbox.decrypt(row.number) or "")
        except secretbox.SecretError:
            continue
        seen.setdefault((row.person_id, row.kind, row.program), set()).add(number)
    return [{"person_id": p, "kind": k, "program": g} for (p, k, g), numbers in sorted(seen.items()) if len(numbers) > 1]


def _person_exists(conn: db.Connection, person_id: int) -> bool:
    return conn.orm.scalar(select(Person.id).where(Person.id == person_id)) is not None


def _holds(conn: db.Connection, fields: Fields, *, besides: int | None = None) -> bool:
    if fields["program"] == OTHER:
        return False
    found = select(LoyaltyId.id).where(LoyaltyId.person_id == fields["person_id"], LoyaltyId.kind == fields["kind"],
                                        LoyaltyId.program == fields["program"])
    if besides is not None:
        found = found.where(LoyaltyId.id != besides)
    return conn.orm.scalar(found.limit(1)) is not None


def add(conn: db.Connection, fields: Fields) -> Listed:
    if not _person_exists(conn, fields["person_id"]):
        raise NoSuchPerson()
    if _holds(conn, fields):
        raise Duplicate()
    if not fields["number"]:
        raise ValueError("a new membership needs a number")
    row = LoyaltyId(person_id=fields["person_id"], kind=fields["kind"], program=fields["program"],
                    number=secretbox.encrypt(fields["number"]) or "", expiry=fields["expiry"],
                    notes=fields["notes"])
    conn.orm.add(row)
    conn.orm.flush()
    return listed(row)


def edit(conn: db.Connection, loyalty_id: int, fields: Fields) -> Listed | None:
    if not _person_exists(conn, fields["person_id"]):
        raise NoSuchPerson()
    current = conn.orm.get(LoyaltyId, loyalty_id)
    moved = current is not None and (current.person_id, current.kind, current.program) != (fields["person_id"], fields["kind"], fields["program"])
    if moved and _holds(conn, fields, besides=loyalty_id):
        raise Duplicate()
    values = {"person_id": fields["person_id"], "kind": fields["kind"], "program": fields["program"],
              "expiry": fields["expiry"], "notes": fields["notes"]}
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
    wanted = _plain(number)
    if not wanted:
        return None
    found: set[int] = set()
    for row in conn.orm.scalars(select(LoyaltyId)).all():
        try:
            saved = secretbox.decrypt(row.number) or ""
        except secretbox.SecretError:
            continue
        if _plain(saved) == wanted:
            found.add(row.person_id)
    return found.pop() if len(found) == 1 else None


def known_numbers(conn: db.Connection) -> list[str]:
    found: list[str] = []
    for row in conn.orm.scalars(select(LoyaltyId)).all():
        try:
            found.append(secretbox.decrypt(row.number) or "")
        except secretbox.SecretError:
            continue
    return [n for n in found if n.strip()]
