from __future__ import annotations

from collections.abc import Callable, Sequence

from ... import monitoring
from ...storage import db, gate_codes
from ...storage.stored_mail import Image
from . import ai


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
    if len(found) < 2:
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
    picked = ai.pick_picture(cfg, [image["data"] for image in pictures], timeout)
    if picked is None:
        return False
    with db.session() as conn:
        return gate_codes.keep_chosen(conn, segment_id, mailbox_id, pictures[picked], day, now)
