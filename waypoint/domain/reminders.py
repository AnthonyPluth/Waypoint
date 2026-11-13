from __future__ import annotations

import hashlib
import ipaddress
import secrets
import time
import urllib.parse
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, TypedDict

from sqlalchemy import delete, select

from .. import monitoring, oidc
from ..providers import webpush
from ..storage import db
from ..storage.models import AppDevice, CalendarFeed, PushDevice, ReminderPrefs, ReminderSent, Segment, User
from . import app_push, calendar, people, trips
from .mail import review
from .trips import SegmentOut, TripOut
from .visibility import Viewer

Kind = Literal["check_in", "day_of", "review", "review_retry", "times", "times_retry"]
CHECK_IN_AHEAD = timedelta(hours=24)
DAY_OF_HOUR = 7
LOCAL_OWNER = "local"
MAX_DEVICES = 10
MAX_ITEMS = 5
ENDPOINT_LIMIT = 2048
KEY_LIMIT = 256


class Invalid(ValueError):
    pass


class Prefs(TypedDict):
    check_in: bool
    day_of: bool
    review: bool


class DeviceOut(TypedDict):
    id: int
    service: str
    created: float


@dataclass(frozen=True)
class Device:
    id: int
    endpoint: str
    p256dh: str
    auth: str


Send = Callable[[Device, dict[str, Any]], None]


def viewer_for(conn: db.Connection, owner: str) -> Viewer:
    if owner == LOCAL_OWNER:
        return Viewer(None, household=True)
    return Viewer(people.person_for_sub(conn, owner))


def lapsed(conn: db.Connection, owner: str, now: float) -> bool:
    email = conn.execute(select(User.email).where(User.sub == owner)).scalar()
    return oidc.access_lapsed(conn, owner, email, now) is not None


def _forget(conn: db.Connection, owner: str) -> None:
    conn.execute(delete(PushDevice).where(PushDevice.owner_sub == owner))
    app_push.forget(conn, owner)
    conn.execute(delete(CalendarFeed).where(CalendarFeed.owner_sub == owner))
    conn.execute(delete(ReminderPrefs).where(ReminderPrefs.owner_sub == owner))
    conn.execute(delete(ReminderSent).where(ReminderSent.owner_sub == owner))


def end_lapsed(conn: db.Connection, now: float | None = None) -> int:
    now = time.time() if now is None else now
    owners = (set(conn.execute(select(PushDevice.owner_sub)).scalars()) | set(conn.execute(select(CalendarFeed.owner_sub)).scalars())
              | set(conn.execute(select(AppDevice.owner_sub)).scalars()))
    gone = [o for o in sorted(owners) if lapsed(conn, o, now)]
    for owner in gone:
        _forget(conn, owner)
    return len(gone)


def prefs(conn: db.Connection, owner: str) -> Prefs:
    row = conn.orm.get(ReminderPrefs, owner)
    return {"check_in": row.check_in, "day_of": row.day_of, "review": row.review} if row else {"check_in": True, "day_of": True, "review": True}


def set_prefs(conn: db.Connection, owner: str, chosen: Prefs) -> Prefs:
    db.upsert(conn, ReminderPrefs, {"owner_sub": owner, **chosen}, key=["owner_sub"])
    return prefs(conn, owner)


def check_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    if not endpoint or len(endpoint) > ENDPOINT_LIMIT or len(p256dh) > KEY_LIMIT or len(auth) > KEY_LIMIT:
        raise Invalid("That isn’t a notification subscription Waypoint can use.")
    parts = urllib.parse.urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if parts.scheme != "https" or not host or literal or "." not in host or host.endswith((".local", ".internal", ".lan")) \
            or parts.username or parts.password:
        raise Invalid("That isn’t a notification service address Waypoint will send to.")
    try:
        keys_ok = webpush.valid_public_key(p256dh) and len(webpush.unb64u(auth)) >= 16
    except ValueError:
        keys_ok = False
    if not keys_ok:
        raise Invalid("That subscription’s keys aren’t valid.")


SERVICES = (("fcm.googleapis.com", "Chrome or Android (Google)"), ("push.apple.com", "Safari on an Apple device"),
            ("push.services.mozilla.com", "Firefox"), ("notify.windows.com", "Microsoft Edge on Windows"))


def service_name(endpoint: str) -> str:
    host = (urllib.parse.urlsplit(endpoint).hostname or "").lower()
    for suffix, name in SERVICES:
        if host == suffix or host.endswith("." + suffix):
            return name
    return f"Notifications to {host}"


