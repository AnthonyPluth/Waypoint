from __future__ import annotations

import itertools
import json
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, select, update

from ... import dates, monitoring
from ...providers import gmail, mailimages
from ...storage import db, gate_codes, stored_mail
from ...storage.models import Mailbox, ReviewItem, ScannedMessage
from ...storage.stored_mail import Content
from .. import airports, loyalty, people, trips
from ..visibility import Viewer
from . import ai, autoask, extract, followup, glance, ingest, query, review, triage
from .booking import Passenger

State = Literal["done", "failed", "not_started", "busy"]
BOOKING, UNREADABLE, SKIPPED, FOLLOW_UP = "booking", "unreadable", "skipped", "follow-up"
IGNORED = review.IGNORED
BUDGET = 1200
_clock = time.monotonic
MAX_CHAIN = 12
LOCAL = "local"
OVERLAP_DAYS = 2
TOKEN_LIFE = 2400
FAILED_GENERALLY = "Something went wrong while reading this mailbox. Waypoint will try again; the details are in its log."
NO_PERSON = "Waypoint doesn’t know who this mailbox’s owner is yet. They sign in once, then it scans."
GONE = "That mailbox isn’t connected."


@dataclass(frozen=True)
class Result:
    state: State
    error: str | None = None
    messages: int = 0
    bookings: int = 0
    review: int = 0
    found: int = 0
    skipped: int = 0
    capped: bool = False


@dataclass(frozen=True)
class Summary:
    found: int
    read: int
    bookings: int
    review: int
    skipped: int
    capped: bool
    labels_dropped: int = 0
    triaged: int = 0
    total: int = 0
    not_travel: int = 0
    followups: int = 0
    with_facts: int = 0
    attached: int = 0
    ai_asked: int = 0


_running: set[int] = set()
_lock = threading.Lock()
_filing = threading.Lock()
_notices: dict[int, str] = {}
_reading: dict[int, str] = {}


def running(mailbox_id: int) -> bool:
    with _lock:
        return mailbox_id in _running


def notice(mailbox_id: int) -> str | None:
    with _lock:
        return _notices.get(mailbox_id)


def reading_again(mailbox_id: int) -> str | None:
    with _lock:
        return _reading.get(mailbox_id)


def scan(mailbox_id: int, now: float, today: date, again: bool = False, backfill: bool = False, sender: str | None = None) -> Result:
    with _lock:
        if mailbox_id in _running:
            return Result("busy")
        _running.add(mailbox_id)
        if sender:
            _reading[mailbox_id] = sender
    try:
        result = _scan(mailbox_id, now, today, again, backfill)
    finally:
        with _lock:
            _running.discard(mailbox_id)
            _reading.pop(mailbox_id, None)
    with _lock:
        if result.state == "not_started" and result.error:
            _notices[mailbox_id] = result.error
        elif result.state != "busy":
            _notices.pop(mailbox_id, None)
    return result


def encode(found: Summary) -> str:
    return json.dumps({"found": found.found, "read": found.read, "bookings": found.bookings, "review": found.review,
                       "skipped": found.skipped, "capped": found.capped, "labels_dropped": found.labels_dropped,
                       "triaged": found.triaged, "total": found.total, "not_travel": found.not_travel,
                       "followups": found.followups, "with_facts": found.with_facts, "attached": found.attached,
                       "ai_asked": found.ai_asked}, separators=(",", ":"))


def decode(text: str | None) -> Summary | None:
    try:
        raw = json.loads(text) if text else None
    except ValueError:
        return None
    counts = ("found", "read", "bookings", "review", "skipped")
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), int) and not isinstance(raw.get(k), bool) for k in counts) \
            or not isinstance(raw.get("capped"), bool):
        return None
    extra = [raw.get(k, 0) for k in ("labels_dropped", "triaged", "total", "not_travel", "followups", "with_facts", "attached", "ai_asked")]
    return Summary(raw["found"], raw["read"], raw["bookings"], raw["review"], raw["skipped"], raw["capped"],
                   *(n if isinstance(n, int) and not isinstance(n, bool) else 0 for n in extra))


