from __future__ import annotations

import json
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, select, update

from ... import dates, monitoring
from ...providers import gmail, mailimages
from ...storage import db, stored_mail
from ...storage.models import Mailbox, ScannedMessage
from ...storage.stored_mail import Content
from .. import loyalty, people
from ..visibility import Viewer
from . import ai, extract, ingest, query, review, triage

State = Literal["done", "failed", "not_started", "busy"]
BOOKING, UNREADABLE, SKIPPED = "booking", "unreadable", "skipped"
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
                       "triaged": found.triaged, "total": found.total, "not_travel": found.not_travel}, separators=(",", ":"))


def decode(text: str | None) -> Summary | None:
    try:
        raw = json.loads(text) if text else None
    except ValueError:
        return None
    counts = ("found", "read", "bookings", "review", "skipped")
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), int) and not isinstance(raw.get(k), bool) for k in counts) \
            or not isinstance(raw.get("capped"), bool):
        return None
    extra = [raw.get(k, 0) for k in ("labels_dropped", "triaged", "total", "not_travel")]
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


def _ignores(ignored: list[str], domain: str | None) -> bool:
    return bool(domain) and any(domain == d or (domain or "").endswith("." + d) for d in ignored)


def _record(conn: db.Connection, mailbox_id: int, message_id: str, outcome: str, now: float, sender_domain: str | None = None) -> None:
    db.insert_ignore(conn, ScannedMessage, {"mailbox_id": mailbox_id, "message_id": message_id, "outcome": outcome,
                                            "scanned": now, "sender_domain": sender_domain}, key=["mailbox_id", "message_id"])


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


def _file(conn: db.Connection, mailbox_id: int, viewer: Viewer, message_id: str, message: extract.Message,
          ignored: list[str], now: float, why: Counter[str] | None = None, again: bool = False,
          backfill: bool = False, strong: bool = True) -> tuple[int, int, list[int] | None, str | None]:
    why = Counter() if why is None else why
    if again:
        conn.execute(delete(ScannedMessage).where(ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.message_id == message_id))
    if _ignores(ignored, message.sender_domain):
        _record(conn, mailbox_id, message_id, IGNORED, now, message.sender_domain)
        return 0, 0, None, None
    made, failed = 0, 0
    touched: list[int] = []
    held: list[ingest.Held] = []
    proposed: list[extract.Booking] = []
    for booking in message.bookings:
        if booking.generic and not review.trusted(conn, mailbox_id, message.sender_domain):
            proposed.append(booking)
            continue
        filed = ingest.file_booking(conn, viewer, booking, again, touched, backfill, held)
        if filed is None:
            failed += 1
            why[ingest.explain(conn, booking)] += 1
        elif filed not in ("unchanged", "ambiguous"):
            made += 1
    if proposed:
        if review.asked(conn, mailbox_id, message.sender_domain):
            return made, 0, list(dict.fromkeys(touched)) if touched else None, None
        review.add_generic(conn, mailbox_id, message_id, message.sender_domain, message.received,
                           [ingest.suggestion(conn, b) for b in proposed], now, UNREAD_WITH_SUGGESTION if message.unread else None)
        return made, 1, [], UNREADABLE
    usable = len(message.bookings) - failed
    queued = 0
    if failed or message.unread or not usable:
        if not strong and not message.bookings and not message.unread and not message.markup:
            return made, 0, None, SKIPPED
        why.update(message.gaps)
        if not message.bookings and not message.unread:
            why["no structured booking data" if not message.other_markup else "structured data, but no reservation"] += 1
        reason: review.Reason = "broken" if message.broken else "incomplete" if message.markup or message.bookings else "no_markup"
        review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, reason, now, held)
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
        found = review.locate(conn, owner, item_id)
        if found is None:
            raise KeyError(item_id)
        if review.is_match(conn, *found):
            raise NotAskable(HOLDS_BOOKINGS)
        if review.is_generic(conn, *found):
            raise NotAskable(READ_ALREADY)
        if ai.config(conn) is None:
            raise NoAi(NO_AI)
    mailbox_id, message_id, raw = _again(owner, item_id)
    _suggest(mailbox_id, message_id, raw, now)


