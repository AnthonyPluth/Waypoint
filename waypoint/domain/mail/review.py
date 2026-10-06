from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from sqlalchemy import delete, func, or_, select, update

from ...providers import gmail
from ...storage import db, stored_mail
from ...storage.models import IgnoredSender, Mailbox, Person, ReviewItem
from .. import visibility
from ..visibility import Viewer
from . import ai

Reason = Literal["no_markup", "incomplete", "broken"]
UNKNOWN_SENDER = ""


class ItemOut(TypedDict):
    id: int
    address: str
    owner: str
    mine: bool
    sender_domain: str
    subject: str | None
    has_email: bool
    received: str | None
    reason: Reason
    gmail_url: str | None
    suggestion: ai.Suggestion | None
    suggestion_error: str | None


def add(conn: db.Connection, mailbox_id: int, message_id: str, sender_domain: str | None, received: str | None,
        reason: Reason, now: float) -> None:
    db.insert_ignore(conn, ReviewItem, {"mailbox_id": mailbox_id, "message_id": message_id,
                                        "sender_domain": sender_domain or UNKNOWN_SENDER,
                                        "received": received, "reason": reason, "created": now},
                     key=["mailbox_id", "message_id"])


def set_suggestion(conn: db.Connection, mailbox_id: int, message_id: str, suggestion: ai.Suggestion | None,
                   error: str | None) -> None:
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)
                 .values(suggestion=json.dumps(suggestion) if suggestion else None, suggestion_error=error))


def _seen_by(owner: str) -> Any:
    return or_(Mailbox.owner_sub == owner, Mailbox.share_review.is_(True))


def listing(conn: db.Connection, owner: str) -> list[ItemOut]:
    rows = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.message_id, ReviewItem.sender_domain,
                               ReviewItem.received, ReviewItem.reason, Mailbox.address, Mailbox.owner_sub, Person.display_name,
                               ReviewItem.suggestion, ReviewItem.suggestion_error)
                        .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                        .outerjoin(Person, Person.user_sub == Mailbox.owner_sub).where(_seen_by(owner))
                        .order_by(ReviewItem.received.is_(None), ReviewItem.received.desc(), ReviewItem.id.desc())).fetchall()
    subjects = stored_mail.subjects(conn, (r["mailbox_id"] for r in rows))
    return [{"id": r["id"], "address": r["address"], "owner": r["display_name"] or r["address"], "mine": r["owner_sub"] == owner,
             "sender_domain": r["sender_domain"], "subject": subjects.get((r["mailbox_id"], r["message_id"])),
             "has_email": (r["mailbox_id"], r["message_id"]) in subjects,
             "received": r["received"], "reason": r["reason"],
             "gmail_url": gmail.open_url(r["address"], r["message_id"]) if r["owner_sub"] == owner else None,
             "suggestion": json.loads(r["suggestion"]) if r["suggestion"] else None, "suggestion_error": r["suggestion_error"]}
            for r in rows]


def count(conn: db.Connection, owner: str) -> int:
    return int(conn.execute(select(func.count()).select_from(ReviewItem).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                            .where(_seen_by(owner))).scalar() or 0)


def _mine(conn: db.Connection, owner: str, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.sender_domain)
                       .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, Mailbox.owner_sub == owner)).fetchone()
    return dict(row) if row is not None else None


def locate(conn: db.Connection, owner: str, item_id: int) -> tuple[int, str] | None:
    row = conn.execute(select(ReviewItem.mailbox_id, ReviewItem.message_id).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, Mailbox.owner_sub == owner)).fetchone()
    return (int(row["mailbox_id"]), str(row["message_id"])) if row is not None else None


def stored_email(conn: db.Connection, owner: str, item_id: int) -> tuple[bool, stored_mail.Content | None]:
    row = conn.execute(select(ReviewItem.mailbox_id, ReviewItem.message_id).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, _seen_by(owner))).fetchone()
    if row is None:
        return False, None
    return True, stored_mail.get(conn, int(row["mailbox_id"]), str(row["message_id"]))


def dismiss(conn: db.Connection, owner: str, item_id: int, booking: tuple[Viewer, int] | None = None) -> bool:
    seen = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.message_id).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                        .where(ReviewItem.id == item_id, _seen_by(owner))).fetchone()
    if seen is None:
        return False
    if booking is not None and visibility.visible_segment(conn, booking[0], booking[1]) is not None:
        stored_mail.link(conn, booking[1], int(seen["mailbox_id"]), str(seen["message_id"]))
    conn.execute(delete(ReviewItem).where(ReviewItem.id == item_id))
    stored_mail.prune(conn)
    return True


def ignore_sender(conn: db.Connection, owner: str, item_id: int) -> int | None:
    row = _mine(conn, owner, item_id)
    if row is None or row["sender_domain"] == UNKNOWN_SENDER:
        return None
    db.insert_ignore(conn, IgnoredSender, {"mailbox_id": row["mailbox_id"], "domain": row["sender_domain"]},
                     key=["mailbox_id", "domain"])
    left = int(conn.execute(delete(ReviewItem).where(ReviewItem.mailbox_id == row["mailbox_id"],
                                                     ReviewItem.sender_domain == row["sender_domain"])).rowcount)
    stored_mail.prune(conn)
    return left


def ignored(conn: db.Connection, mailbox_id: int) -> list[str]:
    return list(conn.execute(select(IgnoredSender.domain).where(IgnoredSender.mailbox_id == mailbox_id)).scalars())
