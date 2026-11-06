import base64
import json
import os
import tempfile
import time
import unittest
from datetime import UTC, date, datetime
from unittest import mock

import httpx

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from sqlalchemy import delete, select

from waypoint import monitoring
from waypoint.domain import app_push, reminders
from waypoint.providers import apns
from waypoint.storage import db
from waypoint.storage.models import AppDevice
from tests import test_reminders as base

TOKEN = "ab12" * 16
OTHER = "cd34" * 16
KEY_ID = "ABC123DEFG"
TEAM_ID = "TEAM123456"
TOPIC = "com.example.waypoint"
FLIGHT_DAY = datetime(2026, 11, 20, 0, 1, tzinfo=UTC)
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PEM = PRIVATE.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def apple_env(path):
    return {app_push.KEY_FILE_ENV: path, app_push.KEY_ID_ENV: KEY_ID, app_push.TEAM_ID_ENV: TEAM_ID, app_push.TOPIC_ENV: TOPIC}


class Apple(base.Reminders):

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.key_path = os.path.join(folder.name, "AuthKey.p8")
        with open(self.key_path, "wb") as f:
            f.write(PEM)
        patch = mock.patch.dict(os.environ, apple_env(self.key_path))
        patch.start()
        self.addCleanup(patch.stop)
        self.pushed = mock.patch.object(apns, "push")
        self.push = self.pushed.start()
        self.addCleanup(self.pushed.stop)

    def phone(self, owner="u-jane", token=TOKEN, environment="production"):
        return app_push.add_device(self.c, owner, token, environment, time.time())


class DeviceTests(Apple):

    def test_a_second_registration_of_the_same_phone_updates_it(self):
        first = self.phone()
        again = self.phone(environment="sandbox")
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(self.c.orm.scalars(select(AppDevice)).one().environment, "sandbox")

    def test_it_refuses_what_is_not_an_apns_registration(self):
        for token, environment in (("short", "production"), (TOKEN, "staging"), ("not hex! " * 8, "production"), (TOKEN + "zz", "production")):
            with self.assertRaises(app_push.Invalid):
                self.phone(token=token, environment=environment)

    def test_there_is_a_limit_per_member(self):
        for n in range(app_push.MAX_DEVICES):
            self.phone(token=f"{n:02x}" * 32)
        with self.assertRaises(app_push.Invalid):
            self.phone(token="ee" * 32)
        self.phone(token="00" * 32, environment="sandbox")
        self.phone(owner="u-sam", token="ee" * 32)

    def test_a_phone_moves_to_the_member_who_registers_it_next(self):
        self.phone(owner="u-jane")
        self.phone(owner="u-sam")
        self.assertEqual(app_push.devices(self.c, "u-jane"), [])
        self.assertEqual(len(app_push.devices(self.c, "u-sam")), 1)
        self.assertEqual(app_push.wake(self.c, "u-jane", "check-in"), (0, 0))
        self.assertEqual(app_push.wake(self.c, "u-sam", "check-in"), (1, 1))
        self.assertEqual(self.push.call_args.args[1:3], (TOKEN, "production"))

    def test_only_the_owner_removes_a_phone(self):
        added = self.phone()
        self.assertFalse(app_push.remove_device(self.c, "u-sam", added["id"]))
        self.assertTrue(app_push.remove_device(self.c, "u-jane", added["id"]))
        self.assertEqual(app_push.devices(self.c, "u-jane"), [])

    def test_push_is_off_unless_the_whole_key_is_set_and_readable(self):
        self.assertTrue(app_push.enabled())
        for name in apple_env(self.key_path):
            with mock.patch.dict(os.environ, {name: ""}):
                self.assertFalse(app_push.enabled(), name)
        for name, value in ((app_push.KEY_ID_ENV, "short"), (app_push.TEAM_ID_ENV, "lower12345"), (app_push.TOPIC_ENV, "has space"), (app_push.KEY_FILE_ENV, "/nonexistent/AuthKey.p8")):
            with mock.patch.dict(os.environ, {name: value}):
                self.assertFalse(app_push.enabled(), name)
        with open(self.key_path, "wb") as f:
            f.write(b"not a key")
        self.assertFalse(app_push.enabled())


