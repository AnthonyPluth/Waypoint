"""Brand logos (waypoint/providers/logodev.py, waypoint/domain/logos.py, waypoint/server/api/logos.py): what a Logo.dev request
carries, what is kept from the answer, which brand a booking has, how a round of fetching ends, and who can see a logo.
Logo.dev is never called: a fake service stands in for it. Names, codes and keys are invented."""
import json
import threading
import unittest
import urllib.parse
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.shared import DbCase, fetch
from tests.test_trips import HOTEL, OUT, RouteCase
from waypoint.domain import logos
from waypoint.providers import logodev
from waypoint.server import jobs
from waypoint.storage import db
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import BrandLogo, Segment, Setting, Trip

PNG = b"\x89PNG\r\n\x1a\n" + b"made-up image bytes"
TOKEN = "pk_test-publishable-4d7e1a90"
SECRET = "sk_test-secret-9b2c5f31"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class FakeLogoDev(HTTPServer):
    """Logo.dev's image and search endpoints: answers `status, content type, body` per kind of request, and keeps what it was asked."""

    def __init__(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                server = self.server
                path = urllib.parse.urlsplit(self.path).path
                server.calls.append({"path": path, "query": urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query),   # type: ignore[attr-defined]
                                     "headers": dict(self.headers)})
                code, ctype, body = server.search_answer if path == "/search" else server.image_answer   # type: ignore[attr-defined]
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        super().__init__(("127.0.0.1", 0), Handler)
        self.calls: list[dict] = []
        self.image_answer: tuple[int, str, bytes] = (200, "image/png", PNG)
        self.search_answer: tuple[int, str, bytes] = (200, "application/json", b"[]")


