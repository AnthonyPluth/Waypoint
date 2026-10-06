from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, select, update

from ... import dates, monitoring
from ...providers import gmail
from ...storage import db, stored_mail
from ...storage.models import Mailbox, ScannedMessage
from ...storage.stored_mail import Content
from .. import loyalty, people
from ..visibility import Viewer
from . import ai, extract, ingest, query, review

State = Literal["done", "failed", "not_started", "busy"]
BOOKING, UNREADABLE, IGNORED = "booking", "unreadable", "ignored"
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


_running: set[int] = set()
_lock = threading.Lock()
_filing = threading.Lock()
_notices: dict[int, str] = {}


def running(mailbox_id: int) -> bool:
    with _lock:
        return mailbox_id in _running


def notice(mailbox_id: int) -> str | None:
    with _lock:
        return _notices.get(mailbox_id)


def scan(mailbox_id: int, now: float, today: date, again: bool = False, backfill: bool = False) -> Result:
    with _lock:
        if mailbox_id in _running:
            return Result("busy")
        _running.add(mailbox_id)
    try:
        result = _scan(mailbox_id, now, today, again, backfill)
    finally:
        with _lock:
            _running.discard(mailbox_id)
    with _lock:
        if result.state == "not_started" and result.error:
            _notices[mailbox_id] = result.error
        elif result.state != "busy":
            _notices.pop(mailbox_id, None)
    return result


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


def _record(conn: db.Connection, mailbox_id: int, message_id: str, outcome: str, now: float) -> None:
    db.insert_ignore(conn, ScannedMessage, {"mailbox_id": mailbox_id, "message_id": message_id, "outcome": outcome,
                                            "scanned": now}, key=["mailbox_id", "message_id"])


def _keeper(raw: dict[str, Any]) -> Callable[[], Content]:
    return lambda: extract.keep(raw)


def _file(conn: db.Connection, mailbox_id: int, viewer: Viewer, message_id: str, message: extract.Message,
          ignored: list[str], now: float, why: Counter[str] | None = None, again: bool = False,
          keep: Callable[[], Content] | None = None, backfill: bool = False) -> tuple[int, int]:
    why = Counter() if why is None else why
    if again:
        conn.execute(delete(ScannedMessage).where(ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.message_id == message_id))
    if _ignores(ignored, message.sender_domain):
        _record(conn, mailbox_id, message_id, IGNORED, now)
        return 0, 0
    made, failed = 0, 0
    touched: list[int] = []
    held: list[ingest.Held] = []
    for booking in message.bookings:
        filed = ingest.file_booking(conn, viewer, booking, again, touched, backfill, held)
        if filed is None:
            failed += 1
            why[ingest.explain(conn, booking)] += 1
        elif filed not in ("unchanged", "ambiguous"):
            made += 1
    usable = len(message.bookings) - failed
    queued = 0
    if failed or message.unread or not usable:
        why.update(message.gaps)
        if not message.bookings and not message.unread:
            why["no structured booking data" if not message.other_markup else "structured data, but no reservation"] += 1
        reason: review.Reason = "broken" if message.broken else "incomplete" if message.markup or message.bookings else "no_markup"
        review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, reason, now, held)
        queued = 1
    elif held:
        review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, "match", now, held)
        queued = 1
    if keep is not None and (queued or touched):
        stored_mail.put(conn, mailbox_id, message_id, keep(), now)
        for segment_id in dict.fromkeys(touched):
            stored_mail.link(conn, segment_id, mailbox_id, message_id)
    _record(conn, mailbox_id, message_id, BOOKING if usable else UNREADABLE, now)
    return made, queued


SUGGESTION_FAILED = "The AI couldn’t be asked just now. The details are in Waypoint’s log."
NO_AI = "Turn on AI suggestions in Settings first."


class NoAi(Exception):
    pass


