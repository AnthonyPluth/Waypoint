from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, update

from ...storage import db
from ...storage import settings_keys as sk
from ...storage.models import Mailbox, ReviewItem
from . import ai

PER_SCAN = 20
PER_DAY = 100
TRIES = 3
WAITING = "waiting"
READ = "read"
ON = "1"


def chosen(conn: db.Connection) -> bool:
    return db.get_setting(conn, sk.AI_AUTO) == ON


def save_choice(conn: db.Connection, on: bool) -> None:
    db.set_setting(conn, sk.AI_AUTO, ON if on else None)


def switched_on(conn: db.Connection) -> bool:
    return ai.config(conn) is not None and chosen(conn)


def wait(conn: db.Connection, mailbox_id: int, message_id: str) -> None:
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id,
                                          ReviewItem.suggestion.is_(None))
                 .values(auto_state=WAITING, auto_tries=0))


def waiting(conn: db.Connection, mailbox_id: int) -> int:
    return int(conn.execute(select(func.count()).select_from(ReviewItem).where(
        ReviewItem.mailbox_id == mailbox_id, ReviewItem.auto_state == WAITING)).scalar() or 0)


def next_waiting(conn: db.Connection, mailbox_id: int, passed: set[str]) -> str | None:
    rows = conn.execute(select(ReviewItem.message_id).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.auto_state == WAITING)
                        .order_by(ReviewItem.received.is_(None), ReviewItem.received.desc(), ReviewItem.id.desc())).scalars()
    return next((m for m in rows if m not in passed), None)


def asked_today(conn: db.Connection, mailbox_id: int, today: date) -> int:
    row = conn.execute(select(Mailbox.ai_day, Mailbox.ai_day_count).where(Mailbox.id == mailbox_id)).fetchone()
    return int(row["ai_day_count"]) if row is not None and row["ai_day"] == today.isoformat() else 0


def count_request(conn: db.Connection, mailbox_id: int, today: date) -> None:
    total = asked_today(conn, mailbox_id, today) + 1
    conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(ai_day=today.isoformat(), ai_day_count=total))


def room(conn: db.Connection, mailbox_id: int, today: date, asked: int) -> int:
    return max(0, min(PER_SCAN - asked, PER_DAY - asked_today(conn, mailbox_id, today)))


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