def serve_fake(case) -> FakeLogoDev:
    """A fake Logo.dev, which the provider is pointed at until the test is cleaned up."""
    fake = FakeLogoDev()
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    case.addCleanup(fake.server_close)
    case.addCleanup(fake.shutdown)
    base = f"http://127.0.0.1:{fake.server_port}"
    patch = mock.patch.object(logodev, "HOSTS", logodev.Hosts(images=base, search=base + "/search", allow_http=True))
    patch.start()
    case.addCleanup(patch.stop)
    return fake


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.fake = serve_fake(self)

    def test_a_logo_is_asked_for_by_name_with_the_key_and_nothing_else(self):
        self.assertEqual(logodev.fetch(TOKEN, name="Harbour Hotels"), (PNG, "image/png"))
        (call,) = self.fake.calls
        self.assertEqual(call["path"], "/name/Harbour%20Hotels")
        self.assertEqual(call["query"], {"token": [TOKEN], "size": ["96"], "format": ["png"], "fallback": ["404"]})

    def test_a_logo_is_asked_for_by_website_once_a_brand_is_picked(self):
        logodev.fetch(TOKEN, domain="https://www.Example-Hotels.com/rooms")
        self.assertEqual(self.fake.calls[0]["path"], "/example-hotels.com")

    def test_a_website_that_is_not_one_is_never_asked_for(self):
        for bad in ("", "not a site", "a/../b.com", "localhost", "evil.com@x"):
            self.assertIsNone(logodev.fetch(TOKEN, domain=bad), bad)
        self.assertIsNone(logodev.fetch(TOKEN, name="   "))
        self.assertEqual(self.fake.calls, [])

    def test_no_such_brand_is_none_not_an_error(self):
        self.fake.image_answer = (404, "application/json", b"{}")
        self.assertIsNone(logodev.fetch(TOKEN, name="Nowhere Air"))

    def test_a_refused_key_is_not_no_such_brand_and_never_shows_in_the_message(self):
        for code in (401, 402, 403):
            self.fake.image_answer = (code, "text/plain", b"no")
            with self.assertRaises(logodev.Refused) as caught:
                logodev.fetch(TOKEN, name="Example Air")
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_a_server_error_or_no_connection_is_unavailable_without_the_key(self):
        self.fake.image_answer = (500, "text/plain", b"oops")
        with self.assertRaises(logodev.Unavailable) as caught:
            logodev.fetch(TOKEN, name="Example Air")
        self.assertNotIn(TOKEN, str(caught.exception))
        self.fake.shutdown()
        self.fake.server_close()
        with self.assertRaises(logodev.Unavailable) as caught:
            logodev.fetch(TOKEN, name="Example Air")
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_only_a_small_png_jpeg_webp_or_gif_is_kept(self):
        for ctype, body in (("image/svg+xml", b"<svg onload=alert(1)/>"), ("text/html", b"<p>"), ("image/png", b""),
                            ("image/png", b"x" * (logodev.MAX_LOGO + 1))):
            self.fake.image_answer = (200, ctype, body)
            with self.assertRaises(logodev.Unavailable, msg=ctype):
                logodev.fetch(TOKEN, name="Example Air")
        for ctype in ("image/jpeg", "image/webp", "image/gif"):
            self.fake.image_answer = (200, ctype + "; charset=binary", PNG)
            self.assertEqual(logodev.fetch(TOKEN, name="Example Air"), (PNG, ctype))

    def test_brand_search_sends_the_secret_key_as_a_bearer_and_reads_the_brands(self):
        self.fake.search_answer = (200, "application/json", json.dumps([
            {"name": "Harbour Hotels", "domain": "harbour-hotels.com"}, {"name": "Junk", "domain": "not a domain"}, "nope"]).encode())
        found = logodev.search(SECRET, "Harbour Hotel Lisbon")
        self.assertEqual(found, [{"name": "Harbour Hotels", "domain": "harbour-hotels.com"}])
        call = self.fake.calls[0]
        self.assertEqual(call["query"], {"q": ["Harbour Hotel Lisbon"]})
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {SECRET}")

    def test_brand_search_answers_that_are_not_brands_are_unavailable_and_a_refusal_is_refused(self):
        self.fake.search_answer = (200, "application/json", b"<html>")
        with self.assertRaises(logodev.Unavailable):
            logodev.search(SECRET, "Example")
        self.fake.search_answer = (200, "application/json", json.dumps({"results": [{"name": "A", "domain": "a.com"}]}).encode())
        self.assertEqual(logodev.search(SECRET, "A"), [{"name": "A", "domain": "a.com"}])
        self.fake.search_answer = (403, "text/plain", b"no")
        with self.assertRaises(logodev.Refused):
            logodev.search(SECRET, "Example")


class BrandTests(unittest.TestCase):
    AIRLINES = {"EX": "Example Air"}   # (a flight number whose code the table knows)

    def test_a_brand_is_the_provider_else_a_flights_airline(self):
        got = logos.brands_of([("hotel", "Harbour  Hotels", None), ("flight", None, "EX 101"), ("flight", "Other Air", "EX 101"),
                               ("flight", None, "ZZ9"), ("car", None, None), ("cruise", "Sea Line", None)], self.AIRLINES)
        self.assertEqual(got, ["Harbour Hotels", "Example Air", "Other Air", None, None, "Sea Line"])

    def test_a_provider_that_is_not_a_name_is_not_asked_about(self):
        for odd in ("", " ", "A", "12", "x" * 101):
            self.assertEqual(logos.brands_of([("hotel", odd, None)], {}), [None], odd)

    def test_keys_ignore_case_and_spacing(self):
        self.assertEqual(logos.key("  Harbour   HOTELS "), logos.key("harbour hotels"))

    def test_brand_search_picks_only_a_clear_match(self):
        found = [{"name": "Harbour Hotels", "domain": "harbour-hotels.com"}, {"name": "Harbor Freight", "domain": "harborfreight.com"}]
        self.assertEqual(logos.best_match("Harbour Hotels Inc", found), found[0])
        self.assertEqual(logos.best_match("Harbour Hotels Lisbon Marina", found), found[0])   # a brand the name starts with
        self.assertIsNone(logos.best_match("Quayside Inn", found))                              # better none than someone else's
        self.assertIsNone(logos.best_match("ab", found))
        self.assertIsNone(logos.best_match("Harbour", []))


