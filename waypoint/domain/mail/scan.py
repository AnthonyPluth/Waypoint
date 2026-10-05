"""Scanning a connected mailbox for bookings (AGENTS.md, "Email stays on the server").

A scan asks Gmail for the messages that look like bookings (waypoint/domain/mail/query.py: a sender allow-list plus
confirmation words, no promotions), so mail that doesn't match is never downloaded. The first scan looks back 18 months;
later ones take what Gmail's history says was added since the last one's end, among the messages that search finds. Each
message is fetched, read in memory by extract.py and thrown away: what's kept is the booking's fields (as segments, booked
by the mailbox's owner), the message's id and what came of it (`scanned_messages`, so nothing is read twice) and, for mail
that looked like a booking but couldn't be read, a review item (its sender's domain and its day; never its subject or text).

Each message is filed and committed on its own, so a scan that stops halfway keeps what it did, and the scan's end (the
history id and time it resumes from) moves only when it finishes: the last good state stays, and the mailbox says in a
fixed text what failed. A scan that can't start (the connection needs reconnecting, its owner can no longer sign in, no
one to book for) writes nothing about itself: that isn't a failed run. Counts only reach the log, never what a message said.

When the household turned the AI fallback on (waypoint/domain/mail/ai.py), a message that goes to the review queue is also
offered to it, once, and what it reads (or why it couldn't) is kept on the item as a suggestion for a person to confirm. The
setting is read again before each message, so turning it off stops the sending at once, mid-scan too."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, update

from ... import dates, monitoring
from ...providers import gmail
from ...storage import db
from ...storage.models import Mailbox, ScannedMessage
from .. import loyalty, people
from ..visibility import Viewer
from . import ai, extract, ingest, query, review

State = Literal["done", "failed", "not_started", "busy"]
BOOKING, UNREADABLE, IGNORED = "booking", "unreadable", "ignored"   # what came of a message (scanned_messages.outcome)
LOCAL = "local"             # the owner of a mailbox connected without sign-in (waypoint/server/api/mailboxes.py)
OVERLAP_DAYS = 2            # a later scan's search starts this many days before the last one ended
TOKEN_LIFE = 2400           # seconds an access token is used before asking for a new one (Google's last an hour)
FAILED_GENERALLY = "Something went wrong while reading this mailbox. Waypoint will try again; the details are in its log."
NO_PERSON = "Waypoint doesn’t know who this mailbox’s owner is yet. They sign in once, then it scans."
GONE = "That mailbox isn’t connected."


@dataclass(frozen=True)
class Result:
    state: State
    error: str | None = None     # for `failed` and `not_started`: fixed text, fit to show
    messages: int = 0            # read
    bookings: int = 0            # segments added or changed
    review: int = 0              # queued for review


_running: set[int] = set()
_lock = threading.Lock()


def running(mailbox_id: int) -> bool:
    with _lock:
        return mailbox_id in _running


def scan(mailbox_id: int, now: float, today: date) -> Result:
    """Scan one mailbox: `now` is the time to note it by, `today` the local day (the search's reach). One scan of a mailbox
    at a time: asking while one runs gives `busy`."""
    with _lock:
        if mailbox_id in _running:
            return Result("busy")
        _running.add(mailbox_id)
    try:
        return _scan(mailbox_id, now, today)
    finally:
        with _lock:
            _running.discard(mailbox_id)


def _viewer(owner: str, conn: db.Connection) -> Viewer | None:
    """Who the mailbox's bookings are for: its owner; without sign-in, the one local household."""
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


def _file(conn: db.Connection, mailbox_id: int, viewer: Viewer, message_id: str, message: extract.Message,
          ignored: list[str], now: float) -> tuple[int, int]:
    """File what one message held: its bookings among the owner's segments, a review item for what couldn't be read, and
    the message as seen. Returns (segments added or changed, 1 if queued for review)."""
    if _ignores(ignored, message.sender_domain):
        _record(conn, mailbox_id, message_id, IGNORED, now)
        return 0, 0
    made, failed = 0, 0
    for booking in message.bookings:
        filed = ingest.file_booking(conn, viewer, booking)
        if filed is None:
            failed += 1
        elif filed != "unchanged":
            made += 1
    usable = len(message.bookings) - failed
    queued = 0
    if failed or message.unread or not usable:
        reason: review.Reason = "broken" if message.broken else "incomplete" if message.markup or message.bookings else "no_markup"
        review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, reason, now)
        queued = 1
    _record(conn, mailbox_id, message_id, BOOKING if usable else UNREADABLE, now)
    return made, queued


