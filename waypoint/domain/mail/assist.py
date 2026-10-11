from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any, Literal, TypedDict

from sqlalchemy import select

from ...storage import db, stored_mail
from ...storage.models import Person, Segment
from .. import trips, visibility
from ..visibility import Viewer
from . import review

Confidence = Literal["exact", "likely", "possible"]
RANK: dict[str, int] = {"exact": 3, "likely": 2, "possible": 1}
REASONS = ("no_markup", "incomplete", "broken", "match", "generic")
DISMISS_REASONS = ("not_travel", "duplicate", "already_added", "other")
DEFAULT_PAGE = 20
MAX_PAGE = 50
MAX_FIELD = 200
MAX_TEXT = 20_000
MAX_EMAILS = 5
SHOWN_DETAILS = tuple(k for k in trips.DETAIL_KEYS if k not in ("notes", trips.TIME_UNKNOWN, "address", "phone"))
NOT_KEPT = "This message wasn’t kept."


class Verdict(TypedDict):
    confidence: Confidence
    agreed: list[str]
    differed: list[str]


class MatchOut(TypedDict):
    segment_id: int
    trip_id: int
    confidence: Confidence


class ItemOut(TypedDict):
    id: int
    mailbox_id: int
    mine: bool
    sender_domain: str
    reason: str
    status: str | None
    kind: str | None
    received: str | None
    has_email: bool
    bookings: int
    match: MatchOut | None


class ItemsOut(TypedDict):
    items: list[ItemOut]
    total: int
    not_shown: int
    next: str | None


class ParsedOut(TypedDict):
    kind: str | None
    status: str | None
    provider: str | None
    confirmation: str | None
    origin: str | None
    destination: str | None
    address: str | None
    phone: str | None
    start_local: str | None
    start_zone: str | None
    end_local: str | None
    end_zone: str | None
    details: dict[str, str]
    travelers: list[str]
    read: dict[str, str]


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
    confidence: Confidence
    agreed: list[str]
    differed: list[str]


class EntryOut(TypedDict):
    entry: int
    booking: ParsedOut
    candidates: list[CandidateOut]


class DetailOut(ItemOut):
    entries: list[EntryOut]
    suggestion: ParsedOut | None


class EmailOut(TypedDict):
    subject: str | None
    sender_domain: str | None
    received: str | None
    text: str
    truncated: bool
    kept: Literal["original", "plain text"]


def _same_code(a: str, b: str) -> bool:
    return trips._code_key(a) == trips._code_key(b)


def _same_provider(a: str, b: str) -> bool:
    return trips.provider_key(a) == trips.provider_key(b)


def _same_place(a: str, b: str) -> bool:
    return trips._text_key(a) == trips._text_key(b) or trips._same_place(a, b)


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _overlap(booking: Mapping[str, Any], seg: Segment) -> bool | None:
    first, last = _day(booking.get("start_local")), _day(booking.get("end_local"))
    mine, theirs = _day(seg.start_local), _day(seg.end_local)
    if first is None or last is None or mine is None or theirs is None:
        return None
    return first <= theirs and mine <= last


def judge(booking: Mapping[str, Any], seg: Segment) -> Verdict:
    agreed: list[str] = []
    differed: list[str] = []

    def compare(name: str, said: Any, held: str | None, same: Callable[[str, str], bool]) -> None:
        if isinstance(said, str) and said.strip() and held:
            (agreed if same(said, held) else differed).append(name)

    compare("kind", booking.get("kind"), seg.kind, lambda a, b: a == b)
    compare("confirmation", booking.get("confirmation"), seg.confirmation, _same_code)
    compare("provider", booking.get("provider"), seg.provider, _same_provider)
    compare("origin", booking.get("origin"), seg.origin, _same_place)
    compare("destination", booking.get("destination"), seg.destination, _same_place)
    together = _overlap(booking, seg)
    if together is not None:
        (agreed if together else differed).append("dates")
    if "confirmation" in agreed and not differed:
        confidence: Confidence = "exact"
    elif "confirmation" in agreed or ("dates" in agreed and len(agreed) >= 3 and not differed):
        confidence = "likely"
    else:
        confidence = "possible"
    return {"confidence": confidence, "agreed": agreed, "differed": differed}


