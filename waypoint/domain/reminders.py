"""Reminders and the calendar feed: each member's notification devices, which reminders they get, and the private key to
their calendar feed.

A device and a feed belong to the member who made them, and end when that member can no longer sign in
(oidc.access_lapsed, AGENTS.md, "Access that outlives the person"). Reminders and the feed hold only what a booking holds,
and only for the trips the member can see (waypoint/domain/visibility.py): no loyalty or Known Traveler number is ever
read here (AGENTS.md, "IDs are for the household"). The feed's key is shown once, when it's made, and kept only as a hash.

The two reminders: "Check-in opens", 24 hours before a flight leaves (a moment worked out from the flight's wall-clock
time and its airport's zone, only to compare it with now), and the day-of summary, sent from DAY_OF_HOUR (the machine's
local time) on each day something starts, listing the day's bookings by their own wall-clock times."""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, TypedDict

from sqlalchemy import delete, select

from .. import monitoring, oidc
from ..providers import webpush
from ..storage import db
from ..storage.models import CalendarFeed, PushDevice, ReminderPrefs, ReminderSent, User
from . import calendar, people, trips
from .trips import SegmentOut, TripOut
from .visibility import Viewer

Kind = Literal["check_in", "day_of"]
CHECK_IN_AHEAD = timedelta(hours=24)
DAY_OF_HOUR = 7          # the machine's local hour from which a day's summary goes out
LOCAL_OWNER = "local"    # who everything belongs to without sign-in (your own machine)
MAX_DEVICES = 10         # a member's, so a stuck page can't fill the table
MAX_ITEMS = 5            # bookings named in a day's summary; the rest are counted
ENDPOINT_LIMIT = 2048
KEY_LIMIT = 256


class Invalid(ValueError):
    """What a person sent isn't a push subscription Waypoint will use; the message says why, never what was sent."""


class Prefs(TypedDict):
    check_in: bool
    day_of: bool


class DeviceOut(TypedDict):
    id: int
    service: str       # the push service's host (fcm.googleapis.com, …), so a person can tell their devices apart
    created: float


@dataclass(frozen=True)
class Device:
    id: int
    endpoint: str
    p256dh: str
    auth: str


Send = Callable[[Device, dict[str, Any]], None]   # raises webpush.Gone for a device that no longer exists


# ------------------------------------------------------------------------------------------------ who it belongs to

def viewer_for(conn: db.Connection, owner: str) -> Viewer:
    """The trips an owner sees: the person their sign-in belongs to; without sign-in, the whole local household."""
    if owner == LOCAL_OWNER:
        return Viewer(None, household=True)
    return Viewer(people.person_for_sub(conn, owner))


def lapsed(conn: db.Connection, owner: str, now: float) -> bool:
    """Whether the owner can no longer sign in, so what they made must end."""
    email = conn.execute(select(User.email).where(User.sub == owner)).scalar()
    return oidc.access_lapsed(conn, owner, email, now) is not None


def _forget(conn: db.Connection, owner: str) -> None:
    conn.execute(delete(PushDevice).where(PushDevice.owner_sub == owner))
    conn.execute(delete(CalendarFeed).where(CalendarFeed.owner_sub == owner))
    conn.execute(delete(ReminderPrefs).where(ReminderPrefs.owner_sub == owner))
    conn.execute(delete(ReminderSent).where(ReminderSent.owner_sub == owner))


def end_lapsed(conn: db.Connection, now: float | None = None) -> int:
    """End the devices and feed of everyone who can no longer sign in, without waiting for something to use them. Returns
    how many people's ended."""
    now = time.time() if now is None else now
    owners = set(conn.execute(select(PushDevice.owner_sub)).scalars()) | set(conn.execute(select(CalendarFeed.owner_sub)).scalars())
    gone = [o for o in sorted(owners) if lapsed(conn, o, now)]
    for owner in gone:
        _forget(conn, owner)
    return len(gone)


# ------------------------------------------------------------------------------------------------ preferences

def prefs(conn: db.Connection, owner: str) -> Prefs:
    """Which reminders the owner gets (both, until they choose)."""
    row = conn.orm.get(ReminderPrefs, owner)
    return {"check_in": row.check_in, "day_of": row.day_of} if row else {"check_in": True, "day_of": True}


