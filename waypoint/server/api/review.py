"""Review: mail Waypoint thought was a booking and couldn't read (visible only to the member whose mailbox it came from,
with Open in Gmail, Ask AI, Add by hand and Ignore this sender), and the names on bookings that aren't matched
to a person yet ("Who is this?": any traveller on a trip the member sees). A message's text is shown only by the preview, to its
mailbox's owner, fetched from Gmail when asked and kept nowhere."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ... import validate
from ...domain import people, trips
import time

from ...domain.mail import ai, review, scan
from ...providers import gmail
from ..common import ApiError, own_session, row_id
from ..contract import Matched, Ok, Preview, Review, ReviewItem, WhoBody
from .mailboxes import owner
from .trips import viewer

NO_ITEM = "No such item"
_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")


def api_review(conn, _q, _b) -> Review:
    """The signed-in member's review items (their own mailboxes' only) and the names on their trips to match to people."""
    return {"items": [cast(ReviewItem, {**i}) for i in review.listing(conn, owner())],
            "who": [{"id": t.id, "name": t.name or "", "segment_id": s["id"], "trip_id": s["trip_id"], "kind": s["kind"],
                     "provider": s["provider"], "origin": s["origin"], "destination": s["destination"],
                     "start_local": s["start_local"], "start_zone": s["start_zone"]}
                    for t, s in trips.unmatched(conn, viewer(conn))],
            "ai": ai.config(conn) is not None}


def api_review_dismiss(conn, _q, _b, item_id: str) -> Ok:
    """Take an item off the queue (once it's added by hand, or when it isn't a booking). Someone else's is a 404."""
    if not review.dismiss(conn, owner(), row_id(item_id, NO_ITEM)):
        raise ApiError(NO_ITEM, 404)
    return {"ok": True}


def api_review_ignore(conn, _q, _b, item_id: str) -> Ok:
    """Stop reviewing the item's sender: later scans skip their mail, and their other items leave the queue."""
    if review.ignore_sender(conn, owner(), row_id(item_id, NO_ITEM)) is None:
        raise ApiError(NO_ITEM, 404)
    return {"ok": True}


def _who(body: Mapping[str, Any]) -> tuple[int | None, str | None]:
    if body.get("person_id") is not None and body.get("new_guest") is not None:
        raise ApiError("Choose a person, or add a guest, not both")
    if body.get("new_guest") is not None and not isinstance(body["new_guest"], str):
        raise ApiError('Send "new_guest" as text')
    guest = _v.text(body.get("new_guest"), "guest’s name", 100)
    person = row_id(body["person_id"], "Choose someone from People", 400) if body.get("person_id") is not None else None
    if person is None and guest is None:
        raise ApiError("Choose someone from People, or add a guest")
    return person, guest


def api_review_who(conn, _q, body: WhoBody, traveler_id: str) -> Matched:
    """Say who a printed name is: a person in People, or a new guest. Every traveller with that printed name on the member's
    trips becomes them, and the name is kept as an alias so later bookings match."""
    person, guest = _who(body)
    who = viewer(conn)
    row = row_id(traveler_id, "No such traveller")
    if not any(t.id == row for t, _ in trips.unmatched(conn, who)):
        raise ApiError("No such traveller", 404)
    if guest is not None:
        person = people.add_guest(conn, {"display_name": guest, "first_name": None, "legal_name": None, "aliases": []})["id"]
    try:
        matched = trips.name_traveler(conn, who, row, person or 0)
    except trips.Invalid as e:
        raise ApiError(str(e)) from e
    if matched is None:
        raise ApiError("No such traveller", 404)
    return {"ok": True, "matched": matched}


GONE = "That message is no longer in Gmail."


@own_session
def api_review_preview(_conn, _q, _b, item_id: str) -> Preview:
    """The item's message as plain text, to read beside the form: fetched from Gmail now, for its mailbox's owner alone, and
    not kept or logged. Someone else's item is a 404."""
    try:
        text, truncated = scan.preview(owner(), row_id(item_id, NO_ITEM))
    except KeyError:
        raise ApiError(NO_ITEM, 404) from None
    except gmail.MessageGone:
        raise ApiError(GONE, 404) from None
    except gmail.GmailError as e:
        raise ApiError(str(e), 502) from e
    return {"text": text, "truncated": truncated}


@own_session
def api_review_suggest(_conn, _q, _b, item_id: str) -> Ok:
    """Ask the optional AI about this item now (the answer, or why there is none, shows on the item). 400 when the AI is off."""
    try:
        scan.suggest_now(owner(), row_id(item_id, NO_ITEM), time.time())
    except KeyError:
        raise ApiError(NO_ITEM, 404) from None
    except scan.NoAi as e:
        raise ApiError(str(e)) from e
    except gmail.MessageGone:
        raise ApiError(GONE, 404) from None
    except gmail.GmailError as e:
        raise ApiError(str(e), 502) from e
    return {"ok": True}
