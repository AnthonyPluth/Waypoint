"""tests/privacy.py's no_leaks: it catches a canary wherever Waypoint could let one out, and passes when nothing
escapes (an encrypted value included)."""
import logging
import unittest

from waypoint import monitoring
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

    def test_sentry(self):
        def report():
            try:
                raise ValueError(f"couldn't read {CANARY}")
            except ValueError:
                monitoring.report()
        self.assertIn("what was sent to Sentry", self.leaks(report))
        self.assertIn("what was sent to Sentry", self.leaks(lambda: monitoring.send_log(f"read {CANARY}")))

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
