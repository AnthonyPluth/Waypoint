import io
import os
import time
import unittest
import urllib.error
from datetime import UTC, date, datetime
from unittest import mock

from sqlalchemy import delete, select

from waypoint import monitoring
from waypoint.domain import app_push, reminders
from waypoint.providers import relay
from waypoint.storage import db
from waypoint.storage.models import AppDevice
from tests import test_reminders as base

RELAY = "https://relay.example.com"
DEVICE = "dev_abcdefgh12345"
SECRET = "s" * 43
FLIGHT_DAY = datetime(2026, 11, 20, 0, 1, tzinfo=UTC)


class Relay(base.Reminders):

    def setUp(self):
        super().setUp()
        patch = mock.patch.dict(os.environ, {app_push.RELAY_ENV: RELAY})
        patch.start()
        self.addCleanup(patch.stop)
        self.woken = mock.patch.object(relay, "wake")
        self.wake = self.woken.start()
        self.addCleanup(self.woken.stop)

    def phone(self, owner="u-jane", device=DEVICE, secret=SECRET):
        return app_push.add_device(self.c, owner, device, secret, time.time())


class DeviceTests(Relay):

    def test_the_secret_is_kept_encrypted_and_a_second_registration_replaces_it(self):
        first = self.phone()
        stored = self.c.orm.scalars(select(AppDevice)).one()
        self.assertTrue(stored.secret.startswith("enc:"))
        self.assertNotIn(SECRET, stored.secret)
        again = self.phone(secret="t" * 43)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(app_push.devices(self.c, "u-jane")), 1)
        app_push.wake(self.c, "u-jane", "x")
        self.assertEqual(self.wake.call_args.args[2], "t" * 43)

    def test_it_refuses_what_is_not_a_relay_registration(self):
        for device, secret in (("short", SECRET), (DEVICE, "short"), ("bad id!!!!", SECRET), (DEVICE, "bad secret " * 4)):
            with self.assertRaises(app_push.Invalid):
                self.phone(device=device, secret=secret)

    def test_there_is_a_limit_per_member(self):
        for n in range(app_push.MAX_DEVICES):
            self.phone(device=f"device-number-{n:02d}")
        with self.assertRaises(app_push.Invalid):
            self.phone(device="device-number-extra")
        self.phone(device="device-number-00", secret="u" * 43)
        self.phone(owner="u-sam", device="device-number-extra")

    def test_only_the_owner_removes_a_phone(self):
        added = self.phone()
        self.assertFalse(app_push.remove_device(self.c, "u-sam", added["id"]))
        self.assertTrue(app_push.remove_device(self.c, "u-jane", added["id"]))
        self.assertEqual(app_push.devices(self.c, "u-jane"), [])

    def test_the_relay_address_must_be_https_and_is_off_unless_set(self):
        for value in ("", "http://relay.example.com", "relay.example.com", "https://", "https://u:p@relay.example.com", "https://relay.example.com/?x=1"):
            with mock.patch.dict(os.environ, {app_push.RELAY_ENV: value}):
                self.assertIsNone(app_push.relay_url(), value)
        with mock.patch.dict(os.environ, {app_push.RELAY_ENV: " https://relay.example.com/ "}):
            self.assertEqual(app_push.relay_url(), RELAY)


class SendingTests(Relay):

    def due(self, now=FLIGHT_DAY, hour=3):
        return reminders.run_due(self.c, now, date(2026, 11, 20), hour, self.send)

    def test_a_phone_alone_is_woken_for_check_in_with_the_reminders_tag_and_nothing_else(self):
        self.phone()
        self.assertEqual(self.due(), 1)
        self.wake.assert_called_once_with(RELAY, DEVICE, SECRET, f"check-in-{self.out['id']}")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.due(), 0)
        self.wake.assert_called_once()

    def test_a_member_with_a_browser_and_a_phone_gets_both(self):
        self.device()
        self.phone()
        self.assertEqual(self.due(), 1)
        self.assertEqual(len(self.sent), 1)
        self.wake.assert_called_once()

    def test_no_phone_is_woken_when_the_relay_is_off(self):
        self.phone()
        with mock.patch.dict(os.environ, {app_push.RELAY_ENV: ""}):
            self.assertEqual(self.due(), 0)
        self.wake.assert_not_called()

    def test_the_members_own_reminder_choices_apply(self):
        self.phone()
        reminders.set_prefs(self.c, "u-jane", {"check_in": False, "day_of": False, "review": True})
        self.assertEqual(self.due(), 0)
        self.wake.assert_not_called()

    def test_a_phone_the_relay_forgot_is_dropped_and_the_reminder_counts_as_sent(self):
        self.phone()
        self.wake.side_effect = relay.Gone(DEVICE)
        self.assertEqual(self.due(), 1)
        self.assertEqual(app_push.devices(self.c, "u-jane"), [])

    def test_a_relay_that_is_down_is_reported_and_tried_again_next_time(self):
        self.phone()
        self.wake.side_effect = RuntimeError("couldn't reach the push relay")
        with mock.patch.object(monitoring, "report") as report:
            self.assertEqual(self.due(), 0)
            report.assert_called_once()
        self.assertEqual(len(app_push.devices(self.c, "u-jane")), 1)
        self.wake.side_effect = None
        self.assertEqual(self.due(), 1)


