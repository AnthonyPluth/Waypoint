"""The "Couldn't read" queue: mail that looked like a booking and couldn't be read, and the senders a person stopped
reviewing. Each item belongs to its mailbox's owner and is visible to no one else, unless the owner shares that mailbox
with the household (`Mailbox.share_review`, off until they say): then every member sees its items and can add the booking
by hand or dismiss them, while what reads the owner's Gmail or changes the owner's scan (the preview, asking the AI,
ignoring a sender, Open in Gmail) stays the owner's. Every read and change here starts from the person asking (an item
that isn't theirs to see answers as one that isn't there). An item holds the message's id, its sender's
domain and its day. The message itself (its subject and text) is kept, encrypted, while the item waits
(waypoint/storage/stored_mail.py), for everyone who sees the item to read beside the form; it is deleted when the item is
dismissed, unless a booking was made from it (the booking keeps it). A person opens the message in Gmail, adds the booking by
hand, or ignores the sender."""
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
UNKNOWN_SENDER = ""   # an item's sender domain when the message didn't say


class ItemOut(TypedDict):
    id: int
    address: str                  # the mailbox it came from
    owner: str                    # whose mailbox it is (their name in People)
    mine: bool                    # it is the asking member's own: the rest are shared with them by their owner
    sender_domain: str
    subject: str | None           # the message's subject, when the message was kept
    has_email: bool               # the message is kept: it can be read here
    received: str | None
    reason: Reason
    gmail_url: str | None         # opens the message in its owner's Gmail: none for someone else's
    suggestion: ai.Suggestion | None         # what the optional AI read from it, for the person to confirm or edit
    suggestion_error: str | None             # why it gave none, in fixed text


def add(conn: db.Connection, mailbox_id: int, message_id: str, sender_domain: str | None, received: str | None,
        reason: Reason, now: float) -> None:
    """Queue a message for review (once: asking again for a message already there changes nothing)."""
    db.insert_ignore(conn, ReviewItem, {"mailbox_id": mailbox_id, "message_id": message_id,
                                        "sender_domain": sender_domain or UNKNOWN_SENDER,
                                        "received": received, "reason": reason, "created": now},
                     key=["mailbox_id", "message_id"])


def set_suggestion(conn: db.Connection, mailbox_id: int, message_id: str, suggestion: ai.Suggestion | None,
                   error: str | None) -> None:
    """Keep what the AI made of a queued message: the booking's fields it read, or why it gave none. Never the message's
    text, nor the AI's reply as it came."""
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)
                 .values(suggestion=json.dumps(suggestion) if suggestion else None, suggestion_error=error))


def _seen_by(owner: str) -> Any:
    """What `owner` may see: their own mailboxes' items, and the items of mailboxes whose owners share them."""
    return or_(Mailbox.owner_sub == owner, Mailbox.share_review.is_(True))


def listing(conn: db.Connection, owner: str) -> list[ItemOut]:
    """The items `owner` may see (their own, and those of mailboxes shared with the household), newest message first."""
    rows = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.message_id, ReviewItem.sender_domain,
                               ReviewItem.received, ReviewItem.reason, Mailbox.address, Mailbox.owner_sub, Person.display_name,
                               ReviewItem.suggestion, ReviewItem.suggestion_error)
                        .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                        .outerjoin(Person, Person.user_sub == Mailbox.owner_sub).where(_seen_by(owner))
                        .order_by(ReviewItem.received.is_(None), ReviewItem.received.desc(), ReviewItem.id.desc())).fetchall()
    subjects = stored_mail.subjects(conn, (r["mailbox_id"] for r in rows))   # (not the messages: a list opens none of them)
    return [{"id": r["id"], "address": r["address"], "owner": r["display_name"] or r["address"], "mine": r["owner_sub"] == owner,
             "sender_domain": r["sender_domain"], "subject": subjects.get((r["mailbox_id"], r["message_id"])),
             "has_email": (r["mailbox_id"], r["message_id"]) in subjects,
             "received": r["received"], "reason": r["reason"],
             "gmail_url": gmail.open_url(r["address"], r["message_id"]) if r["owner_sub"] == owner else None,
             "suggestion": json.loads(r["suggestion"]) if r["suggestion"] else None, "suggestion_error": r["suggestion_error"]}
            for r in rows]


def count(conn: db.Connection, owner: str) -> int:
    """How many items `owner` may see."""
    return int(conn.execute(select(func.count()).select_from(ReviewItem).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                            .where(_seen_by(owner))).scalar() or 0)


def _mine(conn: db.Connection, owner: str, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.sender_domain)
                       .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, Mailbox.owner_sub == owner)).fetchone()
    return dict(row) if row is not None else None


def locate(conn: db.Connection, owner: str, item_id: int) -> tuple[int, str] | None:
    """The mailbox and Gmail message id of one of `owner`'s own items, to fetch it again; None when it isn't theirs (or isn't
    there)."""
    row = conn.execute(select(ReviewItem.mailbox_id, ReviewItem.message_id).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, Mailbox.owner_sub == owner)).fetchone()
    return (int(row["mailbox_id"]), str(row["message_id"])) if row is not None else None


def stored_email(conn: db.Connection, owner: str, item_id: int) -> tuple[bool, stored_mail.Content | None]:
    """Whether `owner` may see this item (their own, or one shared with the household), and its message as kept (None when it
    wasn't kept: an item from before messages were, or one whose key was lost)."""
    row = conn.execute(select(ReviewItem.mailbox_id, ReviewItem.message_id).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, _seen_by(owner))).fetchone()
    if row is None:
        return False, None
    return True, stored_mail.get(conn, int(row["mailbox_id"]), str(row["message_id"]))


def dismiss(conn: db.Connection, owner: str, item_id: int, booking: tuple[Viewer, int] | None = None) -> bool:
    """Take an item off the queue (it was added by hand, or isn't a booking), one `owner` may see: their own, or one its owner
    shares with the household. The message stays remembered as read, so a scan doesn't queue it again. Its kept copy goes with
    it, unless `booking` (who is asking, and the booking they added from it) was made from it: then the booking keeps the
    message for as long as it exists (only if the asker can see that booking). False: it isn't one of those, or isn't there."""
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
    """Stop reviewing this item's sender in its mailbox: later scans skip their mail, and the mailbox's other items from that
    sender leave the queue. Returns how many items left; None: it isn't `owner`'s, or isn't there, or has no sender."""
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
    """The sender domains this mailbox's owner stopped reviewing."""
    return list(conn.execute(select(IgnoredSender.domain).where(IgnoredSender.mailbox_id == mailbox_id)).scalars())
