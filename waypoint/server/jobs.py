"""Background jobs: the sweep that ends Gmail connections whose owners can no longer sign in."""
from __future__ import annotations

import threading

from .. import monitoring
from ..providers import gmail
from ..storage import db

SWEEP_EVERY = 3600   # seconds


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


def start(stop: threading.Event) -> threading.Thread:
    def run() -> None:
        while True:
            sweep_lapsed()
            if stop.wait(SWEEP_EVERY):
                return
    t = threading.Thread(target=run, daemon=True, name="gmail-lapse-sweep")
    t.start()
    return t
