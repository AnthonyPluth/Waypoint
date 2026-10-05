"""Background jobs: the sweep that ends Gmail connections whose owners can no longer sign in, the flight status checks, and the
mail scan (every few hours, and on "Scan now")."""
from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime

from .. import monitoring
from ..domain import flightstatus
from ..domain.mail import scan
from ..providers import gmail
from ..storage import db

SWEEP_EVERY = 3600   # seconds
FLIGHT_STATUS_EVERY = 300   # the checks are at set points before a flight (20 minutes is the closest), so a round this often is enough
SCAN_EVERY = 4 * 3600
SCAN_FIRST = 300     # the first scan waits this long after Waypoint starts


def sweep_lapsed() -> None:
    """End the mailbox connections of people who can no longer sign in, then again every hour (so a connection nothing
    uses doesn't outlive its owner)."""
    try:
        with db.session() as conn:
            ended = gmail.end_lapsed(conn)
        if ended:
            monitoring.log(f"Ended {ended} Gmail connection(s) whose owner can no longer sign in.")
    except Exception as e:   # the next round tries again; never the details (they may name a row)
        monitoring.report(e, values=False)


def check_flights() -> None:
    """Fetch the live status of the flights whose check is due, within the month's budget (waypoint/domain/flightstatus.py)."""
    try:
        with db.session() as conn:
            flightstatus.run_due(conn, datetime.now(UTC))
    except Exception as e:   # the next round tries again; never the details (they may name a row)
        monitoring.report(e, values=False)


def scan_mailboxes() -> None:
    """Scan every connected mailbox, as the machine's local day goes (TZ): what each scan did is in its mailbox's row."""
    if not gmail.configured():
        return
    try:
        scan.scan_all(time.time(), date.today())
    except Exception as e:   # the next round tries again; never the details (they may name a row)
        monitoring.report(e, values=False)


def scan_now(mailbox_id: int) -> bool:
    """Start a scan of one mailbox in the background (Scan now). False when it is already being scanned."""
    if scan.running(mailbox_id):
        return False

    def run() -> None:
        try:
            scan.scan(mailbox_id, time.time(), date.today())
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
               threading.Thread(target=every, args=(SCAN_EVERY, scan_mailboxes, SCAN_FIRST), daemon=True, name="mail-scan")]
    for t in threads:
        t.start()
    return threads
