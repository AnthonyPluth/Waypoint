"""Brand logos (waypoint/providers/logodev.py, waypoint/providers/wikimedia.py, waypoint/domain/logos.py, waypoint/server/api/logos.py):
what a Logo.dev or Wikimedia request carries, what is kept from the answer, which brand a booking has, how a round of fetching ends,
and who can see a logo. Neither service is ever called: fake ones stand in for them. Names, codes and keys are invented."""
import json
import threading
import unittest
import urllib.parse
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from sqlalchemy import insert, select

from tests.privacy import no_leaks
from tests.shared import DbCase, fetch
from tests.test_trips import HOTEL, OUT, RouteCase
from waypoint.domain import logos
from waypoint.providers import logodev, wikimedia
from waypoint.server import jobs
from waypoint.storage import db
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import BrandLogo, Segment, Setting, Trip

PNG = b"\x89PNG\r\n\x1a\n" + b"made-up image bytes"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"another made-up image"
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


class FakeWikimedia(HTTPServer):
    """Wikidata's search and entity API and Commons' file service: knows `brands` (label -> its logo file) and `files` (file ->
    status, content type, body), and keeps what it was asked. `busy` answers every request with 429."""

    def __init__(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, ctype, body, headers=()):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(url.query)
                outer.calls.append({"path": url.path, "query": query, "headers": dict(self.headers)})
                if outer.busy:
                    return self.reply(429, "text/plain", b"slow down")
                if url.path == "/w/api.php" and query["action"] == ["wbsearchentities"]:
                    hits = [{"id": f"Q{i}", "label": label, "description": outer.described.get(label, "hotel brand")}   # (all it knows: search is fuzzy)
                            for i, label in enumerate(outer.brands, 1)]
                    return self.reply(200, "application/json", json.dumps({"search": hits}).encode())
                if url.path == "/w/api.php" and query["action"] == ["wbgetentities"]:
                    labels = {f"Q{i}": label for i, label in enumerate(outer.brands, 1)}
                    entities = {q: {"labels": {"en": {"value": labels[q]}}, "claims": {"P154": [
                        {"rank": "normal", "mainsnak": {"datavalue": {"value": outer.brands[labels[q]]}}}]} if outer.brands[labels[q]] else {}}
                                for q in query["ids"][0].split("|")}
                    return self.reply(200, "application/json", json.dumps({"entities": entities}).encode())
                if url.path == "/files/redirect":
                    return self.reply(302, "text/plain", b"", [("Location", "http://other.example/logo.png")])
                if url.path.startswith("/files/"):
                    code, ctype, body = outer.files.get(urllib.parse.unquote(url.path[len("/files/"):]), (404, "text/plain", b""))
                    return self.reply(code, ctype, body)
                self.reply(404, "text/plain", b"")
        super().__init__(("127.0.0.1", 0), Handler)
        self.calls: list[dict] = []
        self.brands: dict[str, str] = {}
        self.described: dict[str, str] = {}
        self.files: dict[str, tuple[int, str, bytes]] = {}
        self.busy = False

    def know(self, label: str, file: str | None = None, image: bytes = PNG, description: str | None = None):
        """Wikidata has an item called `label`, with its logo in `file` on Commons (None: no logo)."""
        file = file if file is not None else label + " logo.svg"
        self.brands[label] = file
        self.files[file] = (200, "image/png", image)
        if description:
            self.described[label] = description


def serve_wikimedia(case) -> FakeWikimedia:
    """A fake Wikidata and Commons, which the provider is pointed at until the test is cleaned up."""
    fake = FakeWikimedia()
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    case.addCleanup(fake.server_close)
    case.addCleanup(fake.shutdown)
    base = f"http://127.0.0.1:{fake.server_port}"
    patch = mock.patch.object(wikimedia, "HOSTS", wikimedia.Hosts(wikidata=base + "/w/api.php", files=base + "/files", allow_http=True))
    patch.start()
    case.addCleanup(patch.stop)
    return fake


