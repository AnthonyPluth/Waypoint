from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from ... import validate
from ...domain import people
from ..common import ApiError, _current, row_id
from ..contract import ClaimSuggestions, Ok, People, Person, PersonBody

NAME_LIMIT = 100
MAX_ALIASES = 20
_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")


def fields(body: Mapping[str, Any]) -> people.Fields:
    raw = body.get("aliases")
    if raw is None:
        raw = []
    if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
        raise ApiError('Send "aliases" as a list of texts')
    if len(raw) > MAX_ALIASES:
        raise ApiError(f"Add at most {MAX_ALIASES} aliases")
    aliases: list[str] = []
    for a in raw:
        kept = _v.text(a, "alias", NAME_LIMIT)
        if kept and kept not in aliases:
            aliases.append(kept)
    for key in ("display_name", "first_name", "legal_name"):
        if key in body and body[key] is not None and not isinstance(body[key], str):
            raise ApiError(f'Send "{key}" as text')
    return {"display_name": _v.text(body.get("display_name"), "name", NAME_LIMIT, required=True) or "",
            "first_name": _v.text(body.get("first_name"), "first name", NAME_LIMIT),
            "legal_name": _v.text(body.get("legal_name"), "legal name", NAME_LIMIT * 2),
            "aliases": aliases}


def signed_in_member(conn) -> tuple[int | None, str | None]:
    user = getattr(_current, "user", None) or {}
    sub = user.get("sub")
    if user.get("local") or not sub:
        return None, None
    return people.person_for_sub(conn, str(sub)), user.get("name")


def api_people(conn, _q, _b) -> People:
    return {"people": [Person(**p) for p in people.everyone(conn)]}


def api_person_add(conn, _q, body: PersonBody) -> Person:
    return Person(**people.add_guest(conn, fields(body)))


def api_person_edit(conn, _q, body: PersonBody, person_id) -> Person:
    found = people.edit(conn, row_id(person_id, "No such person"), fields(body))
    if found is None:
        raise ApiError("No such person", 404)
    return Person(**found)


def api_person_remove(conn, _q, _b, person_id) -> Ok:
    try:
        if not people.remove_guest(conn, row_id(person_id, "No such person")):
            raise ApiError("No such person", 404)
    except people.MemberRemoval:
        raise ApiError("A member can’t be removed here: they’re part of the household because they sign in.", 409) from None
    return {"ok": True}


def api_person_claim(conn, _q, _b, person_id) -> Person:
    member, _ = signed_in_member(conn)
    if member is None:
        raise ApiError("Sign in as a household member to link a guest to yourself.", 403)
    try:
        return Person(**people.claim_guest(conn, member, row_id(person_id, "No such person"), date.today().isoformat()))
    except people.NoSuchGuest:
        raise ApiError("No such person", 404) from None
    except people.NotAGuest:
        raise ApiError("That person is a household member, not a guest.", 409) from None
    except people.NotAMember:
        raise ApiError("Sign in as a household member to link a guest to yourself.", 403) from None


def api_claim_suggestions(conn, _q, _b) -> ClaimSuggestions:
    member, name = signed_in_member(conn)
    found = people.claim_suggestions(conn, member, name) if member is not None else []
    return {"guests": [Person(**g) for g in found]}


def api_claim_dismiss(conn, _q, _b) -> Ok:
    member, _ = signed_in_member(conn)
    if member is not None:
        people.dismiss_claims(conn, member)
    return {"ok": True}
