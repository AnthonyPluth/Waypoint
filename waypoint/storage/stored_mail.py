"""Messages kept while they are needed: the message behind a review item (until it is added or dismissed) and the messages a
booking was made from (as long as the booking exists), so a person can read them without Gmail. What is kept is what the app
shows: the subject, the sender's domain and day, the message as plain text and as the cleaned markup of waypoint/domain/mail/
safe_html.py, cut at a fixed length (waypoint/domain/mail/extract.py makes it). It is one encrypted value (waypoint/storage/
secretbox.py), decrypted only here, so a copy of the database or a backup holds none of it in the clear; the key that unlocks
it is the one that unlocks the Gmail connections.

A message is deleted when nothing holds it any more (`prune`): no review item for it and no booking made from it. A mailbox's
disconnecting, and a booking's removal, take what only they held. Who may read one is decided by what holds it
(waypoint/domain/mail/review.py: the item's viewers; waypoint/domain/trips.py: the booking's viewers), never here."""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, TypedDict

from sqlalchemy import delete, exists, select

from . import db, secretbox
from .models import ReviewItem, SegmentMessage, StoredMessage


class Content(TypedDict):
    subject: str | None
    sender_domain: str | None
    received: str | None          # the day on its Date header
    text: str
    html: str | None              # cleaned markup, when the message had an HTML part
    truncated: bool               # the text or the markup was cut at the limit


def _open(value: str) -> Content | None:
    """The kept content, or None when it can't be unlocked (the key changed) or isn't what was kept."""
    try:
        found = json.loads(secretbox.decrypt(value) or "null")
    except (secretbox.SecretError, ValueError):
        return None
    if not isinstance(found, dict):
        return None
    html = found.get("html")
    return {"subject": found.get("subject") if isinstance(found.get("subject"), str) else None,
            "sender_domain": found.get("sender_domain") if isinstance(found.get("sender_domain"), str) else None,
            "received": found.get("received") if isinstance(found.get("received"), str) else None,
            "text": str(found.get("text") or ""), "html": html if isinstance(html, str) else None,
            "truncated": bool(found.get("truncated"))}


def put(conn: db.Connection, mailbox_id: int, message_id: str, content: Mapping[str, Any], now: float) -> int:
    """Keep a message (again: what was kept is replaced). Returns its row's id."""
    sealed = secretbox.encrypt(json.dumps(dict(content), separators=(",", ":"))) or ""
    db.upsert(conn, StoredMessage, {"mailbox_id": mailbox_id, "message_id": message_id, "content": sealed, "created": now},
              key=["mailbox_id", "message_id"], update=["content"])
    found = conn.execute(select(StoredMessage.id).where(StoredMessage.mailbox_id == mailbox_id, StoredMessage.message_id == message_id)).scalar()
    return int(found)


def get(conn: db.Connection, mailbox_id: int, message_id: str) -> Content | None:
    """A kept message; None when none is kept (or it can't be unlocked)."""
    value = conn.execute(select(StoredMessage.content).where(StoredMessage.mailbox_id == mailbox_id,
                                                              StoredMessage.message_id == message_id)).scalar()
    return _open(value) if value else None


def link(conn: db.Connection, segment_id: int, mailbox_id: int, message_id: str) -> bool:
    """Say a booking was made from (or updated by) a kept message, so it stays as long as the booking does. False: none is kept."""
    stored = conn.execute(select(StoredMessage.id).where(StoredMessage.mailbox_id == mailbox_id,
                                                          StoredMessage.message_id == message_id)).scalar()
    if stored is None:
        return False
    db.insert_ignore(conn, SegmentMessage, {"segment_id": segment_id, "stored_message_id": stored}, key=["segment_id", "stored_message_id"])
    return True


def for_segment(conn: db.Connection, segment_id: int) -> list[Content]:
    """The messages a booking was made from, the newest first (the ones that can't be unlocked are left out)."""
    rows = conn.execute(select(StoredMessage.content).join(SegmentMessage, SegmentMessage.stored_message_id == StoredMessage.id)
                        .where(SegmentMessage.segment_id == segment_id).order_by(StoredMessage.created.desc(), StoredMessage.id.desc())).scalars()
    return [c for c in (_open(v) for v in rows) if c is not None]


def with_messages(conn: db.Connection, segment_ids: Iterable[int]) -> set[int]:
    """Which of these bookings have a message to read."""
    ids = sorted(set(segment_ids))
    if not ids:
        return set()
    return set(conn.execute(select(SegmentMessage.segment_id).where(SegmentMessage.segment_id.in_(ids)).distinct()).scalars())


def prune(conn: db.Connection) -> int:
    """Delete the messages nothing holds: no review item waiting on one, no booking made from it. Returns how many went."""
    held_by_item = exists().where(ReviewItem.mailbox_id == StoredMessage.mailbox_id, ReviewItem.message_id == StoredMessage.message_id)
    held_by_booking = exists().where(SegmentMessage.stored_message_id == StoredMessage.id)
    return int(conn.execute(delete(StoredMessage).where(~held_by_item, ~held_by_booking)).rowcount)