def decode_labels(text: str | None) -> list[str]:
    try:
        raw = json.loads(text) if text else []
    except ValueError:
        return []
    return [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []


def encode_labels(ids: list[str]) -> str | None:
    return json.dumps(list(dict.fromkeys(ids)), separators=(",", ":")) if ids else None


def summary(mailbox_id: int) -> Summary | None:
    with db.session() as conn:
        return decode(conn.execute(select(Mailbox.scan_summary).where(Mailbox.id == mailbox_id)).scalar())


def remember(mailbox_id: int, found: Summary) -> None:
    with db.session() as conn:
        conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(scan_summary=encode(found)))


def forget(mailbox_id: int) -> None:
    with _lock:
        _notices.pop(mailbox_id, None)


def _viewer(owner: str, conn: db.Connection) -> Viewer | None:
    if owner == LOCAL:
        return Viewer(None, household=True)
    person = people.person_for_sub(conn, owner)
    return Viewer(person) if person is not None else None


def _since(last_scan: float | None, today: date) -> date:
    if last_scan is None:
        return dates.add_months(today, -query.LOOKBACK_MONTHS)
    return datetime.fromtimestamp(last_scan, UTC).date() - timedelta(days=OVERLAP_DAYS)


def _unread(mailbox_id: int, pages: Iterable[list[str]], filtering: bool, tally: Counter[str]) -> Iterator[str]:
    for page in pages:
        tally["found"] += len(page)
        seen: set[str] = set()
        for start in range(0, len(page) if filtering else 0, gmail.SEARCH_PAGE):
            with db.session() as conn:
                seen.update(conn.execute(select(ScannedMessage.message_id).where(
                    ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.message_id.in_(page[start:start + gmail.SEARCH_PAGE]))).scalars())
        fresh = [m for m in page if m not in seen]
        tally["pending"] += len(fresh)
        yield from fresh


def _ignores(ignored: list[str], domain: str | None) -> bool:
    return bool(domain) and any(domain == d or (domain or "").endswith("." + d) for d in ignored)


def _record(conn: db.Connection, mailbox_id: int, message_id: str, outcome: str, now: float, sender_domain: str | None = None,
            segment_id: int | None = None) -> None:
    db.insert_ignore(conn, ScannedMessage, {"mailbox_id": mailbox_id, "message_id": message_id, "outcome": outcome,
                                            "scanned": now, "sender_domain": sender_domain, "segment_id": segment_id},
                     key=["mailbox_id", "message_id"])


def keep_message(mailbox_id: int, message_id: str, raw: dict[str, Any], segments: list[int], now: float) -> Content:
    content, images = extract.keep(raw, mailimages.Fetcher())
    with db.session() as conn:
        stored_mail.put(conn, mailbox_id, message_id, content, now, images)
        for segment_id in segments:
            stored_mail.link(conn, segment_id, mailbox_id, message_id)
    return content


def _keep_quietly(mailbox_id: int, message_id: str, raw: dict[str, Any], segments: list[int], now: float) -> None:
    try:
        keep_message(mailbox_id, message_id, raw, segments, now)
    except Exception as e:
        if db.is_busy(e):
            raise
        monitoring.report(e, values=False)


def keep_code(mailbox_id: int, segment_id: int, raw: dict[str, Any], now: float) -> None:
    with db.session() as conn:
        if not gate_codes.is_parking(conn, segment_id):
            return
    content, images = extract.keep(raw, mailimages.Fetcher())
    with db.session() as conn:
        gate_codes.offer(conn, segment_id, mailbox_id, images, content["received"], now)


def _keep_code_quietly(mailbox_id: int, segment_id: int, raw: dict[str, Any], now: float) -> None:
    try:
        keep_code(mailbox_id, segment_id, raw, now)
    except Exception as e:
        if db.is_busy(e):
            raise
        monitoring.report(e, values=False)