class LapseTests(Relay):

    def test_a_phone_ends_when_its_owner_can_no_longer_sign_in(self):
        self.phone("u-jane")
        self.phone("u-sam")
        allowed = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "u-jane@example.com"}
        with mock.patch.dict(os.environ, allowed):
            self.assertEqual(reminders.end_lapsed(self.c), 1)
        self.assertEqual(app_push.devices(self.c, "u-sam"), [])
        self.assertEqual(len(app_push.devices(self.c, "u-jane")), 1)


class RelayCallTests(unittest.TestCase):

    def test_it_asks_the_relay_to_wake_the_device_with_the_secret(self):
        with mock.patch.object(relay.tls, "urlopen") as opened:
            opened.return_value.__enter__.return_value.read.return_value = b"{}"
            relay.wake(RELAY + "/", "dev/with space", SECRET, "check-in-1")
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, f"{RELAY}/v1/devices/dev%2Fwith%20space/wake")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {SECRET}")
        self.assertEqual(request.data, b'{"kind": "alert", "collapse_id": "check-in-1"}')

    def test_what_the_relay_says_decides_whether_the_phone_is_kept(self):
        def says(code):
            error = urllib.error.HTTPError(RELAY, code, "x", {}, io.BytesIO(b""))
            self.addCleanup(error.close)
            return error
        for code in (401, 404, 410):
            with mock.patch.object(relay.tls, "urlopen", side_effect=says(code)), self.assertRaises(relay.Gone):
                relay.wake(RELAY, DEVICE, SECRET)
        for failure in (says(429), says(502), urllib.error.URLError("down"), TimeoutError()):
            with mock.patch.object(relay.tls, "urlopen", side_effect=failure), self.assertRaises(RuntimeError):
                relay.wake(RELAY, DEVICE, SECRET)


class ApiTests(base.RouteCase):

    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(delete(AppDevice))
        patch = mock.patch.dict(os.environ, {app_push.RELAY_ENV: RELAY})
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_app_learns_the_relay_address_and_its_own_phones(self):
        self.assertEqual(self.call("ana", "GET", "/api/reminders/app"), (200, {"relay": RELAY, "devices": []}))
        with mock.patch.dict(os.environ, {app_push.RELAY_ENV: ""}):
            self.assertEqual(self.call("ana", "GET", "/api/reminders/app"), (200, {"relay": None, "devices": []}))

    def test_a_phone_is_registered_listed_and_removed_by_its_owner_alone(self):
        status, added = self.call("ana", "POST", "/api/reminders/app/devices", {"device_id": DEVICE, "secret": SECRET})
        self.assertEqual((status, added["service"]), (200, "iPhone"))
        self.assertEqual(len(self.call("ana", "GET", "/api/reminders/app")[1]["devices"]), 1)
        self.assertEqual(self.call("ben", "GET", "/api/reminders/app")[1]["devices"], [])
        self.assertEqual(self.call("ben", "DELETE", f"/api/reminders/app/devices/{added['id']}")[0], 404)
        self.assertEqual(self.call("ana", "DELETE", "/api/reminders/app/devices/x")[0], 404)
        self.assertEqual(self.call("ana", "DELETE", f"/api/reminders/app/devices/{added['id']}"), (200, {"ok": True}))

    def test_it_refuses_bad_registrations_without_quoting_them_and_registration_when_the_relay_is_off(self):
        for body in ({}, {"device_id": DEVICE}, {"device_id": 5, "secret": SECRET}, {"device_id": DEVICE, "secret": "CANARY-SECRET"}):
            status, got = self.call("ana", "POST", "/api/reminders/app/devices", body)
            self.assertEqual(status, 400)
            self.assertNotIn("CANARY-SECRET", got["error"])
        with mock.patch.dict(os.environ, {app_push.RELAY_ENV: ""}):
            self.assertEqual(self.call("ana", "POST", "/api/reminders/app/devices", {"device_id": DEVICE, "secret": SECRET})[0], 400)


if __name__ == "__main__":
    unittest.main()