def devices(conn: db.Connection, owner: str) -> list[DeviceOut]:
    rows = conn.orm.scalars(select(PushDevice).where(PushDevice.owner_sub == owner).order_by(PushDevice.id)).all()
    return [{"id": d.id, "service": service_name(d.endpoint), "created": d.created} for d in rows]


def add_device(conn: db.Connection, owner: str, endpoint: str, p256dh: str, auth: str, now: float) -> DeviceOut:
    check_subscription(endpoint, p256dh, auth)
    mine = conn.orm.scalars(select(PushDevice).where(PushDevice.owner_sub == owner)).all()
    if len(mine) >= MAX_DEVICES and endpoint not in {d.endpoint for d in mine}:
        raise Invalid(f"Turn notifications off on a device you no longer use first (at most {MAX_DEVICES}).")
    db.upsert(conn, PushDevice, {"owner_sub": owner, "endpoint": endpoint, "p256dh": p256dh, "auth": auth, "created": now},
              key=["endpoint"])
    found = conn.orm.scalars(select(PushDevice).where(PushDevice.endpoint == endpoint)).one()
    conn.orm.refresh(found)
    return {"id": found.id, "service": service_name(found.endpoint), "created": found.created}


def remove_device(conn: db.Connection, owner: str, device_id: int) -> bool:
    return conn.execute(delete(PushDevice).where(PushDevice.id == device_id, PushDevice.owner_sub == owner)).rowcount > 0


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def feed_on(conn: db.Connection, owner: str) -> bool:
    return conn.orm.get(CalendarFeed, owner) is not None


def new_feed_key(conn: db.Connection, owner: str, now: float) -> str:
    key = secrets.token_urlsafe(32)
    db.upsert(conn, CalendarFeed, {"owner_sub": owner, "key_hash": key_hash(key), "created": now}, key=["owner_sub"])
    return key


def feed_off(conn: db.Connection, owner: str) -> bool:
    return conn.execute(delete(CalendarFeed).where(CalendarFeed.owner_sub == owner)).rowcount > 0


def feed_owner(conn: db.Connection, key: str, now: float) -> str | None:
    owner = conn.execute(select(CalendarFeed.owner_sub).where(CalendarFeed.key_hash == key_hash(key))).scalar()
    if owner is None:
        return None
    if lapsed(conn, owner, now):
        _forget(conn, owner)
        return None
    return str(owner)


def feed_text(conn: db.Connection, owner: str, now: datetime) -> str:
    return calendar.feed(trips.listing(conn, viewer_for(conn, owner)), now)


def _clock(local: str) -> str:
    return f"{datetime.fromisoformat(local):%H:%M}"


def _day(local: str) -> str:
    t = datetime.fromisoformat(local)
    return f"{t:%a} {t.day} {t:%b}"


def _when(seg: SegmentOut) -> str:
    return "Time not recorded" if trips.untimed(seg["details"]) else _clock(seg["start_local"])


def _label(seg: SegmentOut) -> str:
    where = " → ".join(p for p in (seg["origin"], seg["destination"]) if p)
    number = seg["details"].get("flight_number")
    names = {"flight": "Flight", "hotel": "Hotel check-in", "car": "Car pickup", "train": "Train", "cruise": "Cruise", "parking": "Parking", "visit": "Visit"}
    return " ".join(p for p in (names[seg["kind"]], number, where) if p)


def check_in_message(seg: SegmentOut) -> dict[str, Any]:
    return {"title": "Check-in opens", "tag": f"check-in-{seg['id']}", "url": f"/#trip/{seg['trip_id']}",
            "body": f"{_label(seg)} leaves {_day(seg['start_local'])} at {_clock(seg['start_local'])}."}


def day_of_message(today_trips: list[tuple[SegmentOut, TripOut]], day: str) -> dict[str, Any]:
    items = sorted(today_trips, key=lambda p: p[0]["start_local"])
    lines = [f"{_when(s)} {_label(s)}" for s, _t in items[:MAX_ITEMS]]
    if len(items) > MAX_ITEMS:
        lines.append(f"and {len(items) - MAX_ITEMS} more")
    first = items[0][1]["id"]
    return {"title": "Today", "tag": f"day-of-{day}", "url": f"/#trip/{first}" if len({t['id'] for _s, t in items}) == 1 else "/",
            "body": "\n".join(lines)}


