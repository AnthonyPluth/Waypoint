from __future__ import annotations

from sqlalchemy import and_, select, update

from ...storage import db
from ...storage.models import ReviewItem, ScannedMessage
from . import ai, review

TRIES = 3
ROUNDS = 3
CAP = TRIES * ROUNDS
RETRYABLE = ("incomplete", "broken", "no_markup")
LIMITED_STORED_BEFORE_SHORTENING = "The AI service is busy or over its limit. Try again later."
UNANSWERED = (None, ai.BAD_REPLY, ai.TOO_LONG, ai.UNREACHABLE, ai.REFUSED, ai.LIMITED, LIMITED_STORED_BEFORE_SHORTENING, ai.FAILED, ai.ASK_FAILED)
WAITING = "waiting"
READ = "read"


def active(conn: db.Connection) -> bool:
    return ai.mail_config(conn) is not None


def wait(conn: db.Connection, mailbox_id: int, message_id: str) -> None:
    held = conn.execute(select(ReviewItem.suggestion).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)).scalar()
    if held is not None and not review.fixed_suggestions(conn, mailbox_id, message_id):
        return
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)
                 .values(auto_state=WAITING, auto_tries=0))


def next_waiting(conn: db.Connection, mailbox_id: int, passed: set[str]) -> str | None:
    rows = conn.execute(select(ReviewItem.message_id).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.auto_state == WAITING)
                        .order_by(ReviewItem.received.is_(None), ReviewItem.received.desc(), ReviewItem.id.desc())).scalars()
    return next((m for m in rows if m not in passed), None)


def stop_waiting(conn: db.Connection, mailbox_id: int, message_id: str) -> None:
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id,
                                          ReviewItem.auto_state == WAITING).values(auto_state=None))


def failed(conn: db.Connection, mailbox_id: int, message_id: str) -> None:
    tries = conn.execute(select(ReviewItem.auto_tries).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)).scalar()
    if tries is None:
        return
    left = int(tries) + 1
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)
                 .values(auto_tries=left, **({"auto_state": None} if left % TRIES == 0 else {})))


def tries_of(conn: db.Connection, mailbox_id: int, message_id: str) -> int:
    return int(conn.execute(select(ReviewItem.auto_tries).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)).scalar() or 0)


def spent(conn: db.Connection, mailbox_id: int, message_id: str, before: int) -> None:
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)
                 .values(auto_tries=(before // TRIES + 1) * TRIES, auto_state=None))


def stranded(conn: db.Connection, mailbox_id: int, unreadable: str) -> list[tuple[str, str]]:
    rows = list(conn.execute(
        select(ReviewItem.message_id, ReviewItem.reason, ReviewItem.suggestion, ReviewItem.suggestion_error)
        .join(ScannedMessage, and_(ScannedMessage.mailbox_id == ReviewItem.mailbox_id, ScannedMessage.message_id == ReviewItem.message_id))
        .where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.auto_state.is_(None), ReviewItem.reason.in_(RETRYABLE),
               ReviewItem.auto_tries < CAP, ReviewItem.matches.is_(None), ScannedMessage.outcome == unreadable)
        .order_by(ReviewItem.received.is_(None), ReviewItem.received.desc(), ReviewItem.id.desc())))
    return [(r["message_id"], r["reason"]) for r in rows
            if r["suggestion_error"] in UNANSWERED and all(x.get("parsed") for x in review.suggestions_of(r["suggestion"]))]


def queue(conn: db.Connection, mailbox_id: int, message_id: str) -> None:
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id,
                                          ReviewItem.auto_state.is_(None)).values(auto_state=WAITING))


def exempt(conn: db.Connection, mailbox_id: int, message_id: str) -> None:
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id,
                                          ReviewItem.auto_state.is_(None)).values(auto_tries=CAP))
