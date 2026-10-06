from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime

from .. import monitoring, oidc
from ..domain import flightstatus, logos, reminders
from ..domain.mail import scan
from ..providers import gmail
from ..storage import db

SUBJECT = "mailto:waypoint@localhost"
_fetching = threading.Lock()
SWEEP_EVERY = 3600
FLIGHT_STATUS_EVERY = 300
REMINDERS_EVERY = 300
SCAN_EVERY = 4 * 3600
LOGOS_EVERY = 900
SCAN_FIRST = 300


def sweep_lapsed() -> None:
    try:
        with db.session() as conn:
            ended = gmail.end_lapsed(conn)
        with db.session() as conn:
            others = reminders.end_lapsed(conn)
        if ended or others:
            monitoring.log(f"Ended {ended} Gmail connection(s) and {others} person(s)' reminders and calendar feed whose owner can no longer sign in.")
    except Exception as e:
        monitoring.report(e, values=False)


def send_reminders() -> None:
    try:
        local = datetime.now().astimezone()
        with db.session() as conn:
            reminders.run_due(conn, datetime.now(UTC), local.date(), local.hour, reminders.sender(conn, oidc.config()["public_url"] or SUBJECT))
    except Exception as e:
        monitoring.report(e, values=False)


def check_flights() -> None:
    try:
        with db.session() as conn:
            flightstatus.run_due(conn, datetime.now(UTC))
    except Exception as e:
        monitoring.report(e, values=False)


def fetch_logos() -> bool:
    if not _fetching.acquire(blocking=False):
        return False
    try:
        with db.session() as conn:
            logos.fetch_due(conn, datetime.now(UTC))
    except Exception as e:
        monitoring.report(e, values=False)
    finally:
        _fetching.release()
    return True


def fetch_logos_now() -> bool:
    if _fetching.locked():
        return False
    threading.Thread(target=fetch_logos, daemon=True, name="logos-now").start()
    return True


def scan_mailboxes() -> None:
    if not gmail.configured():
        return
    try:
        scan.scan_all(time.time(), date.today())
    except Exception as e:
        monitoring.report(e, values=False)


def scan_now(mailbox_id: int, again: bool = False, backfill: bool = False) -> bool:
    if scan.running(mailbox_id):
        return False

    def run() -> None:
        try:
            scan.scan(mailbox_id, time.time(), date.today(), again, backfill)
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
    except Exception as e:
        monitoring.report(e, values=False)
    threads = [threading.Thread(target=every, args=(SWEEP_EVERY, sweep_lapsed), daemon=True, name="gmail-lapse-sweep"),
               threading.Thread(target=every, args=(FLIGHT_STATUS_EVERY, check_flights), daemon=True, name="flight-status"),
               threading.Thread(target=every, args=(REMINDERS_EVERY, send_reminders), daemon=True, name="reminders"),
               threading.Thread(target=every, args=(LOGOS_EVERY, fetch_logos, 60), daemon=True, name="logos"),
               threading.Thread(target=every, args=(SCAN_EVERY, scan_mailboxes, SCAN_FIRST), daemon=True, name="mail-scan")]
    for t in threads:
        t.start()
    return threads
