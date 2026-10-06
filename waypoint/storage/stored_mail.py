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
    received: str | None
    text: str
    html: str | None
    truncated: bool


def _open(value: str) -> Content | None:
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
    sealed = secretbox.encrypt(json.dumps(dict(content), separators=(",", ":"))) or ""
    subject = content.get("subject")
    db.upsert(conn, StoredMessage, {"mailbox_id": mailbox_id, "message_id": message_id, "content": sealed, "created": now,
                                    "subject": secretbox.encrypt(subject) if isinstance(subject, str) else None},
              key=["mailbox_id", "message_id"], update=["content", "subject"])
    found = conn.execute(select(StoredMessage.id).where(StoredMessage.mailbox_id == mailbox_id, StoredMessage.message_id == message_id)).scalar()
    return int(found)


def get(conn: db.Connection, mailbox_id: int, message_id: str) -> Content | None:
    value = conn.execute(select(StoredMessage.content).where(StoredMessage.mailbox_id == mailbox_id,
                                                              StoredMessage.message_id == message_id)).scalar()
    return _open(value) if value else None


def subjects(conn: db.Connection, mailbox_ids: Iterable[int]) -> dict[tuple[int, str], str | None]:
    ids = sorted(set(mailbox_ids))
    if not ids:
        return {}
    found: dict[tuple[int, str], str | None] = {}
    for r in conn.execute(select(StoredMessage.mailbox_id, StoredMessage.message_id, StoredMessage.subject)
                          .where(StoredMessage.mailbox_id.in_(ids))).fetchall():
        try:
            found[(int(r["mailbox_id"]), str(r["message_id"]))] = secretbox.decrypt(r["subject"]) if r["subject"] else None
        except secretbox.SecretError:
            found[(int(r["mailbox_id"]), str(r["message_id"]))] = None
    return found


def link(conn: db.Connection, segment_id: int, mailbox_id: int, message_id: str) -> bool:
    stored = conn.execute(select(StoredMessage.id).where(StoredMessage.mailbox_id == mailbox_id,
                                                          StoredMessage.message_id == message_id)).scalar()
    if stored is None:
        return False
    db.insert_ignore(conn, SegmentMessage, {"segment_id": segment_id, "stored_message_id": stored}, key=["segment_id", "stored_message_id"])
    return True


def for_segment(conn: db.Connection, segment_id: int) -> list[Content]:
    rows = conn.execute(select(StoredMessage.content).join(SegmentMessage, SegmentMessage.stored_message_id == StoredMessage.id)
                        .where(SegmentMessage.segment_id == segment_id).order_by(StoredMessage.created.desc(), StoredMessage.id.desc())).scalars()
    return [c for c in (_open(v) for v in rows) if c is not None]


def with_messages(conn: db.Connection, segment_ids: Iterable[int]) -> set[int]:
    ids = sorted(set(segment_ids))
    if not ids:
        return set()
    return set(conn.execute(select(SegmentMessage.segment_id).where(SegmentMessage.segment_id.in_(ids)).distinct()).scalars())


def prune(conn: db.Connection) -> int:
    held_by_item = exists().where(ReviewItem.mailbox_id == StoredMessage.mailbox_id, ReviewItem.message_id == StoredMessage.message_id)
    held_by_booking = exists().where(SegmentMessage.stored_message_id == StoredMessage.id)
    return int(conn.execute(delete(StoredMessage).where(~held_by_item, ~held_by_booking)).rowcount)