def _file(conn: db.Connection, mailbox_id: int, viewer: Viewer, message_id: str, message: extract.Message,
          ignored: list[str], now: float, why: Counter[str] | None = None, again: bool = False,
          backfill: bool = False, strong: bool = True, follow: list[followup.Followed] | None = None,
          joined: list[int] | None = None, gaps: list[str] | None = None) -> tuple[int, int, list[int] | None, str | None]:
    why = Counter() if why is None else why
    if again:
        conn.execute(delete(ScannedMessage).where(ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.message_id == message_id))
    if _ignores(ignored, message.sender_domain):
        _record(conn, mailbox_id, message_id, IGNORED, now, message.sender_domain)
        return 0, 0, None, None
    conn.execute(delete(ReviewItem).where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id,
                                         ReviewItem.reason == "generic"))
    made, failed = 0, 0
    touched: list[int] = []
    held: list[ingest.Held] = []
    lacks: list[str] = []
    for booking in message.bookings:
        filed = ingest.file_booking(conn, viewer, booking, again, touched, backfill, held)
        if filed is None:
            failed += 1
            lacks.append(ingest.explain(conn, booking))
            why[lacks[-1]] += 1
        elif filed == "attached":
            if joined is not None:
                joined.append(1)
        elif filed not in ("unchanged", "ambiguous"):
            made += 1
        if gaps is not None and filed in ("added", "updated", "unchanged", "attached") and ingest.lacks_details(booking) and message_id not in gaps:
            gaps.append(message_id)
    usable = len(message.bookings) - failed
    queued = 0
    if failed or message.unread or not usable:
        attached = followup.attach(conn, viewer, message)
        if attached is None and not strong and not message.bookings and not message.unread and not message.markup:
            return made, 0, None, SKIPPED
        if attached is not None:
            if follow is not None:
                follow.append(attached)
            return made, 0, None, FOLLOW_UP
        why.update(message.gaps)
        if not message.bookings and not message.unread:
            why["no structured booking data" if not message.other_markup else "structured data, but no reservation"] += 1
        reason: review.Reason = "broken" if message.broken else "incomplete" if message.markup or message.bookings else "no_markup"
        review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, reason, now, held,
                   reference=message.found.reference, gap=glance.gap_of(lacks + list(message.gaps)) if reason == "incomplete" else None)
        if not usable and (strong or message.markup or message.bookings) and autoask.switched_on(conn):
            autoask.wait(conn, mailbox_id, message_id)
        queued = 1
    elif held:
        review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, "match", now, held)
        queued = 1
    return made, queued, list(dict.fromkeys(touched)) if queued or touched else None, BOOKING if usable else UNREADABLE


UNREAD_WITH_SUGGESTION = "Something else in this email couldn’t be read. Add it by hand if you need it."
SUGGESTION_FAILED = "The AI couldn’t be asked just now. The details are in Waypoint’s log."
NO_AI = "Turn on AI suggestions in Settings first."


class NoAi(Exception):
    pass


class NotAskable(Exception):
    pass


HOLDS_BOOKINGS = "This item holds bookings to settle, not a message to read."
READ_ALREADY = "Waypoint already read this one: check what it found."


def _again(owner: str, item_id: int) -> tuple[int, str, dict[str, Any]]:
    with db.session() as conn:
        found = review.locate(conn, owner, item_id)
        if found is None:
            raise KeyError(item_id)
        token = gmail.access_token(conn, found[0], time.time())
    return found[0], found[1], gmail.fetch(token, found[1])


def preview(owner: str, item_id: int) -> Content:
    mailbox_id, message_id, raw = _again(owner, item_id)
    return keep_message(mailbox_id, message_id, raw, [], time.time())


def suggest_now(owner: str, item_id: int, now: float) -> None:
    with db.session() as conn:
        found = review.seen_message(conn, owner, item_id)
        if found is None:
            raise KeyError(item_id)
        mailbox_id, message_id, mine = found
        if review.is_match(conn, mailbox_id, message_id):
            raise NotAskable(HOLDS_BOOKINGS)
        if review.is_generic(conn, mailbox_id, message_id):
            raise NotAskable(READ_ALREADY)
        if ai.config(conn) is None:
            raise NoAi(NO_AI)
        kept = None if mine else stored_mail.get(conn, mailbox_id, message_id)
        token = None if mine or kept is not None else gmail.access_token(conn, mailbox_id, time.time())
    if kept is not None:
        _ask(mailbox_id, message_id, kept["text"], now)
    elif token is not None:
        _suggest(mailbox_id, message_id, gmail.fetch(token, message_id), now)
    else:
        _suggest(mailbox_id, message_id, _again(owner, item_id)[2], now)


