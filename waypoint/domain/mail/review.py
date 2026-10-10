from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from sqlalchemy import delete, func, or_, select, update

from ...providers import gmail
from ...storage import db, stored_mail
from ...storage.models import IgnoredSender, Mailbox, Person, ReviewItem
from .. import trips, visibility
from ..visibility import Viewer
from . import ai

Reason = Literal["no_markup", "incomplete", "broken", "match"]
UNKNOWN_SENDER = ""


class ItemOut(TypedDict):
    id: int
    address: str
    owner: str
    mine: bool
    sender_domain: str
    subject: str | None
    has_email: bool
    received: str | None
    reason: Reason
    gmail_url: str | None
    suggestion: ai.Suggestion | None
    suggestion_error: str | None


def add(conn: db.Connection, mailbox_id: int, message_id: str, sender_domain: str | None, received: str | None,
        reason: Reason, now: float, held: list[tuple[trips.SegmentIn, list[int]]] | None = None) -> None:
    matches = json.dumps([{"id": n, "booking": b, "candidates": c} for n, (b, c) in enumerate(held, 1)], separators=(",", ":")) if held else None
    db.insert_ignore(conn, ReviewItem, {"mailbox_id": mailbox_id, "message_id": message_id,
                                        "sender_domain": sender_domain or UNKNOWN_SENDER,
                                        "received": received, "reason": reason, "created": now, "matches": matches},
                     key=["mailbox_id", "message_id"])


def is_match(conn: db.Connection, mailbox_id: int, message_id: str) -> bool:
    reason = conn.execute(select(ReviewItem.reason).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)).scalar()
    return bool(reason == "match")


def set_suggestion(conn: db.Connection, mailbox_id: int, message_id: str, suggestion: ai.Suggestion | None,
                   error: str | None) -> None:
    conn.execute(update(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)
                 .values(suggestion=json.dumps(suggestion) if suggestion else None, suggestion_error=error))


def _seen_by(owner: str) -> Any:
    return or_(Mailbox.owner_sub == owner, Mailbox.share_review.is_(True))


def listing(conn: db.Connection, owner: str) -> list[ItemOut]:
    rows = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.message_id, ReviewItem.sender_domain,
                               ReviewItem.received, ReviewItem.reason, Mailbox.address, Mailbox.owner_sub, Person.display_name,
                               ReviewItem.suggestion, ReviewItem.suggestion_error)
                        .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                        .outerjoin(Person, Person.user_sub == Mailbox.owner_sub).where(_seen_by(owner), ReviewItem.reason != "match")
                        .order_by(ReviewItem.received.is_(None), ReviewItem.received.desc(), ReviewItem.id.desc())).fetchall()
    subjects = stored_mail.subjects(conn, (r["mailbox_id"] for r in rows))
    return [{"id": r["id"], "address": r["address"], "owner": r["display_name"] or r["address"], "mine": r["owner_sub"] == owner,
             "sender_domain": r["sender_domain"], "subject": subjects.get((r["mailbox_id"], r["message_id"])),
             "has_email": (r["mailbox_id"], r["message_id"]) in subjects,
             "received": r["received"], "reason": r["reason"],
             "gmail_url": gmail.open_url(r["address"], r["message_id"]) if r["owner_sub"] == owner else None,
             "suggestion": json.loads(r["suggestion"]) if r["suggestion"] else None, "suggestion_error": r["suggestion_error"]}
            for r in rows]


def count(conn: db.Connection, owner: str) -> int:
    return int(conn.execute(select(func.count()).select_from(ReviewItem).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                            .where(_seen_by(owner))).scalar() or 0)


def _mine(conn: db.Connection, owner: str, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.sender_domain)
                       .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, Mailbox.owner_sub == owner)).fetchone()
    return dict(row) if row is not None else None


def locate(conn: db.Connection, owner: str, item_id: int) -> tuple[int, str] | None:
    row = conn.execute(select(ReviewItem.mailbox_id, ReviewItem.message_id).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, Mailbox.owner_sub == owner)).fetchone()
    return (int(row["mailbox_id"]), str(row["message_id"])) if row is not None else None


def _seen_message(conn: db.Connection, owner: str, item_id: int) -> tuple[int, str] | None:
    row = conn.execute(select(ReviewItem.mailbox_id, ReviewItem.message_id).join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.id == item_id, _seen_by(owner))).fetchone()
    return None if row is None else (int(row["mailbox_id"]), str(row["message_id"]))


def stored_email(conn: db.Connection, owner: str, item_id: int) -> tuple[bool, stored_mail.Content | None]:
    found = _seen_message(conn, owner, item_id)
    return (False, None) if found is None else (True, stored_mail.get(conn, *found))


def stored_image(conn: db.Connection, owner: str, item_id: int, index: int) -> stored_mail.Image | None:
    found = _seen_message(conn, owner, item_id)
    return None if found is None else stored_mail.image_of(conn, *found, index)


