import http.client
import json
import struct
import threading
import time
import unittest
import urllib.parse
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import delete, update

from tests.privacy import no_leaks
from tests.shared import fetch
from tests.test_every_route import NOT_JSON
from tests.test_immich_provider import http_error
from tests.test_photo_access import AccessCase
from tests.test_photos_api import ASSET, KEY, SOHO, photo_row, stored
from waypoint import tls
from waypoint.domain import photoproxy, photos, photosources
from waypoint.providers import immich
from waypoint.server import mcp_access, mcp_http
from waypoint.storage import db, secretbox
from waypoint.storage.models import Person, Photo, PhotoExclusion, PhotoGrant, PhotoSource

HOST = "immich-canary-8h2k.example"
HEADER_CANARY = "canary-immich-header-3v8n"
BODY_CANARY = b"canary-immich-error-7t2q"
NO_IMAGE = {"error": "No such image"}
CSP = "default-src 'none'; sandbox"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + bytes(64)
JPEG = b"\xff\xd8\xff\xe0" + bytes(64)
PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + bytes(range(256)) * 40
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + bytes(64)
TIFF = b"II*\x00" + bytes(64)
GIF = b"GIF89a" + bytes(64)
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>" + bytes(64)
IMAGE_ROUTES = ("/api/photos/{id}/thumbnail", "/api/photos/{id}/preview", "/api/photos/{id}/original")


class Reply:
    def __init__(self, status, body, headers=None, piece=None, pause=0.0, gate=None, gate_after=0, idle=30.0):
        self.status = status
        self.headers = {"Content-Length": str(len(body)), **(headers or {})}
        self._body, self._at, self._piece, self._pause = body, 0, piece, pause
        self._gate, self._gate_after, self._reads, self._due = gate, gate_after, 0, None
        self.fp = SimpleNamespace(raw=SimpleNamespace(_owner=SimpleNamespace(timeout=idle)))

    def read1(self, size=-1):
        limit = self.fp.raw._owner.timeout
        if self._pause:
            now = time.monotonic()
            due = self._due if self._due is not None else now + self._pause
            if due - now > limit:
                time.sleep(limit)
                self._due = due
                raise TimeoutError("not yet")
            time.sleep(max(0.0, due - now))
            self._due = time.monotonic() + self._pause
        if self._gate is not None and self._reads >= self._gate_after and not self._gate.wait(limit):
            raise TimeoutError("stalled")
        self._reads += 1
        take = len(self._body) if size < 0 else size
        if self._piece:
            take = min(take, self._piece)
        chunk = self._body[self._at:self._at + take]
        self._at += len(chunk)
        return chunk

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fixed(status, body=b"", headers=None, **more):
    return lambda sent: Reply(status, body, headers, **more)


def failing(error):
    def answer(sent):
        raise error
    return answer


def ranged(body, content_type, **more):
    def answer(sent):
        asked = immich.BYTE_RANGE.fullmatch(sent.get("range") or "")
        headers = {"Content-Type": content_type, "Accept-Ranges": "bytes"}
        if asked is None:
            return Reply(200, body, headers, **more)
        if asked.group(3):
            first, last = max(0, len(body) - int(asked.group(3))), len(body) - 1
        else:
            first = int(asked.group(1))
            last = min(int(asked.group(2)), len(body) - 1) if asked.group(2) else len(body) - 1
        if first >= len(body):
            return Reply(416, b"", {**headers, "Content-Range": f"bytes */{len(body)}"})
        return Reply(206, body[first:last + 1], {**headers, "Content-Range": f"bytes {first}-{last}/{len(body)}"}, **more)
    return answer


class FakeImmich:
    def __init__(self):
        self.routes = {}
        self.calls = []

    def __call__(self, req, timeout=None, **kwargs):
        parts = urllib.parse.urlsplit(req.full_url)
        sent = {k.lower(): v for k, v in req.header_items()}
        self.calls.append({"url": req.full_url, "path": parts.path, "query": parts.query, "headers": sent, "deadline": kwargs.get("deadline")})
        answer = self.routes.get(parts.path)
        if answer is None:
            raise http_error(404)
        return answer(sent)


def png_size(data):
    return struct.unpack(">II", data[16:24])