class RoundTests(DbCase):
    """A round of fetching: new brands noted, asked about, kept; and how it ends when Logo.dev can't be asked."""

    def setUp(self):
        super().setUp()
        db.init(self.path)
        self.fake = serve_fake(self)
        with db.session() as conn:
            conn.execute(Trip.__table__.insert().values(id=1, name="Trip", auto=True))
            for i, (kind, provider, details) in enumerate([("hotel", "Harbour Hotels", None), ("hotel", "harbour  hotels", None),
                                                           ("flight", None, json.dumps({"flight_number": "AA 100"})),
                                                           ("car", None, None)], 1):
                conn.execute(Segment.__table__.insert().values(
                    id=i, trip_id=1, kind=kind, status="confirmed", provider=provider, details=details, start_local="2026-11-20T19:00",
                    start_zone="UTC", end_local="2026-11-21T07:10", end_zone="UTC", source="manual"))

    def conn(self):
        return db.session()

    def test_nothing_is_asked_without_a_key(self):
        with self.conn() as conn:
            self.assertEqual(logos.fetch_due(conn, NOW), 0)
            self.assertEqual(conn.execute(select(BrandLogo.key)).fetchall(), [])
        self.assertEqual(self.fake.calls, [])

    def test_each_brand_is_asked_once_and_kept(self):
        with self.conn() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
            logos.fetch_due(conn, NOW)
            kept = {k: (bytes(logo), t) for k, logo, t in conn.execute(select(BrandLogo.key, BrandLogo.logo, BrandLogo.logo_type))}
            self.assertEqual(kept["harbour hotels"], (PNG, "image/png"))
            self.assertEqual(len([c for c in self.fake.calls if c["path"].endswith("Harbour%20Hotels")]), 1)
            self.assertEqual(logos.status(conn)["waiting"], 0)
            self.assertIsNone(logos.status(conn)["last_error"])

    def test_a_brand_logo_dev_has_none_for_is_remembered_and_asked_again_after_a_month(self):
        self.fake.image_answer = (404, "text/plain", b"")
        with self.conn() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
            self.assertEqual(logos.fetch_due(conn, NOW), 0)
            asked = len(self.fake.calls)
            self.assertGreater(asked, 0)
            self.assertEqual(logos.status(conn)["waiting"], 0)
            self.assertEqual(logos.status(conn)["unknown"], asked)
            logos.fetch_due(conn, NOW + timedelta(days=1))
            self.assertEqual(len(self.fake.calls), asked)
            self.fake.image_answer = (200, "image/png", PNG)
            self.assertGreater(logos.fetch_due(conn, NOW + timedelta(days=logos.REFRESH_DAYS + 1)), 0)

    def test_a_refused_key_stops_the_round_says_why_and_leaves_the_rest_to_try_again(self):
        self.fake.image_answer = (403, "text/plain", b"no")
        with self.conn() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
            self.assertEqual(logos.fetch_due(conn, NOW), 0)
            self.assertEqual(len(self.fake.calls), 1)
            status = logos.status(conn)
            self.assertIn("refused the key", status["last_error"] or "")
            self.assertNotIn(TOKEN, status["last_error"] or "")
            self.assertEqual(status["unknown"], 0)   # not taken for "no such brand"
            self.assertGreater(status["waiting"], 0)
            self.fake.image_answer = (200, "image/png", PNG)
            logos.fetch_due(conn, NOW + timedelta(minutes=15))
            self.assertIsNone(logos.status(conn)["last_error"])

    def test_a_logo_already_kept_survives_logo_dev_losing_it(self):
        with self.conn() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
            logos.fetch_due(conn, NOW)
            self.fake.image_answer = (404, "text/plain", b"")
            logos.fetch_due(conn, NOW + timedelta(days=logos.REFRESH_DAYS + 1))
            self.assertEqual(logos.logo(conn, "Harbour Hotels"), (PNG, "image/png"))

    def test_with_a_secret_key_brand_search_picks_the_brand_and_its_website_is_asked_for(self):
        self.fake.search_answer = (200, "application/json", json.dumps([{"name": "Harbour Hotels", "domain": "harbour-hotels.com"}]).encode())
        with self.conn() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
            db.set_setting(conn, sk.LOGODEV_SECRET, SECRET)
            self.assertTrue(logos.searchable(conn))
            logos.fetch_due(conn, NOW)
            self.assertIn("/harbour-hotels.com", [c["path"] for c in self.fake.calls])
            self.assertEqual(logos.logo(conn, "harbour hotels"), (PNG, "image/png"))

    def test_the_job_fetches_with_the_machines_time_and_never_raises(self):
        with db.session() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
        jobs.fetch_logos()
        with db.session() as conn:
            self.assertEqual(logos.status(conn)["waiting"], 0)
        with mock.patch.object(logos, "fetch_due", side_effect=RuntimeError("boom")), mock.patch("waypoint.monitoring.report") as report:
            jobs.fetch_logos()
        report.assert_called_once()


