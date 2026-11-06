import email.message
import io
import json
import threading
import time
import traceback
import unittest
import urllib.error
from datetime import UTC, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.privacy import no_leaks
from waypoint import tls
from waypoint.providers import immich

FIXTURES = Path(__file__).parent / "fixtures" / "immich"
KEY = "canary-immich-key-q7v3x9"
ASSET = "0a000000-0000-4000-8000-000000000001"
OWNER = "0c000000-0000-4000-8000-000000000001"
PARTNER = "0c000000-0000-4000-8000-000000000002"
AFTER = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
BEFORE = datetime(2026, 7, 10, 3, 59, 59, tzinfo=UTC)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


class FakeImmich(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def answer(self):
                path = self.path.split("?")[0]
                length = int(self.headers.get("Content-Length") or 0)
                self.server.calls.append({"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},   # type: ignore[attr-defined]
                                          "body": self.rfile.read(length) if length else b""})
                code, headers, body = self.server.routes.get(path, (404, {}, b'{"message":"Not Found"}'))   # type: ignore[attr-defined]
                if callable(body):
                    body = body()
                self.send_response(code)
                for name, value in headers.items():
                    self.send_header(name, value)
                if headers.get("_chunked"):
                    self.send_header("Transfer-Encoding", "chunked")
                    body = (f"{len(body):x};pad={'x' * 150}\r\n".encode() + body + b"\r\n0\r\n"
                            + b"".join(f"X-Pad-{i}: {'y' * 40}\r\n".encode() for i in range(4)) + b"\r\n")
                elif "Content-Length" not in headers and not headers.get("_no_length"):
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                pause = float(headers.get("_trickle") or 0)
                if not pause:
                    self.wfile.write(body)
                    return
                for i in range(len(body)):
                    try:
                        self.wfile.write(body[i:i + 1])
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(pause)

            do_GET = answer
            do_POST = answer

        super().__init__(("127.0.0.1", 0), Handler)
        self.calls: list[dict] = []
        self.routes: dict[str, tuple] = {}

    def handle_error(self, request, client_address):
        pass

    @property
    def source(self) -> immich.Source:
        return immich.Source(url=f"http://127.0.0.1:{self.server_port}", key=KEY, allow_http=True, user_id=OWNER)


def serve(case) -> FakeImmich:
    fake = FakeImmich()
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    case.addCleanup(fake.server_close)
    case.addCleanup(fake.shutdown)
    return fake


def http_error(code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    message = email.message.Message()
    for name, value in (headers or {}).items():
        message[name] = value
    return urllib.error.HTTPError("https://photos.example.com/api/x", code, "nope", message, io.BytesIO(b""))


JSON_HEADERS = {"Content-Type": "application/json"}


class CleanUrlTests(unittest.TestCase):
    def test_keeps_scheme_host_and_port(self):
        cases = {
            "https://photos.example.com": "https://photos.example.com",
            "  https://photos.example.com/  ": "https://photos.example.com",
            "HTTPS://Photos.Example.COM": "https://photos.example.com",
            "http://192.168.1.20:2283": "http://192.168.1.20:2283",
            "http://immich:2283/": "http://immich:2283",
            "https://photos.example.com.": "https://photos.example.com",
            "http://[fd00::20]:2283": "http://[fd00::20]:2283",
            "http://[FD00:0:0::20]": "http://[fd00::20]",
            "https://photos.example.com:443": "https://photos.example.com:443",
        }
        for text, cleaned in cases.items():
            with self.subTest(text=text):
                self.assertEqual(immich.clean_url(text), cleaned)

    def test_refuses_anything_but_a_bare_web_address(self):
        refused = ["", "   ", "photos.example.com", "ftp://photos.example.com", "file:///etc/passwd", "javascript:alert(1)",
                   "https://photos.example.com/api", "https://photos.example.com/immich/", "https://photos.example.com?x=1",
                   "https://photos.example.com/?", "https://photos.example.com#top", "https://user:pw@photos.example.com",
                   "https://user@photos.example.com", "https://@photos.example.com", "https://photos.example.com:0",
                   "https://photos.example.com:99999", "https://photos.example.com:port", "https://photos example.com",
                   "https://photos.\texample.com", "https://photos..example.com",
                   "https://photos.example.com..", "https://-photos.example.com", "https://phötos.example.com",
                   "https://photos_lib.example.com", "http://[fe80::1%25eth0]", "http://[not-an-ip]", "https:///",
                   "https://photos.example.com\\@evil.example", "https://" + "a" * 250 + ".example"]
        for text in refused:
            with self.subTest(text=text):
                self.assertIsNone(immich.clean_url(text))


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.page = immich.parse_page(json.loads(fixture("search_page")), 1, OWNER)
        self.by_id = {a.id[-2:]: a for a in self.page.assets}

    def test_a_mixed_page_becomes_records_and_drops_what_has_no_time_or_kind(self):
        self.assertEqual(sorted(self.by_id), ["01", "02", "03", "04", "06", "07", "08", "09"])
        self.assertEqual(self.page.next_page, 2)

    def test_gps_and_an_iana_zone_at_that_instant(self):
        self.assertEqual(self.by_id["01"], immich.Asset(
            id=ASSET, kind="image", taken_utc="2026-07-04T18:30:12.000Z", taken_local="2026-07-04T14:30", taken_offset=-240,
            latitude=44.3876, longitude=-68.2039, state="Maine", country="United States of America",
            updated_at="2026-07-05T02:00:00.123Z"))

    def test_a_fixed_utc_offset_zone_and_no_gps(self):
        a = self.by_id["02"]
        self.assertEqual((a.taken_utc, a.taken_local, a.taken_offset), ("2026-01-10T14:15:00.000Z", "2026-01-10T09:15", -300))
        self.assertEqual((a.latitude, a.longitude, a.state, a.country), (None, None, None, None))

    def test_no_exif_has_no_offset(self):
        a = self.by_id["03"]
        self.assertEqual((a.taken_utc, a.taken_local, a.taken_offset, a.latitude), ("2026-03-01T08:00:00.000Z", "2026-03-01T08:00", None, None))

    def test_a_video_in_a_half_hour_zone(self):
        a = self.by_id["04"]
        self.assertEqual((a.kind, a.taken_offset, a.taken_local, a.state), ("video", 330, "2026-02-14T19:45", "Karnataka"))

    def test_local_and_file_created_are_each_taken_from_their_own_field(self):
        a = self.by_id["06"]
        self.assertEqual((a.taken_utc, a.taken_local, a.taken_offset), ("2026-05-02T01:00:00.000Z", "2026-05-01T18:00", None))

    def test_utc_alone_and_a_position_at_zero_zero(self):
        a = self.by_id["07"]
        self.assertEqual((a.taken_offset, a.latitude, a.longitude), (0, 0.0, 0.0))

    def test_the_pole_and_the_antimeridian_are_positions(self):
        a = self.by_id["08"]
        self.assertEqual((a.latitude, a.longitude, a.taken_offset, a.taken_local), (-90.0, 180.0, 720, "2026-12-24T23:59"))

    def test_an_unknown_zone_leaves_the_offset_unknown_and_bad_gps_is_dropped(self):
        a = self.by_id["09"]
        self.assertEqual((a.taken_utc, a.taken_local, a.taken_offset, a.latitude, a.longitude),
                         ("2026-08-15T08:00:00.000Z", "2026-08-15T10:00", None, None, None))

    def test_file_created_wins_over_date_time_original(self):
        item = {"id": "a1", "type": "IMAGE", "ownerId": OWNER, "localDateTime": "2026-01-01T10:00:00.000Z", "fileCreatedAt": "2026-01-01T09:00:00.000Z",
                "updatedAt": "2026-01-02T00:00:00Z", "exifInfo": {"dateTimeOriginal": "2026-01-01T09:00:05.000Z", "timeZone": None}}
        a = immich.parse_asset(item, OWNER)
        assert a
        self.assertEqual((a.taken_utc, a.taken_offset), ("2026-01-01T09:00:00.000Z", None))

    def test_an_asset_without_a_usable_file_created_is_skipped(self):
        for created in (None, "", "yesterday", "2026-01-01T09:00:00"):
            for zone in (None, "Europe/Paris"):
                item = {"id": "a1", "type": "IMAGE", "ownerId": OWNER, "localDateTime": "2026-01-01T10:00:00.000Z", "fileCreatedAt": created,
                        "updatedAt": "2026-01-02T00:00:00Z", "exifInfo": {"dateTimeOriginal": "2026-01-01T09:00:00.000Z", "timeZone": zone}}
                with self.subTest(created=created, zone=zone):
                    self.assertIsNone(immich.parse_asset(item, OWNER))

    def test_another_owner_s_asset_is_dropped(self):
        self.assertNotIn("11", self.by_id)
        good = {"id": "a1", "type": "IMAGE", "ownerId": OWNER, "localDateTime": "2026-01-01T10:00:00.000Z",
                "fileCreatedAt": "2026-01-01T15:00:00.000Z", "updatedAt": "2026-01-02T00:00:00Z"}
        self.assertIsNotNone(immich.parse_asset(good, OWNER))
        for owner in (PARTNER, None, "", 7, OWNER.upper()):
            with self.subTest(owner=owner):
                self.assertIsNone(immich.parse_asset({**good, "ownerId": owner}, OWNER))
        without = dict(good)
        del without["ownerId"]
        self.assertIsNone(immich.parse_asset(without, OWNER))

    def test_the_offset_comes_only_from_the_time_zone(self):
        base = {"id": "a1", "type": "IMAGE", "ownerId": OWNER, "localDateTime": "2026-01-01T10:00:00.000Z", "fileCreatedAt": "2026-01-01T09:00:00.000Z",
                "updatedAt": "2026-01-02T00:00:00Z"}
        for exif, offset in (({"dateTimeOriginal": "2026-01-01T09:00:00.000Z", "timeZone": None}, None),
                             ({"dateTimeOriginal": "2026-01-01T10:00:00+01:00"}, None),
                             ({"dateTimeOriginal": "2026-01-01T09:00:00.000Z", "timeZone": "Mars/Olympus_Mons"}, None),
                             ({"dateTimeOriginal": "2026-01-01T09:00:00.000Z", "timeZone": "UTC+01:00"}, 60)):
            with self.subTest(exif=exif):
                a = immich.parse_asset({**base, "exifInfo": exif}, OWNER)
                assert a
                self.assertEqual(a.taken_offset, offset)

    def test_assets_that_are_not_usable_are_dropped(self):
        good = {"id": "a1", "type": "IMAGE", "ownerId": OWNER, "localDateTime": "2026-01-01T10:00:00.000Z", "fileCreatedAt": "2026-01-01T15:00:00.000Z",
                "updatedAt": "2026-01-02T00:00:00Z"}
        self.assertIsNotNone(immich.parse_asset(good, OWNER))
        broken = [None, [], "x", {**good, "id": None}, {**good, "id": ""}, {**good, "id": "../users/me"}, {**good, "id": "a" * 65},
                  {**good, "type": "AUDIO"}, {**good, "type": None}, {**good, "type": ["IMAGE"]}, {**good, "fileCreatedAt": None},
                  {**good, "fileCreatedAt": "2026-01-01T15:00:00"}, {**good, "fileCreatedAt": "yesterday"},
                  {**good, "fileCreatedAt": 1767279600}, {**good, "localDateTime": None}, {**good, "localDateTime": "2026-02-30T10:00"},
                  {**good, "localDateTime": "10:00"}, {**good, "updatedAt": None}, {**good, "updatedAt": "soon"},
                  {**good, "fileCreatedAt": "0001-01-01T00:00:00+05:00"}]
        for item in broken:
            with self.subTest(item=item):
                self.assertIsNone(immich.parse_asset(item, OWNER))

    def test_gps_needs_both_numbers_in_range(self):
        base = {"id": "a1", "type": "IMAGE", "ownerId": OWNER, "localDateTime": "2026-01-01T10:00:00.000Z", "fileCreatedAt": "2026-01-01T15:00:00.000Z",
                "updatedAt": "2026-01-02T00:00:00Z"}
        for lat, lon in ((True, 10), (10, "20"), (10, None), (float("nan"), 10), (10, float("inf")), (10, 180.5), (-90.1, 0), (10**400, 0)):
            with self.subTest(lat=lat, lon=lon):
                a = immich.parse_asset({**base, "exifInfo": {"latitude": lat, "longitude": lon}}, OWNER)
                assert a
                self.assertEqual((a.latitude, a.longitude), (None, None))

    def test_state_and_country_are_trimmed_text(self):
        base = {"id": "a1", "type": "IMAGE", "ownerId": OWNER, "localDateTime": "2026-01-01T10:00:00.000Z", "fileCreatedAt": "2026-01-01T15:00:00.000Z",
                "updatedAt": "2026-01-02T00:00:00Z"}
        a = immich.parse_asset({**base, "exifInfo": {"state": "  Maine ", "country": "x" * 300}}, OWNER)
        assert a
        self.assertEqual((a.state, a.country), ("Maine", "x" * 100))
        a = immich.parse_asset({**base, "exifInfo": {"state": "   ", "country": 7}}, OWNER)
        assert a
        self.assertEqual((a.state, a.country), (None, None))

    def test_zone_offsets(self):
        summer, winter = datetime(2026, 7, 1, 12, tzinfo=UTC), datetime(2026, 1, 1, 12, tzinfo=UTC)
        cases = [("America/New_York", summer, -240), ("America/New_York", winter, -300), ("Asia/Kolkata", winter, 330),
                 ("Asia/Kathmandu", winter, 345), ("America/St_Johns", winter, -210), ("UTC", winter, 0), ("UTC+0", winter, 0),
                 ("UTC-05:00", summer, -300), ("UTC-5", summer, -300), ("UTC+5:30", winter, 330), ("UTC+05:45", winter, 345),
                 ("UTC+14", winter, 840), ("UTC-0930", winter, -570), ("Etc/GMT+5", winter, -300),
                 ("Europe/London", datetime(2026, 3, 29, 0, 59, tzinfo=UTC), 0), ("Europe/London", datetime(2026, 3, 29, 1, 0, tzinfo=UTC), 60),
                 ("Mars/Olympus_Mons", winter, None), ("", winter, None), (None, winter, None), (5, winter, None),
                 ("UTC+19", winter, None), ("UTC+18:30", winter, None), ("UTC-18:01", winter, None), ("UTC+18", winter, 1080), ("UTC-18:00", winter, -1080), ("UTC+05:60", winter, None), ("../../etc/passwd", winter, None), ("/etc/localtime", winter, None),
                 ("x" * 80, winter, None), ("America/New_York\x00", winter, None), ("America/New_York", datetime(9999, 12, 31, 23, tzinfo=UTC), -300)]
        for name, at, offset in cases:
            with self.subTest(name=name, at=at):
                self.assertEqual(immich.zone_offset(name, at), offset)

    def test_next_page(self):
        for value, page, expected in (("2", 1, 2), ("5", 4, 5), (None, 1, None), (None, 7, None)):
            with self.subTest(value=value, page=page):
                self.assertEqual(immich.next_page(value, page), expected)

    def test_pagination_that_does_not_advance_by_one_is_unreadable(self):
        for value, page in (("", 1), ("next", 1), ("1", 1), ("0", 1), ("3", 1), ("-2", 1), (" 2", 1), (2, 1), (3, 2), (True, 0),
                            (2.0, 1), ([], 1), ({}, 1)):
            with self.subTest(value=value, page=page), self.assertRaises(immich.Unavailable) as e:
                immich.next_page(value, page)
            self.assertEqual(str(e.exception), immich.UNREADABLE)

    def test_a_page_without_next_page_is_unreadable_not_the_last(self):
        with self.assertRaises(immich.Unavailable) as e:
            immich.parse_page({"assets": {"items": []}}, 1, OWNER)
        self.assertEqual(str(e.exception), immich.UNREADABLE)

    def test_an_empty_last_page(self):
        self.assertEqual(immich.parse_page({"assets": {"items": [], "nextPage": None}}, 3, OWNER), immich.Page(assets=(), next_page=None))

    def test_a_reply_that_is_not_a_page_is_unreadable(self):
        for body in (None, [], "x", {}, {"assets": []}, {"assets": {"items": None}}, {"assets": {"items": {}}}):
            with self.subTest(body=body), self.assertRaises(immich.Unavailable) as e:
                immich.parse_page(body, 1, OWNER)
            self.assertEqual(str(e.exception), immich.UNREADABLE)

    def test_markers(self):
        self.assertEqual(immich.parse_markers(json.loads(fixture("markers"))), [
            ("0b000000-0000-4000-8000-000000000001", 44.3876, -68.2039), ("0b000000-0000-4000-8000-000000000002", 0.0, 0.0),
            ("0b000000-0000-4000-8000-000000000005", -33.8688, -180.0)])
        for body in ({}, None, "x"):
            with self.subTest(body=body), self.assertRaises(immich.Unavailable):
                immich.parse_markers(body)
        self.assertEqual(immich.parse_markers([None, {"id": 5, "lat": 1, "lon": 1}]), [])

    def test_account(self):
        self.assertEqual(immich.parse_account(json.loads(fixture("users_me"))),
                         immich.Account(user_id="0c000000-0000-4000-8000-000000000001", name="Jane Example", email="jane@example.com"))
        self.assertEqual(immich.parse_account({"id": "u1"}), immich.Account(user_id="u1", name=None, email=None))
        for body in (None, [], {}, {"id": ""}, {"id": 7}):
            with self.subTest(body=body), self.assertRaises(immich.Unavailable):
                immich.parse_account(body)

    def test_retry_after(self):
        now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
        cases = [("120", 120.0), ("0", 0.0), (" 30 ", 30.0), (None, None), ("", None), ("-5", None), ("1.5", None), ("soon", None),
                 ("²", None), ("Fri, 06 Nov 2026 12:01:30 GMT", 90.0), ("Fri, 06 Nov 2026 11:00:00 GMT", 0.0),
                 ("Fri, 06 Nov 2026 12:00:10 -0000", 10.0)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(immich.retry_after(value, now), expected)

    def test_sniff(self):
        self.assertEqual([immich.sniff(d) for d in (JPEG, PNG, WEBP, b"GIF89a", b"<svg", b"<html>", b"")],
                         ["image/jpeg", "image/png", "image/webp", None, None, None, None])

    def test_request_times_need_a_zone(self):
        with self.assertRaises(ValueError):
            immich.search_body(datetime(2026, 7, 1), BEFORE, None, 1)


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.fake = serve(self)

    def test_search_posts_the_filters_with_the_key_in_a_header(self):
        self.fake.routes["/api/search/metadata"] = (200, JSON_HEADERS, fixture("search_page"))
        page = immich.search(self.fake.source, AFTER, BEFORE, page=1)
        self.assertEqual(len(page.assets), 8)
        self.assertEqual(page.next_page, 2)
        [call] = self.fake.calls
        self.assertEqual((call["method"], call["path"]), ("POST", "/api/search/metadata"))
        self.assertEqual(call["headers"]["x-api-key"], KEY)
        self.assertEqual(call["headers"]["user-agent"], "Waypoint/1")
        self.assertEqual(call["headers"]["accept"], "application/json")
        self.assertEqual(call["headers"]["content-type"], "application/json")
        self.assertEqual(json.loads(call["body"]), {"takenAfter": "2026-07-01T04:00:00.000Z", "takenBefore": "2026-07-10T03:59:59.000Z",
                                                     "withExif": True, "visibility": "timeline", "size": 1000, "order": "asc", "page": 1})
        self.assertNotIn(KEY, call["path"])

    def test_search_keeps_only_the_key_s_own_assets(self):
        self.fake.routes["/api/search/metadata"] = (200, JSON_HEADERS, fixture("search_page"))
        ids = [a.id for a in immich.search(self.fake.source, AFTER, BEFORE).assets]
        self.assertNotIn("0a000000-0000-4000-8000-000000000011", ids)
        self.assertEqual(len(ids), 8)

    def test_search_needs_the_library_s_immich_user(self):
        opened = mock.Mock(side_effect=AssertionError("nothing may be opened"))
        for user_id in (None, ""):
            source = immich.Source(url=self.fake.source.url, key=KEY, allow_http=True, user_id=user_id)
            with self.subTest(user_id=user_id), mock.patch.object(tls, "urlopen", opened), self.assertRaises(immich.NotConfigured):
                immich.search(source, AFTER, BEFORE)
        opened.assert_not_called()

    def test_an_incremental_search_adds_updated_after_and_the_page(self):
        self.fake.routes["/api/search/metadata"] = (200, JSON_HEADERS, b'{"assets": {"items": [], "nextPage": null}}')
        later = datetime(2026, 7, 2, 9, 30, tzinfo=timezone(timedelta(hours=-4)))
        self.assertEqual(immich.search(self.fake.source, AFTER, BEFORE, updated_after=later, page=4), immich.Page((), None))
        body = json.loads(self.fake.calls[0]["body"])
        self.assertEqual((body["updatedAfter"], body["page"]), ("2026-07-02T13:30:00.000Z", 4))

    def test_markers_ask_for_the_window_and_the_library_s_own_assets(self):
        self.fake.routes["/api/map/markers"] = (200, JSON_HEADERS, fixture("markers"))
        self.assertEqual(len(immich.markers(self.fake.source, AFTER, BEFORE)), 3)
        [call] = self.fake.calls
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["path"], "/api/map/markers?fileCreatedAfter=2026-07-01T04%3A00%3A00.000Z&fileCreatedBefore=2026-07-10T03%3A59%3A59.000Z"
                                       "&isArchived=false&withPartners=false&withSharedAlbums=false")

    def test_ping_reports_who_the_key_belongs_to(self):
        self.fake.routes["/api/server/ping"] = (200, JSON_HEADERS, b'{"res": "pong"}')
        self.fake.routes["/api/users/me"] = (200, JSON_HEADERS, fixture("users_me"))
        self.assertEqual(immich.ping(self.fake.source).name, "Jane Example")
        self.assertEqual([c["path"] for c in self.fake.calls], ["/api/server/ping", "/api/users/me"])
        self.assertTrue(all(c["headers"]["x-api-key"] == KEY for c in self.fake.calls))

    def test_ping_that_does_not_pong_is_unreadable(self):
        for body in (b'{"res": "nope"}', b"[]", b"<html>", b"\xff\xfe", b"[" * 100_000):
            self.fake.routes["/api/server/ping"] = (200, JSON_HEADERS, body)
            with self.subTest(body=body[:10]), self.assertRaises(immich.Unavailable) as e:
                immich.ping(self.fake.source)
            self.assertEqual(str(e.exception), immich.UNREADABLE)

    def test_a_missing_endpoint_or_an_empty_answer_is_unavailable(self):
        with self.assertRaises(immich.Unavailable) as e:
            immich.ping(self.fake.source)
        self.assertEqual(str(e.exception), immich.UNAVAILABLE)
        self.fake.routes["/api/server/ping"] = (204, {}, b"")
        with self.assertRaises(immich.Unavailable) as e:
            immich.ping(self.fake.source)
        self.assertEqual(str(e.exception), immich.UNAVAILABLE)

    def test_thumbnails_and_previews(self):
        for size, body, kind in (("thumbnail", WEBP, "image/webp"), ("preview", JPEG, "image/jpeg"), ("thumbnail", PNG, "image/png")):
            self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (200, {"Content-Type": "image/whatever"}, body)
            with self.subTest(size=size):
                self.assertEqual(immich.thumbnail(self.fake.source, ASSET, size), (kind, body))  # type: ignore[arg-type]
                call = self.fake.calls[-1]
                self.assertEqual(call["path"], f"/api/assets/{ASSET}/thumbnail?size={size}")
                self.assertEqual(call["headers"]["accept"], "image/webp,image/jpeg,image/png")
                self.assertEqual(call["headers"]["x-api-key"], KEY)

    def test_a_missing_thumbnail_is_none(self):
        self.assertIsNone(immich.thumbnail(self.fake.source, ASSET, "thumbnail"))

    def test_a_thumbnail_that_is_not_a_picture_is_refused(self):
        for headers, body in (({"Content-Type": "text/html"}, b"<html><script>x</script></html>"),
                              ({"Content-Type": "image/svg+xml"}, b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
                              ({"Content-Type": "image/gif"}, b"GIF89a" + b"\x00" * 20), ({"Content-Type": "image/jpeg"}, b"")):
            self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (200, headers, body)
            with self.subTest(headers=headers), self.assertRaises(immich.Unavailable) as e:
                immich.thumbnail(self.fake.source, ASSET, "thumbnail")
            self.assertEqual(str(e.exception), immich.NOT_AN_IMAGE)

    def test_a_thumbnail_over_the_cap_is_refused(self):
        big = JPEG + b"\x00" * immich.CAPS["thumbnail"]
        for headers in ({}, {"_no_length": "1"}):
            self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (200, headers, big)
            with self.subTest(headers=headers), self.assertRaises(immich.Unavailable) as e:
                immich.thumbnail(self.fake.source, ASSET, "thumbnail")
            self.assertEqual(str(e.exception), immich.TOO_LARGE)
        self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (200, {}, big)
        self.assertEqual(immich.thumbnail(self.fake.source, ASSET, "preview"), ("image/jpeg", big))

    def test_a_declared_length_over_the_cap_is_refused_before_reading(self):
        response = mock.Mock()
        response.headers = {"Content-Length": str(immich.CAPS["thumbnail"] + 1)}
        with self.assertRaises(immich.Unavailable) as e:
            immich._read(response, immich.CAPS["thumbnail"], 5)
        self.assertEqual(str(e.exception), immich.TOO_LARGE)
        response.read1.assert_not_called()

    def test_a_body_that_takes_too_long_is_refused(self):
        response = mock.Mock()
        response.headers = {}
        response.read1.side_effect = [b"x" * 10] * 5 + [b""]
        clock = iter([0.0, 1.0, 2.0, 30.0, 31.0])
        with mock.patch.object(immich.time, "monotonic", lambda: next(clock)), self.assertRaises(immich.Unavailable) as e:
            immich._read(response, 1000, immich.IMAGE_SECONDS)
        self.assertEqual(str(e.exception), immich.TOO_SLOW)

    def _slow(self, call):
        began = time.monotonic()
        with self.assertRaises(immich.Unavailable) as e:
            call()
        self.assertEqual(str(e.exception), immich.TOO_SLOW)
        self.assertLess(time.monotonic() - began, 2.0)

    def test_a_thumbnail_that_trickles_stops_at_its_budget(self):
        self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (200, {"_trickle": "0.02"}, JPEG + b"\x00" * 400)
        with mock.patch.object(immich, "IMAGE_SECONDS", 0.5):
            self._slow(lambda: immich.thumbnail(self.fake.source, ASSET, "thumbnail"))

    def test_a_thumbnail_that_stalls_part_way_stops_at_its_budget(self):
        self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (200, {"_trickle": "4"}, JPEG[:2])
        with mock.patch.object(immich, "IMAGE_SECONDS", 0.5):
            self._slow(lambda: immich.thumbnail(self.fake.source, ASSET, "thumbnail"))

    def test_a_search_reply_that_trickles_stops_at_its_budget(self):
        self.fake.routes["/api/search/metadata"] = (200, {**JSON_HEADERS, "_trickle": "0.02"}, b'{"assets": {"items": [], "nextPage": null}}' + b" " * 400)
        with mock.patch.object(immich, "JSON_SECONDS", 0.5):
            self._slow(lambda: immich.search(self.fake.source, AFTER, BEFORE))

    def test_a_chunked_thumbnail_whose_size_line_and_trailers_trickle_stops_at_its_budget(self):
        self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (200, {"_chunked": "1", "_trickle": "0.02"}, JPEG)
        with mock.patch.object(immich, "IMAGE_SECONDS", 0.5):
            self._slow(lambda: immich.thumbnail(self.fake.source, ASSET, "thumbnail"))

    def test_a_chunked_search_reply_whose_size_line_and_trailers_trickle_stops_at_its_budget(self):
        self.fake.routes["/api/search/metadata"] = (200, {**JSON_HEADERS, "_chunked": "1", "_trickle": "0.02"},
                                                    b'{"assets": {"items": [], "nextPage": null}}')
        with mock.patch.object(immich, "JSON_SECONDS", 0.5):
            self._slow(lambda: immich.search(self.fake.source, AFTER, BEFORE))

    def test_a_chunked_reply_that_arrives_in_time_is_read_whole(self):
        self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (200, {"_chunked": "1"}, JPEG)
        self.fake.routes["/api/search/metadata"] = (200, {**JSON_HEADERS, "_chunked": "1"}, fixture("search_page"))
        self.assertEqual(immich.thumbnail(self.fake.source, ASSET, "thumbnail"), ("image/jpeg", JPEG))
        self.assertEqual(len(immich.search(self.fake.source, AFTER, BEFORE).assets), 8)

    def test_each_read_below_the_parser_gets_only_the_time_left(self):
        source = io.BufferedReader(io.BytesIO(b"abcdef"))
        buffer = bytearray(4)
        self.assertEqual(immich._Deadline(source, time.monotonic() + 5).readinto(buffer), 4)
        self.assertEqual(bytes(buffer), b"abcd")
        with self.assertRaises(TimeoutError):
            immich._Deadline(source, time.monotonic() - 0.001).readinto(buffer)
        sock = mock.Mock()
        raw = mock.Mock(_sock=sock)
        buffered = mock.Mock(raw=raw)
        buffered.readinto1.return_value = 2
        wrapped = immich._Deadline(buffered, time.monotonic() + 3)
        self.assertEqual(wrapped.readinto(bytearray(2)), 2)
        [(timeout,), _] = sock.settimeout.call_args
        self.assertTrue(2 < timeout <= 3)
        wrapped.close()
        buffered.close.assert_called_once()

    def test_a_connection_cut_while_reading_is_unreachable(self):
        response = mock.Mock()
        response.headers = {}
        response.read1.side_effect = [b"x", ConnectionResetError(f"reset by {KEY}")]
        with self.assertRaises(immich.Unavailable) as e:
            immich._read(response, 1000, 5)
        self.assertEqual(str(e.exception), immich.UNREACHABLE)
        self.assertIsNone(e.exception.__context__)

    def test_an_asset_id_that_is_not_an_id_is_never_requested(self):
        for asset_id in ("../users/me", "", "a/b", "a?b", "a" * 65, "%2e%2e"):
            with self.subTest(asset_id=asset_id):
                self.assertIsNone(immich.thumbnail(self.fake.source, asset_id, "thumbnail"))
                self.assertIsNone(immich.open_original(self.fake.source, asset_id))
        self.assertIsNone(immich.thumbnail(self.fake.source, ASSET, "fullsize"))  # type: ignore[arg-type]
        self.assertEqual(self.fake.calls, [])

    def test_an_original_streams_in_chunks(self):
        body = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 400
        self.fake.routes[f"/api/assets/{ASSET}/original"] = (200, {"Content-Type": "video/mp4"}, body)
        original = immich.open_original(self.fake.source, ASSET)
        assert original
        with original:
            chunks = []
            while chunk := original.read(10_000):
                chunks.append(chunk)
        self.assertEqual(b"".join(chunks), body)
        self.assertGreater(len(chunks), 1)
        call = self.fake.calls[0]
        self.assertEqual((call["path"], call["headers"]["x-api-key"], call["headers"]["user-agent"]),
                         (f"/api/assets/{ASSET}/original", KEY, "Waypoint/1"))

    def test_a_missing_original_is_none(self):
        self.assertIsNone(immich.open_original(self.fake.source, ASSET))

    def test_an_original_cut_off_part_way_is_unavailable(self):
        for error, text in ((ConnectionResetError(f"reset by {KEY}"), immich.UNREACHABLE), (TimeoutError(f"timed out reading from {KEY}"), immich.TOO_SLOW)):
            response = mock.Mock()
            response.read1.side_effect = error
            original = immich.Original(response, time.monotonic() + 5)
            with self.subTest(error=error), self.assertRaises(immich.Unavailable) as e:
                original.read()
            self.assertEqual(str(e.exception), text)
            self.assertIsNone(e.exception.__context__)
            original.close()
            response.close.assert_called_once()

    def test_an_original_past_its_budget_reads_nothing_more(self):
        response = mock.Mock()
        original = immich.Original(response, time.monotonic() - 0.001)
        with self.assertRaises(immich.Unavailable) as e:
            original.read()
        self.assertEqual(str(e.exception), immich.TOO_SLOW)
        response.read1.assert_not_called()

    def test_an_original_s_budget_defaults_to_ten_minutes(self):
        self.assertEqual(immich.ORIGINAL_SECONDS, 600.0)
        self.fake.routes[f"/api/assets/{ASSET}/original"] = (200, {}, b"abc")
        began = time.monotonic()
        with mock.patch.object(immich, "Original", wraps=immich.Original) as made:
            original = immich.open_original(self.fake.source, ASSET)
        assert original
        with original:
            self.assertEqual(original.read(), b"abc")
        [(_, deadline), _] = made.call_args
        self.assertTrue(began + 599 < deadline <= time.monotonic() + 600)

    def test_an_original_read_returns_what_has_arrived(self):
        body = b"\x00" * 400
        self.fake.routes[f"/api/assets/{ASSET}/original"] = (200, {"_trickle": "0.005"}, body)
        original = immich.open_original(self.fake.source, ASSET)
        assert original
        with original:
            first = original.read(10_000)
        self.assertGreater(len(first), 0)
        self.assertLess(len(first), len(body))

    def _original_until_slow(self, headers):
        self.fake.routes[f"/api/assets/{ASSET}/original"] = (200, headers, b"\x00" * 400)
        began = time.monotonic()
        original = immich.open_original(self.fake.source, ASSET, seconds=0.5)
        assert original
        with original, self.assertRaises(immich.Unavailable) as e:
            while original.read(10_000):
                pass
        self.assertEqual(str(e.exception), immich.TOO_SLOW)
        self.assertLess(time.monotonic() - began, 2.0)

    def test_an_original_that_trickles_stops_at_the_budget_it_was_given(self):
        self._original_until_slow({"_trickle": "0.02"})

    def test_a_chunked_original_that_trickles_stops_at_the_budget_it_was_given(self):
        self._original_until_slow({"_chunked": "1", "_trickle": "0.02"})

    def test_refused_and_rate_limited_answers(self):
        for code, headers, kind in ((401, {}, immich.Refused), (403, {}, immich.Refused), (429, {}, immich.RateLimited),
                                    (500, {}, immich.Unavailable), (502, {}, immich.Unavailable), (410, {}, immich.Unavailable),
                                    (400, {}, immich.Unavailable)):
            self.fake.routes["/api/search/metadata"] = (code, {**JSON_HEADERS, **headers}, b'{"message": "no"}')
            self.fake.routes[f"/api/assets/{ASSET}/thumbnail"] = (code, headers, b"no")
            self.fake.routes[f"/api/assets/{ASSET}/original"] = (code, headers, b"no")
            for call in (lambda: immich.search(self.fake.source, AFTER, BEFORE), lambda: immich.thumbnail(self.fake.source, ASSET, "preview"),
                         lambda: immich.open_original(self.fake.source, ASSET)):
                with self.subTest(code=code), self.assertRaises(kind):
                    call()

    def test_retry_after_is_passed_on(self):
        for value, expected in (("90", 90.0), (None, None), ("tomorrow-ish", None)):
            self.fake.routes["/api/search/metadata"] = (429, {"Retry-After": value} if value else {}, b"")
            with self.subTest(value=value), self.assertRaises(immich.RateLimited) as e:
                immich.search(self.fake.source, AFTER, BEFORE)
            self.assertEqual(e.exception.retry_after, expected)
            self.assertEqual(str(e.exception), immich.RATE_LIMITED)
        future = (datetime.now(UTC) + timedelta(minutes=5)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.fake.routes["/api/search/metadata"] = (429, {"Retry-After": future}, b"")
        with self.assertRaises(immich.RateLimited) as e:
            immich.search(self.fake.source, AFTER, BEFORE)
        assert e.exception.retry_after is not None
        self.assertTrue(250 < e.exception.retry_after <= 300)

    def test_a_redirect_is_not_followed_so_the_key_goes_nowhere_else(self):
        elsewhere = serve(self)
        self.fake.routes["/api/server/ping"] = (302, {"Location": f"http://127.0.0.1:{elsewhere.server_port}/steal"}, b"")
        self.fake.routes[f"/api/assets/{ASSET}/original"] = (307, {"Location": f"http://127.0.0.1:{elsewhere.server_port}/steal"}, b"")
        with self.assertRaises(immich.Unavailable):
            immich.ping(self.fake.source)
        with self.assertRaises(immich.Unavailable):
            immich.open_original(self.fake.source, ASSET)
        self.assertEqual(elsewhere.calls, [])

    def test_a_connection_error_is_unreachable(self):
        self.fake.server_close()
        source = immich.Source(url="http://127.0.0.1:9", key=KEY, allow_http=True)
        for call in (lambda: immich.ping(source), lambda: immich.thumbnail(source, ASSET, "thumbnail"), lambda: immich.open_original(source, ASSET)):
            with self.assertRaises(immich.Unavailable) as e:
                call()
            self.assertEqual(str(e.exception), immich.UNREACHABLE)

    def test_a_server_that_does_not_answer_times_out(self):
        self.fake.routes["/api/server/ping"] = (200, JSON_HEADERS, lambda: time.sleep(1.5) or b'{"res": "pong"}')
        with mock.patch.object(immich, "TIMEOUT", 0.3), self.assertRaises(immich.Unavailable) as e:
            immich.ping(self.fake.source)
        self.assertEqual(str(e.exception), immich.UNREACHABLE)

    def test_plain_http_needs_allow_http(self):
        self.fake.routes["/api/server/ping"] = (200, JSON_HEADERS, b'{"res": "pong"}')
        with self.assertRaises(immich.Unavailable):
            immich.ping(immich.Source(url=self.fake.source.url, key=KEY))
        self.assertEqual(self.fake.calls, [])

    def test_a_source_without_a_usable_address_or_key_is_not_configured(self):
        opened = mock.Mock(side_effect=AssertionError("nothing may be opened"))
        bad = [immich.Source(url="", key=KEY), immich.Source(url="https://photos.example.com/api", key=KEY),
               immich.Source(url="https://photos.example.com", key=""), immich.Source(url="https://photos.example.com", key="a b"),
               immich.Source(url="https://photos.example.com", key=f"{KEY}\r\nX-Evil: 1"), immich.Source(url="https://photos.example.com", key="ké")]
        with mock.patch.object(tls, "urlopen", opened):
            for source in bad:
                for call in (immich.ping, lambda s: immich.search(s, AFTER, BEFORE), lambda s: immich.markers(s, AFTER, BEFORE),
                             lambda s: immich.thumbnail(s, ASSET, "thumbnail"), lambda s: immich.open_original(s, ASSET)):
                    with self.subTest(source=source), self.assertRaises(immich.NotConfigured) as e:
                        call(source)
                    self.assertEqual(str(e.exception), immich.NOT_CONFIGURED)
        opened.assert_not_called()


class PrivacyTests(unittest.TestCase):
    HOST = "immich-canary-r4t8.example"

    def _failures(self):
        source = immich.Source(url=f"https://{self.HOST}:2283", key=KEY, user_id=OWNER)
        where = f"https://{self.HOST}:2283/api/search/metadata?key={KEY}"
        raised = [urllib.error.URLError(f"<urlopen error [Errno -2] Name or service not known: {self.HOST} {KEY}>"),
                  TimeoutError(f"timed out talking to {self.HOST}"), ValueError(f"Invalid header value {KEY!r}"),
                  urllib.error.HTTPError(where, 401, f"Unauthorized {KEY}", email.message.Message(), io.BytesIO(KEY.encode())),
                  urllib.error.HTTPError(where, 429, f"slow down {self.HOST}", email.message.Message(), io.BytesIO(b"")),
                  urllib.error.HTTPError(where, 500, f"boom {self.HOST}", email.message.Message(), io.BytesIO(b""))]
        calls = (lambda: immich.ping(source), lambda: immich.search(source, AFTER, BEFORE), lambda: immich.markers(source, AFTER, BEFORE),
                 lambda: immich.thumbnail(source, ASSET, "preview"), lambda: immich.open_original(source, ASSET))
        for error in raised:
            for call in calls:
                yield error, call

    def test_errors_carry_neither_the_host_nor_the_key(self):
        seen = []
        with no_leaks(self, KEY, self.HOST, sent_ok=True):
            for error, call in self._failures():
                with mock.patch.object(tls, "urlopen", mock.Mock(side_effect=error)):
                    try:
                        call()
                    except immich.ImmichError as e:
                        seen.append(e)
                        text = "".join(traceback.format_exception(e)) + repr(e) + str(e.args)
                        self.assertNotIn(KEY, text)
                        self.assertNotIn(self.HOST, text)
                        self.assertIsNone(e.__cause__)
                        self.assertIsNone(e.__context__)
        self.assertEqual(len(seen), 30)
        self.assertEqual({type(e) for e in seen}, {immich.Unavailable, immich.Refused, immich.RateLimited})

    def test_a_source_s_repr_shows_neither(self):
        source = immich.Source(url=f"https://{self.HOST}", key=KEY, allow_http=True)
        self.assertNotIn(KEY, repr(source))
        self.assertNotIn(self.HOST, repr(source))

    def test_the_key_is_sent_only_in_its_header(self):
        sent = []

        def recording(req, *args, **kwargs):
            sent.append(req)
            raise urllib.error.URLError("down")

        source = immich.Source(url=f"https://{self.HOST}", key=KEY, user_id=OWNER)
        with mock.patch.object(tls, "urlopen", recording):
            for call in (lambda: immich.ping(source), lambda: immich.search(source, AFTER, BEFORE), lambda: immich.markers(source, AFTER, BEFORE),
                         lambda: immich.thumbnail(source, ASSET, "thumbnail"), lambda: immich.open_original(source, ASSET)):
                with self.assertRaises(immich.Unavailable):
                    call()
        self.assertEqual(len(sent), 5)
        for req in sent:
            self.assertNotIn(KEY, req.full_url)
            self.assertNotIn(KEY, (req.data or b"").decode())
            self.assertEqual(req.get_header("X-api-key"), KEY)
            self.assertEqual(req.get_header("User-agent"), "Waypoint/1")


if __name__ == "__main__":
    unittest.main()