class ProxyCase(AccessCase):
    def setUp(self):
        super().setUp()
        self.immich = FakeImmich()
        patch = mock.patch.object(tls, "urlopen", self.immich)
        patch.start()
        self.addCleanup(patch.stop)
        self.share("ben")
        self.mine = self.photo("ben")
        self.asset = f"/api/assets/{self.asset_of(self.mine)}"
        self.immich.routes[f"{self.asset}/thumbnail"] = self.rendition
        self.immich.routes[f"{self.asset}/original"] = ranged(MP4, "video/mp4")
        self.immich.routes[self.asset] = fixed(200, b"{}", {"Content-Type": "application/json"})

    def rendition(self, sent):
        size = urllib.parse.parse_qs(urllib.parse.urlsplit(self.immich.calls[-1]["url"]).query).get("size", [""])[0]
        body = WEBP if size == "thumbnail" else JPEG
        return Reply(200, body, {"Content-Type": "image/webp", "X-Immich-Canary": HEADER_CANARY, "Set-Cookie": f"immich={HEADER_CANARY}"})

    def asset_of(self, photo_id):
        with db.session() as conn:
            row = conn.orm.get(Photo, photo_id)
            assert row is not None
            return row.asset_id

    def get(self, who, path, headers=None):
        return fetch(self.base, "GET", path, None, {"X-Waypoint": "1", **self.who[who], **(headers or {})})

    def image(self, who, path, headers=None):
        status, got, raw = self.get(who, path, headers)
        self.assertEqual(status, 200, raw)
        return got, raw

    def missing(self, who, path, headers=None):
        status, got, raw = self.get(who, path, headers)
        self.assertEqual((status, raw), (404, b'{"error": "No such image"}'))
        return got

    def exclude(self, who, photo_id):
        with db.session() as conn:
            conn.orm.add(PhotoExclusion(person_id=self.person[who], asset_id=self.asset_of(photo_id), trip_id=self.trip, created=1.0))

    def revoke(self, who):
        with db.session() as conn:
            conn.execute(update(PhotoGrant).where(PhotoGrant.person_id == self.person[who]).values(revoked=5.0))

    def replace_asset(self, photo_id):
        replacement = f"{ASSET}-replacement-2k9x"
        with db.session() as conn:
            old = conn.orm.get(Photo, photo_id)
            assert old is not None
            conn.orm.delete(old)
            conn.orm.flush()
            row = photo_row(self.sources["ben"], self.trip, "2026-06-02T10:00", where=SOHO, segment_id=self.stay["id"], asset=replacement)
            row.id = photo_id
            conn.orm.add(row)
        return f"/api/assets/{replacement}"

    def source_status(self, who):
        with db.session() as conn:
            row = conn.orm.get(PhotoSource, self.sources[who])
            assert row is not None
            return row.status, row.last_error

    def upstream(self):
        return [(c["path"], c["query"], c["headers"].get("range")) for c in self.immich.calls]


