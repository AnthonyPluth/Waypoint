import contextlib
import io
import json
from unittest import mock

import psycopg.errors
from sqlalchemy.exc import OperationalError

from waypoint import monitoring
from waypoint.server import routes
from waypoint.server.api import state
from waypoint.server.common import ApiError
from tests.shared import ServerCase, fetch

PRIVATE = "Acme Coffee 12.34"
FAILURES = (KeyError(PRIVATE), TypeError(f"unsupported operand type(s) for +: 'NoneType' and '{PRIVATE}'"),
            ValueError(f"invalid literal for int() with base 10: '{PRIVATE}'"), AttributeError(PRIVATE))
DEADLOCK = OperationalError("UPDATE settings SET value=?", {}, psycopg.errors.DeadlockDetected("deadlock detected"))


class ErrorTests(ServerCase):
    def setUp(self):
        super().setUp()
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def api(self, path):
        return self.req("GET", path)

    def assertReported(self, ref: str, kind: str):
        logged = self.stderr.getvalue()
        self.assertIn(f"{kind}: [Filtered]", logged)
        self.assertIn("api_state", logged)
        for private in ("Acme", "12.34"):
            self.assertNotIn(private, logged)

    def test_a_value_that_cant_be_read_is_a_400_saying_which(self):
        status, _, raw = fetch(self.base, "POST", "/api/backup/inspect", b"not a backup",
                               {"X-Waypoint": "1", "Content-Type": "application/octet-stream"})
        self.assertEqual(status, 400)
        self.assertIn("isn't a Waypoint backup", json.loads(raw)["error"])

    def test_a_bug_in_a_handler_is_a_500_and_reported(self):
        for e in FAILURES:
            with self.subTest(error=type(e).__name__), mock.patch.object(state, "with_offset", side_effect=e), \
                    mock.patch.object(monitoring, "log") as log:
                status, reply = self.api("/api/state")
                self.assertEqual(status, 500)
                ref = reply["error"].split("reference ")[1].split(";")[0]
                self.assertEqual(reply["error"], f"Something went wrong on Waypoint's side (reference {ref}; the details are in its log).")
                log.assert_any_call(f"[error {ref}] GET /api/state", "error")
                self.assertReported(ref, type(e).__name__)

    def test_a_busy_database_is_a_503(self):
        with mock.patch.object(state, "with_offset", side_effect=DEADLOCK):
            self.assertEqual(self.api("/api/state"), (503, {"error": routes.BUSY}))
        self.assertEqual(self.stderr.getvalue(), "")

    def test_a_handlers_own_refusal_is_its_status_and_message(self):
        with mock.patch.object(state, "with_offset", side_effect=ApiError("Not today", 409)):
            self.assertEqual(self.api("/api/state"), (409, {"error": "Not today"}))

    def test_what_is_logged(self):
        found = routes.match("GET", "/api/state")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(state, "with_offset", side_effect=FAILURES[2]), self.assertRaises(ApiError) as cm, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            routes.dispatch(found, {}, {})
        self.assertEqual(cm.exception.status, 500)
        ref = str(cm.exception).split("reference ", 1)[1].split(";", 1)[0]
        self.assertIn(f"[error {ref}] GET /api/state", out.getvalue())
        self.assertIn("builtins.ValueError: [Filtered]", err.getvalue())
        self.assertIn("in api_state", err.getvalue())
        for private in ("Acme", "12.34"):
            self.assertNotIn(private, out.getvalue() + err.getvalue())


class DatabaseErrorTests(ServerCase):
    def test_a_database_error_keeps_its_sql_and_loses_its_values(self):
        orig = psycopg.errors.UndefinedColumn(f'column "value" does not exist: {PRIVATE}')
        err = OperationalError("UPDATE settings SET value=? WHERE key=?", {"value": PRIVATE, "key": "secret-key-1"}, orig)

        def fails(_stamp):
            raise err from orig
        out = io.StringIO()
        with contextlib.redirect_stderr(out), mock.patch.object(state, "with_offset", side_effect=fails), \
                self.assertRaises(ApiError) as cm:
            routes.dispatch(routes.match("GET", "/api/state"), {}, {})
        self.assertEqual(cm.exception.status, 500)
        logged = out.getvalue()
        self.assertIn("[SQL: UPDATE settings SET value=? WHERE key=?]", logged)
        self.assertIn("psycopg.errors.UndefinedColumn: [Filtered]", logged)
        self.assertNotIn("Acme", logged)
        self.assertNotIn("secret-key-1", logged)
