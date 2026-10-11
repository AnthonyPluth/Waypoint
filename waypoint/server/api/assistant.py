from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ... import validate
from ...domain import trips, visibility
from ...domain.mail import assist, review
from ..common import ApiError, row_id
from ..contract import (AssistantCreateBody, AssistantDismissBody, AssistantDismissed, AssistantItemDetail,
                        AssistantItems, AssistantMatchBody, AssistantMatched, Segment)
from .mailboxes import owner
from .trips import NO_SEGMENT, NO_TRIP, segment_fields, viewer

NO_ITEM = "No such item"
NOTHING_TO_MATCH = ("This item has no booking Waypoint read to match. Use create_segment_from_review_item to add one, or "
                    "dismiss_review_item if it isn’t travel.")
NOTE_LIMIT = 200
_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")


def _first(q: Mapping[str, list[str]], key: str) -> str | None:
    values = q.get(key) or [""]
    return values[0].strip() or None


def _flag(text: str | None) -> bool | None:
    if text is None:
        return None
    if text.casefold() not in ("true", "false", "1", "0"):
        raise ApiError("has_match must be true or false")
    return validate.on(text.casefold())


def api_assistant_review(conn, q, _b) -> AssistantItems:
    mailbox = _first(q, "mailbox")
    try:
        found = assist.listing(
            conn, owner(), viewer(conn), reason=_first(q, "reason"), kind=_first(q, "kind"),
            mailbox=None if mailbox is None else row_id(mailbox, "mailbox must be a mailbox id from list_review_items", 400),
            has_match=_flag(_first(q, "has_match")), since=_v.day(_first(q, "since"), "since"),
            limit=_v.integer(_first(q, "limit"), "limit", 1, assist.MAX_PAGE) or assist.DEFAULT_PAGE, cursor=_first(q, "cursor"))
    except trips.Invalid as e:
        raise ApiError(str(e)) from None
    return cast(AssistantItems, found)


def api_assistant_review_item(conn, _q, _b, item_id: str) -> AssistantItemDetail:
    found = assist.detail(conn, owner(), viewer(conn), row_id(item_id, NO_ITEM))
    if found is None:
        raise ApiError(NO_ITEM, 404)
    return cast(AssistantItemDetail, found)


def _whole(body: Mapping[str, Any], key: str, missing: str) -> int | None:
    if body.get(key) is None:
        return None
    return row_id(body[key], missing, 400)


def api_assistant_review_match(conn, _q, body: AssistantMatchBody, item_id: str) -> AssistantMatched:
    who, item = viewer(conn), row_id(item_id, NO_ITEM)
    row = review.visible(conn, owner(), item)
    if row is None:
        raise ApiError(NO_ITEM, 404)
    entries = review.entries_of(row)
    if not entries:
        raise ApiError(NOTHING_TO_MATCH)
    entry = _whole(body, "entry", "entry must be a number from get_review_item")
    if entry is None and len(entries) == 1:
        entry = entries[0]["id"]
    if entry is None:
        raise ApiError(f"This message holds {len(entries)} bookings: say which one with entry (1 to {len(entries)})")
    segment, trip = _whole(body, "segment_id", NO_SEGMENT), _whole(body, "trip_id", NO_TRIP)
    if (segment is None) == (trip is None):
        raise ApiError("Give a segment_id to attach the booking to, or a trip_id to add it to, not both and not neither")
    if segment is not None and visibility.visible_segment(conn, who, segment) is None:
        raise ApiError(NO_SEGMENT, 404)
    if trip is not None and visibility.visible_trip(conn, who, trip) is None:
        raise ApiError(NO_TRIP, 404)
    try:
        target = review.settle(conn, owner(), who, item, entry, segment, trip, any_visible=True)
    except trips.Invalid as e:
        raise ApiError(str(e)) from None
    if target is None:
        raise ApiError("That isn’t one of the bookings in this message")
    placed = visibility.visible_segment(conn, who, target)
    return {"ok": True, "segment_id": target, "trip_id": placed.trip_id if placed else 0}


def api_assistant_review_create(conn, _q, body: AssistantCreateBody, item_id: str) -> Segment:
    who, item = viewer(conn), row_id(item_id, NO_ITEM)
    fields = segment_fields(body)
    try:
        added = assist.create(conn, owner(), who, item, _whole(body, "entry", "entry must be a number from get_review_item"), fields)
    except trips.Invalid as e:
        raise ApiError(str(e)) from None
    if added is None:
        raise ApiError(NO_ITEM, 404)
    return Segment(**added)


def api_assistant_review_dismiss(conn, _q, body: AssistantDismissBody, item_id: str) -> AssistantDismissed:
    reason = body.get("reason")
    if reason not in assist.DISMISS_REASONS:
        raise ApiError(f"Give a reason: {', '.join(assist.DISMISS_REASONS)}")
    if body.get("note") is not None and not isinstance(body["note"], str):
        raise ApiError('Send "note" as text')
    _v.text(body.get("note"), "note", NOTE_LIMIT)
    if not review.dismiss(conn, owner(), row_id(item_id, NO_ITEM)):
        raise ApiError(NO_ITEM, 404)
    return {"ok": True, "reason": body["reason"]}