class RenditionTests(ProxyCase):
    def test_a_member_on_the_trip_gets_the_sniffed_image_with_the_csp_and_nothing_of_immichs_headers(self):
        for size, body, kind in (("thumbnail", WEBP, "image/webp"), ("preview", JPEG, "image/jpeg")):
            with self.subTest(size=size):
                self.immich.calls.clear()
                headers, raw = self.image("ana", f"/api/photos/{self.mine}/{size}")
                self.assertEqual(raw, body)
                self.assertEqual((headers["Content-Type"], headers["Cache-Control"], headers["X-Content-Type-Options"]), (kind, "private, no-cache", "nosniff"))
                self.assertIn(CSP, headers.get_all("Content-Security-Policy"))
                self.assertTrue(headers["ETag"].startswith('"') and headers["ETag"].endswith('"'))
                self.assertNotIn(HEADER_CANARY, str(headers))
                self.assertIsNone(headers.get("Set-Cookie"))
                self.assertEqual(self.upstream(), [(f"{self.asset}/thumbnail", f"size={size}", None)])
                self.assertEqual(self.immich.calls[0]["headers"]["x-api-key"], KEY)
                self.assertNotIn(KEY, self.immich.calls[0]["url"])
        headers, _ = self.image("ben", f"/api/photos/{self.mine}/thumbnail")
        self.assertEqual(headers["Content-Type"], "image/webp")

    def test_everyone_who_may_not_see_the_photo_gets_the_same_404_without_an_immich_request(self):
        self.share("ana", scope="only_me")
        private = self.photo("ana")
        excluded = self.photo("ben")
        self.exclude("ben", excluded)
        waiting = self.keep(photo_row(self.sources["ben"], None, "2026-06-02T11:00", match="ambiguous"))
        cases = [("cy", self.mine), ("ben", private), ("ana", excluded), ("ben", excluded), ("ana", waiting), ("ana", 987654), ("ana", "x")]
        for size in ("thumbnail", "preview", "original"):
            for who, photo_id in cases:
                with self.subTest(size=size, who=who, photo=photo_id):
                    self.missing(who, f"/api/photos/{photo_id}/{size}")
        self.assertEqual(self.immich.calls, [])
        for photo_id in (waiting, private):
            self.immich.routes[f"/api/assets/{self.asset_of(photo_id)}/thumbnail"] = self.rendition
        headers, _ = self.image("ben", f"/api/photos/{waiting}/thumbnail")
        self.assertEqual(headers["Content-Type"], "image/webp")
        self.assertEqual(self.get("ana", f"/api/photos/{private}/thumbnail")[0], 200)

    def test_the_key_and_the_host_stay_out_of_logs_replies_and_errors(self):
        route = f"{self.asset}/thumbnail"
        outcomes = [(self.rendition, 200), (failing(http_error(401)), 404), (failing(http_error(404)), 404), (failing(TimeoutError(f"timed out {KEY}")), 503),
                    (failing(http_error(500)), 503)]
        with no_leaks(self, KEY, HOST, sent_ok=True):
            for answer, status in outcomes:
                with self.subTest(status=status):
                    self.immich.routes[route] = answer
                    got, headers, raw = self.get("ana", f"/api/photos/{self.mine}/thumbnail")
                    self.assertEqual(got, status, raw)
                    self.assertNotIn(KEY.encode(), raw)
                    self.assertNotIn(HOST.encode(), raw)
                    self.assertNotIn(KEY, str(headers))
                    self.assertNotIn(HOST, str(headers))
                    if status == 503:
                        self.assertEqual(json.loads(raw), {"error": photoproxy.UNAVAILABLE})
        for call in self.immich.calls:
            self.assertNotIn(KEY, call["url"])
            self.assertEqual(call["headers"]["x-api-key"], KEY)

    def test_a_refusal_marks_the_library_refused_and_a_lost_key_does_too(self):
        self.immich.routes[f"{self.asset}/thumbnail"] = failing(http_error(403))
        self.missing("ana", f"/api/photos/{self.mine}/thumbnail")
        self.assertEqual(self.source_status("ben"), ("refused", immich.REFUSED))
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.sources["ben"]).values(status="ok", last_error=None))
        with mock.patch.object(secretbox, "decrypt", side_effect=secretbox.SecretError("the key was lost")):
            self.missing("ana", f"/api/photos/{self.mine}/preview")
        self.assertEqual(self.source_status("ben"), ("refused", photosources.KEY_LOST))
        self.assertEqual(len(self.immich.calls), 1)

    def test_a_body_over_the_cap_a_non_image_and_an_immich_500_answer_without_immichs_text(self):
        route = f"{self.asset}/thumbnail"
        cases = [(fixed(200, WEBP, {"Content-Length": str(immich.CAPS["thumbnail"] + 1)}), 503), (fixed(200, b"RIFF" + bytes(2_000_100), piece=500_000), 503),
                 (fixed(200, b"<html>" + BODY_CANARY + b"</html>", {"Content-Type": "text/html"}), 404), (fixed(500, BODY_CANARY), 503),
                 (fixed(200, SVG, {"Content-Type": "image/svg+xml"}), 404)]
        for answer, status in cases:
            with self.subTest(status=status):
                self.immich.routes[route] = answer
                got, headers, raw = self.get("ana", f"/api/photos/{self.mine}/thumbnail")
                self.assertEqual(got, status, raw)
                self.assertNotIn(BODY_CANARY, raw)
                self.assertEqual(headers["Content-Type"], "application/json")
        self.assertIsNotNone(stored(self.mine))

    def test_a_missing_rendition_is_a_retryable_miss_and_the_row_goes_only_when_the_asset_is_gone_too(self):
        for code in (404, 410):
            with self.subTest(code=code):
                self.immich.routes[f"{self.asset}/thumbnail"] = failing(http_error(code))
                self.immich.calls.clear()
                self.missing("ana", f"/api/photos/{self.mine}/thumbnail")
                self.assertEqual(self.upstream(), [(f"{self.asset}/thumbnail", "size=thumbnail", None), (self.asset, "", None)])
                self.assertIsNotNone(stored(self.mine))
        self.immich.routes[self.asset] = failing(http_error(410))
        self.missing("ana", f"/api/photos/{self.mine}/preview")
        self.assertIsNone(stored(self.mine))
        self.missing("ben", f"/api/photos/{self.mine}/preview")

    def test_a_missing_asset_deletes_only_the_row_that_was_served_never_one_that_reused_its_id(self):
        self.immich.routes[f"{self.asset}/thumbnail"] = failing(http_error(404))
        replacement = []

        def gone_meanwhile(sent):
            replacement.append(self.replace_asset(self.mine))
            raise http_error(404)

        self.immich.routes[self.asset] = gone_meanwhile
        self.missing("ana", f"/api/photos/{self.mine}/thumbnail")
        self.assertEqual(f"/api/assets/{self.asset_of(self.mine)}", replacement[0])
        self.assertIsNotNone(stored(self.mine))

    def test_the_asset_lookup_after_a_miss_shares_the_renditions_budget(self):
        self.immich.routes[f"{self.asset}/thumbnail"] = failing(http_error(404))
        self.missing("ana", f"/api/photos/{self.mine}/thumbnail")
        rendition, lookup = self.immich.calls
        self.assertEqual((rendition["path"], lookup["path"]), (f"{self.asset}/thumbnail", self.asset))
        self.assertAlmostEqual(rendition["deadline"], lookup["deadline"], delta=0.05)
        self.assertLess(rendition["deadline"] - time.monotonic(), immich.IMAGE_SECONDS)

    def test_a_missing_original_follows_the_same_rule(self):
        for code in (404, 410):
            for headers in ({}, {"Range": "bytes=0-9"}):
                with self.subTest(code=code, headers=headers):
                    self.immich.routes[f"{self.asset}/original"] = failing(http_error(code))
                    self.immich.calls.clear()
                    self.missing("ana", f"/api/photos/{self.mine}/original", headers)
                    self.assertEqual([c["path"] for c in self.immich.calls], [f"{self.asset}/original", self.asset])
                    self.assertIsNotNone(stored(self.mine))
        self.immich.routes[self.asset] = failing(http_error(410))
        self.missing("ana", f"/api/photos/{self.mine}/original")
        self.assertIsNone(stored(self.mine))

    def test_the_etag_round_trips_to_304_through_the_predicate_and_to_404_once_the_photo_is_taken_back(self):
        headers, _ = self.image("ana", f"/api/photos/{self.mine}/thumbnail")
        tag = headers["ETag"]
        self.immich.calls.clear()
        status, headers, raw = self.get("ana", f"/api/photos/{self.mine}/thumbnail", {"If-None-Match": tag})
        self.assertEqual((status, raw, headers["ETag"]), (304, b"", tag))
        self.assertEqual(self.immich.calls, [])
        preview, _ = self.image("ana", f"/api/photos/{self.mine}/preview", {"If-None-Match": tag})
        self.assertNotEqual(preview["ETag"], tag)
        with db.session() as conn:
            conn.execute(update(Photo).where(Photo.id == self.mine).values(asset_updated="2026-06-03T00:00:00Z"))
        self.immich.calls.clear()
        headers, raw = self.image("ana", f"/api/photos/{self.mine}/thumbnail", {"If-None-Match": tag})
        self.assertEqual(raw, WEBP)
        self.assertNotEqual(headers["ETag"], tag)
        self.assertEqual(len(self.immich.calls), 1)
        fresh = headers["ETag"]
        self.exclude("ben", self.mine)
        self.immich.calls.clear()
        self.missing("ana", f"/api/photos/{self.mine}/thumbnail", {"If-None-Match": fresh})
        self.missing("ben", f"/api/photos/{self.mine}/thumbnail", {"If-None-Match": fresh})
        with db.session() as conn:
            conn.execute(delete(PhotoExclusion))
        self.revoke("ben")
        self.missing("ana", f"/api/photos/{self.mine}/thumbnail", {"If-None-Match": fresh})
        self.assertEqual(self.immich.calls, [])

    def test_a_photo_id_reused_for_another_asset_with_the_same_revision_never_answers_304(self):
        headers, _ = self.image("ana", f"/api/photos/{self.mine}/thumbnail")
        tag = headers["ETag"]
        replacement = self.replace_asset(self.mine)
        self.immich.routes[f"{replacement}/thumbnail"] = fixed(200, PNG, {"Content-Type": "image/png"})
        self.immich.calls.clear()
        headers, raw = self.image("ana", f"/api/photos/{self.mine}/thumbnail", {"If-None-Match": tag})
        self.assertEqual((raw, headers["Content-Type"]), (PNG, "image/png"))
        self.assertNotEqual(headers["ETag"], tag)
        self.assertEqual(self.upstream(), [(f"{replacement}/thumbnail", "size=thumbnail", None)])


