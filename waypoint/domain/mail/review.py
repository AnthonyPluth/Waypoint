"""The "Couldn't read" queue: mail that looked like a booking and couldn't be read, and the senders a person stopped
reviewing. Each item belongs to its mailbox's owner and is visible to no one else: every read and change here starts from
the owner (a mailbox that isn't theirs answers as one that isn't there). An item holds the message's id, its sender's
domain, its day and its subject, encrypted (this is one of the places that decrypts, with `waypoint-decrypt`'s
allowance); never the message's text. A person opens the message in Gmail, adds the booking by hand, or ignores the sender."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from sqlalchemy import delete, func, select

from ...providers import gmail
from ...storage import db, secretbox
from ...storage.models import IgnoredSender, Mailbox, ReviewItem

Reason = Literal["no_markup", "incomplete", "broken"]
UNKNOWN_SENDER = ""   # an item's sender domain when the message didn't say


class ItemOut(TypedDict):
    id: int
    address: str                  # the mailbox it came from
    sender_domain: str
    subject: str | None           # None: Waypoint can't unlock it (the key changed)
    received: str | None
    reason: Reason
    gmail_url: str


def add(conn: db.Connection, mailbox_id: int, message_id: str, sender_domain: str | None, subject: str,
        received: str | None, reason: Reason, now: float) -> None:
    """Queue a message for review (once: asking again for a message already there changes nothing)."""
    db.insert_ignore(conn, ReviewItem, {"mailbox_id": mailbox_id, "message_id": message_id,
                                        "sender_domain": sender_domain or UNKNOWN_SENDER,
                                        "subject": secretbox.encrypt(subject) if subject else None,
                                        "received": received, "reason": reason, "created": now},
                     key=["mailbox_id", "message_id"])


def _subject(stored: str | None) -> str | None:
    try:
        return secretbox.decrypt(stored) or ""
    except secretbox.SecretError:
        return None


def listing(conn: db.Connection, owner: str) -> list[ItemOut]:
    """`owner`'s own items, newest message first."""
    rows = conn.execute(select(ReviewItem.id, ReviewItem.message_id, ReviewItem.sender_domain, ReviewItem.subject,
                               ReviewItem.received, ReviewItem.reason, Mailbox.address)
                        .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id).where(Mailbox.owner_sub == owner)
                        .order_by(ReviewItem.received.is_(None), ReviewItem.received.desc(), ReviewItem.id.desc())).fetchall()
    return [{"id": r["id"], "address": r["address"], "sender_domain": r["sender_domain"], "subject": _subject(r["subject"]),
             "received": r["received"], "reason": r["reason"], "gmail_url": gmail.open_url(r["address"], r["message_id"])}
            for r in rows]


def count(conn: db.Connection, owner: str) -> int:
    return int(conn.execute(select(func.count()).select_from(ReviewItem).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                            .where(Mailbox.owner_sub == owner)).scalar() or 0)


def _mine(conn: db.Connection, owner: str, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.sender_domain)
                       .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, Mailbox.owner_sub == owner)).fetchone()
    return dict(row) if row is not None else None


def dismiss(conn: db.Connection, owner: str, item_id: int) -> bool:
    """Take an item off the queue (it was added by hand, or isn't a booking). The message stays remembered as read, so a scan
    doesn't queue it again. False: it isn't `owner`'s, or isn't there."""
    if _mine(conn, owner, item_id) is None:
        return False
    conn.execute(delete(ReviewItem).where(ReviewItem.id == item_id))
    return True


def ignore_sender(conn: db.Connection, owner: str, item_id: int) -> int | None:
    """Stop reviewing this item's sender in its mailbox: later scans skip their mail, and the mailbox's other items from that
    sender leave the queue. Returns how many items left; None: it isn't `owner`'s, or isn't there, or has no sender."""
    row = _mine(conn, owner, item_id)
    if row is None or row["sender_domain"] == UNKNOWN_SENDER:
        return None
    db.insert_ignore(conn, IgnoredSender, {"mailbox_id": row["mailbox_id"], "domain": row["sender_domain"]},
                     key=["mailbox_id", "domain"])
    return int(conn.execute(delete(ReviewItem).where(ReviewItem.mailbox_id == row["mailbox_id"],
                                                     ReviewItem.sender_domain == row["sender_domain"])).rowcount)


def ignored(conn: db.Connection, mailbox_id: int) -> list[str]:
    """The sender domains this mailbox's owner stopped reviewing."""
    return list(conn.execute(select(IgnoredSender.domain).where(IgnoredSender.mailbox_id == mailbox_id)).scalars())
