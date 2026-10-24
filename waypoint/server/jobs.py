from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime

from .. import monitoring, oidc
from ..domain import flightstatus, reminders
from ..domain.mail import scan
from ..providers import gmail
from ..storage import db, roads, states

SUBJECT = "mailto:waypoint@localhost"
SWEEP_EVERY = 3600
FLIGHT_STATUS_EVERY = 300
REMINDERS_EVERY = 300
SCAN_EVERY = 4 * 3600
SCAN_FIRST = 300


def warm_map_data() -> None:
    try:
        roads.highways()
        states.state_lines()
    except Exception as e:
        monitoring.report(e, values=False)


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


def notify_review(since: float) -> None:
    try:
        with db.session() as conn:
            reminders.review_due(conn, since, time.time(), reminders.sender(conn, oidc.config()["public_url"] or SUBJECT))
    except Exception as e:
        monitoring.report(e, values=False)


def check_flights() -> None:
    try:
        with db.session() as conn:
            flightstatus.run_due(conn, datetime.now(UTC))
    except Exception as e:
        monitoring.report(e, values=False)


def scan_mailboxes() -> None:
    if not gmail.configured():
        return
    started = time.time()
    try:
        scan.scan_all(date.today())
    except Exception as e:
        monitoring.report(e, values=False)
    notify_review(started)


def scan_now(mailbox_id: int, again: bool = False, backfill: bool = False, sender: str | None = None) -> bool:
    if scan.running(mailbox_id):
        return False

    def run() -> None:
        started = time.time()
        try:
            scan.run(mailbox_id, date.today(), again, backfill, sender)
        except Exception as e:
            monitoring.report(e, values=False)
        notify_review(started)
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
    threads = [threading.Thread(target=warm_map_data, daemon=True, name="map-data"),
               threading.Thread(target=every, args=(SWEEP_EVERY, sweep_lapsed), daemon=True, name="gmail-lapse-sweep"),
               threading.Thread(target=every, args=(FLIGHT_STATUS_EVERY, check_flights), daemon=True, name="flight-status"),
               threading.Thread(target=every, args=(REMINDERS_EVERY, send_reminders), daemon=True, name="reminders"),
               threading.Thread(target=every, args=(SCAN_EVERY, scan_mailboxes, SCAN_FIRST), daemon=True, name="mail-scan")]
    for t in threads:
        t.start()
    return threads
