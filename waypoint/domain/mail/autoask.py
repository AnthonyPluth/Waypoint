from __future__ import annotations

from sqlalchemy import select, update

from ...storage import db
from ...storage.models import ReviewItem
from . import ai, review

TRIES = 3
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
                 .values(auto_tries=left, **({"auto_state": None} if left >= TRIES else {})))
