from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ... import validate
from ...domain import people, trips
import time

from ...domain.mail import ai, review, scan
from ...providers import gmail
from ...storage import db
from ..common import NO_IMAGE, ApiError, Response, image_response, own_session, position, row_id
from ..contract import Matched, MatchBody, Ok, Preview, Review, ReviewItem, ReviewMatch, WhoBody
from .mailboxes import owner
from .trips import viewer

NO_ITEM = "No such item"
_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")


def api_review(conn, _q, _b) -> Review:
    gmail.end_lapsed(conn)
    return {"items": [cast(ReviewItem, {**i}) for i in review.listing(conn, owner())],
            "matches": [cast(ReviewMatch, {**m}) for m in review.matches(conn, owner(), viewer(conn))],
            "who": [{"id": t.id, "name": t.name or "", "segment_id": s["id"], "trip_id": s["trip_id"], "kind": s["kind"],
                     "provider": s["provider"], "origin": s["origin"], "destination": s["destination"],
                     "start_local": s["start_local"], "start_zone": s["start_zone"]}
                    for t, s in trips.unmatched(conn, viewer(conn))],
            "ai": ai.config(conn) is not None}


def api_review_dismiss(conn, _q, _b, item_id: str) -> Ok:
    held = (_q.get("entry") or [""])[0]
    if held:
        if not review.drop(conn, owner(), row_id(item_id, NO_ITEM), row_id(held, "No such booking", 400)):
            raise ApiError(NO_ITEM, 404)
        return {"ok": True}
    added = (_q.get("segment") or [""])[0]
    booking = (viewer(conn), row_id(added, "No such segment", 400)) if added else None
    if not review.dismiss(conn, owner(), row_id(item_id, NO_ITEM), booking):
        raise ApiError(NO_ITEM, 404)
    return {"ok": True}


def api_review_match(conn, _q, body: MatchBody, item_id: str) -> Ok:
    entry = body.get("entry")
    if not isinstance(entry, int) or isinstance(entry, bool):
        raise ApiError('Send "entry" as a whole number')
    segment = body.get("segment_id")
    chosen = None if segment is None else row_id(segment, "No such booking", 400)
    try:
        settled = review.settle(conn, owner(), viewer(conn), row_id(item_id, NO_ITEM), entry, chosen)
    except trips.Invalid as e:
        raise ApiError(str(e)) from e
    if not settled:
        raise ApiError(NO_ITEM, 404)
    return {"ok": True}


def api_review_ignore(conn, _q, _b, item_id: str) -> Ok:
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


NOT_KEPT = "This message wasn’t kept. Its owner can open it in Gmail."


def _preview(kept: Mapping[str, Any]) -> Preview:
    return {"subject": kept["subject"], "text": kept["text"], "html": kept["html"], "truncated": kept["truncated"],
            "original": kept["original"], "images": kept["images"]}


@own_session
def api_review_preview(_conn, _q, _b, item_id: str) -> Preview:
    item = row_id(item_id, NO_ITEM)
    with db.session() as conn:
        visible, kept = review.stored_email(conn, owner(), item)
    if not visible:
        raise ApiError(NO_ITEM, 404)
    if kept is not None:
        return _preview(kept)
    try:
        shown = scan.preview(owner(), item)
    except KeyError:
        raise ApiError(NOT_KEPT, 404) from None
    except gmail.MessageGone:
        raise ApiError(GONE, 404) from None
    except gmail.GmailError as e:
        raise ApiError(str(e), 502) from e
    return _preview(shown)


def api_review_image(conn, _q, _b, item_id: str, index: str) -> Response:
    found = review.stored_image(conn, owner(), row_id(item_id, NO_IMAGE), position(index))
    if found is None:
        raise ApiError(NO_IMAGE, 404)
    return image_response(found)


@own_session
def api_review_suggest(_conn, _q, _b, item_id: str) -> Ok:
    try:
        scan.suggest_now(owner(), row_id(item_id, NO_ITEM), time.time())
    except KeyError:
        raise ApiError(NO_ITEM, 404) from None
    except (scan.NoAi, scan.NotAskable) as e:
        raise ApiError(str(e)) from e
    except gmail.MessageGone:
        raise ApiError(GONE, 404) from None
    except gmail.GmailError as e:
        raise ApiError(str(e), 502) from e
    return {"ok": True}