class DemoTests(ProxyCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.sources["ben"]).values(url="demo", api_key=""))
        failed = mock.patch.object(tls, "urlopen", side_effect=AssertionError("a demo library opened a connection"))
        failed.start()
        self.addCleanup(failed.stop)

    def test_a_demo_library_answers_placeholders_without_a_connection(self):
        headers, thumbnail = self.image("ana", f"/api/photos/{self.mine}/thumbnail")
        self.assertEqual((headers["Content-Type"], headers["Cache-Control"], png_size(thumbnail)), ("image/png", "private, no-cache", (256, 256)))
        self.assertIn(CSP, headers.get_all("Content-Security-Policy"))
        headers, preview = self.image("ana", f"/api/photos/{self.mine}/preview")
        self.assertEqual((headers["Content-Type"], png_size(preview)), ("image/png", (1280, 1280)))
        headers, original = self.image("ana", f"/api/photos/{self.mine}/original")
        self.assertEqual((headers["Content-Type"], headers["Cache-Control"], headers["Content-Disposition"], original), ("image/png", "private, no-store", "inline", preview))
        self.assertEqual(self.image("ben", f"/api/photos/{self.mine}/thumbnail")[1], thumbnail)
        other = self.photo("ben")
        self.assertNotEqual(self.image("ana", f"/api/photos/{other}/thumbnail")[1], thumbnail)
        self.missing("cy", f"/api/photos/{self.mine}/thumbnail")

    def test_testing_and_syncing_a_demo_library_answer_locally_and_the_original_opens_no_connection(self):
        with db.session() as conn:
            name = conn.orm.get(Person, self.person["ben"]).display_name
            before = conn.orm.get(PhotoSource, self.sources["ben"]).status
        source = self.sources["ben"]
        self.assertEqual(self.ok("ben", "POST", f"/api/photo-sources/{source}/test", {}), {"name": name, "same_account": True})
        self.assertEqual(self.ok("ben", "POST", f"/api/photo-sources/{source}/test", {"key": "canary-demo-key-3c9"}), {"name": name, "same_account": True})
        self.assertEqual(self.ok("ben", "POST", f"/api/photo-sources/{source}/sync"), {"started": False})
        self.assertEqual(self.image("ana", f"/api/photos/{self.mine}/original")[0]["Content-Type"], "image/png")
        with db.session() as conn:
            self.assertEqual(conn.orm.get(PhotoSource, source).status, before)
        self.assertEqual(self.immich.calls, [])

    def test_the_placeholder_is_a_deterministic_gradient_of_its_asset(self):
        kind, data = photos.placeholder("asset-one", "thumbnail")
        self.assertEqual((kind, png_size(data), data), ("image/png", (256, 256), photos.placeholder("asset-one", "thumbnail")[1]))
        self.assertNotEqual(data, photos.placeholder("asset-two", "thumbnail")[1])
        self.assertEqual(png_size(photos.placeholder("asset-one", "preview")[1]), (1280, 1280))
        self.assertEqual(immich.sniff(data), "image/png")