class SendingTests(Apple):

    def due(self, now=FLIGHT_DAY, hour=3):
        return reminders.run_due(self.c, now, date(2026, 11, 20), hour, self.send)

    def test_a_phone_alone_is_woken_for_the_day_of_summary_with_a_tag_of_the_date_alone(self):
        self.phone()
        self.assertEqual(self.due(hour=8), 2)
        self.assertEqual([c.args[3] for c in self.push.call_args_list], [f"check-in-{self.out['id']}", "day-of-2026-11-20"])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.due(hour=8), 0)

    def test_a_phone_alone_is_woken_for_check_in_with_the_reminders_tag_and_nothing_else(self):
        self.phone()
        self.assertEqual(self.due(), 1)
        self.push.assert_called_once_with(app_push.credentials(), TOKEN, "production", f"check-in-{self.out['id']}")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.due(), 0)
        self.push.assert_called_once()

    def test_a_member_with_a_browser_and_a_phone_gets_both(self):
        self.device()
        self.phone()
        self.assertEqual(self.due(), 1)
        self.assertEqual(len(self.sent), 1)
        self.push.assert_called_once()

    def test_a_failed_phone_wake_is_retried_even_when_the_browser_got_it(self):
        self.device()
        self.phone()
        self.push.side_effect = RuntimeError("couldn't reach Apple's push service")
        with mock.patch.object(monitoring, "report"):
            self.assertEqual(self.due(), 0)
        self.push.side_effect = None
        self.assertEqual(self.due(), 1)

    def test_no_phone_is_woken_when_push_is_off(self):
        self.phone()
        with mock.patch.dict(os.environ, {app_push.KEY_FILE_ENV: ""}):
            self.assertEqual(self.due(), 0)
        self.push.assert_not_called()

    def test_the_members_own_reminder_choices_apply(self):
        self.phone()
        reminders.set_prefs(self.c, "u-jane", {"check_in": False, "day_of": False, "review": True})
        self.assertEqual(self.due(), 0)
        self.push.assert_not_called()

    def test_a_phone_apple_says_is_gone_is_dropped_and_the_reminder_counts_as_sent(self):
        self.phone()
        self.push.side_effect = apns.Gone(TOKEN)
        self.assertEqual(self.due(), 1)
        self.assertEqual(app_push.devices(self.c, "u-jane"), [])

    def test_apple_being_down_is_reported_and_tried_again_next_time(self):
        self.phone()
        self.push.side_effect = RuntimeError("couldn't reach Apple's push service")
        with mock.patch.object(monitoring, "report") as report:
            self.assertEqual(self.due(), 0)
            report.assert_called_once()
        self.assertEqual(len(app_push.devices(self.c, "u-jane")), 1)
        self.push.side_effect = None
        self.assertEqual(self.due(), 1)


class LapseTests(Apple):

    def test_a_phone_ends_when_its_owner_can_no_longer_sign_in(self):
        self.phone("u-jane")
        self.phone("u-sam", token=OTHER)
        allowed = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "u-jane@example.com"}
        with mock.patch.dict(os.environ, allowed):
            self.assertEqual(reminders.end_lapsed(self.c), 1)
        self.assertEqual(app_push.devices(self.c, "u-sam"), [])
        self.assertEqual(len(app_push.devices(self.c, "u-jane")), 1)