class RouteTests(RouteCase):
    """Who sees a logo, and Settings → Logos."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self.forget)
        with db.session() as conn:
            conn.execute(BrandLogo.__table__.delete())
            for key in (sk.LOGODEV_TOKEN, sk.LOGODEV_SECRET, sk.LOGODEV_LAST_ERROR):
                db.set_setting(conn, key, None)
        patch = mock.patch.object(jobs, "fetch_logos_now", return_value=True)
        self.started = patch.start()
        self.addCleanup(patch.stop)

    def forget(self):
        with db.session() as conn:
            conn.execute(BrandLogo.__table__.delete())
            for key in (sk.LOGODEV_TOKEN, sk.LOGODEV_SECRET, sk.LOGODEV_LAST_ERROR):
                db.set_setting(conn, key, None)

    def keep(self, brand="Harbour Hotels"):
        with db.session() as conn:
            conn.execute(BrandLogo.__table__.insert().values(key=logos.key(brand), name=brand, logo=PNG, logo_type="image/png",
                                                              checked=NOW.isoformat()))

    def test_a_segment_with_a_brand_that_has_a_logo_links_to_it_and_serves_it(self):
        self.keep()
        seg = self.book("ana", HOTEL, provider="Harbour Hotels", travelers=[{"person_id": self.person["ana"]}])
        self.assertEqual(seg["logo"], f"/api/segments/{seg['id']}/logo")
        status, headers, body = fetch(self.base, "GET", seg["logo"], headers={"X-Waypoint": "1", **self.who["ana"]})
        self.assertEqual((status, headers["Content-Type"], body), (200, "image/png", PNG))
        self.assertIn("private", headers["Cache-Control"])

    def test_no_logo_link_without_a_logo(self):
        seg = self.book("ana", OUT, travelers=[{"person_id": self.person["ana"]}])
        self.assertIsNone(seg["logo"])
        self.assertEqual(self.call("ana", "GET", f"/api/segments/{seg['id']}/logo")[0], 404)

    def test_a_stranger_gets_the_same_404_as_for_a_segment_that_isnt_there(self):
        self.keep()
        seg = self.book("ana", HOTEL, provider="Harbour Hotels", travelers=[{"person_id": self.person["ana"]}])
        stranger = self.req("GET", f"/api/segments/{seg['id']}/logo", None, self.who["ben"])
        missing = self.req("GET", "/api/segments/99999/logo", None, self.who["ben"])
        self.assertEqual(stranger, missing)
        self.assertEqual(stranger[0], 404)

    def test_saving_the_keys_checks_their_kind_and_never_sends_them_back(self):
        got = self.ok("ana", "POST", "/api/logodev", {"token": TOKEN})
        self.assertEqual((got["configured"], got["searchable"]), (True, False))
        self.started.assert_called_once()
        got = self.ok("ana", "POST", "/api/logodev", {"secret": SECRET})
        self.assertEqual((got["configured"], got["searchable"]), (True, True))
        for reply in (got, self.ok("ben", "GET", "/api/logodev")):
            self.assertNotIn(TOKEN, json.dumps(reply))
            self.assertNotIn(SECRET, json.dumps(reply))
        with db.session() as conn:   # saved encrypted
            raw = conn.execute(select(Setting.value).where(Setting.key == sk.LOGODEV_TOKEN)).scalar()
            self.assertNotIn(TOKEN, raw)
            self.assertEqual(db.get_setting(conn, sk.LOGODEV_TOKEN), TOKEN)

    def test_a_key_of_the_wrong_kind_is_refused(self):
        self.assertEqual(self.call("ana", "POST", "/api/logodev", {"token": SECRET})[0], 400)
        self.assertEqual(self.call("ana", "POST", "/api/logodev", {"token": 12})[0], 400)
        self.assertEqual(self.call("ana", "POST", "/api/logodev", {"token": TOKEN})[0], 200)
        self.assertEqual(self.call("ana", "POST", "/api/logodev", {"secret": TOKEN})[0], 400)

    def test_the_secret_key_needs_the_publishable_one_first(self):
        self.assertEqual(self.call("ana", "POST", "/api/logodev", {"secret": SECRET})[0], 400)

    def test_forgetting_the_key_forgets_the_secret_one_too(self):
        self.ok("ana", "POST", "/api/logodev", {"token": TOKEN})
        self.ok("ana", "POST", "/api/logodev", {"secret": SECRET})
        got = self.ok("ana", "POST", "/api/logodev", {"clear_secret": True})
        self.assertEqual((got["configured"], got["searchable"]), (True, False))
        self.ok("ana", "POST", "/api/logodev", {"secret": SECRET})
        got = self.ok("ana", "POST", "/api/logodev", {"clear": True})
        self.assertEqual((got["configured"], got["searchable"]), (False, False))

    def test_fetching_now_needs_a_key(self):
        self.assertEqual(self.call("ana", "POST", "/api/logodev/fetch", {})[0], 400)
        self.ok("ana", "POST", "/api/logodev", {"token": TOKEN})
        self.assertEqual(self.ok("ana", "POST", "/api/logodev/fetch", {}), {"started": True})

    def test_an_assistant_cannot_reach_the_settings(self):
        from waypoint.server import mcp_access
        self.assertTrue(mcp_access.blocked("/api/logodev"))
        self.assertTrue(mcp_access.blocked("/api/logodev/fetch"))


class PrivacyTests(DbCase):
    """Logo.dev is told a brand's name and the key, nothing about who travelled, when, or the booking."""

    def test_a_request_carries_neither_a_traveller_nor_a_confirmation_code(self):
        db.init(self.path)
        fake = serve_fake(self)
        with db.session() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
            conn.execute(Trip.__table__.insert().values(id=1, name="Quiet Getaway For Mx Vellacott", auto=True))
            conn.execute(Segment.__table__.insert().values(
                id=1, trip_id=1, kind="hotel", status="confirmed", provider="Harbour Hotels", confirmation="ZQXJ7WK2", start_local="2026-11-20T15:00",
                start_zone="UTC", end_local="2026-11-21T10:00", end_zone="UTC", origin="12 Vellacott Lane", source="manual"))
            with no_leaks(self, "ZQXJ7WK2", "Vellacott", "2026-11-20", sent_ok=True):
                logos.fetch_due(conn, NOW)
        text = json.dumps(fake.calls)
        for private in ("ZQXJ7WK2", "Vellacott", "2026-11", "Quiet"):
            self.assertNotIn(private, text)


if __name__ == "__main__":
    unittest.main()
