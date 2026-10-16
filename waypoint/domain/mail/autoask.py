from __future__ import annotations

from sqlalchemy import select, update

from ...storage import db
from ...storage import settings_keys as sk
from ...storage.models import ReviewItem
from . import ai

TRIES = 3
WAITING = "waiting"
READ = "read"
ON = "1"
GAPS = "2"


def chosen(conn: db.Connection) -> bool:
    return db.get_setting(conn, sk.AI_AUTO) in (ON, GAPS)


def fills_gaps(conn: db.Connection) -> bool:
    return ai.config(conn) is not None and db.get_setting(conn, sk.AI_AUTO) == GAPS


def save_choice(conn: db.Connection, on: bool) -> None:
    if not on:
        db.set_setting(conn, sk.AI_AUTO, None)
    elif not chosen(conn):
        db.set_setting(conn, sk.AI_AUTO, GAPS)


def switched_on(conn: db.Connection) -> bool:
    return ai.config(conn) is not None and chosen(conn)


def wait(conn: db.Connection, mailbox_id: int, message_id: str) -> None:
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id,
                                          ReviewItem.suggestion.is_(None))
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