def times_message(seg: SegmentOut) -> dict[str, Any]:
    return {"title": "Flight times changed", "tag": f"times-{seg['id']}", "url": f"/#trip/{seg['trip_id']}",
            "body": f"{_label(seg)} now leaves {_day(seg['start_local'])} at {_clock(seg['start_local'])}."}


def review_message(waiting: int) -> dict[str, Any]:
    return {"title": "Booking emails to review", "tag": "review", "url": "/#review",
            "body": f"{waiting} booking email{' needs' if waiting == 1 else 's need'} your review"}


def _deliver(conn: db.Connection, owner: str, message: dict[str, Any], send: Send) -> bool:
    rows = conn.orm.scalars(select(PushDevice).where(PushDevice.owner_sub == owner).order_by(PushDevice.id)).all()
    reached, tried = 0, 0
    for d in rows:
        tried += 1
        try:
            send(Device(d.id, d.endpoint, d.p256dh, d.auth), message)
            reached += 1
        except webpush.Gone:
            conn.execute(delete(PushDevice).where(PushDevice.id == d.id))
            tried -= 1
        except Exception as e:
            monitoring.report(e, values=False)
    app_reached, app_tried = app_push.wake(conn, owner, str(message.get("tag", "")))
    return reached + app_reached > 0 or tried + app_tried == 0


def _record(conn: db.Connection, owner: str, kind: Kind, ref: str, now: float) -> None:
    db.insert_ignore(conn, ReminderSent, {"owner_sub": owner, "kind": kind, "ref": ref, "sent": now},
                     key=["owner_sub", "kind", "ref"])


def _sent(conn: db.Connection, owner: str, kind: Kind, ref: str) -> bool:
    return conn.execute(select(ReminderSent.id).where(ReminderSent.owner_sub == owner, ReminderSent.kind == kind,
                                                       ReminderSent.ref == ref)).fetchone() is not None


def _live(segs: Sequence[SegmentOut]) -> list[SegmentOut]:
    return [live[0] for group in trips.flight_groups(segs) if (live := [s for s in group if s["status"] != "cancelled"])]


def run_due(conn: db.Connection, now: datetime, today: date, hour: int, send: Send) -> int:
    stamp = now.timestamp()
    end_lapsed(conn, stamp)
    sent = 0
    for owner in sorted(set(conn.execute(select(PushDevice.owner_sub)).scalars()) | app_push.owners(conn)):
        chosen = prefs(conn, owner)
        if not (chosen["check_in"] or chosen["day_of"]):
            continue
        mine = trips.listing(conn, viewer_for(conn, owner))
        if chosen["check_in"]:
            for trip in mine:
                for seg in (s for s in _live(trip["segments"]) if s["kind"] == "flight" and not trips.untimed(s["details"])):
                    leaves = trips.instant(seg["start_local"], seg["start_zone"])
                    ref = f"{seg['id']}@{seg['start_local']}"
                    if leaves - CHECK_IN_AHEAD <= now < leaves and not _sent(conn, owner, "check_in", ref) \
                            and _deliver(conn, owner, check_in_message(seg), send):
                        _record(conn, owner, "check_in", ref, stamp)
                        sent += 1
        day = today.isoformat()
        if chosen["day_of"] and hour >= DAY_OF_HOUR and not _sent(conn, owner, "day_of", day):
            starting = [(s, t) for t in mine for s in _live(t["segments"]) if s["kind"] != "visit" and s["start_local"][:10] == day]
            if starting and _deliver(conn, owner, day_of_message(starting, day), send):
                _record(conn, owner, "day_of", day, stamp)
                sent += 1
    return sent


def _times_waiting(conn: db.Connection, owner: str) -> set[str]:
    return set(conn.execute(select(ReminderSent.ref).where(ReminderSent.owner_sub == owner, ReminderSent.kind == "times_retry")).scalars())


def _times_forget(conn: db.Connection, owner: str, refs: Collection[str]) -> None:
    if refs:
        conn.execute(delete(ReminderSent).where(ReminderSent.owner_sub == owner, ReminderSent.kind == "times_retry", ReminderSent.ref.in_(sorted(refs))))


