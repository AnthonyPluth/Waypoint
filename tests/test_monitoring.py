import contextlib
import io
import time
import unittest
from unittest import mock

import sqlalchemy as sa

from waypoint import monitoring
from waypoint.server.handler import route_name

SERVICE = "https://user:secretpass@api.travel.example/v2"
CODE = "QX7P2L"


def logged(fn) -> tuple[str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        fn()
    return out.getvalue(), err.getvalue()


class ScrubTests(unittest.TestCase):
    def test_what_a_service_said_is_kept_safe(self):
        self.assertEqual(monitoring.public_text("Northwind Air: booking 123456789 needs a new login (HTTP 401)"),
                         "Northwind Air: booking [number] needs a new login (HTTP 401)")
        self.assertEqual(monitoring.public_text(f"refused at {SERVICE}/accounts?x=1"),
                         monitoring.scrub(f"refused at {SERVICE}/accounts?x=1"))
        self.assertIsNone(monitoring.public_text(None))

    def test_secrets_are_blanked(self):
        text = f"Couldn't reach {SERVICE}/accounts?start-date=1 with access-production-1234abcd-9f00-4c1e"
        out = monitoring.scrub(text)
        for secret in ("secretpass", "user:", "start-date", "1234abcd"):
            self.assertNotIn(secret, out)
        self.assertIn("api.travel.example/v2/accounts", out)
        self.assertEqual(monitoring.scrub(None), None)

    def test_database_errors_lose_the_row_they_were_writing(self):
        pg = ("(psycopg.errors.NotNullViolation) null value in column \"category\" violates not-null constraint\n"
              "DETAIL:  Failing row contains (tx-9, 2026-09-01, -87.12, NORTHWIND AIR, null).\n"
              "[SQL: INSERT INTO segments ...]\n[parameters: {'id': 'tx-9', 'code': 'QX7P2L'}]\n"
              "(Background on this error at: https://sqlalche.me/e/20/gkpj)")
        dup = "DETAIL:  Key (confirmation_code)=(p-csp) already exists."
        out = monitoring.scrub(pg) + monitoring.scrub(dup)
        for private in ("NORTHWIND AIR", "87.12", "tx-9", "QX7P2L", "p-csp"):
            self.assertNotIn(private, out)
        self.assertIn("Failing row contains ([Filtered])", out)
        self.assertIn("Key (confirmation_code)=([Filtered]) already exists", out)
        self.assertIn("(Background on this error at: https://sqlalche.me/e/20/gkpj)", out)

    def test_text_that_repeats_a_marker_is_scrubbed_in_linear_time(self):
        for marker in ("[parameters: ", "Failing row contains (", "Key (", "Key ()=("):
            started = time.monotonic()
            monitoring.scrub(marker * 50_000)
            self.assertLess(time.monotonic() - started, 1, marker)


class ReportTests(unittest.TestCase):
    def test_a_report_is_logged_scrubbed(self):
        def fail():
            try:
                raise ValueError(f"The provider said no: {SERVICE}?token=abc")
            except ValueError:
                monitoring.report()
        out, err = logged(fail)
        self.assertEqual(out, "")
        self.assertIn("ValueError: The provider said no: https://[Filtered]@api.travel.example/v2?[Filtered]", err)
        self.assertNotIn("secretpass", err)

    def test_without_values_only_the_type_and_the_sql_are_kept(self):
        engine = sa.create_engine("sqlite://")
        with engine.begin() as c:
            c.exec_driver_sql("CREATE TABLE seg (id INTEGER PRIMARY KEY, code TEXT)")
            c.execute(sa.text("INSERT INTO seg VALUES (1, :code)"), {"code": CODE})
        try:
            with engine.begin() as c:
                c.execute(sa.text("INSERT INTO seg VALUES (:id, :code)"), {"id": 1, "code": CODE})
        except sa.exc.IntegrityError as e:
            self.assertIn(CODE, str(e))
            caught = e
            err = logged(lambda: monitoring.report(caught, values=False))[1]
        self.assertNotIn(CODE, err)
        self.assertIn("[SQL: INSERT INTO seg VALUES", err)

        def fail():
            try:
                int(f"Northwind Air {CODE}")
            except ValueError as e:
                monitoring.report(e, values=False)
        err = logged(fail)[1]
        self.assertIn("builtins.ValueError: [Filtered]", err)
        self.assertNotIn(CODE, err)

    def test_a_chain_of_errors_keeps_each_type(self):
        def fail():
            try:
                try:
                    raise KeyError(CODE)
                except KeyError as e:
                    raise RuntimeError(f"while reading {CODE}") from e
            except RuntimeError as e:
                monitoring.report(e, values=False)
        err = logged(fail)[1]
        self.assertIn("builtins.KeyError: [Filtered]", err)
        self.assertIn("builtins.RuntimeError: [Filtered]", err)
        self.assertNotIn(CODE, err)


class LogTests(unittest.TestCase):
    def test_a_line_goes_to_stdout_or_stderr(self):
        self.assertEqual(logged(lambda: monitoring.log("Scanned the mailbox.")), ("Scanned the mailbox.\n", ""))
        self.assertEqual(logged(lambda: monitoring.log("Couldn't scan.", "error", stderr=True)), ("", "Couldn't scan.\n"))

    def test_nothing_is_sent_anywhere(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("sent")), \
                mock.patch("socket.create_connection", side_effect=AssertionError("sent")):
            logged(lambda: monitoring.log("Scanned the mailbox."))
            logged(lambda: monitoring.report(RuntimeError("x")))


class RouteNameTests(unittest.TestCase):
    def test_a_failure_is_logged_by_its_route(self):
        cases = {"/api/state": "/api/state", "/api/backup/inspect": "/api/backup/inspect", "/api/restore": "/api/restore",
                 "/api/nope/secret-name": "/api/*", "/api/trips/kyoto%20spring": "/api/trips/{id}", "/api/things/kyoto%20spring": "/api/*",
                 "/": "/", "/trips/kyoto": "/", "/auth/callback": "/auth/callback", "/auth/login": "/auth/login",
                 "/auth/whatever": "/"}
        for path, name in cases.items():
            self.assertEqual(route_name(path), name, path)


if __name__ == "__main__":
    unittest.main()
