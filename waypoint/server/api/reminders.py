"""Reminders and the calendar feed (Settings → Reminders): the signed-in member's own devices, which reminders they get,
and their private calendar feed. Each member sees and changes only their own."""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from ...domain import reminders
from ...providers import webpush
from ..common import ApiError, row_id
from ..contract import DeviceBody, FeedMade, Ok, ReminderDevice, Reminders, RemindersBody
from .mailboxes import owner, public_base

NO_DEVICE = "No such device"


def _flag(body: Mapping[str, Any], key: str) -> bool:
    value = body.get(key)
    if not isinstance(value, bool):
        raise ApiError(f'Send "{key}" as true or false')
    return value


def _view(conn) -> Reminders:
    me = owner()
    chosen = reminders.prefs(conn, me)
    return {"public_key": webpush.vapid_keys(conn)[1], "check_in": chosen["check_in"], "day_of": chosen["day_of"],
            "devices": [ReminderDevice(**d) for d in reminders.devices(conn, me)], "feed": reminders.feed_on(conn, me)}


def api_reminders(conn, _q, _b) -> Reminders:
    """Which reminders the member gets, their devices, and whether they have a calendar feed. A device or feed whose owner
    lost access is ended first (they can't open Settings to turn it off)."""
    reminders.end_lapsed(conn)
    return _view(conn)


def api_reminders_set(conn, _q, body: RemindersBody) -> Reminders:
    """Choose which reminders to get."""
    reminders.set_prefs(conn, owner(), {"check_in": _flag(body, "check_in"), "day_of": _flag(body, "day_of")})
    return _view(conn)


def api_device_add(conn, _q, body: DeviceBody) -> ReminderDevice:
    """Turn notifications on for this browser (its push subscription)."""
    texts = []
    for key in ("endpoint", "p256dh", "auth"):
        if not isinstance(body.get(key), str):
            raise ApiError(f'Send "{key}" as text')
        texts.append(body[key])
    try:
        return ReminderDevice(**reminders.add_device(conn, owner(), texts[0], texts[1], texts[2], time.time()))
    except reminders.Invalid as e:
        raise ApiError(str(e)) from None


def api_device_remove(conn, _q, _b, device_id) -> Ok:
    """Stop notifications to one of the member's devices."""
    if not reminders.remove_device(conn, owner(), row_id(device_id, NO_DEVICE)):
        raise ApiError(NO_DEVICE, 404)
    return {"ok": True}


def api_feed_make(conn, _q, _b) -> FeedMade:
    """Make the member's calendar feed, or a new address for it (the old one stops working at once). The address, with its
    key, is in this answer only: Waypoint keeps just a hash of the key."""
    base = public_base("The calendar feed")
    key = reminders.new_feed_key(conn, owner(), time.time())
    return {"url": f"{base}/feed/{key}.ics"}


def api_feed_off(conn, _q, _b) -> Ok:
    """Turn the member's calendar feed off."""
    reminders.feed_off(conn, owner())
    return {"ok": True}
