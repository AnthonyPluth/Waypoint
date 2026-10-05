"""People: everyone who travels. A member is a signed-in household member, linked to their sign-in (`user_sub`) and made
the first time they sign in; a guest has no login (a child, a grandparent) and is added, renamed and removed by any
member. Everyone is visible to every member (AGENTS.md, "IDs are for the household"). A person's names: the display name
the app shows, their first name, their legal name as on an ID, and the aliases an airline prints for them
("DOE/JANE MS"), which later bookings are matched against. A member who was already a guest (a booking's passenger was
matched to a guest before they signed in) claims that guest, "This is me": the guest's trips, numbers and names move to the
member and the guest is gone."""
from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from sqlalchemy import delete, select, update

from ..storage import db
from ..storage.models import LoyaltyId, Person, Segment, SegmentTraveler, Trip
from . import visibility


class Fields(TypedDict):
    """What a person's page edits: already checked and trimmed (waypoint/server/api/people.py)."""
    display_name: str
    first_name: str | None
    legal_name: str | None
    aliases: list[str]


class Link(TypedDict):
    """A guest a member claimed: the guest's name, the member who claimed it and the day (YYYY-MM-DD)."""
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
    """Only guests are removed: a member goes with their login."""


class NotAMember(Exception):
    """Only a signed-in member claims a guest, and only for themselves."""


class NoSuchGuest(Exception):
    """There's no one by that id to claim."""


class NotAGuest(Exception):
    """The person to claim is a member: members aren't merged."""


def decode_aliases(raw: str | None) -> list[str]:
    """The aliases stored in a row (a JSON list of texts); anything else reads as none."""
    try:
        found = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [a for a in found if isinstance(a, str)] if isinstance(found, list) else []


def encode_aliases(aliases: list[str]) -> str | None:
    return json.dumps(aliases, ensure_ascii=False) if aliases else None


def decode_links(raw: str | None) -> list[Link]:
    """The guests a member claimed, as stored (a JSON list of objects); anything else reads as none."""
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
    """Members first, then guests, each by name."""
    found = conn.orm.scalars(select(Person)).all()
    return [listed(p) for p in sorted(found, key=lambda p: (p.user_sub is None, p.display_name.casefold(), p.id))]


def person_for_sub(conn: db.Connection, sub: str) -> int | None:
    """The person a sign-in belongs to (made at their first sign-in), or None."""
    return conn.orm.scalars(select(Person.id).where(Person.user_sub == sub)).first()


def existing(conn: db.Connection, ids: list[int]) -> dict[int, str]:
    """The display name of each of these people that exists."""
    return dict(conn.execute(select(Person.id, Person.display_name).where(Person.id.in_(ids))).fetchall())


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


# ------------------------------------------------------------------------------------------------ matching names

TITLES = frozenset({"mr", "mrs", "ms", "miss", "mstr", "master", "mx", "dr", "prof", "sir", "lady"})


def normalize(name: str) -> str:
    """A name as people and airlines write it, in one form to compare: no case, no titles, no punctuation, first name
    first ("DOE/JANE MS" and "Jane Doe" are both "jane doe")."""
    text = name.casefold()
    if "/" in text:   # an airline's LAST/FIRST MIDDLE TITLE
        last, _, first = text.partition("/")
        text = f"{first} {last}"
    return " ".join(t for t in re.split(r"\W+", text) if t and t not in TITLES)


def _called(p: Person, wanted: str) -> bool:
    """Whether this person's display name, legal name or an alias is the (normalized) name."""
    return any(normalize(n) == wanted for n in [p.display_name, p.legal_name or "", *decode_aliases(p.aliases)] if n)


def match_name(conn: db.Connection, name: str) -> int | None:
    """The one person whose display name, legal name or an alias is this name (as printed on a booking). None when no one
    is, or when more than one person is (a booking never guesses between two people), except that a member beats a guest
    who has the same name."""
    wanted = normalize(name)
    if not wanted:
        return None
    found: list[Person] = [p for p in conn.orm.scalars(select(Person)).all() if _called(p, wanted)]
    if len(found) > 1:   # a member wins over a guest with the same name (who they are is known); two members, or two guests, don't
        found = [p for p in found if p.user_sub is not None]
    return found[0].id if len(found) == 1 else None


def add_alias(conn: db.Connection, person_id: int, printed: str) -> None:
    """Remember how a booking printed someone's name, so later bookings match them, unless it already would."""
    found = conn.orm.get(Person, person_id)
    if found is None or not printed.strip() or match_name(conn, printed) == person_id:
        return
    found.aliases = encode_aliases([*decode_aliases(found.aliases), printed.strip()])
    conn.orm.flush()


# ------------------------------------------------------------------------------------------------ claiming a guest

def _new_names(known: list[str], extra: list[str]) -> list[str]:
    """Those of `extra` that aren't already one of `known` in the same normalized form (nor repeated among themselves)."""
    have = {normalize(n) for n in known}
    out: list[str] = []
    for n in extra:
        key = normalize(n)
        if key and key not in have:
            have.add(key)
            out.append(n)
    return out


def claim_guest(conn: db.Connection, member_id: int, guest_id: int, today: str) -> Listed:
    """The member says a guest is them: everything on the guest moves to the member in one transaction (the caller's), and
    the guest is deleted. Segment travellers, loyalty IDs and who booked trips and segments move over (someone already on
    the same segment isn't added twice); the guest's legal name and aliases, and the display name as a way to match it, are
    added to the member's names; the member's own display and first names stay unless empty. The merge is kept in the
    member's `links` for People to show. Raises NotAMember (the claimer has no login), NoSuchGuest and NotAGuest."""
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
    """The guests this member may be, to offer after sign-in ("Are you one of these?"): only while they have no trips and
    haven't said "None of these", and only guests whose display name, legal name or an alias is the sign-in's name."""
    me = conn.orm.get(Person, member_id)
    wanted = normalize(sign_in_name or "")
    if me is None or me.user_sub is None or me.claim_dismissed or not wanted:
        return []
    if visibility.visible_trips(conn, visibility.Viewer(member_id)):
        return []
    found = [p for p in conn.orm.scalars(select(Person).where(Person.user_sub.is_(None))).all() if _called(p, wanted)]
    return [listed(p) for p in sorted(found, key=lambda p: (p.display_name.casefold(), p.id))]


def dismiss_claims(conn: db.Connection, member_id: int) -> None:
    """"None of these": the member isn't offered the suggestion again."""
    conn.execute(update(Person).where(Person.id == member_id, Person.user_sub.is_not(None)).values(claim_dismissed=True))