class OriginalTests(ProxyCase):
    def test_an_original_streams_with_the_sniffed_type_inline_and_no_store(self):
        headers, raw = self.image("ana", f"/api/photos/{self.mine}/original")
        self.assertEqual(raw, MP4)
        self.assertEqual((headers["Content-Type"], headers["Cache-Control"], headers["Content-Disposition"], headers["X-Content-Type-Options"]),
                         ("video/mp4", "private, no-store", "inline", "nosniff"))
        self.assertEqual((headers["Content-Length"], headers["Accept-Ranges"]), (str(len(MP4)), "bytes"))
        self.assertIn(CSP, headers.get_all("Content-Security-Policy"))
        self.assertIsNone(headers.get("ETag"))
        self.assertEqual(self.upstream(), [(f"{self.asset}/original", "", None)])
        self.assertEqual(self.immich.calls[0]["headers"]["x-api-key"], KEY)

    def test_a_single_range_is_checked_against_a_sniffed_prefix_then_passed_through(self):
        status, headers, raw = self.get("ana", f"/api/photos/{self.mine}/original", {"Range": "bytes=10-19"})
        self.assertEqual((status, raw), (206, MP4[10:20]))
        total = len(MP4)
        self.assertEqual((headers["Content-Range"], headers["Content-Length"], headers["Accept-Ranges"], headers["Content-Type"]),
                         (f"bytes 10-19/{total}", "10", "bytes", "video/mp4"))
        self.assertEqual(self.upstream(), [(f"{self.asset}/original", "", "bytes=0-4095"), (f"{self.asset}/original", "", "bytes=10-19")])
        status, headers, raw = self.get("ana", f"/api/photos/{self.mine}/original", {"Range": "bytes=-5"})
        self.assertEqual((status, raw, headers["Content-Range"]), (206, MP4[-5:], f"bytes {total - 5}-{total - 1}/{total}"))
        self.assertEqual(self.upstream()[2:], [(f"{self.asset}/original", "", "bytes=-5")])
        status, headers, raw = self.get("ana", f"/api/photos/{self.mine}/original", {"Range": "bytes=20000-"})
        self.assertEqual((status, raw, headers["Content-Range"], headers["Content-Type"]), (416, b"", f"bytes */{total}", "video/mp4"))
        for byte_range in ("bytes=0-1,5-6", "items=0-1", "bytes=9-3"):
            with self.subTest(byte_range=byte_range):
                status, headers, raw = self.get("ana", f"/api/photos/{self.mine}/original", {"Range": byte_range})
                self.assertEqual((status, raw, headers.get("Content-Range")), (200, MP4, None))
        self.assertEqual(self.upstream()[-1], (f"{self.asset}/original", "", None))

    def test_a_photo_id_reused_for_another_asset_never_reuses_the_sniffed_type(self):
        status, _, _ = self.get("ana", f"/api/photos/{self.mine}/original", {"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        replacement = self.replace_asset(self.mine)
        self.immich.routes[f"{replacement}/original"] = ranged(SVG, "image/svg+xml")
        self.missing("ana", f"/api/photos/{self.mine}/original", {"Range": "bytes=10-19"})
        self.assertEqual(self.upstream()[2:], [(f"{replacement}/original", "", "bytes=0-4095")])

    def streamed(self, who, path, headers):
        link = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=20)
        self.addCleanup(link.close)
        link.request("GET", path, headers={"X-Waypoint": "1", **self.who[who], **headers})
        reply = link.getresponse()
        got = bytearray()
        while piece := reply.read(1024):
            got += piece
        return reply.status, reply.headers, bytes(got)

    def test_one_budget_covers_the_prefix_probe_and_the_range_it_allows(self):
        body = bytes(MP4) * 4
        self.immich.routes[f"{self.asset}/original"] = ranged(body, "video/mp4", piece=1024, pause=0.2)
        with mock.patch.object(immich, "ORIGINAL_SECONDS", 1.0):
            status, headers, raw = self.streamed("ana", f"/api/photos/{self.mine}/original", {"Range": "bytes=0-8191"})
        self.assertEqual((status, headers["Content-Length"]), (206, "8192"))
        self.assertLess(len(raw), 8192)
        self.assertEqual(raw, body[:len(raw)])
        probe, streamed = self.immich.calls[-2:]
        self.assertEqual((probe["headers"].get("range"), streamed["headers"].get("range")), ("bytes=0-4095", "bytes=0-8191"))
        self.assertAlmostEqual(probe["deadline"], streamed["deadline"], delta=0.05)

    def test_a_range_of_a_type_the_prefix_refuses_streams_nothing(self):
        self.immich.routes[f"{self.asset}/original"] = ranged(SVG, "image/svg+xml")
        self.missing("ana", f"/api/photos/{self.mine}/original", {"Range": "bytes=10-19"})
        self.assertEqual(self.upstream(), [(f"{self.asset}/original", "", "bytes=0-4095")])
        self.immich.routes[f"{self.asset}/original"] = ranged(b"", "video/mp4")
        self.missing("ana", f"/api/photos/{self.mine}/original", {"Range": "bytes=0-1"})

    def test_types_browsers_cannot_show_are_attachments_and_unknown_types_are_404(self):
        cases = [(HEIC, "image/heic", "attachment"), (TIFF, "image/tiff", "attachment"), (GIF, "image/gif", "inline"), (PNG, "image/png", "inline"),
                 (WEBP, "image/webp", "inline"), (b"\x1a\x45\xdf\xa3\x01\x00\x00\x00webm" + bytes(64), "video/webm", "inline"),
                 (b"\x1a\x45\xdf\xa3\x01\x00\x00\x00matroska" + bytes(64), "video/x-matroska", "attachment"),
                 (b"\x00\x00\x00\x14ftypqt  " + bytes(64), "video/quicktime", "inline"), (b"\x00\x00\x00\x14ftypavif" + bytes(64), "image/avif", "inline"),
                 (b"FUJIFILMCCD-RAW " + bytes(64), "application/octet-stream", "attachment")]
        for body, kind, disposition in cases:
            with self.subTest(kind=kind):
                self.immich.routes[f"{self.asset}/original"] = ranged(body, "application/octet-stream")
                headers, raw = self.image("ana", f"/api/photos/{self.mine}/original")
                self.assertEqual((raw, headers["Content-Type"], headers["Content-Disposition"]), (body, kind, disposition))
        for body in (SVG, b"<!doctype html><html>" + BODY_CANARY + b"</html>", b"\x00\x00\x00\x14ftypxxxx" + bytes(64), b"plain text " + bytes(64), b""):
            with self.subTest(body=body[:12]):
                self.immich.routes[f"{self.asset}/original"] = ranged(body, "text/html")
                self.assertNotIn(BODY_CANARY, self.get("ana", f"/api/photos/{self.mine}/original")[2])
                self.missing("ana", f"/api/photos/{self.mine}/original")
        self.assertIsNotNone(stored(self.mine))

    def test_a_refused_or_failing_original_answers_like_a_rendition(self):
        self.immich.routes[f"{self.asset}/original"] = failing(TimeoutError("slow"))
        status, _, raw = self.get("ana", f"/api/photos/{self.mine}/original")
        self.assertEqual((status, json.loads(raw)), (503, {"error": photoproxy.UNAVAILABLE}))
        self.immich.routes[f"{self.asset}/original"] = failing(http_error(401))
        self.missing("ana", f"/api/photos/{self.mine}/original")
        self.assertEqual(self.source_status("ben")[0], "refused")

    def test_a_stream_is_cut_off_once_the_photo_is_taken_back(self):
        body = bytes(MP4) * 4
        self.immich.routes[f"{self.asset}/original"] = ranged(body, "video/mp4", piece=1024, pause=0.02)
        with mock.patch.object(photoproxy, "RECHECK_SECONDS", 0.05):
            link = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=20)
            self.addCleanup(link.close)
            link.request("GET", f"/api/photos/{self.mine}/original", headers={"X-Waypoint": "1", **self.who["ana"]})
            reply = link.getresponse()
            self.assertEqual((reply.status, reply.getheader("Content-Length")), (200, str(len(body))))
            first = reply.read(2048)
            self.assertEqual(first, body[:2048])
            self.revoke("ben")
            got = bytearray(first)
            while piece := reply.read(1024):
                got += piece
        self.assertLess(len(got), len(body))
        self.assertEqual(bytes(got), body[:len(got)])
        self.missing("ana", f"/api/photos/{self.mine}/original")

    def blocked_stream(self, taken_back, release=True, recheck=0.0, idle=30.0):
        body = bytes(MP4) * 4
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.immich.routes[f"{self.asset}/original"] = ranged(body, "video/mp4", piece=1024, gate=gate, gate_after=4, idle=idle)
        with mock.patch.object(photoproxy, "RECHECK_SECONDS", recheck):
            link = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=20)
            self.addCleanup(link.close)
            link.request("GET", f"/api/photos/{self.mine}/original", headers={"X-Waypoint": "1", **self.who["ana"]})
            reply = link.getresponse()
            self.assertEqual(reply.status, 200)
            first = reply.read(4096)
            self.assertEqual(first, body[:4096])
            taken_back()
            if release:
                gate.set()
            began = time.monotonic()
            rest = bytearray()
            while piece := reply.read(1024):
                rest += piece
        self.assertEqual(bytes(rest), b"")
        return time.monotonic() - began

    def test_nothing_more_is_sent_once_the_photo_is_taken_back_while_a_read_is_blocked(self):
        self.blocked_stream(lambda: self.revoke("ben"))

    def test_a_stream_stops_when_another_photo_takes_over_its_id(self):
        self.blocked_stream(lambda: self.replace_asset(self.mine))
        self.assertEqual(self.get("ana", f"/api/photos/{self.mine}/original")[0], 404)

    def test_a_stalled_upstream_is_cut_off_at_the_recheck_once_the_photo_is_taken_back_not_at_the_idle_limit(self):
        took = self.blocked_stream(lambda: self.revoke("ben"), release=False, recheck=0.2, idle=3.0)
        self.assertLess(took, 1.5)

    def test_an_upstream_that_stalls_just_before_the_recheck_is_cut_off_within_one_interval_once_the_photo_is_taken_back(self):
        body = bytes(MP4) * 4
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.immich.routes[f"{self.asset}/original"] = ranged(body, "video/mp4", piece=1024, pause=0.05, gate=gate, gate_after=14, idle=30.0)
        with mock.patch.object(photoproxy, "RECHECK_SECONDS", 1.0):
            began = time.monotonic()
            link = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=20)
            self.addCleanup(link.close)
            link.request("GET", f"/api/photos/{self.mine}/original", headers={"X-Waypoint": "1", **self.who["ana"]})
            reply = link.getresponse()
            self.assertEqual(reply.status, 200)
            self.revoke("ben")
            got = bytearray()
            while piece := reply.read(1024):
                got += piece
            took = time.monotonic() - began
        self.assertLess(len(got), len(body))
        self.assertEqual(bytes(got), body[:len(got)])
        self.assertLess(took, 1.5)

    def test_a_slow_but_live_upstream_streams_to_the_end_across_rechecks(self):
        body = bytes(MP4)
        self.immich.routes[f"{self.asset}/original"] = ranged(body, "video/mp4", piece=2048, pause=0.3)
        with mock.patch.object(photoproxy, "RECHECK_SECONDS", 0.1):
            status, headers, raw = self.streamed("ana", f"/api/photos/{self.mine}/original", {})
        self.assertEqual((status, headers["Content-Length"], raw), (200, str(len(body)), body))


