from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select

from ...storage import db, stored_mail
from ...storage.models import Segment, SegmentTraveler
from .. import trips, visibility
from ..visibility import Viewer
from . import extract, references

MIN_NAME = 4
GENERIC_NAMES = frozenset({"hotel", "hotels", "stay", "stays", "resort", "resorts", "lodge", "lodging", "travel", "airlines", "airline", "airways", "booking", "bookings", "rental", "rentals", "reservations", "cruise", "cruises", "parking", "trains", "train"})


@dataclass(frozen=True)
class Followed:
    segment_id: int
    new_facts: bool


def _squash(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").casefold())


def _related(domain: str, other: str) -> bool:
    return domain == other or domain.endswith("." + other) or other.endswith("." + domain)


def _labels(domain: str) -> set[str]:
    return {_squash(label) for label in domain.split(".")[:-1] if label}


def _same_sender(conn: db.Connection, segment: Segment, domain: str) -> bool:
    name = _squash(trips.provider_key(segment.provider))
    if len(name) >= MIN_NAME and name not in GENERIC_NAMES and name in _labels(domain):
        return True
    return any(_related(domain, known) for known in stored_mail.senders_for_segment(conn, segment.id))


def _lacks(conn: db.Connection, segment: Segment, facts: frozenset[str]) -> bool:
    stored = trips.decode_details(segment.details)
    seated = conn.execute(select(SegmentTraveler.id).where(SegmentTraveler.segment_id == segment.id, SegmentTraveler.seat.is_not(None))).fetchone() is not None
    for fact in facts:
        key = references.FACT_DETAIL[fact]
        if key is None or not (stored.get(key) or (key == "seat" and seated)):
            return True
    return False


def attach(conn: db.Connection, viewer: Viewer, message: extract.Message) -> Followed | None:
    if message.bookings or message.unread or message.broken or message.revises or not message.sender_domain or not message.found.codes:
        return None
    sharing = [s for s in visibility.visible_segments(conn, viewer) if s.confirmation and references.normal(s.confirmation) in message.found.codes]
    related = [s for s in sharing if _same_sender(conn, s, message.sender_domain)]
    if len(related) != 1:
        return None
    return Followed(related[0].id, _lacks(conn, related[0], message.found.facts))