def _read(cfg: ai.Config, text: str, known: tuple[str, ...], timeout: float | None = None) -> tuple[list[ai.Suggestion], str | None, bool]:
    try:
        reading = ai.suggest(cfg, text, known, timeout)
        return reading.bookings, reading.error, False
    except ai.AiError as e:
        return [], str(e), str(e) != ai.NO_BOOKING and not e.retried
    except Exception as e:
        monitoring.report(e, values=False)
        return [], SUGGESTION_FAILED, True


def _suggest(mailbox_id: int, message_id: str, raw: dict[str, Any], now: float) -> None:
    content = keep_message(mailbox_id, message_id, raw, [], now)
    _ask(mailbox_id, message_id, content["text"], now)


def _ask(mailbox_id: int, message_id: str, text: str, now: float) -> None:
    with db.session() as conn:
        cfg = ai.config(conn)
        known = tuple(loyalty.known_numbers(conn)) if cfg else ()
        asking = not review.is_match(conn, mailbox_id, message_id)
    if cfg is None or not asking:
        return
    suggestions, error, _ = _read(cfg, text, known)
    with db.session() as conn:
        _file_ai(conn, mailbox_id, message_id, suggestions, error, False, now)


def _ai_fields(conn: db.Connection, s: ai.Suggestion) -> trips.SegmentIn | None:
    kind = s.get("kind")
    if not kind or not all(s.get(key) for key in ("confirmation", "origin", "start_local", "end_local")):
        return None
    if kind in ("flight", "train", "car") and not s.get("destination"):
        return None
    first, last = s.get("start_zone"), s.get("end_zone")
    if kind == "flight":
        if not s.get("flight_number"):
            return None
        a, b = airports.lookup(conn, s["origin"]), airports.lookup(conn, s["destination"])
        first, last = a["zone"] if a else None, b["zone"] if b else None
    if not first or not (last or kind in ("hotel", "parking")):
        return None
    fields: trips.SegmentIn = {"kind": kind, "status": "confirmed", "provider": s.get("provider"), "confirmation": s["confirmation"],
                              "origin": s["origin"], "destination": s.get("destination"), "start_local": s["start_local"],
                              "end_local": s["end_local"], "start_zone": first, "end_zone": last or first,
                              "details": {k: s[k] for k in ("address", "phone", "room", "ship", "deck", "flight_number", "cabin") if s.get(k)}}
    if travelers := s.get("travelers"):
        fields["travelers"] = [{**person, "seat": traveler["seat"]} for person, traveler in
                               zip(ingest.travelers(conn, tuple(Passenger(t["name"]) for t in travelers)), travelers, strict=True)]
    if s.get("price_minor") is not None and s.get("price_currency"):
        fields["price"] = {"amount_minor": s["price_minor"], "currency": s["price_currency"]}
    try:
        trips.check(conn, fields)
        trips.check_price(fields.get("price"))
    except trips.Invalid:
        return None
    return fields


