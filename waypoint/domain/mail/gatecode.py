from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import NamedTuple

from sqlalchemy import func, select

from ... import monitoring
from ...storage import db, gate_codes
from ...storage.models import Segment, SegmentMessage, StoredMessage
from ...storage.stored_mail import Image
from . import ai

REVIEW_CAP = 30


class Linked(NamedTuple):
    mailbox_id: int
    message_id: str
    segments: tuple[int, ...]
    parking: int = 0
    target: int | None = None


def _quietly(work: Callable[[], bool]) -> bool:
    try:
        return work()
    except Exception as e:
        if db.is_busy(e):
            raise
        monitoring.report(e, values=False)
        return False


def settle(segment_id: int, mailbox_id: int, message_id: str, now: float, timeout: float | None = None) -> bool:
    return _quietly(lambda: _settle(segment_id, mailbox_id, message_id, now, timeout))


def settle_linked(linked: Linked | None, now: float, cap: float | None = None) -> bool:
    if linked is None or not linked.segments:
        return False
    try:
        return _settle_linked(linked, now, REVIEW_CAP if cap is None else cap)
    except Exception as e:
        if not db.is_busy(e):
            monitoring.report(e, values=False)
        return False


def settle_pictures(segment_id: int, mailbox_id: int, pictures: Sequence[Image], day: str | None, now: float, timeout: float | None = None) -> bool:
    return _quietly(lambda: _settle_pictures(segment_id, mailbox_id, pictures, day, now, timeout))


def _config(segment_id: int) -> ai.Config | None:
    with db.session() as conn:
        cfg = ai.mail_config(conn)
        return cfg if cfg is not None and gate_codes.waiting(conn, segment_id) else None


def _settle(segment_id: int, mailbox_id: int, message_id: str, now: float, timeout: float | None) -> bool:
    cfg = _config(segment_id)
    if cfg is None:
        return False
    with db.session() as conn:
        stored = gate_codes.stored_id(conn, mailbox_id, message_id)
        found = [] if stored is None else gate_codes.candidates(conn, segment_id, stored)
        opens = gate_codes.opens_choice(conn, segment_id, stored)
    if len(found) < 2 or not opens:
        return False
    picked = ai.pick_picture(cfg, [c.image["data"] for c in found], timeout)
    if picked is None:
        return False
    with db.session() as conn:
        return gate_codes.keep_candidate(conn, segment_id, found[picked], now)


def _settle_pictures(segment_id: int, mailbox_id: int, pictures: Sequence[Image], day: str | None, now: float, timeout: float | None) -> bool:
    if len(pictures) < 2:
        return False
    cfg = _config(segment_id)
    if cfg is None:
        return False
    with db.session() as conn:
        if not gate_codes.opens_unstored(conn, segment_id, day):
            return False
    picked = ai.pick_picture(cfg, [image["data"] for image in pictures], timeout)
    if picked is None:
        return False
    with db.session() as conn:
        return gate_codes.keep_chosen(conn, segment_id, mailbox_id, pictures[picked], day, now)


def parking_linked(conn: db.Connection, mailbox_id: int, message_id: str) -> int:
    return int(conn.execute(select(func.count(func.distinct(SegmentMessage.segment_id)))
                            .join(StoredMessage, StoredMessage.id == SegmentMessage.stored_message_id)
                            .join(Segment, Segment.id == SegmentMessage.segment_id)
                            .where(StoredMessage.mailbox_id == mailbox_id, StoredMessage.message_id == message_id,
                                   Segment.kind == gate_codes.KIND)).scalar() or 0)


def _settle_linked(linked: Linked, now: float, cap: float) -> bool:
    with db.session() as conn:
        parking = [n for n in dict.fromkeys(linked.segments) if gate_codes.is_parking(conn, n)]
        held = parking_linked(conn, linked.mailbox_id, linked.message_id)
    if len(parking) != 1 or max(linked.parking, held) > 1:
        return False
    return _settle(parking[0], linked.mailbox_id, linked.message_id, now, cap)