class RouteTests(unittest.TestCase):
    def test_the_image_routes_are_blocked_for_assistants_and_are_not_json(self):
        for pattern in IMAGE_ROUTES:
            self.assertTrue(mcp_access.blocked(pattern), pattern)
            self.assertIsNone(mcp_http.needs("GET", pattern), pattern)
            self.assertIn(f"GET {pattern}", NOT_JSON)

    def test_original_types_come_from_magic_bytes_alone(self):
        self.assertEqual(immich.original_type(MP4), ("video/mp4", True))
        self.assertEqual(immich.original_type(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomavc1"), ("video/mp4", True))
        self.assertEqual(immich.original_type(b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic"), ("image/heic", False))
        self.assertEqual(immich.original_type(b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1avif"), ("image/avif", True))
        self.assertEqual(immich.original_type(b"MM\x00*" + bytes(8)), ("image/tiff", False))
        self.assertEqual(immich.original_type(b"IIU\x00" + bytes(8)), ("application/octet-stream", False))
        for data in (b"", b"\x00\x00\x00", b"\x00\x00\x00\x08ftyp", b"RIFF\x00\x00\x00\x00WAVE", SVG, b"GIF87" , b"\x1a\x45\xdf\xa3"):
            self.assertIsNone(immich.original_type(data), data)
        self.assertEqual(immich.original_type(b"GIF87a" + bytes(8)), ("image/gif", True))


if __name__ == "__main__":
    unittest.main()