def dismiss(conn: db.Connection, owner: str, item_id: int, booking: tuple[Viewer, int] | None = None) -> bool:
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
    return list(conn.execute(select(IgnoredSender.domain).where(IgnoredSender.mailbox_id == mailbox_id)).scalars())


class CandidateOut(TypedDict):
    segment_id: int
    trip_id: int
    trip_name: str
    kind: str
    provider: str | None
    origin: str | None
    destination: str | None
    start_local: str
    end_local: str


class BookingOut(TypedDict):
    kind: str
    provider: str | None
    confirmation: str | None
    origin: str | None
    destination: str | None
    start_local: str
    end_local: str


class MatchOut(TypedDict):
    item_id: int
    entry: int
    subject: str | None
    received: str | None
    mine: bool
    booking: BookingOut
    candidates: list[CandidateOut]


def matches(conn: db.Connection, owner: str, viewer: Viewer) -> list[MatchOut]:
    rows = conn.execute(select(ReviewItem.id, ReviewItem.mailbox_id, ReviewItem.message_id, ReviewItem.received, ReviewItem.matches,
                               Mailbox.owner_sub)
                        .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                        .where(_seen_by(owner), ReviewItem.matches.is_not(None))
                        .order_by(ReviewItem.received.is_(None), ReviewItem.received.desc(), ReviewItem.id.desc())).fetchall()
    if not rows:
        return []
    subjects = stored_mail.subjects(conn, (r["mailbox_id"] for r in rows))
    seen = {s.id: s for s in visibility.visible_segments(conn, viewer)}
    names = {t.id: t.name for t in visibility.visible_trips(conn, viewer)}
    out: list[MatchOut] = []
    for r in rows:
        for i, entry in enumerate(json.loads(r["matches"]), 1):
            entry = {"id": i, **entry}
            b = entry["booking"]
            out.append({
                "item_id": r["id"], "entry": entry["id"], "subject": subjects.get((r["mailbox_id"], r["message_id"])), "received": r["received"],
                "mine": r["owner_sub"] == owner,
                "booking": {"kind": b["kind"], "provider": b.get("provider"), "confirmation": b.get("confirmation"),
                            "origin": b.get("origin"), "destination": b.get("destination"),
                            "start_local": b["start_local"], "end_local": b["end_local"]},
                "candidates": [{"segment_id": s.id, "trip_id": s.trip_id, "trip_name": names.get(s.trip_id, ""), "kind": s.kind,
                                "provider": s.provider, "origin": s.origin, "destination": s.destination,
                                "start_local": s.start_local, "end_local": s.end_local}
                               for s in (seen.get(c) for c in entry["candidates"]) if s is not None]})
    return out


def _held(conn: db.Connection, owner: str, item_id: int) -> Any:
    return conn.execute(select(ReviewItem.mailbox_id, ReviewItem.message_id, ReviewItem.reason, ReviewItem.matches)
                        .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                        .where(ReviewItem.id == item_id, _seen_by(owner), ReviewItem.matches.is_not(None))).fetchone()


def _entries(row: Any) -> list[dict[str, Any]]:
    return [{"id": i, **e} for i, e in enumerate(json.loads(row["matches"]), 1)]


def _leave(conn: db.Connection, item_id: int, reason: str, left: list[dict[str, Any]]) -> None:
    if left:
        conn.execute(update(ReviewItem).where(ReviewItem.id == item_id).values(matches=json.dumps(left, separators=(",", ":"))))
    elif reason == "match":
        conn.execute(delete(ReviewItem).where(ReviewItem.id == item_id))
    else:
        conn.execute(update(ReviewItem).where(ReviewItem.id == item_id).values(matches=None))
    stored_mail.prune(conn)


def settle(conn: db.Connection, owner: str, viewer: Viewer, item_id: int, entry_id: int, segment_id: int | None) -> bool:
    row = _held(conn, owner, item_id)
    if row is None:
        return False
    entries = _entries(row)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if entry is None:
        return False
    if segment_id is None:
        added = trips.add_segment(conn, viewer, entry["booking"], source="email")
        if added is None:
            raise trips.Invalid("The booking couldn’t be added")
        target = added["id"]
    else:
        if segment_id not in entry["candidates"]:
            raise trips.Invalid("That isn’t one of the bookings it could be")
        trips.merge_email_segment(conn, viewer, entry["booking"], into=segment_id)
        target = segment_id
    stored_mail.link(conn, target, int(row["mailbox_id"]), str(row["message_id"]))
    _leave(conn, item_id, row["reason"], [e for e in entries if e["id"] != entry_id])
    return True


def drop(conn: db.Connection, owner: str, item_id: int, entry_id: int) -> bool:
    row = _held(conn, owner, item_id)
    if row is None:
        return False
    entries = _entries(row)
    if not any(e["id"] == entry_id for e in entries):
        return False
    _leave(conn, item_id, row["reason"], [e for e in entries if e["id"] != entry_id])
    return True