def _again(owner: str, item_id: int) -> tuple[int, str, dict[str, Any]]:
    with db.session() as conn:
        found = review.locate(conn, owner, item_id)
        if found is None:
            raise KeyError(item_id)
        token = gmail.access_token(conn, found[0], time.time())
    return found[0], found[1], gmail.fetch(token, found[1])


def preview(owner: str, item_id: int) -> tuple[str, str | None, bool]:
    mailbox_id, message_id, raw = _again(owner, item_id)
    kept = extract.keep(raw)
    with db.session() as conn:
        stored_mail.put(conn, mailbox_id, message_id, kept, time.time())
    return kept["text"], kept["html"], kept["truncated"]


def suggest_now(owner: str, item_id: int, now: float) -> None:
    with db.session() as conn:
        if review.locate(conn, owner, item_id) is None:
            raise KeyError(item_id)
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
    suggestion: ai.Suggestion | None = None
    error: str | None = None
    try:
        suggestion = ai.suggest(cfg, extract.plain_text(raw), known)
    except ai.AiError as e:
        error = str(e)
    except Exception as e:
        monitoring.report(e, values=False)
        error = SUGGESTION_FAILED
    with db.session() as conn:
        review.set_suggestion(conn, mailbox_id, message_id, suggestion, error)


def _fail(mailbox_id: int, text: str, partial: tuple[int, int, int]) -> Result:
    with db.session() as conn:
        conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(scan_error=text))
    return Result("failed", text, *partial)


def _scan(mailbox_id: int, now: float, today: date, again: bool = False, backfill: bool = False) -> Result:
    with db.session() as conn:
        row = conn.execute(select(Mailbox.owner_sub, Mailbox.address, Mailbox.history_id, Mailbox.last_scan)
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
    read = made = queued = 0
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
            with db.session() as conn:
                seen = set(conn.execute(select(ScannedMessage.message_id).where(
                    ScannedMessage.mailbox_id == mailbox_id, ScannedMessage.message_id.in_(found))).scalars()) if found else set()
        for message_id in (m for m in found if m not in seen):
            if time.monotonic() - issued > TOKEN_LIFE:
                with db.session() as conn:
                    token = gmail.access_token(conn, mailbox_id, time.time())
                issued = time.monotonic()
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
                    a, b = _file(conn, mailbox_id, viewer, message_id, message, ignored, now, why, again, _keeper(raw), backfill)
            except Exception as e:
                if db.is_busy(e):
                    raise
                monitoring.report(e, values=False)
                with db.session() as conn:
                    review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, "incomplete", now)
                    stored_mail.put(conn, mailbox_id, message_id, extract.keep(raw), now)
                    _record(conn, mailbox_id, message_id, UNREADABLE, now)
                a, b = 0, 1
            if b:
                _suggest(mailbox_id, message_id, raw, now)
            read, made, queued = read + 1, made + a, queued + b
        if not again and not backfill:
            with db.session() as conn:
                conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(
                    last_scan=now, scan_error=None, **({"history_id": arrived} if arrived else {})))
    except gmail.GmailError as e:
        return _fail(mailbox_id, str(e), (read, made, queued))
    except Exception as e:
        monitoring.report(e, values=False)
        return _fail(mailbox_id, FAILED_GENERALLY, (read, made, queued))
    monitoring.log(f"{'Read a mailbox’s bookings again' if again else 'Looked back through a mailbox' if backfill else 'Scanned a mailbox'}: {read} message(s) read, "
                   f"{made} booking(s) added or changed, {queued} to review.")
    if why:
        monitoring.log("What stopped messages being read: " + "; ".join(f"{n} × {what}" for what, n in sorted(why.items())) + ".")
    return Result("done", None, read, made, queued)


def scan_all(now: float, today: date) -> list[Result]:
    with db.session() as conn:
        ids = list(conn.execute(select(Mailbox.id).where(Mailbox.status != gmail.RECONNECT).order_by(Mailbox.id)).scalars())
    return [scan(i, now, today) for i in ids]