def _file_ai(conn: db.Connection, mailbox_id: int, message_id: str, suggestions: list[ai.Suggestion], error: str | None,
             auto: bool | None, now: float) -> tuple[int, int]:
    row = conn.execute(select(ReviewItem.id, ReviewItem.sender_domain, ReviewItem.received, ReviewItem.matches, Mailbox.owner_sub)
                       .join(Mailbox, Mailbox.id == ReviewItem.mailbox_id)
                       .where(ReviewItem.mailbox_id == mailbox_id, ReviewItem.message_id == message_id)).fetchone()
    viewer = _viewer(row["owner_sub"], conn) if row else None
    if row is None or viewer is None or row["matches"]:
        return 0, 0
    pending: list[ai.Suggestion] = []
    touched: list[int] = []
    held: list[ingest.Held] = []
    added = 0
    for suggestion in suggestions:
        fields = _ai_fields(conn, suggestion)
        if fields is None:
            pending.append(suggestion)
            continue
        candidates: list[int] = []
        try:
            outcome = trips.merge_email_segment(conn, viewer, fields, touched=touched, candidates=candidates)
        except trips.Invalid:
            pending.append(suggestion)
            continue
        if outcome == "ambiguous":
            held.append((fields, candidates))
        elif outcome != "unchanged":
            added += 1
    for segment_id in touched:
        stored_mail.link(conn, segment_id, mailbox_id, message_id)
    if held:
        matches = json.dumps([{"id": n, "booking": b, "candidates": c} for n, (b, c) in enumerate(held, 1)], separators=(",", ":"))
        conn.execute(update(ReviewItem).where(ReviewItem.id == row["id"]).values(reason="incomplete" if pending or error else "match", matches=matches))
    if pending or error or held or not suggestions:
        review.set_suggestions(conn, mailbox_id, message_id, pending, error, auto=auto)
        return added, 0
    else:
        review.dismiss(conn, row["owner_sub"], row["id"], (viewer, touched))
        conn.execute(update(ScannedMessage).where(ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.message_id == message_id)
                     .values(outcome=BOOKING, scanned=now, segment_id=touched[0] if touched else None))
        return added, 1


def _fill_gaps(token: Callable[[], str], started: float, viewer: Viewer, message_ids: list[str]) -> int:
    asked = 0
    for message_id in message_ids:
        with db.session() as conn:
            cfg = ai.config(conn)
            if cfg is None or not autoask.chosen(conn):
                return asked
            known = tuple(loyalty.known_numbers(conn))
        left = BUDGET - (_clock() - started)
        if left <= 0:
            return asked
        try:
            raw = gmail.fetch(token(), message_id)
        except gmail.GmailError:
            continue
        asked += 1
        suggestions, _, _ = _read(cfg, extract.plain_text(raw), known, left)
        if not suggestions:
            continue
        with db.session() as conn:
            for suggestion in suggestions:
                fields = _ai_fields(conn, suggestion)
                if fields is None:
                    continue
                try:
                    same = trips.find_same_reservation(conn, viewer, fields, sure=True)
                    if same is not None:
                        trips.merge_email_segment(conn, viewer, fields, fill_only=True, into=same.id)
                except trips.Invalid:
                    continue
    return asked


def _ask_waiting(mailbox_id: int, token: Callable[[], str], started: float) -> tuple[int, int, int]:
    asked = made = cleared = 0
    passed: set[str] = set()
    while True:
        with db.session() as conn:
            cfg = ai.config(conn)
            if cfg is None or not autoask.chosen(conn):
                return asked, made, cleared
            message_id = autoask.next_waiting(conn, mailbox_id, passed)
            known = tuple(loyalty.known_numbers(conn))
        if message_id is None:
            return asked, made, cleared
        passed.add(message_id)
        try:
            raw = gmail.fetch(token(), message_id)
        except gmail.MessageGone:
            with db.session() as conn:
                autoask.stop_waiting(conn, mailbox_id, message_id)
            continue
        except gmail.GmailError:
            continue
        left = BUDGET - (_clock() - started)
        if left <= 0:
            return asked, made, cleared
        asked += 1
        suggestions, error, failed = _read(cfg, extract.plain_text(raw), known, left)
        with db.session() as conn:
            added, removed = _file_ai(conn, mailbox_id, message_id, suggestions, error, None if failed else True, time.time())
            made, cleared = made + added, cleared + removed
            if failed:
                autoask.failed(conn, mailbox_id, message_id)
            else:
                autoask.stop_waiting(conn, mailbox_id, message_id)


def _fail(mailbox_id: int, text: str, partial: tuple[int, int, int]) -> Result:
    with db.session() as conn:
        conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(scan_error=text))
    return Result("failed", text, *partial)