def set_prefs(conn: db.Connection, owner: str, chosen: Prefs) -> Prefs:
    db.upsert(conn, ReminderPrefs, {"owner_sub": owner, **chosen}, key=["owner_sub"])
    return prefs(conn, owner)


# ------------------------------------------------------------------------------------------------ devices

def check_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    """Raises Invalid unless this is a browser's push subscription: an https address on a named host (a push service's,
    never an address inside the network), and the keys it came with."""
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


def devices(conn: db.Connection, owner: str) -> list[DeviceOut]:
    rows = conn.orm.scalars(select(PushDevice).where(PushDevice.owner_sub == owner).order_by(PushDevice.id)).all()
    return [{"id": d.id, "service": urllib.parse.urlsplit(d.endpoint).hostname or "", "created": d.created} for d in rows]


def add_device(conn: db.Connection, owner: str, endpoint: str, p256dh: str, auth: str, now: float) -> DeviceOut:
    """Turn notifications on for a browser (again, for one that's already here: it keeps one row, now this owner's).
    Raises Invalid for a subscription Waypoint won't use, or when the owner already has MAX_DEVICES."""
    check_subscription(endpoint, p256dh, auth)
    mine = conn.orm.scalars(select(PushDevice).where(PushDevice.owner_sub == owner)).all()
    if len(mine) >= MAX_DEVICES and endpoint not in {d.endpoint for d in mine}:
        raise Invalid(f"Turn notifications off on a device you no longer use first (at most {MAX_DEVICES}).")
    db.upsert(conn, PushDevice, {"owner_sub": owner, "endpoint": endpoint, "p256dh": p256dh, "auth": auth, "created": now},
              key=["endpoint"])
    found = conn.orm.scalars(select(PushDevice).where(PushDevice.endpoint == endpoint)).one()
    conn.orm.refresh(found)
    return {"id": found.id, "service": urllib.parse.urlsplit(found.endpoint).hostname or "", "created": found.created}


def remove_device(conn: db.Connection, owner: str, device_id: int) -> bool:
    """Forget one of the owner's devices; False when it isn't theirs (or isn't there)."""
    return conn.execute(delete(PushDevice).where(PushDevice.id == device_id, PushDevice.owner_sub == owner)).rowcount > 0


# ------------------------------------------------------------------------------------------------ the calendar feed

def key_hash(key: str) -> str:
    """What's kept of a feed key. The key is 256 random bits, so a plain SHA-256 is enough: there's nothing to guess."""
    return hashlib.sha256(key.encode()).hexdigest()


def feed_on(conn: db.Connection, owner: str) -> bool:
    return conn.orm.get(CalendarFeed, owner) is not None


def new_feed_key(conn: db.Connection, owner: str, now: float) -> str:
    """Make the owner's feed key (the old one, if any, stops working at once) and return it: the only time it's known."""
    key = secrets.token_urlsafe(32)
    db.upsert(conn, CalendarFeed, {"owner_sub": owner, "key_hash": key_hash(key), "created": now}, key=["owner_sub"])
    return key


def feed_off(conn: db.Connection, owner: str) -> bool:
    return conn.execute(delete(CalendarFeed).where(CalendarFeed.owner_sub == owner)).rowcount > 0


def feed_owner(conn: db.Connection, key: str, now: float) -> str | None:
    """Whose feed this key opens, or None: no such key, or its owner can no longer sign in (the feed ends then)."""
    owner = conn.execute(select(CalendarFeed.owner_sub).where(CalendarFeed.key_hash == key_hash(key))).scalar()
    if owner is None:
        return None
    if lapsed(conn, owner, now):
        _forget(conn, owner)
        return None
    return str(owner)


def feed_text(conn: db.Connection, owner: str, now: datetime) -> str:
    """The owner's calendar: the trips they can see."""
    return calendar.feed(trips.listing(conn, viewer_for(conn, owner)), now)


# ------------------------------------------------------------------------------------------------ sending

def _clock(local: str) -> str:
    """A wall-clock time as it's written at its place, never converted."""
    return f"{datetime.fromisoformat(local):%H:%M}"


def _day(local: str) -> str:
    t = datetime.fromisoformat(local)
    return f"{t:%a} {t.day} {t:%b}"