def _clip(value: Any, limit: int = MAX_FIELD) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _names(conn: db.Connection, bookings: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    wanted = {int(t["person_id"]) for b in bookings for t in b.get("travelers") or [] if isinstance(t.get("person_id"), int)}
    if not wanted:
        return {}
    return {int(r["id"]): str(r["display_name"]) for r in conn.execute(select(Person.id, Person.display_name).where(Person.id.in_(wanted))).fetchall()}


def parsed(booking: Mapping[str, Any], names: Mapping[int, str], read: Mapping[str, str] | None = None) -> ParsedOut:
    given = booking.get("details")
    held: Mapping[str, Any] = given if isinstance(given, dict) else {}

    def pick(key: str) -> str | None:
        return _clip(held.get(key) if held.get(key) is not None else booking.get(key), trips.ADDRESS_LIMIT if key == "address" else MAX_FIELD)

    travelers = []
    for t in booking.get("travelers") or []:
        name = _clip(t.get("name")) or names.get(t.get("person_id") if isinstance(t.get("person_id"), int) else -1)
        if name:
            travelers.append(name)
    return {"kind": _clip(booking.get("kind")), "status": _clip(booking.get("status")), "provider": _clip(booking.get("provider")),
            "confirmation": _clip(booking.get("confirmation")), "origin": _clip(booking.get("origin")),
            "destination": _clip(booking.get("destination")), "address": pick("address"), "phone": pick("phone"),
            "start_local": _clip(booking.get("start_local")), "start_zone": _clip(booking.get("start_zone")),
            "end_local": _clip(booking.get("end_local")), "end_zone": _clip(booking.get("end_zone")),
            "details": {k: v for k in SHOWN_DETAILS if (v := pick(k))}, "travelers": travelers[:20],
            "read": {str(k)[:40]: str(v)[:40] for k, v in (read or {}).items()}}


class _Loaded(TypedDict):
    row: Any
    entries: list[dict[str, Any]]
    suggestion: dict[str, Any] | None


def _load(row: Any) -> _Loaded:
    suggestion = json.loads(row["suggestion"]) if row["suggestion"] else None
    return {"row": row, "entries": review.entries_of(row), "suggestion": suggestion if isinstance(suggestion, dict) else None}


def _rank(entries: Sequence[EntryOut]) -> MatchOut | None:
    best: MatchOut | None = None
    for e in entries:
        for c in e["candidates"]:
            if best is None or RANK[c["confidence"]] > RANK[best["confidence"]]:
                best = {"segment_id": c["segment_id"], "trip_id": c["trip_id"], "confidence": c["confidence"]}
    return best


def _entries(conn: db.Connection, viewer: Viewer, loaded: Sequence[_Loaded]) -> dict[int, list[EntryOut]]:
    if not any(item["entries"] for item in loaded):
        return {}
    seen = {s.id: s for s in visibility.visible_segments(conn, viewer)}
    trip_names = {t.id: t.name for t in visibility.visible_trips(conn, viewer)}
    names = _names(conn, [e["booking"] for item in loaded for e in item["entries"]])
    out: dict[int, list[EntryOut]] = {}
    for item in loaded:
        out[int(item["row"]["id"])] = [
            {"entry": int(e["id"]), "booking": parsed(e["booking"], names),
             "candidates": [{"segment_id": s.id, "trip_id": s.trip_id, "trip_name": (trip_names.get(s.trip_id) or "")[:MAX_FIELD], "kind": s.kind,
                             "provider": s.provider, "origin": s.origin, "destination": s.destination,
                             "start_local": s.start_local, "end_local": s.end_local, **judge(e["booking"], s)}
                            for s in (seen.get(c) for c in e["candidates"]) if s is not None]}
            for e in item["entries"]]
    return out


def _summary(item: _Loaded, entries: Sequence[EntryOut], owner: str, has_email: bool) -> ItemOut:
    row = item["row"]
    first = entries[0]["booking"] if entries else None
    kind = first["kind"] if first else (_clip(item["suggestion"].get("kind")) if item["suggestion"] else None)
    return {"id": int(row["id"]), "mailbox_id": int(row["mailbox_id"]), "mine": row["owner_sub"] == owner,
            "sender_domain": str(row["sender_domain"])[:MAX_FIELD], "reason": str(row["reason"]), "status": first["status"] if first else None,
            "kind": kind, "received": row["received"], "has_email": has_email, "bookings": len(entries) or (1 if item["suggestion"] else 0),
            "match": _rank(entries)}


def _key(row: Any) -> tuple[bool, str, int]:
    return (row["received"] is not None, row["received"] or "", int(row["id"]))


def _cursor(key: tuple[bool, str, int]) -> str:
    return json.dumps(list(key), separators=(",", ":")).encode().hex()


def _after(cursor: str) -> tuple[bool, str, int]:
    try:
        flag, received, last = json.loads(bytes.fromhex(cursor))
        if isinstance(flag, bool) and isinstance(received, str) and isinstance(last, int) and not isinstance(last, bool):
            return flag, received, last
    except (ValueError, TypeError):
        pass
    raise trips.Invalid("That cursor isn’t one Waypoint gave out. Start again without it.")


def listing(conn: db.Connection, owner: str, viewer: Viewer, *, reason: str | None = None, kind: str | None = None, mailbox: int | None = None,
            has_match: bool | None = None, since: str | None = None, limit: int = DEFAULT_PAGE, cursor: str | None = None) -> ItemsOut:
    if reason is not None and reason not in REASONS:
        raise trips.Invalid(f"reason must be one of {', '.join(REASONS)}")
    if kind is not None and kind not in trips.KINDS:
        raise trips.Invalid(f"kind must be one of {', '.join(trips.KINDS)}")
    rows = sorted(review.pending(conn, owner), key=_key, reverse=True)
    rows = [r for r in rows if (reason is None or r["reason"] == reason) and (mailbox is None or r["mailbox_id"] == mailbox)
            and (since is None or (r["received"] is not None and r["received"] >= since))]
    loaded = [_load(r) for r in rows]
    entries = _entries(conn, viewer, loaded)
    kept = stored_mail.held(conn, (r["mailbox_id"] for r in rows))
    summaries = [(_key(i["row"]), _summary(i, entries.get(int(i["row"]["id"]), []), owner, (i["row"]["mailbox_id"], i["row"]["message_id"]) in kept))
                 for i in loaded]
    summaries = [(k, s) for k, s in summaries if (kind is None or s["kind"] == kind) and (has_match is None or (s["match"] is not None) == has_match)]
    if cursor:
        after = _after(cursor)
        summaries = [(k, s) for k, s in summaries if k < after]
    page = summaries[:max(1, min(limit, MAX_PAGE))]
    left = len(summaries) - len(page)
    return {"items": [s for _, s in page], "total": len(summaries), "not_shown": left, "next": _cursor(page[-1][0]) if left and page else None}


def detail(conn: db.Connection, owner: str, viewer: Viewer, item_id: int) -> DetailOut | None:
    row = review.visible(conn, owner, item_id)
    if row is None:
        return None
    item = _load(row)
    entries = _entries(conn, viewer, [item]).get(item_id, [])
    kept = (row["mailbox_id"], row["message_id"]) in stored_mail.held(conn, [row["mailbox_id"]])
    suggestion = None
    if item["suggestion"] is not None:
        sources = item["suggestion"].get("sources")
        suggestion = parsed(item["suggestion"], {}, sources if isinstance(sources, dict) else None)
    return {**_summary(item, entries, owner, kept), "entries": entries, "suggestion": suggestion}


def _emailed(kept: stored_mail.Content) -> EmailOut:
    return {"subject": _clip(kept["subject"], MAX_FIELD * 2), "sender_domain": kept["sender_domain"], "received": kept["received"],
            "text": kept["text"][:MAX_TEXT], "truncated": kept["truncated"] or len(kept["text"]) > MAX_TEXT,
            "kept": "original" if kept["original"] else "plain text"}


def email_of_item(conn: db.Connection, owner: str, item_id: int) -> EmailOut | None:
    seen, kept = review.stored_email(conn, owner, item_id)
    if not seen:
        return None
    if kept is None:
        raise trips.Invalid(NOT_KEPT)
    return _emailed(kept)


def emails_of_segment(conn: db.Connection, viewer: Viewer, segment_id: int) -> list[EmailOut] | None:
    found = trips.emails_of(conn, viewer, segment_id)
    return None if found is None else [_emailed(k) for k in found[:MAX_EMAILS]]


def _from_suggestion(suggestion: Mapping[str, Any]) -> trips.SegmentIn:
    out: trips.SegmentIn = {}
    for key in ("kind", "provider", "confirmation", "origin", "destination", "start_local", "end_local", "start_zone", "end_zone"):
        if suggestion.get(key):
            out[key] = suggestion[key]
    details = {k: suggestion[k] for k in ("address", "phone", "room", "ship", "deck") if suggestion.get(k)}
    if details:
        out["details"] = details
    return out


def create(conn: db.Connection, owner: str, viewer: Viewer, item_id: int, entry_id: int | None, overrides: trips.SegmentIn) -> trips.SegmentOut | None:
    row = review.visible(conn, owner, item_id)
    if row is None:
        return None
    entries = review.entries_of(row)
    base: trips.SegmentIn = {}
    entry: dict[str, Any] | None = None
    if entries:
        if entry_id is None and len(entries) > 1:
            raise trips.Invalid(f"This message holds {len(entries)} bookings: say which one with entry (1 to {len(entries)})")
        entry = next((e for e in entries if entry_id is None or e["id"] == entry_id), None)
        if entry is None:
            raise trips.Invalid("That isn’t one of the bookings in this message")
        base = entry["booking"]
    elif row["suggestion"]:
        suggestion = json.loads(row["suggestion"])
        base = _from_suggestion(suggestion) if isinstance(suggestion, dict) else {}
    fields: trips.SegmentIn = {**base, **overrides}
    if "details" in overrides:
        fields["details"] = {**(base.get("details") or {}), **overrides["details"]}
    added = trips.add_segment(conn, viewer, fields, source="email" if entry is not None else "manual")
    if added is None:
        raise trips.Invalid("The booking couldn’t be added")
    if entry is not None:
        review.finish_entry(conn, row, int(entry["id"]), added["id"])
    else:
        review.dismiss(conn, owner, item_id, (viewer, added["id"]))
    return trips.get_segment(conn, viewer, added["id"]) or added
