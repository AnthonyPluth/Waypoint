from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ... import validate
from ...domain import loyalty
from ..common import ApiError, Response, row_id
from ..contract import LoyaltyBody, LoyaltyConflict, LoyaltyEntry, LoyaltyList, Ok, Revealed

NUMBER_LIMIT = 64
TEXT_LIMIT = 100
NOTES_LIMIT = 500
_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")
NO_SUCH = "No such membership"
DUPLICATE = "They already have a membership in that program. Edit that one instead."


def fields(body: Mapping[str, Any], *, need_number: bool) -> loyalty.Fields:
    for key in ("kind", "program", "number", "expiry", "notes"):
        if body.get(key) is not None and not isinstance(body[key], str):
            raise ApiError(f'Send "{key}" as text')
    kind = body.get("kind")
    if kind not in loyalty.KINDS:
        raise ApiError("Choose what kind of membership it is")
    program = _v.text(body.get("program"), "program", TEXT_LIMIT, required=True)
    if program not in loyalty.PROGRAMS[kind]:
        raise ApiError("Choose a program from the list (Other if it isn’t there)")
    person = body.get("person_id")
    if not isinstance(person, int) or isinstance(person, bool):
        raise ApiError("Choose whose it is")
    number = _v.text(body.get("number"), "number", NUMBER_LIMIT, required=need_number)
    expiry = _v.day(body.get("expiry"), "expiry")
    if expiry and kind not in loyalty.EXPIRES:
        raise ApiError("Only Known Traveler and redress numbers expire")
    return {"person_id": person, "kind": kind, "program": program, "number": number,
            "expiry": expiry,
            "notes": _v.text(body.get("notes"), "notes", NOTES_LIMIT)}


def api_loyalty(conn, _q, _b) -> LoyaltyList:
    return {"loyalty": [LoyaltyEntry(**e) for e in loyalty.everyone(conn)],
            "conflicts": [LoyaltyConflict(**c) for c in loyalty.conflicts(conn)],
            "programs": {k: list(p) for k, p in loyalty.PROGRAMS.items()}}


def api_loyalty_add(conn, _q, body: LoyaltyBody) -> LoyaltyEntry:
    try:
        return LoyaltyEntry(**loyalty.add(conn, fields(body, need_number=True)))
    except loyalty.NoSuchPerson:
        raise ApiError("No such person", 404) from None
    except loyalty.Duplicate:
        raise ApiError(DUPLICATE) from None


def api_loyalty_edit(conn, _q, body: LoyaltyBody, loyalty_id) -> LoyaltyEntry:
    try:
        found = loyalty.edit(conn, row_id(loyalty_id, NO_SUCH), fields(body, need_number=False))
    except loyalty.NoSuchPerson:
        raise ApiError("No such person", 404) from None
    except loyalty.Duplicate:
        raise ApiError(DUPLICATE) from None
    if found is None:
        raise ApiError(NO_SUCH, 404)
    return LoyaltyEntry(**found)


def api_loyalty_logo(conn, _q, _b, loyalty_id) -> Response:
    found = loyalty.logo(conn, row_id(loyalty_id, NO_SUCH))
    if found is None:
        raise ApiError(NO_SUCH, 404)
    data, content_type = found
    return Response(data, content_type, cache="private, max-age=86400")


def api_loyalty_remove(conn, _q, _b, loyalty_id) -> Ok:
    if not loyalty.remove(conn, row_id(loyalty_id, NO_SUCH)):
        raise ApiError(NO_SUCH, 404)
    return {"ok": True}


def api_loyalty_reveal(conn, _q, _b, loyalty_id) -> Revealed:
    try:
        number = loyalty.reveal(conn, row_id(loyalty_id, NO_SUCH))
    except loyalty.Unreadable:
        raise ApiError("Waypoint can’t unlock this number with its current key. Enter it again.", 409) from None
    if number is None:
        raise ApiError(NO_SUCH, 404)
    return {"number": number}