def _times_changed(conn: db.Connection, owner: str, since: float, now: datetime, waiting: set[str]) -> dict[str, SegmentOut]:
    found: dict[str, SegmentOut] = {}
    for trip in trips.listing(conn, viewer_for(conn, owner)):
        flights = [s for s in trip["segments"] if s["kind"] == "flight" and s["status"] != "cancelled" and not trips.untimed(s["details"])]
        for group in trips.flight_groups(flights):
            moved_at = trips.departure_moved_at(conn, [s["id"] for s in group])
            for seg in group:
                ref = f"{seg['id']}@{seg['start_local']}"
                moved = moved_at.get(seg["id"], -1.0) >= since
                if not (moved or ref in waiting):
                    continue
                leaves = trips.instant(seg["start_local"], seg["start_zone"])
                if leaves - CHECK_IN_AHEAD <= now < leaves:
                    found[ref] = seg
                    break
    return found


def times_due(conn: db.Connection, since: float, now: datetime, sender_for: Callable[[], Send]) -> int:
    changed = conn.execute(select(Segment.id).where(Segment.email_updated >= since, Segment.kind == "flight")).fetchone() is not None
    waiting_any = conn.execute(select(ReminderSent.id).where(ReminderSent.kind == "times_retry")).fetchone() is not None
    if not changed and not waiting_any:
        return 0
    send = sender_for()
    stamp = now.timestamp()
    sent = 0
    for owner in sorted(set(conn.execute(select(PushDevice.owner_sub)).scalars()) | app_push.owners(conn)):
        waiting = _times_waiting(conn, owner)
        if not prefs(conn, owner)["check_in"]:
            _times_forget(conn, owner, waiting)
            continue
        found = _times_changed(conn, owner, since, now, waiting)
        _times_forget(conn, owner, waiting - set(found))
        for ref, seg in found.items():
            if _sent(conn, owner, "times", ref):
                _times_forget(conn, owner, [ref])
            elif _deliver(conn, owner, times_message(seg), send):
                _record(conn, owner, "times", ref, stamp)
                _times_forget(conn, owner, [ref])
                sent += 1
            else:
                _record(conn, owner, "times_retry", ref, stamp)
    return sent


def _retries(conn: db.Connection, owner: str) -> list[str]:
    return list(conn.execute(select(ReminderSent.ref).where(ReminderSent.owner_sub == owner, ReminderSent.kind == "review_retry")
                             .order_by(ReminderSent.id)).scalars())


def _forget_retries(conn: db.Connection, owner: str, refs: Collection[str]) -> None:
    if refs:
        conn.execute(delete(ReminderSent).where(ReminderSent.owner_sub == owner, ReminderSent.kind == "review_retry", ReminderSent.ref.in_(sorted(refs))))


def _unsent_review(conn: db.Connection, owner: str, arrived: list[str], mailbox_ids: Collection[int]) -> list[str]:
    retries = _retries(conn, owner)
    if retries:
        waiting = set(review.arrived(conn, owner, 0.0, mailbox_ids))
        scanned = {str(n) for n in mailbox_ids}
        _forget_retries(conn, owner, [ref for ref in retries if ref.split("/", 1)[0] in scanned and ref not in waiting])
        arrived = list(dict.fromkeys([*arrived, *(ref for ref in retries if ref in waiting)]))
    told = set(conn.execute(select(ReminderSent.ref).where(ReminderSent.owner_sub == owner, ReminderSent.kind == "review",
                                                           ReminderSent.ref.in_(arrived))).scalars()) if arrived else set()
    return [ref for ref in arrived if ref not in told]


def review_due(conn: db.Connection, since: float, now: float, send: Send, mailbox_ids: Collection[int]) -> int:
    end_lapsed(conn, now)
    sent = 0
    for owner in sorted(set(conn.execute(select(PushDevice.owner_sub)).scalars()) | app_push.owners(conn)):
        if not prefs(conn, owner)["review"]:
            continue
        arrived = _unsent_review(conn, owner, review.arrived(conn, owner, since, mailbox_ids), mailbox_ids)
        if arrived and _deliver(conn, owner, review_message(len(arrived)), send):
            for ref in arrived:
                _record(conn, owner, "review", ref, now)
            _forget_retries(conn, owner, arrived)
            sent += 1
        else:
            for ref in arrived:
                _record(conn, owner, "review_retry", ref, now)
    return sent


def sender(conn: db.Connection, subject: str) -> Send:
    vapid, _public = webpush.vapid_keys(conn)

    def send(device: Device, message: dict[str, Any]) -> None:
        webpush.send({"endpoint": device.endpoint, "p256dh": device.p256dh, "auth": device.auth}, message, vapid, subject)
    return send

