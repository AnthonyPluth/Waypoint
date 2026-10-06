"""Background jobs: the sweep that ends Gmail connections, notification devices and calendar feeds whose owners can no longer
sign in, the flight status checks, the reminders, the brand logos and the mail scan (every few hours, and on "Scan now")."""
from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime

from .. import monitoring, oidc
from ..domain import flightstatus, logos, reminders
from ..domain.mail import scan
from ..providers import gmail
from ..storage import db

SUBJECT = "mailto:waypoint@localhost"   # the contact a push service gets with each notification (RFC 8292) when there's no WAYPOINT_PUBLIC_URL; no one's address
_fetching = threading.Lock()   # a logo round is running
SWEEP_EVERY = 3600   # seconds
FLIGHT_STATUS_EVERY = 300   # the checks are at set points before a flight (20 minutes is the closest), so a round this often is enough
REMINDERS_EVERY = 300   # a reminder is sent in the round after it falls due, so up to five minutes late
SCAN_EVERY = 4 * 3600
LOGOS_EVERY = 900    # a round fetches a few brands (logos.PER_ROUND), so a new booking's logo shows up within the hour
SCAN_FIRST = 300     # the first scan waits this long after Waypoint starts


def sweep_lapsed() -> None:
    """End the mailbox connections, notification devices and calendar feeds of people who can no longer sign in, then again
    every hour (so what nothing uses doesn't outlive its owner)."""
    try:
        with db.session() as conn:
            ended = gmail.end_lapsed(conn)
        with db.session() as conn:
            others = reminders.end_lapsed(conn)
        if ended or others:
            monitoring.log(f"Ended {ended} Gmail connection(s) and {others} person(s)' reminders and calendar feed whose owner can no longer sign in.")
    except Exception as e:   # the next round tries again; never the details (they may name a row)
        monitoring.report(e, values=False)


def send_reminders() -> None:
    """Send the reminders that are due ("Check-in opens", the day-of summary): the machine's local day and hour decide the
    summary's, a flight's own zone its check-in."""
    try:
        local = datetime.now().astimezone()
        with db.session() as conn:
            reminders.run_due(conn, datetime.now(UTC), local.date(), local.hour, reminders.sender(conn, oidc.config()["public_url"] or SUBJECT))
    except Exception as e:   # the next round tries again; never the details (they may name a row)
        monitoring.report(e, values=False)


def check_flights() -> None:
    """Fetch the live status of the flights whose check is due, within the month's budget (waypoint/domain/flightstatus.py)."""
    try:
        with db.session() as conn:
            flightstatus.run_due(conn, datetime.now(UTC))
    except Exception as e:   # the next round tries again; never the details (they may name a row)
        monitoring.report(e, values=False)


def fetch_logos() -> None:
    """Fetch the logos of the brands in bookings that Waypoint hasn't asked Logo.dev about (when a key is saved)."""
    try:
        with db.session() as conn:
            logos.fetch_due(conn, datetime.now(UTC))
    except Exception as e:   # the next round tries again; never the details (they may name a row)
        monitoring.report(e, values=False)


def fetch_logos_now() -> bool:
    """Start a round of logo fetching in the background (a key was just saved, or "Fetch them now"). False when one is running."""
    if not _fetching.acquire(blocking=False):
        return False

    def run() -> None:
        try:
            fetch_logos()
        finally:
            _fetching.release()
    threading.Thread(target=run, daemon=True, name="logos-now").start()
    return True


def scan_mailboxes() -> None:
    """Scan every connected mailbox, as the machine's local day goes (TZ): what each scan did is in its mailbox's row."""
    if not gmail.configured():
        return
    try:
        scan.scan_all(time.time(), date.today())
    except Exception as e:   # the next round tries again; never the details (they may name a row)
        monitoring.report(e, values=False)


def scan_now(mailbox_id: int, again: bool = False) -> bool:
    """Start a scan of one mailbox in the background (Scan now), or, with `again`, a reading of the messages it already found
    that made bookings (Read bookings again). False when it is already being scanned."""
    if scan.running(mailbox_id):
        return False

    def run() -> None:
        try:
            scan.scan(mailbox_id, time.time(), date.today(), again)
        except Exception as e:
            monitoring.report(e, values=False)
    threading.Thread(target=run, daemon=True, name="mail-scan-now").start()
    return True


def start(stop: threading.Event) -> list[threading.Thread]:
    def every(seconds: int, job, first: int = 0) -> None:
        if first and stop.wait(first):
            return
        while True:
            job()
            if stop.wait(seconds):
                return
    try:
        with db.session() as conn:
            flightstatus.forget_key_pause(conn)
    except Exception as e:   # never the details (they may name a row)
        monitoring.report(e, values=False)
    threads = [threading.Thread(target=every, args=(SWEEP_EVERY, sweep_lapsed), daemon=True, name="gmail-lapse-sweep"),
               threading.Thread(target=every, args=(FLIGHT_STATUS_EVERY, check_flights), daemon=True, name="flight-status"),
               threading.Thread(target=every, args=(REMINDERS_EVERY, send_reminders), daemon=True, name="reminders"),
               threading.Thread(target=every, args=(LOGOS_EVERY, fetch_logos, 60), daemon=True, name="logos"),
               threading.Thread(target=every, args=(SCAN_EVERY, scan_mailboxes, SCAN_FIRST), daemon=True, name="mail-scan")]
    for t in threads:
        t.start()
    return threads