def _label(seg: SegmentOut) -> str:
    where = " → ".join(p for p in (seg["origin"], seg["destination"]) if p)
    number = seg["details"].get("flight_number")
    names = {"flight": "Flight", "hotel": "Hotel check-in", "car": "Car pickup", "train": "Train"}
    return " ".join(p for p in (names[seg["kind"]], number, where) if p)


def check_in_message(seg: SegmentOut) -> dict[str, Any]:
    return {"title": "Check-in opens", "tag": f"check-in-{seg['id']}", "url": f"/#trip/{seg['trip_id']}",
            "body": f"{_label(seg)} leaves {_day(seg['start_local'])} at {_clock(seg['start_local'])}."}


def day_of_message(today_trips: list[tuple[SegmentOut, TripOut]], day: str) -> dict[str, Any]:
    items = sorted(today_trips, key=lambda p: p[0]["start_local"])
    lines = [f"{_clock(s['start_local'])} {_label(s)}" for s, _t in items[:MAX_ITEMS]]
    if len(items) > MAX_ITEMS:
        lines.append(f"and {len(items) - MAX_ITEMS} more")
    first = items[0][1]["id"]
    return {"title": "Today", "tag": f"day-of-{day}", "url": f"/#trip/{first}" if len({t['id'] for _s, t in items}) == 1 else "/",
            "body": "\n".join(lines)}


def _deliver(conn: db.Connection, owner: str, message: dict[str, Any], send: Send) -> bool:
    """Send to each of the owner's devices; dead ones are forgotten. True when at least one took it, or there's no one left
    to send to: only then is the reminder counted as sent (a push service that couldn't be reached is tried again)."""
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
        except Exception as e:   # the next round tries again; never the details (they may name an address)
            monitoring.report(e, values=False)
    return reached > 0 or tried == 0


def _record(conn: db.Connection, owner: str, kind: Kind, ref: str, now: float) -> None:
    db.insert_ignore(conn, ReminderSent, {"owner_sub": owner, "kind": kind, "ref": ref, "sent": now},
                     key=["owner_sub", "kind", "ref"])


def _sent(conn: db.Connection, owner: str, kind: Kind, ref: str) -> bool:
    return conn.execute(select(ReminderSent.id).where(ReminderSent.owner_sub == owner, ReminderSent.kind == kind,
                                                       ReminderSent.ref == ref)).fetchone() is not None


def run_due(conn: db.Connection, now: datetime, today: date, hour: int, send: Send) -> int:
    """Send the reminders that are due, to the devices of members who may still sign in. `now` is a moment (aware);
    `today` and `hour` are the machine's local day and hour (the day-of summary's). Each reminder goes out once. Returns
    how many were sent."""
    stamp = now.timestamp()
    end_lapsed(conn, stamp)
    sent = 0
    for owner in sorted(set(conn.execute(select(PushDevice.owner_sub)).scalars())):
        chosen = prefs(conn, owner)
        if not (chosen["check_in"] or chosen["day_of"]):
            continue
        mine = trips.listing(conn, viewer_for(conn, owner))
        if chosen["check_in"]:
            for trip in mine:
                for seg in trip["segments"]:
                    if seg["kind"] != "flight" or seg["status"] == "cancelled":
                        continue
                    leaves = trips.instant(seg["start_local"], seg["start_zone"])
                    ref = f"{seg['id']}@{seg['start_local']}"   # a flight moved to another time gets its own reminder
                    if leaves - CHECK_IN_AHEAD <= now < leaves and not _sent(conn, owner, "check_in", ref) \
                            and _deliver(conn, owner, check_in_message(seg), send):
                        _record(conn, owner, "check_in", ref, stamp)
                        sent += 1
        day = today.isoformat()
        if chosen["day_of"] and hour >= DAY_OF_HOUR and not _sent(conn, owner, "day_of", day):
            starting = [(s, t) for t in mine for s in t["segments"] if s["status"] != "cancelled" and s["start_local"][:10] == day]
            if starting and _deliver(conn, owner, day_of_message(starting, day), send):
                _record(conn, owner, "day_of", day, stamp)
                sent += 1
    return sent


def sender(conn: db.Connection, subject: str) -> Send:
    """The real thing: send through the push service, signed with this server's key."""
    vapid, _public = webpush.vapid_keys(conn)

    def send(device: Device, message: dict[str, Any]) -> None:
        webpush.send({"endpoint": device.endpoint, "p256dh": device.p256dh, "auth": device.auth}, message, vapid, subject)
    return send

