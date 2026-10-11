from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy import select

from ...storage import db
from ...storage.models import Mailbox, ReviewItem
from . import query, triage
from .review import UNKNOWN_SENDER, Reason

DAYS = 30
TOP_DOMAINS = 10
LAST_SCANS = 10
REASONS: tuple[Reason, ...] = ("no_markup", "incomplete", "broken", "match", "generic")

NO_START = "no start time"
NO_END = "no end time"
NO_PLACE = "no place"
DATES_ONLY = "dates without times"
TIME_UNCLEAR = "time can’t be read"
OTHER = "something else"
GAP_LABELS: tuple[str, ...] = (NO_START, NO_END, NO_PLACE, DATES_ONLY, TIME_UNCLEAR, OTHER)

_LABEL_OF = {
    "departure time": NO_START, "check-in time": NO_START, "pick-up time": NO_START,
    "arrival time": NO_END, "check-out time": NO_END, "drop-off time": NO_END,
    "origin airport": NO_PLACE, "destination airport": NO_PLACE, "hotel name": NO_PLACE, "pick-up place": NO_PLACE,
    "departure station": NO_PLACE, "arrival station": NO_PLACE, "unknown airport": NO_PLACE, "place's time zone unknown": NO_PLACE,
    "dates without times": DATES_ONLY,
    "time isn't a date and time": TIME_UNCLEAR, "time offset doesn't match its place": TIME_UNCLEAR,
}


def gap_label(lack: str) -> str:
    return _LABEL_OF.get(lack, OTHER)


def gap_of(lacks: Iterable[str]) -> str:
    counted = Counter(gap_label(x) for x in lacks)
    return counted.most_common(1)[0][0] if counted else OTHER


class ReasonOut(TypedDict):
    reason: Reason
    waiting: int
    recent: int


class GapOut(TypedDict):
    label: str
    count: int


class DomainOut(TypedDict):
    domain: str
    count: int
    reason: Reason
    item_id: int | None
    known_sender: bool


class ScanOut(TypedDict):
    at: str
    added: int


class GlanceOut(TypedDict):
    waiting: int
    days: int
    reasons: list[ReasonOut]
    gaps: list[GapOut]
    domains: list[DomainOut]
    scans: list[ScanOut]


def _commonest(reasons: Counter[Reason]) -> Reason:
    return max(REASONS, key=lambda r: (reasons[r], -REASONS.index(r)))


def glance(conn: db.Connection, owner: str, mailbox_id: int, now: float) -> GlanceOut | None:
    if conn.execute(select(Mailbox.id).where(Mailbox.id == mailbox_id, Mailbox.owner_sub == owner)).fetchone() is None:
        return None
    rows = conn.execute(select(ReviewItem.id, ReviewItem.sender_domain, ReviewItem.reason, ReviewItem.created, ReviewItem.gap)
                        .where(ReviewItem.mailbox_id == mailbox_id)).fetchall()
    since = now - DAYS * 86400
    by_reason: Counter[str] = Counter(r["reason"] for r in rows)
    recent: Counter[str] = Counter(r["reason"] for r in rows if r["created"] >= since)
    gaps: Counter[str] = Counter(r["gap"] for r in rows if r["reason"] == "incomplete" and r["gap"] in GAP_LABELS)
    by_domain: dict[str, Counter[Reason]] = {}
    newest: dict[str, int] = {}
    for r in rows:
        by_domain.setdefault(r["sender_domain"], Counter())[r["reason"]] += 1
        newest[r["sender_domain"]] = max(newest.get(r["sender_domain"], 0), r["id"])
    ranked = sorted(by_domain, key=lambda d: (-by_domain[d].total(), d))[:TOP_DOMAINS]
    scans: Counter[float] = Counter(r["created"] for r in rows if r["created"] >= since)
    return {
        "waiting": len(rows), "days": DAYS,
        "reasons": [{"reason": r, "waiting": by_reason[r], "recent": recent[r]} for r in REASONS if by_reason[r]],
        "gaps": [{"label": label, "count": gaps[label]} for label in sorted(gaps, key=lambda g: (-gaps[g], GAP_LABELS.index(g)))],
        "domains": [{"domain": d, "count": by_domain[d].total(), "reason": _commonest(by_domain[d]),
                     "item_id": None if d == UNKNOWN_SENDER else newest[d],
                     "known_sender": triage.sender_in(d, query.SENDERS)} for d in ranked],
        "scans": [{"at": datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds"), "added": scans[t]}
                  for t in sorted(scans, reverse=True)[:LAST_SCANS]],
    }
