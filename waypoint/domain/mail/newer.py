from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...storage import db, stored_mail
from .. import trips
from ..visibility import Viewer

Action = Literal["older", "undated", "newer"]


@dataclass(frozen=True)
class Decision:
    action: Action
    segment_id: int


def decide(conn: db.Connection, viewer: Viewer, fields: trips.SegmentIn, received: str | None, cancels: bool) -> Decision | None:
    try:
        if trips.find_same_booking(conn, viewer, fields) is not None:
            return None
        seg = trips.find_same_reservation(conn, viewer, fields, sure=True)
    except trips.Invalid:
        return None
    if seg is None:
        return None
    dated = [a["received"] for a in stored_mail.attached(conn, seg.id) if a["received"]]
    if not dated:
        return None
    if received is None:
        return Decision("undated", seg.id)
    if received < max(dated):
        return Decision("older", seg.id)
    if received == max(dated) or cancels:
        return None
    return Decision("newer", seg.id)