SUGGESTION_FAILED = "The AI couldn’t be asked just now. The details are in Waypoint’s log."


def _suggest(mailbox_id: int, message_id: str, raw: dict[str, Any], now: float) -> None:
    """Offer a queued message to the AI, if the household has it on (read now, not when the scan began), and keep the answer
    on its review item. A failure here is the item's note, never the scan's."""
    with db.session() as conn:
        cfg = ai.config(conn)
        known = tuple(loyalty.known_numbers(conn)) if cfg else ()
    if cfg is None:
        return
    suggestion: ai.Suggestion | None = None
    error: str | None = None
    try:
        suggestion = ai.suggest(cfg, extract.plain_text(raw), known)
    except ai.AiError as e:
        error = str(e)
    except Exception as e:   # a bug: reported without what was sent or answered
        monitoring.report(e, values=False)
        error = SUGGESTION_FAILED
    with db.session() as conn:
        review.set_suggestion(conn, mailbox_id, message_id, suggestion, error)


def _fail(mailbox_id: int, text: str, partial: tuple[int, int, int]) -> Result:
    """The scan stopped: say what, in a fixed text. Where it resumes from is left as it was."""
    with db.session() as conn:
        conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(scan_error=text))
    return Result("failed", text, *partial)


def _scan(mailbox_id: int, now: float, today: date) -> Result:
    with db.session() as conn:
        row = conn.execute(select(Mailbox.owner_sub, Mailbox.address, Mailbox.history_id, Mailbox.last_scan)
                           .where(Mailbox.id == mailbox_id)).fetchone()
        if row is None:
            return Result("not_started", GONE)
        viewer = _viewer(row["owner_sub"], conn)
        if viewer is None:
            return Result("not_started", NO_PERSON)
        try:
            token = gmail.access_token(conn, mailbox_id, now)   # (marks the mailbox Reconnect, or ends it, when it must)
        except gmail.GmailError as e:
            return Result("not_started", str(e))
        ignored = review.ignored(conn, mailbox_id)
    history, last_scan = row["history_id"], row["last_scan"]
    read = made = queued = 0
    issued = time.monotonic()
    try:
        arrived = gmail.history_id(token)   # noted first, so mail arriving during the scan is for the next one
        found = gmail.search(token, query.build(_since(last_scan, today), ignored))
        if history and last_scan is not None:
            try:
                added = gmail.added_since(token, history)
                found = [m for m in found if m in added]
            except gmail.HistoryExpired:
                pass   # the search by date (from the last scan's end) covers it
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
                message = extract.read(raw)   # (the body is in memory only while this message is handled)
            except gmail.MessageGone:   # deleted since it was found: nothing to read
                with db.session() as conn:
                    _record(conn, mailbox_id, message_id, IGNORED, now)
                continue
            try:
                with db.session() as conn:
                    a, b = _file(conn, mailbox_id, viewer, message_id, message, ignored, now)
            except Exception as e:
                if db.is_busy(e):
                    raise
                # A message that can't be filed mustn't stop every later scan at the same place: it goes to the review
                # queue, and the reason is reported (without what it held).
                monitoring.report(e, values=False)
                with db.session() as conn:
                    review.add(conn, mailbox_id, message_id, message.sender_domain, message.received, "incomplete", now)
                    _record(conn, mailbox_id, message_id, UNREADABLE, now)
                a, b = 0, 1
            if b:
                _suggest(mailbox_id, message_id, raw, now)
            read, made, queued = read + 1, made + a, queued + b
        with db.session() as conn:
            conn.execute(update(Mailbox).where(Mailbox.id == mailbox_id).values(
                last_scan=now, scan_error=None, **({"history_id": arrived} if arrived else {})))
    except gmail.GmailError as e:
        return _fail(mailbox_id, str(e), (read, made, queued))
    except Exception as e:   # a bug, or the database busy: never the details (a row, a message) in what's shown or logged
        monitoring.report(e, values=False)
        return _fail(mailbox_id, FAILED_GENERALLY, (read, made, queued))
    monitoring.log(f"Scanned a mailbox: {read} message(s) read, {made} booking(s) added or changed, {queued} to review.")
    return Result("done", None, read, made, queued)


def scan_all(now: float, today: date) -> list[Result]:
    """Scan every mailbox (one that needs reconnecting is passed over until it's connected again)."""
    with db.session() as conn:
        ids = list(conn.execute(select(Mailbox.id).where(Mailbox.status != gmail.RECONNECT).order_by(Mailbox.id)).scalars())
    return [scan(i, now, today) for i in ids]