class WikimediaProviderTests(unittest.TestCase):
    def setUp(self):
        self.fake = serve_wikimedia(self)

    def test_a_brand_is_found_by_name_and_its_logo_asked_for_as_a_png_of_one_width(self):
        self.fake.know("Hyatt Place", "Hyatt Place logo.svg")
        self.assertEqual(wikimedia.find_logo("Hyatt Place"), (PNG, "image/png"))
        search, entity, image = self.fake.calls
        self.assertEqual(search["query"]["search"], ["Hyatt Place"])
        self.assertEqual(entity["query"]["ids"], ["Q1"])
        self.assertEqual((image["path"], image["query"]), ("/files/Hyatt%20Place%20logo.svg", {"width": ["256"]}))
        self.assertIn("Waypoint", image["headers"]["User-Agent"])   # (Wikimedia asks who is calling)
        self.assertNotIn("@", image["headers"]["User-Agent"])

    def test_the_same_brand_give_or_take_hotels_by_marriott_accents_and_punctuation(self):
        for asked, label in (("Sheraton", "Sheraton Hotels and Resorts"), ("Courtyard by Marriott", "Courtyard"),
                             ("Le Méridien", "Le Meridien Hotels & Resorts"), ("Hampton by Hilton", "Hampton"),
                             ("The Ritz-Carlton", "Ritz Carlton Hotel Company"), ("Radisson RED", "Radisson Red")):
            with self.subTest(asked=asked):
                self.fake.brands.clear()
                self.fake.know(label)
                self.assertEqual(wikimedia.find_logo(asked), (PNG, "image/png"))

    def test_another_brand_is_never_taken_for_this_one(self):
        self.fake.know("Holiday Inn Express")
        self.assertIsNone(wikimedia.find_logo("Holiday Inn"))
        self.assertEqual([c["query"]["action"] for c in self.fake.calls], [["wbsearchentities"]])   # (no item to look at, no image asked for)

    def test_a_building_or_one_hotel_is_not_a_brand(self):
        for description in ("skyscraper in Chicago", "hotel in Dubai", "building in Quebec"):
            self.fake.brands.clear()
            self.fake.know("Grand Hyatt", description=description)
            self.assertIsNone(wikimedia.find_logo("Grand Hyatt"), description)

    def test_an_item_with_no_logo_is_none_and_no_image_is_asked_for(self):
        self.fake.brands["Andaz"] = ""
        self.assertIsNone(wikimedia.find_logo("Andaz"))
        self.assertFalse([c for c in self.fake.calls if c["path"].startswith("/files/")])

    def test_the_preferred_logo_and_else_the_newest_is_the_one_asked_for(self):
        claims = [{"rank": "normal", "mainsnak": {"datavalue": {"value": "old.svg"}}}, {"rank": "preferred", "mainsnak": {"datavalue": {"value": "best.svg"}}},
                  {"rank": "deprecated", "mainsnak": {"datavalue": {"value": "bad.svg"}}}, {"rank": "normal", "mainsnak": {"datavalue": {"value": "new.svg"}}}]
        self.assertEqual(wikimedia._logo_file(claims), "best.svg")
        self.assertEqual(wikimedia._logo_file([claims[0], claims[2], claims[3]]), "new.svg")
        for odd in (None, [], {}, [None], [{"mainsnak": {}}], [{"mainsnak": {"datavalue": {"value": 7}}}]):
            self.assertIsNone(wikimedia._logo_file(odd), odd)

    def test_a_name_that_is_nothing_is_not_asked_about(self):
        for odd in ("", " ", "a", None):
            self.assertIsNone(wikimedia.find_logo(odd))   # type: ignore[arg-type]
        self.assertEqual(self.fake.calls, [])

    def test_a_logo_wikimedia_does_not_have_is_none_not_an_error(self):
        self.fake.know("Kimpton Hotels")
        self.fake.files.clear()
        self.assertIsNone(wikimedia.find_logo("Kimpton"))

    def test_only_a_small_png_jpeg_webp_or_gif_is_kept_and_any_other_file_is_no_logo_not_an_outage(self):
        self.fake.know("Moxy Hotels", "m.png")
        for ctype, body in (("image/svg+xml", b"<svg onload=alert(1)/>"), ("text/html", b"<p>"), ("image/png", b""),
                            ("image/png", b"x" * (wikimedia.MAX_LOGO + 1))):
            self.fake.files["m.png"] = (200, ctype, body)
            self.assertIsNone(wikimedia.find_logo("Moxy"), ctype)
        for code in (400, 403, 415):   # (a file Commons won't draw)
            self.fake.files["m.png"] = (code, "text/plain", b"no")
            self.assertIsNone(wikimedia.find_logo("Moxy"), code)
        for ctype in ("image/jpeg", "image/webp", "image/gif"):
            self.fake.files["m.png"] = (200, ctype + "; charset=binary", PNG)
            self.assertEqual(wikimedia.find_logo("Moxy"), (PNG, ctype))

    def test_a_busy_or_unreachable_service_is_unavailable_not_no_such_brand(self):
        self.fake.know("Aloft Hotels")
        self.fake.busy = True
        with self.assertRaises(wikimedia.Unavailable) as caught:
            wikimedia.find_logo("Aloft")
        self.assertIn("busy", str(caught.exception))
        self.fake.busy = False
        for code in (429, 500, 503):   # (the service's trouble, not that file's)
            self.fake.files["Aloft Hotels logo.svg"] = (code, "text/plain", b"oops")
            with self.assertRaises(wikimedia.Unavailable, msg=code):
                wikimedia.find_logo("Aloft")
        self.fake.shutdown()
        self.fake.server_close()
        with self.assertRaises(wikimedia.Unavailable):
            wikimedia.find_logo("Aloft")

    def test_an_answer_that_is_not_what_was_asked_for_is_unavailable(self):
        with mock.patch.object(wikimedia, "_open", return_value=(b"<html>", "text/html")):
            with self.assertRaises(wikimedia.Unavailable):
                wikimedia.find_logo("Sofitel")
        with mock.patch.object(wikimedia, "_open", return_value=(b'{"error": {"code": "ratelimited"}}', "application/json")):
            with self.assertRaises(wikimedia.Unavailable):
                wikimedia.find_logo("Sofitel")
        with mock.patch.object(wikimedia, "_open", return_value=(b'{"error": {"code": "badvalue"}}', "application/json")):
            self.assertIsNone(wikimedia.find_logo("Sofitel"))   # (that question has no answer; the service is fine)

    def test_a_redirect_leaves_wikimedia_only_for_its_own_image_hosts(self):
        with self.assertRaises(wikimedia.Unavailable):
            wikimedia._download("redirect")   # (the fake sends it to another host)
        self.assertEqual([c["path"] for c in self.fake.calls], ["/files/redirect"])


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

    def test_a_hotel_is_asked_about_by_its_own_brand_first_without_the_rest_of_its_name(self):
        for hotel, brand in (("Hyatt Place Chicago River North", "Hyatt Place"), ("Hyatt Regency O'Hare", "Hyatt Regency"),
                             ("hyatt  regency chicago", "Hyatt Regency"), ("Courtyard Denver Downtown", "Courtyard by Marriott"),
                             ("Holiday Inn Express & Suites Reno", "Holiday Inn Express"), ("Holiday Inn Reno", "Holiday Inn"),
                             ("Hampton Inn Boston", "Hampton by Hilton"), ("The Westin Chicago River North", "Westin"),
                             ("Le Méridien Paris Etoile", "Le Méridien"), ("W Hotel Barcelona", "W Hotels"),
                             ("The Ritz-Carlton, Amelia Island", "The Ritz-Carlton"), ("Radisson Blu Edwardian", "Radisson Blu")):
            with self.subTest(hotel=hotel):
                self.assertEqual(logos.sub_brand(hotel), brand)
                self.assertEqual(logos.brands_of([("hotel", "Hyatt", None, hotel)], {}), [brand])
        for hotel in ("Harbour Hotel", "Hyatt", "Hyattsville Inn", "Placeholder Hyatt Place", "W Motel", "Glo Inn", "Vib Lodge", "", None):
            with self.subTest(hotel=hotel):
                self.assertIsNone(logos.sub_brand(hotel))
                self.assertEqual(logos.brands_of([("hotel", "Hyatt", None, hotel)], {}), ["Hyatt"])
        self.assertEqual(logos.brands_of([("car", "Hertz", None, "Hyatt Place Chicago")], {}), ["Hertz"])   # (only a hotel's name says its brand)

    def test_a_hotel_of_a_known_brand_falls_back_to_its_group_not_to_the_booking_site(self):
        self.assertEqual(logos._candidates("hotel", "Booking.com", None, "Hyatt Regency Chicago", {}), ["Hyatt Regency", "Hyatt"])
        self.assertEqual(logos._candidates("hotel", None, None, "Courtyard Denver", {}), ["Courtyard by Marriott", "Marriott"])
        self.assertEqual(logos._candidates("hotel", "Booking.com", None, "Harbour Hotel", {}), ["Booking.com"])   # (no brand of a group: its provider)
        self.assertEqual(logos._candidates("car", "Hertz", None, "Hyatt Regency Chicago", {}), ["Hertz"])

    def test_every_brand_has_a_group_and_each_start_is_listed_once(self):
        starts = [start for start, _ in logos.SUB_BRANDS]
        self.assertEqual(len(starts), len(set(starts)))
        for start, brand in logos.SUB_BRANDS:
            self.assertEqual(start, logos._plain(start), start)   # (written as a hotel's name is read)
            self.assertIn(logos.key(brand), logos.GROUP_OF, brand)
        self.assertEqual(logos.GROUP_OF[logos.key("Hyatt Regency")], "Hyatt")
        self.assertGreater(len(logos.SUB_BRANDS), 140)

    def test_a_chip_names_the_brand_without_its_group_tail(self):
        for brand, label in (("Courtyard by Marriott", "Courtyard"), ("Hyatt Regency", "Hyatt Regency"), ("Kimpton Hotels", "Kimpton"),
                             ("Bvlgari Hotels & Resorts", "Bvlgari"), ("Hampton by Hilton", "Hampton"), ("The Ritz-Carlton", "The Ritz-Carlton")):
            self.assertEqual(logos.chip_label(brand), label, brand)

    def test_a_hotel_shows_a_chip_only_when_the_logo_is_its_groups(self):
        self.assertEqual(logos.chip("hotel", "Hyatt Regency Chicago", "Hyatt"), "Hyatt Regency")
        self.assertIsNone(logos.chip("hotel", "Hyatt Regency Chicago", "Hyatt Regency"))   # (its own)
        self.assertIsNone(logos.chip("hotel", "Harbour Hotel", "Harbour Hotels"))          # (no brand of a group)
        self.assertIsNone(logos.chip("car", "Hyatt Regency Chicago", "Hertz"))
        self.assertIsNone(logos.chip("hotel", "Hyatt Regency Chicago", None))

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

    def test_a_refused_secret_key_falls_back_to_asking_by_name_and_says_so(self):
        self.fake.search_answer = (403, "text/plain", b"no")
        with self.conn() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
            db.set_setting(conn, sk.LOGODEV_SECRET, SECRET)
            self.assertGreater(logos.fetch_due(conn, NOW), 0)
            self.assertEqual(logos.logo(conn, "Harbour Hotels"), (PNG, "image/png"))
            self.assertEqual(len([c for c in self.fake.calls if c["path"] == "/search"]), 1)   # not asked again for each brand
            self.assertIn("secret key", logos.status(conn)["last_error"] or "")
            self.assertNotIn(SECRET, logos.status(conn)["last_error"] or "")

    def test_a_round_is_skipped_while_another_runs(self):
        with db.session() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
        self.assertTrue(jobs._fetching.acquire(blocking=False))
        try:
            self.assertFalse(jobs.fetch_logos())
            self.assertFalse(jobs.fetch_logos_now())
        finally:
            jobs._fetching.release()
        self.assertEqual(self.fake.calls, [])
        self.assertTrue(jobs.fetch_logos())

    def test_the_job_fetches_with_the_machines_time_and_never_raises(self):
        with db.session() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)
        jobs.fetch_logos()
        with db.session() as conn:
            self.assertEqual(logos.status(conn)["waiting"], 0)
        with mock.patch.object(logos, "fetch_due", side_effect=RuntimeError("boom")), mock.patch("waypoint.monitoring.report") as report:
            jobs.fetch_logos()
        report.assert_called_once()


