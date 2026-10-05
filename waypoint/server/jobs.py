"""Background jobs: the sweep that ends Gmail connections whose owners can no longer sign in, and the flight status checks."""
from __future__ import annotations

import threading
from datetime import UTC, datetime

from .. import monitoring
from ..domain import flightstatus
from ..providers import gmail
from ..storage import db

SWEEP_EVERY = 3600   # seconds
FLIGHT_STATUS_EVERY = 300   # the checks are at set points before a flight (20 minutes is the closest), so a round this often is enough


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


def start(stop: threading.Event) -> list[threading.Thread]:
    def every(seconds: int, job) -> None:
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
               threading.Thread(target=every, args=(FLIGHT_STATUS_EVERY, check_flights), daemon=True, name="flight-status")]
    for t in threads:
        t.start()
    return threads
