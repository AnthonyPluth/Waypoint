from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

from .. import monitoring, oidc
from ..domain import flightstatus, photogrants, photoqueue, photosources, photosync, reminders, route_warming
from ..domain.mail import scan
from ..providers import gmail
from ..storage import db

SUBJECT = "mailto:waypoint@localhost"
SWEEP_EVERY = 3600
FLIGHT_STATUS_EVERY = 300
REMINDERS_EVERY = 300
SCAN_EVERY = 4 * 3600
SCAN_FIRST = 300
PHOTO_SYNC_EVERY = 6 * 3600
PHOTO_SYNC_FIRST = 600


def warm_driving_routes(stop: threading.Event, given: route_warming.Memory) -> bool:
    try:
        fetch = route_warming.client(given)
        if fetch is None:
            return False
        outcome = route_warming.run(date.today(), fetch, stop.wait, given, time.time)
        if outcome.refused:
            monitoring.log("Driving routes: Apple's Maps Server API didn't accept the MapKit key, so routes aren't being prepared ahead; check that the Maps Server API is enabled for the key.", "warning")
            return False
        monitoring.log(f"Driving routes: {outcome.fetched} prepared" + (", more to come." if outcome.left else "."))
    except Exception as e:
        monitoring.report(e, values=False)
    return True


def keep_routes_warm(stop: threading.Event, clock: Callable[[], datetime] = datetime.now) -> None:
    given = route_warming.Memory()
    while True:
        if stop.wait(route_warming.seconds_until(clock(), route_warming.hour())):
            return
        if not warm_driving_routes(stop, given):
            return


def sweep_lapsed() -> None:
    try:
        with db.session() as conn:
            ended = gmail.end_lapsed(conn)
        with db.session() as conn:
            others = reminders.end_lapsed(conn)
        with db.session() as conn:
            libraries = photosources.end_lapsed(conn)
        with db.session() as conn:
            shares = photogrants.end_lapsed(conn)
        if ended or others or libraries or shares:
            monitoring.log(f"Ended {ended} Gmail connection(s), {others} person(s)' reminders and calendar feed, {libraries} Immich "
                           f"library connection(s) and {shares} photo sharing grant(s) or setting(s) whose owner can no longer sign in.")
    except Exception as e:
        monitoring.report(e, values=False)


def sync_photos() -> None:
    try:
        photosync.sync_all(datetime.now(UTC))
    except Exception as e:
        monitoring.report(e, values=False)


def sync_photos_now(source_id: int) -> bool:
    return photosync.start(source_id)


def send_reminders() -> None:
    try:
        local = datetime.now().astimezone()
        with db.session() as conn:
            reminders.run_due(conn, datetime.now(UTC), local.date(), local.hour, reminders.sender(conn, oidc.config()["public_url"] or SUBJECT))
    except Exception as e:
        monitoring.report(e, values=False)


def notify_review(since: float, mailbox_ids: list[int]) -> None:
    try:
        with db.session() as conn:
            reminders.review_due(conn, since, time.time(), reminders.sender(conn, oidc.config()["public_url"] or SUBJECT), mailbox_ids)
    except Exception as e:
        monitoring.report(e, values=False)


def notify_times(since: float) -> None:
    try:
        with db.session() as conn:
            reminders.times_due(conn, since, datetime.now(UTC), lambda: reminders.sender(conn, oidc.config()["public_url"] or SUBJECT))
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
    scanned: list[int] = []
    try:
        scan.scan_all(date.today(), scanned)
    except Exception as e:
        monitoring.report(e, values=False)
    notify_review(started, scanned)
    notify_times(started)


def scan_now(mailbox_id: int, again: bool = False, backfill: bool = False, sender: str | None = None) -> bool:
    if scan.running(mailbox_id):
        return False

    def run() -> None:
        started, scanned = time.time(), [mailbox_id]
        try:
            if scan.run(mailbox_id, date.today(), again, backfill, sender).state == "busy":
                scanned = []
        except Exception as e:
            monitoring.report(e, values=False)
        notify_review(started, scanned)
        notify_times(started)
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
               threading.Thread(target=every, args=(SCAN_EVERY, scan_mailboxes, SCAN_FIRST), daemon=True, name="mail-scan"),
               threading.Thread(target=keep_routes_warm, args=(stop,), daemon=True, name="driving-routes"),
               threading.Thread(target=every, args=(PHOTO_SYNC_EVERY, sync_photos, PHOTO_SYNC_FIRST), daemon=True, name="photo-sync")]
    photoqueue.enable(photosync.start)
    for t in threads:
        t.start()
    return threads