class HotelBrandRoundTests(DbCase):
    """A hotel's own brand is asked of Wikimedia and its group of Logo.dev; and what happens when one of them can't answer."""

    def setUp(self):
        super().setUp()
        db.init(self.path)
        self.logodev = serve_fake(self)
        self.wiki = serve_wikimedia(self)
        with db.session() as conn:
            conn.execute(insert(Trip).values(id=1, name="T", auto=True))
            conn.execute(insert(Segment).values(trip_id=1, kind="hotel", status="confirmed", provider="Hyatt", origin="Hyatt Place Quay Street",
                                                start_local="2026-10-01T15:00", start_zone="Europe/London", end_local="2026-10-03T10:00",
                                                end_zone="Europe/London", source="manual"))
            db.set_setting(conn, sk.LOGODEV_TOKEN, TOKEN)

    def kept(self, conn):
        return {k: (bytes(logo) if logo else None, source) for k, logo, source in conn.execute(select(BrandLogo.key, BrandLogo.logo, BrandLogo.source))}

    def logodev_names(self):
        return sorted(c["path"].split("/")[-1].split("?")[0] for c in self.logodev.calls if "/name/" in c["path"])

    def test_the_brand_comes_from_wikimedia_its_group_from_logo_dev_and_the_hotels_name_from_neither(self):
        self.wiki.know("Hyatt Place", image=PNG2)
        with db.session() as conn:
            logos.fetch_due(conn, NOW)
            self.assertEqual(self.kept(conn), {"hyatt place": (PNG2, "wikimedia"), "hyatt": (PNG, "logodev")})
        self.assertEqual(self.logodev_names(), ["Hyatt"])   # (Logo.dev is never asked about the hotel's brand)
        self.assertEqual({c["query"]["search"][0] for c in self.wiki.calls if "search" in c["query"]}, {"Hyatt Place"})
        for calls in (self.logodev.calls, self.wiki.calls):
            self.assertFalse(any("Quay" in str(c) for c in calls))   # (a place never goes to either)

    def test_a_brand_wikimedia_has_none_for_is_remembered_and_the_group_is_still_fetched(self):
        with db.session() as conn:
            self.assertEqual(logos.fetch_due(conn, NOW), 1)
            self.assertEqual(self.kept(conn), {"hyatt place": (None, None), "hyatt": (PNG, "logodev")})
            self.assertEqual(logos.status(conn)["waiting"], 0)
            self.assertIsNone(logos.status(conn)["last_error"])
        self.assertEqual(self.logodev_names(), ["Hyatt"])

    def test_wikimedia_not_answering_defers_only_the_hotel_brands_for_an_hour(self):
        self.wiki.know("Hyatt Place", image=PNG2)
        self.wiki.busy = True
        with db.session() as conn:
            self.assertEqual(logos.fetch_due(conn, NOW), 1)   # (the group still comes from Logo.dev)
            self.assertEqual(self.kept(conn)["hyatt"], (PNG, "logodev"))
            self.assertIn("Wikimedia couldn't be reached", logos.status(conn)["last_error"] or "")
            asked = len(self.wiki.calls)
            logos.fetch_due(conn, NOW + timedelta(minutes=30))   # not yet
            self.assertEqual(len(self.wiki.calls), asked)
            self.wiki.busy = False
            self.assertEqual(logos.fetch_due(conn, NOW + logos.RETRY_AFTER + timedelta(minutes=1)), 1)
            self.assertEqual(self.kept(conn)["hyatt place"], (PNG2, "wikimedia"))
            self.assertIsNone(logos.status(conn)["last_error"])

    def test_a_logo_two_brands_share_is_kept_for_neither_beyond_the_first(self):
        with db.session() as conn:
            conn.execute(insert(Segment).values(trip_id=1, kind="hotel", status="confirmed", provider="Hyatt", origin="Hyatt House Dock Road",
                                                start_local="2026-11-01T15:00", start_zone="Europe/London", end_local="2026-11-03T10:00",
                                                end_zone="Europe/London", source="manual"))
        self.wiki.know("Hyatt House", "shared.svg", image=PNG2)
        self.wiki.brands["Hyatt Place"] = "shared.svg"
        with db.session() as conn:
            logos.fetch_due(conn, NOW)
            got = self.kept(conn)
            self.assertEqual([got["hyatt house"][0], got["hyatt place"][0]].count(PNG2), 1)   # (one has it, not both)

    def test_a_group_logo_from_before_is_dropped_for_a_brand_that_has_none_of_its_own_but_kept_when_it_does(self):
        with db.session() as conn:
            for brand in ("Hyatt Place", "Hyatt"):
                conn.execute(insert(BrandLogo).values(key=logos.key(brand), name=brand, logo=PNG2, logo_type="image/png", source="logodev"))
            logos.fetch_due(conn, NOW)
            got = self.kept(conn)
            self.assertEqual(got["hyatt place"], (None, None))   # (Logo.dev's was the group's)
            self.assertEqual(got["hyatt"], (PNG, "logodev"))     # (the group's own is asked again)
        self.wiki.know("Hyatt Place", image=b"\x89PNG\r\n\x1a\nits own")
        with db.session() as conn:
            logos.fetch_due(conn, NOW + timedelta(days=logos.REFRESH_DAYS + 1))
            self.assertEqual(self.kept(conn)["hyatt place"], (b"\x89PNG\r\n\x1a\nits own", "wikimedia"))

    def test_one_brands_bad_file_is_no_logo_for_it_and_the_next_brand_still_gets_its_own(self):
        with db.session() as conn:
            conn.execute(insert(Segment).values(trip_id=1, kind="hotel", status="confirmed", provider="Hyatt", origin="Hyatt House Dock Road",
                                                start_local="2026-11-01T15:00", start_zone="Europe/London", end_local="2026-11-03T10:00",
                                                end_zone="Europe/London", source="manual"))
        self.wiki.know("Hyatt House", "house.svg")
        self.wiki.files["house.svg"] = (200, "image/svg+xml", b"<svg onload=alert(1)/>")   # ("hyatt house" sorts before "hyatt place")
        self.wiki.know("Hyatt Place", image=PNG2)
        with db.session() as conn:
            logos.fetch_due(conn, NOW)
            self.assertEqual(self.kept(conn), {"hyatt house": (None, None), "hyatt place": (PNG2, "wikimedia"), "hyatt": (PNG, "logodev")})
            self.assertIsNone(logos.status(conn)["last_error"])   # (Wikimedia was never down)
            self.assertEqual(logos.status(conn)["waiting"], 0)

    def test_a_hotel_brand_a_booking_names_as_its_provider_falls_back_to_logo_dev(self):
        with db.session() as conn:
            conn.execute(Segment.__table__.delete())
            conn.execute(insert(Segment).values(trip_id=1, kind="hotel", status="confirmed", provider="Sheraton", origin="Harbour Place",
                                                start_local="2026-10-01T15:00", start_zone="Europe/London", end_local="2026-10-03T10:00",
                                                end_zone="Europe/London", source="manual"))
            logos.fetch_due(conn, NOW)
            self.assertEqual(self.kept(conn), {"sheraton": (PNG, "logodev")})
        self.assertEqual(self.logodev_names(), ["Sheraton"])

    def test_nothing_is_asked_of_wikimedia_without_a_logo_dev_key(self):
        with db.session() as conn:
            db.set_setting(conn, sk.LOGODEV_TOKEN, None)
            self.assertEqual(logos.fetch_due(conn, NOW), 0)
        self.assertEqual((self.wiki.calls, self.logodev.calls), ([], []))


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

    def test_a_hotel_shows_its_own_brands_logo_else_its_providers(self):
        self.keep("Hyatt")
        hyatt = self.book("ana", HOTEL, provider="Hyatt", origin="Hyatt Place Harbour", travelers=[{"person_id": self.person["ana"]}])
        self.assertEqual(hyatt["logo"], f"/api/segments/{hyatt['id']}/logo")   # (no logo of Hyatt Place's own: Hyatt's)
        self.assertEqual(fetch(self.base, "GET", hyatt["logo"], headers={"X-Waypoint": "1", **self.who["ana"]})[2], PNG)
        with db.session() as conn:
            conn.execute(BrandLogo.__table__.insert().values(key="hyatt place", name="Hyatt Place", logo=PNG2, logo_type="image/png", checked=NOW.isoformat()))
        regency = self.book("ana", {**HOTEL, "start_local": "2026-12-01T15:00", "end_local": "2026-12-03T10:00"}, provider="Hyatt",
                            origin="Hyatt Regency Harbour", travelers=[{"person_id": self.person["ana"]}])
        image = lambda seg: fetch(self.base, "GET", f"/api/segments/{seg['id']}/logo", headers={"X-Waypoint": "1", **self.who["ana"]})[2]
        self.assertEqual((image(hyatt), image(regency)), (PNG2, PNG))   # Hyatt Place has its own now; Hyatt Regency falls back to Hyatt's
        label = lambda seg: next(x for x in self.ok("ana", "GET", f"/api/trips/{seg['trip_id']}")["segments"] if x["id"] == seg["id"])["logo_label"]
        self.assertEqual((label(hyatt), label(regency)), (None, "Hyatt Regency"))   # (a chip when the logo is the group's)

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

    def test_a_request_with_one_bad_key_saves_neither(self):
        self.assertEqual(self.call("ana", "POST", "/api/logodev", {"token": TOKEN, "secret": TOKEN})[0], 400)
        self.assertFalse(self.ok("ana", "GET", "/api/logodev")["configured"])
        got = self.ok("ana", "POST", "/api/logodev", {"token": TOKEN, "secret": SECRET})   # both at once, when both are right
        self.assertEqual((got["configured"], got["searchable"]), (True, True))

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
