"""tests/privacy.py's no_leaks: it catches a canary wherever Waypoint could let one out, and passes when nothing
escapes (an encrypted value included)."""
import io
import logging
import unittest
import urllib.request
from unittest import mock

from waypoint import monitoring, tls
from waypoint.storage import db
from waypoint.storage import settings_keys as sk
from tests.privacy import no_leaks
from tests.shared import own_database

CANARY = "CANARY-ZQ7-4471"


class NoLeaksTests(unittest.TestCase):
    def setUp(self):
        self.path = own_database(self)

    def leaks(self, block):
        """no_leaks' failure message for `block`, or None when it passes."""
        try:
            with no_leaks(self, CANARY, database=self.path):
                block()
        except AssertionError as e:
            return str(e)
        return None

    def test_nothing_escapes(self):
        def quiet():
            monitoring.log("Scanned the mailbox.")
            with db.session() as conn:
                db.set_setting(conn, sk.VAPID_PRIVATE_KEY, CANARY)   # a secret: stored encrypted
        self.assertIsNone(self.leaks(quiet))

    def test_the_log(self):
        self.assertIn("what was printed", self.leaks(lambda: monitoring.log(f"read {CANARY}")))
        self.assertIn("stderr", self.leaks(lambda: monitoring.log(f"read {CANARY}", stderr=True)))
        self.assertIn("Python's logging", self.leaks(lambda: logging.getLogger("x").warning("read %s", CANARY)))

    def test_what_is_sent_to_another_service(self):
        def send():
            req = urllib.request.Request("https://api.example.invalid/x", data=f"name={CANARY}".encode())
            tls.urlopen(req, 1)
        with mock.patch.object(urllib.request.OpenerDirector, "open", return_value=io.BytesIO(b"{}")):
            self.assertIn("what was sent to another service", self.leaks(send))
            self.assertIn("what was sent to another service",
                          self.leaks(lambda: tls.urlopen(f"https://api.example.invalid/x?q={CANARY}", 1)))
            with no_leaks(self, CANARY, sent_ok=True):   # the one opt-in path checks its own request
                send()

    def test_the_database(self):
        def store():
            with db.session() as conn:
                db.set_setting(conn, sk.LAST_BACKUP, CANARY)   # not a secret: stored as it is
        self.assertIn(f"{CANARY} in settings.value", self.leaks(store))

    def test_canaries_must_be_distinctive(self):
        with self.assertRaises(AssertionError), no_leaks(self, "abc"):
            pass


if __name__ == "__main__":
    unittest.main()