def _scan(mailbox_id: int, now: float, today: date, again: bool = False, backfill: bool = False) -> Result:
    with db.session() as conn:
        row = conn.execute(select(Mailbox.owner_sub, Mailbox.address, Mailbox.history_id, Mailbox.last_scan, Mailbox.scan_labels)
                           .where(Mailbox.id == mailbox_id)).fetchone()
        if row is None:
            return Result("not_started", GONE)
        viewer = _viewer(row["owner_sub"], conn)
        if viewer is None:
            return Result("not_started", NO_PERSON)
        try:
            token = gmail.access_token(conn, mailbox_id, now)
        except gmail.GmailError as e:
            return Result("not_started", str(e))
        ignored = review.ignored(conn, mailbox_id)
    history, last_scan = row["history_id"], row["last_scan"]
    read = made = queued = skipped = dropped = handled = not_travel = followups = with_facts = attached = asked_by_ai = 0
    gaps: list[str] = []
    with db.session() as conn:
        filling = not again and not backfill and autoask.switched_on(conn)
    started = _clock()
    forced: set[str] = set()
    strong = True
    tally: Counter[str] = Counter()
    capped = False
    why: Counter[str] = Counter()
    issued = time.monotonic()

    def current() -> str:
        nonlocal token, issued
        if time.monotonic() - issued > TOKEN_LIFE:
            with db.session() as conn:
                token = gmail.access_token(conn, mailbox_id, time.time())
            issued = time.monotonic()
        return token

    try:
        if again:
            arrived = None
            with db.session() as conn:
                found = list(conn.execute(select(ScannedMessage.message_id).where(
                    ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.outcome == BOOKING).order_by(ScannedMessage.message_id)).scalars())
            pages: Iterable[list[str]] = [found]
        else:
            arrived = None if backfill else gmail.history_id(token)
            term = query.build(None if backfill else _since(last_scan, today), ignored)
            found = []
            pages = gmail.search_pages(current, term) if backfill else [found]
            if not backfill:
                found += gmail.search(token, term)
                if history and last_scan is not None:
                    try:
                        added = gmail.added_since(token, history)
                        found[:] = [m for m in found if m in added]
                    except gmail.HistoryExpired:
                        pass
            picked = decode_labels(row["scan_labels"])
            if picked:
                alive = {label["id"] for label in gmail.labels(token, counts=False)}
                kept = [label for label in picked if label in alive]
                dropped = len(picked) - len(kept)
                if dropped:
                    with db.session() as conn:
                        conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(scan_labels=encode_labels(kept)))
                labelled = list(dict.fromkeys(m for label in kept for m in gmail.search(token, "", label)))
                forced = set(labelled)
                if backfill:
                    pages = itertools.chain(([m for m in page if m not in forced] for page in pages), [labelled])
                else:
                    already = set(found)
                    found += [m for m in labelled if m not in already]
            if forced:
                with db.session() as conn:
                    conn.execute(delete(ScannedMessage).where(ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.outcome == SKIPPED,
                                                              ScannedMessage.message_id.in_(forced)))
            with db.session() as conn:
                legacy = list(conn.execute(select(ReviewItem.message_id).where(ReviewItem.mailbox_id == mailbox_id,
                                   ReviewItem.reason == "generic", ReviewItem.sender_domain.not_in(ignored))).scalars())
                if legacy:
                    conn.execute(delete(ScannedMessage).where(ScannedMessage.mailbox_id == mailbox_id,
                                                              ScannedMessage.message_id.in_(legacy)))
            if legacy:
                forced.update(legacy)
                pages = itertools.chain(pages, [legacy])
        for message_id in _unread(mailbox_id, pages, not again, tally):
            if handled and _clock() - started > BUDGET:
                capped = True
                break
            token = current()
            strong = True
            if not again and message_id not in forced:
                try:
                    head = extract.head(gmail.fetch_head(token, message_id))
                    verdict = triage.decide(head)
                    strong = triage.strong(head)
                except gmail.MessageGone:
                    with db.session() as conn:
                        _record(conn, mailbox_id, message_id, IGNORED, now)
                    continue
                if verdict == "skip":
                    with db.session() as conn:
                        _record(conn, mailbox_id, message_id, SKIPPED, now)
                    skipped += 1
                    not_travel += triage.shopping(head)
                    handled += 1
                    continue
            try:
                raw = gmail.fetch(token, message_id)
                message = extract.read(raw)
            except gmail.MessageGone:
                if not again:
                    with db.session() as conn:
                        _record(conn, mailbox_id, message_id, IGNORED, now)
                continue
            followed: list[followup.Followed] = []
            joined: list[int] = []
            try:
                with _filing, db.session() as conn:
                    a, b, wanted, outcome = _file(conn, mailbox_id, viewer, message_id, message, ignored, now, why, again, backfill, strong, followed, joined, gaps if filling else None)
            except Exception as e:
                if db.is_busy(e):
                    raise
                monitoring.report(e, values=False)
                with db.session() as conn:
                    review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, "incomplete", now)
                a, b, wanted, outcome = 0, 1, [], UNREADABLE
            if wanted is not None:
                _keep_quietly(mailbox_id, message_id, raw, wanted, now)
            if followed:
                _keep_code_quietly(mailbox_id, followed[0].segment_id, raw, now)
            if outcome is not None:
                with db.session() as conn:
                    _record(conn, mailbox_id, message_id, outcome, now, segment_id=followed[0].segment_id if followed else None)
            if outcome == SKIPPED:
                skipped, not_travel, handled = skipped + 1, not_travel + 1, handled + 1
                continue
            if followed:
                followups, with_facts = followups + 1, with_facts + followed[0].new_facts
            attached += bool(joined) and not a
            read, made, queued, handled = read + 1, made + a, queued + b, handled + 1
        if not capped:
            asked_by_ai, ai_made, ai_cleared = _ask_waiting(mailbox_id, current, started)
            asked_by_ai += _fill_gaps(current, started, viewer, gaps)
            made, queued = made + ai_made, max(0, queued - ai_cleared)
        if not again and not backfill:
            with db.session() as conn:
                conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(
                    scan_error=None, **({} if capped else {"last_scan": now, **({"history_id": arrived} if arrived else {})})))
    except gmail.GmailError as e:
        return _fail(mailbox_id, str(e), (read, made, queued))
    except Exception as e:
        monitoring.report(e, values=False)
        return _fail(mailbox_id, FAILED_GENERALLY, (read, made, queued))
    if not again and not backfill:
        remember(mailbox_id, Summary(tally["pending"], read, made, queued, skipped, capped, dropped, tally["found"] - tally["pending"] + handled, tally["found"], not_travel, followups, with_facts, attached,
                                     asked_by_ai))
    monitoring.log(f"{'Read a mailbox’s bookings again' if again else 'Looked back through a mailbox' if backfill else 'Scanned a mailbox'}: {tally['pending']} message(s) found, "
                   f"{read} read, {made} booking(s) added or changed, {queued} to review, {f'{followups} follow-up(s) attached ({with_facts} with details not applied), ' if followups else ''}{f'{attached} email(s) attached to an existing booking, ' if attached else ''}{f'{asked_by_ai} sent to the AI, ' if asked_by_ai else ''}{skipped} skipped ({not_travel} as not travel){', more waiting' if capped else ''}.")
    if why:
        monitoring.log("What stopped messages being read: " + "; ".join(f"{n} × {what}" for what, n in sorted(why.items())) + ".")
    return Result("done", None, read, made, queued, tally["pending"], skipped, capped)


def run(mailbox_id: int, today: date, again: bool = False, backfill: bool = False, sender: str | None = None) -> Result:
    result = scan(mailbox_id, time.time(), today, again, backfill, sender)
    chained = 0
    while result.state == "done" and result.capped and not again and chained < MAX_CHAIN:
        chained += 1
        result = scan(mailbox_id, time.time(), today, False, backfill, sender)
    return result


def scan_all(today: date) -> list[Result]:
    with db.session() as conn:
        ids = list(conn.execute(select(Mailbox.id).where(Mailbox.status != gmail.RECONNECT).order_by(Mailbox.id)).scalars())
    return [run(i, today) for i in ids]
