"""Background jobs: the sweep that ends Gmail connections whose owners can no longer sign in, and the mail scan (every few
hours, and on "Scan now")."""
from __future__ import annotations

import threading
import time
from datetime import date

from .. import monitoring
from ..domain.mail import scan
from ..providers import gmail
from ..storage import db

SWEEP_EVERY = 3600   # seconds
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
    def sweeping() -> None:
        while True:
            sweep_lapsed()
            if stop.wait(SWEEP_EVERY):
                return

    def scanning() -> None:
        if stop.wait(SCAN_FIRST):
            return
        while True:
            scan_mailboxes()
            if stop.wait(SCAN_EVERY):
                return
    threads = [threading.Thread(target=sweeping, daemon=True, name="gmail-lapse-sweep"),
               threading.Thread(target=scanning, daemon=True, name="mail-scan")]
    for t in threads:
        t.start()
    return threads