class AppleCallTests(unittest.TestCase):

    def setUp(self):
        apns._issued.clear()
        self.creds = apns.Credentials(PEM, KEY_ID, TEAM_ID, TOPIC)

    def test_the_provider_token_is_a_valid_es256_jwt_and_is_reused_until_it_ages(self):
        token = apns.provider_token(self.creds, 1000.0)
        head, claims, signature = token.split(".")
        pad = lambda part: base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
        self.assertEqual(json.loads(pad(head)), {"alg": "ES256", "kid": KEY_ID})
        self.assertEqual(json.loads(pad(claims)), {"iss": TEAM_ID, "iat": 1000})
        raw = pad(signature)
        PRIVATE.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                                    f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
        self.assertEqual(apns.provider_token(self.creds, 1000.0 + apns.JWT_LIFETIME - 1), token)
        self.assertNotEqual(apns.provider_token(self.creds, 1000.0 + apns.JWT_LIFETIME + 1), token)

    def test_it_sends_the_fixed_notification_to_the_right_host_with_the_tag_as_collapse_id(self):
        with mock.patch.object(apns, "post", return_value=(200, b"")) as posted:
            apns.push(self.creds, TOKEN, "sandbox", "check-in-1")
            apns.push(self.creds, TOKEN, "production")
        url, headers, content, _timeout = posted.call_args_list[0].args
        self.assertEqual(url, f"https://api.sandbox.push.apple.com/3/device/{TOKEN}")
        self.assertEqual((headers["apns-topic"], headers["apns-push-type"], headers["apns-collapse-id"]), (TOPIC, "alert", "check-in-1"))
        self.assertTrue(headers["authorization"].startswith("bearer "))
        self.assertEqual(json.loads(content)["aps"]["alert"]["body"], "Open Waypoint to see an update.")
        self.assertEqual(posted.call_args_list[1].args[0], f"https://api.push.apple.com/3/device/{TOKEN}")
        self.assertNotIn("apns-collapse-id", posted.call_args_list[1].args[1])

    def test_what_apple_says_decides_whether_the_phone_is_kept(self):
        for status, reason in ((410, "Unregistered"), (400, "BadDeviceToken"), (400, "DeviceTokenNotForTopic")):
            with mock.patch.object(apns, "post", return_value=(status, json.dumps({"reason": reason}).encode())), self.assertRaises(apns.Gone):
                apns.push(self.creds, TOKEN, "production")
        for status, body in ((403, b'{"reason":"ExpiredProviderToken"}'), (429, b"{}"), (500, b"not json"), (503, b"")):
            with mock.patch.object(apns, "post", return_value=(status, body)), self.assertRaises(RuntimeError) as caught:
                apns.push(self.creds, TOKEN, "production")
            self.assertNotIn(TOKEN, str(caught.exception))
        with mock.patch.object(apns, "post", side_effect=httpx.ConnectError("down")), self.assertRaises(RuntimeError):
            apns.push(self.creds, TOKEN, "production")

    def test_it_does_not_follow_redirects(self):
        with mock.patch.object(apns.httpx, "Client") as client:
            client.return_value.__enter__.return_value.post.return_value = mock.Mock(status_code=200, content=b"")
            apns.post("https://api.push.apple.com/3/device/x", {}, b"{}", 5)
        self.assertIs(client.call_args.kwargs["follow_redirects"], False)
        self.assertIs(client.call_args.kwargs["http2"], True)


class ApiTests(base.RouteCase):

    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(delete(AppDevice))
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.key_path = os.path.join(folder.name, "AuthKey.p8")
        with open(self.key_path, "wb") as f:
            f.write(PEM)
        patch = mock.patch.dict(os.environ, apple_env(self.key_path))
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_app_learns_whether_push_is_on_and_its_own_phones(self):
        self.assertEqual(self.call("ana", "GET", "/api/reminders/app"), (200, {"enabled": True, "devices": []}))
        with mock.patch.dict(os.environ, {app_push.KEY_FILE_ENV: ""}):
            self.assertEqual(self.call("ana", "GET", "/api/reminders/app"), (200, {"enabled": False, "devices": []}))

    def test_a_phone_is_registered_listed_and_removed_by_its_owner_alone(self):
        status, added = self.call("ana", "POST", "/api/reminders/app/devices", {"token": TOKEN, "environment": "production"})
        self.assertEqual((status, added["service"]), (200, "iPhone"))
        self.assertEqual(len(self.call("ana", "GET", "/api/reminders/app")[1]["devices"]), 1)
        self.assertEqual(self.call("ben", "GET", "/api/reminders/app")[1]["devices"], [])
        self.assertEqual(self.call("ben", "DELETE", f"/api/reminders/app/devices/{added['id']}")[0], 404)
        self.assertEqual(self.call("ana", "DELETE", "/api/reminders/app/devices/x")[0], 404)
        self.assertEqual(self.call("ana", "DELETE", f"/api/reminders/app/devices/{added['id']}"), (200, {"ok": True}))

    def test_it_refuses_bad_registrations_without_quoting_them_and_registration_when_push_is_off(self):
        for body in ({}, {"token": TOKEN}, {"token": 5, "environment": "production"}, {"token": "CANARY-TOKEN", "environment": "production"}, {"token": TOKEN, "environment": "CANARY-ENV"}):
            status, got = self.call("ana", "POST", "/api/reminders/app/devices", body)
            self.assertEqual(status, 400)
            self.assertNotIn("CANARY", got["error"])
        with mock.patch.dict(os.environ, {app_push.KEY_FILE_ENV: ""}):
            self.assertEqual(self.call("ana", "POST", "/api/reminders/app/devices", {"token": TOKEN, "environment": "production"})[0], 400)


if __name__ == "__main__":
    unittest.main()
