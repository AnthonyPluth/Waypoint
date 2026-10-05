"""People: everyone who travels. A member is a signed-in household member, linked to their sign-in (`user_sub`) and made
the first time they sign in; a guest has no login (a child, a grandparent) and is added, renamed and removed by any
member. Everyone is visible to every member (AGENTS.md, "IDs are for the household"). A person's names: the display name
the app shows, their first name, their legal name as on an ID, and the aliases an airline prints for them
("DOE/JANE MS"), which later bookings are matched against."""
from __future__ import annotations

import json
from typing import Any, TypedDict

from sqlalchemy import delete, select, update

from ..storage import db
from ..storage.models import Person


class Fields(TypedDict):
    """What a person's page edits: already checked and trimmed (waypoint/server/api/people.py)."""
    display_name: str
    first_name: str | None
    legal_name: str | None
    aliases: list[str]


class Listed(TypedDict):
    id: int
    display_name: str
    first_name: str | None
    legal_name: str | None
    aliases: list[str]
    member: bool


class MemberRemoval(Exception):
    """Only guests are removed: a member goes with their login."""


def decode_aliases(raw: str | None) -> list[str]:
    """The aliases stored in a row (a JSON list of texts); anything else reads as none."""
    try:
        found = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [a for a in found if isinstance(a, str)] if isinstance(found, list) else []


def encode_aliases(aliases: list[str]) -> str | None:
    return json.dumps(aliases, ensure_ascii=False) if aliases else None


def listed(p: Person) -> Listed:
    return {"id": p.id, "display_name": p.display_name, "first_name": p.first_name, "legal_name": p.legal_name,
            "aliases": decode_aliases(p.aliases), "member": p.user_sub is not None}


def everyone(conn: db.Connection) -> list[Listed]:
    """Members first, then guests, each by name."""
    found = conn.orm.scalars(select(Person)).all()
    return [listed(p) for p in sorted(found, key=lambda p: (p.user_sub is None, p.display_name.casefold(), p.id))]


def ensure_member(conn: db.Connection, sub: str, display_name: str, first_name: str | None) -> None:
    """Signing in makes the member's person on the first time. Later sign-ins leave it alone: the person's names may have
    been edited since, and what the sign-in provider says doesn't win over that."""
    db.insert_ignore(conn, Person, {"display_name": display_name, "first_name": first_name, "user_sub": sub},
                     key=["user_sub"])


def _values(fields: Fields) -> dict[str, Any]:
    return {"display_name": fields["display_name"], "first_name": fields["first_name"],
            "legal_name": fields["legal_name"], "aliases": encode_aliases(fields["aliases"])}


def add_guest(conn: db.Connection, fields: Fields) -> Listed:
    guest = Person(**_values(fields), user_sub=None)
    conn.orm.add(guest)
    conn.orm.flush()
    return listed(guest)


def get(conn: db.Connection, person_id: int) -> Listed | None:
    found = conn.orm.get(Person, person_id)
    return listed(found) if found else None


def edit(conn: db.Connection, person_id: int, fields: Fields) -> Listed | None:
    """Rename or re-spell someone (a member's link to their login isn't among the fields). None: there's no such person."""
    if conn.execute(update(Person).where(Person.id == person_id).values(**_values(fields))).rowcount == 0:
        return None
    return get(conn, person_id)


def remove_guest(conn: db.Connection, person_id: int) -> bool:
    """Remove a guest; False when there's no such person. Raises MemberRemoval for a member."""
    found = conn.orm.get(Person, person_id)
    if found is None:
        return False
    if found.user_sub is not None:
        raise MemberRemoval()
    conn.execute(delete(Person).where(Person.id == person_id, Person.user_sub.is_(None)))
    return True
