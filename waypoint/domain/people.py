from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from sqlalchemy import delete, select, update

from ..storage import db
from ..storage.models import LoyaltyId, Person, Segment, SegmentRecipient, SegmentTraveler, Trip
from . import visibility


class Fields(TypedDict):
    display_name: str
    first_name: str | None
    legal_name: str | None
    aliases: list[str]


class Link(TypedDict):
    guest: str
    by: str
    on: str


class Listed(TypedDict):
    id: int
    display_name: str
    first_name: str | None
    legal_name: str | None
    aliases: list[str]
    member: bool
    links: list[Link]


class MemberRemoval(Exception):
    pass


class NotAMember(Exception):
    pass


class NoSuchGuest(Exception):
    pass


class NotAGuest(Exception):
    pass


def decode_aliases(raw: str | None) -> list[str]:
    try:
        found = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [a for a in found if isinstance(a, str)] if isinstance(found, list) else []


def encode_aliases(aliases: list[str]) -> str | None:
    return json.dumps(aliases, ensure_ascii=False) if aliases else None


def decode_links(raw: str | None) -> list[Link]:
    try:
        found = json.loads(raw) if raw else []
    except ValueError:
        return []
    if not isinstance(found, list):
        return []
    return [{"guest": f["guest"], "by": f["by"], "on": f["on"]} for f in found
            if isinstance(f, dict) and all(isinstance(f.get(k), str) for k in ("guest", "by", "on"))]


def listed(p: Person) -> Listed:
    return {"id": p.id, "display_name": p.display_name, "first_name": p.first_name, "legal_name": p.legal_name,
            "aliases": decode_aliases(p.aliases), "member": p.user_sub is not None, "links": decode_links(p.links)}


def everyone(conn: db.Connection) -> list[Listed]:
    found = conn.orm.scalars(select(Person)).all()
    return [listed(p) for p in sorted(found, key=lambda p: (p.user_sub is None, p.display_name.casefold(), p.id))]


def person_for_sub(conn: db.Connection, sub: str) -> int | None:
    return conn.orm.scalars(select(Person.id).where(Person.user_sub == sub)).first()


def existing(conn: db.Connection, ids: list[int]) -> dict[int, str]:
    return dict(conn.execute(select(Person.id, Person.display_name).where(Person.id.in_(ids))).fetchall())


def ensure_member(conn: db.Connection, sub: str, display_name: str, first_name: str | None) -> None:
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
    if conn.execute(update(Person).where(Person.id == person_id).values(**_values(fields))).rowcount == 0:
        return None
    return get(conn, person_id)


def remove_guest(conn: db.Connection, person_id: int) -> bool:
    found = conn.orm.get(Person, person_id)
    if found is None:
        return False
    if found.user_sub is not None:
        raise MemberRemoval()
    conn.execute(delete(Person).where(Person.id == person_id, Person.user_sub.is_(None)))
    return True


TITLES = frozenset({"mr", "mrs", "ms", "miss", "mstr", "master", "mx", "dr", "prof", "sir", "lady"})


def normalize(name: str) -> str:
    text = name.casefold()
    if "/" in text:
        last, _, first = text.partition("/")
        text = f"{first} {last}"
    return " ".join(t for t in re.split(r"\W+", text) if t and t not in TITLES)


def _called(p: Person, wanted: str) -> bool:
    return any(normalize(n) == wanted for n in [p.display_name, p.legal_name or "", *decode_aliases(p.aliases)] if n)


def match_name(conn: db.Connection, name: str) -> int | None:
    wanted = normalize(name)
    if not wanted:
        return None
    found: list[Person] = [p for p in conn.orm.scalars(select(Person)).all() if _called(p, wanted)]
    if len(found) > 1:
        found = [p for p in found if p.user_sub is not None]
    return found[0].id if len(found) == 1 else None


def add_alias(conn: db.Connection, person_id: int, printed: str) -> None:
    found = conn.orm.get(Person, person_id)
    if found is None or not printed.strip() or match_name(conn, printed) == person_id:
        return
    found.aliases = encode_aliases([*decode_aliases(found.aliases), printed.strip()])
    conn.orm.flush()


def _new_names(known: list[str], extra: list[str]) -> list[str]:
    have = {normalize(n) for n in known}
    out: list[str] = []
    for n in extra:
        key = normalize(n)
        if key and key not in have:
            have.add(key)
            out.append(n)
    return out


def claim_guest(conn: db.Connection, member_id: int, guest_id: int, today: str) -> Listed:
    me = conn.orm.get(Person, member_id)
    if me is None or me.user_sub is None:
        raise NotAMember()
    guest = conn.orm.get(Person, guest_id)
    if guest is None:
        raise NoSuchGuest()
    if guest.user_sub is not None:
        raise NotAGuest()
    mine = select(SegmentTraveler.segment_id).where(SegmentTraveler.person_id == member_id)
    conn.execute(delete(SegmentTraveler).where(SegmentTraveler.person_id == guest_id, SegmentTraveler.segment_id.in_(mine)))
    conn.execute(update(SegmentTraveler).where(SegmentTraveler.person_id == guest_id).values(person_id=member_id))
    has = select(SegmentRecipient.segment_id).where(SegmentRecipient.person_id == member_id)
    conn.execute(delete(SegmentRecipient).where(SegmentRecipient.person_id == guest_id, SegmentRecipient.segment_id.in_(has)))
    conn.execute(update(SegmentRecipient).where(SegmentRecipient.person_id == guest_id).values(person_id=member_id))
    conn.execute(update(LoyaltyId).where(LoyaltyId.person_id == guest_id).values(person_id=member_id))
    conn.execute(update(Trip).where(Trip.booked_by == guest_id).values(booked_by=member_id))
    conn.execute(update(Segment).where(Segment.booked_by == guest_id).values(booked_by=member_id))
    if not me.legal_name:
        me.legal_name = guest.legal_name
    known = [me.display_name, me.legal_name or "", *decode_aliases(me.aliases)]
    added = _new_names(known, [guest.legal_name or "", *decode_aliases(guest.aliases), guest.display_name])
    me.aliases = encode_aliases([*decode_aliases(me.aliases), *added])
    if not me.first_name:
        me.first_name = guest.first_name
    me.links = json.dumps([*decode_links(me.links), {"guest": guest.display_name, "by": me.display_name, "on": today}],
                          ensure_ascii=False)
    conn.orm.flush()
    conn.execute(delete(Person).where(Person.id == guest_id, Person.user_sub.is_(None)))
    conn.orm.expire_all()
    return listed(me)


def claim_suggestions(conn: db.Connection, member_id: int, sign_in_name: str | None) -> list[Listed]:
    me = conn.orm.get(Person, member_id)
    wanted = normalize(sign_in_name or "")
    if me is None or me.user_sub is None or me.claim_dismissed or not wanted:
        return []
    if visibility.visible_trips(conn, visibility.Viewer(member_id)):
        return []
    found = [p for p in conn.orm.scalars(select(Person).where(Person.user_sub.is_(None))).all() if _called(p, wanted)]
    return [listed(p) for p in sorted(found, key=lambda p: (p.display_name.casefold(), p.id))]


def dismiss_claims(conn: db.Connection, member_id: int) -> None:
    conn.execute(update(Person).where(Person.id == member_id, Person.user_sub.is_not(None)).values(claim_dismissed=True))