def _suggest(mailbox_id: int, message_id: str, raw: dict[str, Any], now: float) -> None:
    with db.session() as conn:
        cfg = ai.config(conn)
        known = tuple(loyalty.known_numbers(conn)) if cfg else ()
        asking = not review.is_match(conn, mailbox_id, message_id)
    if cfg is None or not asking:
        return
    suggestions: list[ai.Suggestion] = []
    error: str | None = None
    try:
        reading = ai.suggest(cfg, extract.plain_text(raw), known)
        suggestions, error = reading.bookings, reading.error
    except ai.AiError as e:
        error = str(e)
    except Exception as e:
        monitoring.report(e, values=False)
        error = SUGGESTION_FAILED
    with db.session() as conn:
        review.set_suggestions(conn, mailbox_id, message_id, suggestions, error)


def _generic(mailbox_id: int, message_id: str) -> bool:
    with db.session() as conn:
        return review.is_generic(conn, mailbox_id, message_id)


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
    read = made = queued = skipped = dropped = handled = total = not_travel = 0
    started = _clock()
    forced: set[str] = set()
    strong = True
    pending: list[str] = []
    capped = False
    why: Counter[str] = Counter()
    issued = time.monotonic()
    try:
        if again:
            arrived = None
            with db.session() as conn:
                found = list(conn.execute(select(ScannedMessage.message_id).where(
                    ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.outcome == BOOKING).order_by(ScannedMessage.message_id)).scalars())
            seen: set[str] = set()
        else:
            arrived = None if backfill else gmail.history_id(token)
            since = dates.add_months(today, -query.LOOKBACK_MONTHS) if backfill else _since(last_scan, today)
            found = gmail.search(token, query.build(since, ignored))
            if history and last_scan is not None and not backfill:
                try:
                    added = gmail.added_since(token, history)
                    found = [m for m in found if m in added]
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
                found = found + [m for m in labelled if m not in set(found)]
            with db.session() as conn:
                if forced:
                    conn.execute(delete(ScannedMessage).where(ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.outcome == SKIPPED,
                                                              ScannedMessage.message_id.in_(forced)))
                seen = set(conn.execute(select(ScannedMessage.message_id).where(
                    ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.message_id.in_(found))).scalars()) if found else set()
        pending = [m for m in found if m not in seen]
        total = len(found)
        for message_id in pending:
            if handled and _clock() - started > BUDGET:
                capped = True
                break
            if time.monotonic() - issued > TOKEN_LIFE:
                with db.session() as conn:
                    token = gmail.access_token(conn, mailbox_id, time.time())
                issued = time.monotonic()
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
            try:
                with _filing, db.session() as conn:
                    a, b, wanted, outcome = _file(conn, mailbox_id, viewer, message_id, message, ignored, now, why, again, backfill, strong)
            except Exception as e:
                if db.is_busy(e):
                    raise
                monitoring.report(e, values=False)
                with db.session() as conn:
                    review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, "incomplete", now)
                a, b, wanted, outcome = 0, 1, [], UNREADABLE
            if wanted is not None:
                _keep_quietly(mailbox_id, message_id, raw, wanted, now)
            if outcome is not None:
                with db.session() as conn:
                    _record(conn, mailbox_id, message_id, outcome, now)
            if b and not _generic(mailbox_id, message_id):
                _suggest(mailbox_id, message_id, raw, now)
            if outcome == SKIPPED:
                skipped, not_travel, handled = skipped + 1, not_travel + 1, handled + 1
                continue
            read, made, queued, handled = read + 1, made + a, queued + b, handled + 1
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
        remember(mailbox_id, Summary(len(pending), read, made, queued, skipped, capped, dropped, total - len(pending) + handled, total, not_travel))
    monitoring.log(f"{'Read a mailbox’s bookings again' if again else 'Looked back through a mailbox' if backfill else 'Scanned a mailbox'}: {len(pending)} message(s) found, "
                   f"{read} read, {made} booking(s) added or changed, {queued} to review, {skipped} skipped ({not_travel} as not travel){', more waiting' if capped else ''}.")
    if why:
        monitoring.log("What stopped messages being read: " + "; ".join(f"{n} × {what}" for what, n in sorted(why.items())) + ".")
    return Result("done", None, read, made, queued, len(pending), skipped, capped)


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
