import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from waypoint import oidc
from waypoint.domain import basemap
from waypoint.providers import protomaps
from waypoint.server.api import map as api_map
from waypoint.storage import mapfile
from tests import pmtiles_fixture as fx
from tests.shared import ServerCase, fetch

BODY = fx.build(3)


class WithFile(ServerCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.dir.cleanup)
        cls.file = Path(cls.dir.name) / "world.pmtiles"
        cls.file.write_bytes(BODY)
        env = mock.patch.dict(os.environ, {"WAYPOINT_MAP_FILE": str(cls.file)})
        env.start()
        cls.addClassCleanup(env.stop)

    def get(self, path="/api/map/tiles", **headers):
        return fetch(self.base, "GET", path, headers=headers)


class Tiles(WithFile):

    def test_a_byte_range_answers_206_with_exactly_those_bytes(self):
        status, headers, body = self.get(Range="bytes=100-199")
        self.assertEqual(status, 206)
        self.assertEqual(body, BODY[100:200])
        self.assertEqual(headers["Content-Range"], f"bytes 100-199/{len(BODY)}")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(headers["Content-Length"], "100")

    def test_an_open_ended_and_a_suffix_range_work_and_the_end_is_clamped(self):
        self.assertEqual(self.get(Range="bytes=50-")[2], BODY[50:])
        self.assertEqual(self.get(Range="bytes=-30")[2], BODY[-30:])
        status, headers, body = self.get(Range=f"bytes=10-{len(BODY) + 500}")
        self.assertEqual((status, body), (206, BODY[10:]))
        self.assertEqual(headers["Content-Range"], f"bytes 10-{len(BODY) - 1}/{len(BODY)}")

    def test_the_header_is_read_the_way_a_pmtiles_client_does(self):
        status, _, body = self.get(Range="bytes=0-16383")
        self.assertEqual(status, 206)
        self.assertTrue(body.startswith(b"PMTiles"))

    def test_a_range_that_cant_be_served_answers_416(self):
        for bad in (f"bytes={len(BODY)}-", "bytes=9-3", "bytes=-", "bytes=0-1,5-6", "items=0-5", "bytes=a-b"):
            self.assertEqual(self.get(Range=bad)[0], 416, bad)

    def test_a_range_past_the_size_limit_is_refused_not_cut_short(self):
        with mock.patch.object(api_map, "MAX_SPAN", 50):
            self.assertEqual(self.get(Range="bytes=0-99")[0], 416)
            self.assertEqual(self.get(Range="bytes=0-49")[0], 206)

    def test_without_a_range_the_whole_file_comes_back(self):
        status, headers, body = self.get()
        self.assertEqual((status, body), (200, BODY))
        self.assertEqual(headers["Accept-Ranges"], "bytes")

    def test_it_serves_only_the_one_configured_file(self):
        (self.file.parent / "other.pmtiles").write_bytes(b"PMTiles-other")
        for path in ("/api/map/tiles?file=/etc/passwd", "/api/map/tiles?path=other.pmtiles", "/api/map/tiles/../../etc/passwd", "/api/map/tiles/other.pmtiles"):
            status, _, body = self.get(path, Range="bytes=0-20")
            self.assertTrue(status == 404 or body == BODY[:21], path)
            self.assertNotIn(b"other", body)
            self.assertNotIn(b"root:", body)

    def test_it_is_cached_privately_not_publicly(self):
        self.assertIn("private", self.get(Range="bytes=0-9")[1]["Cache-Control"])


class Labels(WithFile):

    def test_the_bundled_glyphs_and_sprites_are_served_even_with_spaces_in_the_name(self):
        for name in ("Noto%20Sans%20Regular", "Noto%20Sans%20Medium", "Noto%20Sans%20Italic"):
            for rng in ("0-255", "256-511", "8192-8447"):
                status, headers, body = self.get(f"/map/fonts/{name}/{rng}.pbf")
                self.assertEqual(status, 200, (name, rng))
                self.assertEqual(headers["Content-Type"], "application/x-protobuf")
                self.assertIn("max-age=604800", headers["Cache-Control"])
                self.assertGreater(len(body), 100)
        for name in ("dark.json", "dark.png", "dark@2x.json", "dark@2x.png"):
            self.assertEqual(self.get(f"/map/sprites/{name}")[0], 200, name)

    def test_an_encoded_path_cant_climb_out_of_the_static_folders(self):
        for path in ("/%2e%2e/%2e%2e/etc/passwd", "/map/fonts/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd", "/map/%00/x", "/%2e%2e%2fwaypoint%2fstorage%2fdb.py"):
            body = self.get(path)[2]
            self.assertNotIn(b"root:", body, path)
            self.assertNotIn(b"def data_dir", body, path)


class Status(WithFile):

    def test_a_usable_file_is_ready(self):
        status, body = self.req("GET", "/api/map")
        self.assertEqual((status, body["state"]), (200, "ready"))
        self.assertEqual(body["bytes"], len(BODY))

    def test_a_file_that_is_not_a_map_is_not_ready(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_MAP_FILE": str(self.file) + ".missing"}):
            self.assertEqual(self.req("GET", "/api/map")[1]["state"], "missing")
            self.assertEqual(self.get(Range="bytes=0-9")[0], 404)
        junk = self.file.with_name("junk.pmtiles")
        junk.write_bytes(b"not a map" * 100)
        with mock.patch.dict(os.environ, {"WAYPOINT_MAP_FILE": str(junk)}):
            self.assertEqual(self.req("GET", "/api/map")[1]["state"], "missing")
            self.assertEqual(self.get(Range="bytes=0-9")[0], 404)


class OnTheTripMap(WithFile):

    def test_a_trips_places_say_whether_the_detailed_map_is_there(self):
        status, trip = self.req("POST", "/api/trips", {"name": "Map trip"})
        self.assertEqual(status, 200)
        found = self.req("GET", f"/api/trips/{trip['id']}/places")[1]
        self.assertIs(found["basemap"], True)
        with mock.patch.dict(os.environ, {"WAYPOINT_MAP_FILE": str(self.file) + ".missing"}):
            self.assertIs(self.req("GET", f"/api/trips/{trip['id']}/places")[1]["basemap"], False)


class Downloaded(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        env = mock.patch.dict(os.environ, {"WAYPOINT_DATA": self.dir.name})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("WAYPOINT_MAP_FILE", None)
        os.environ.pop("WAYPOINT_MAP_DOWNLOAD", None)
        sleep = mock.patch.object(protomaps.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        basemap._failure = None
        self.addCleanup(setattr, basemap, "_failure", None)
        self.base = fx.serve(self, BODY, [{"key": "20260101.pmtiles"}, {"key": "20260202.pmtiles"}])
        hosts = mock.patch.object(protomaps, "HOSTS", protomaps.Hosts(builds=self.base + "builds.json", files=self.base, allow_http=True))
        hosts.start()
        self.addCleanup(hosts.stop)

    def test_the_first_start_downloads_the_map_into_the_data_folder(self):
        self.assertEqual(basemap.status()["state"], "waiting")
        self.assertTrue(basemap.ensure())
        found = basemap.status()
        self.assertEqual(found["state"], "ready")
        self.assertEqual(mapfile.path(), Path(self.dir.name) / "map.pmtiles")
        self.assertTrue(mapfile.usable())
        self.assertFalse(list(Path(self.dir.name).glob("map.pmtiles.*")))
        self.assertIn("/20260202.pmtiles", "".join(self.handler.hits))

    def test_a_map_that_is_already_there_is_not_downloaded_again(self):
        basemap.ensure()
        self.handler.hits.clear()
        self.assertFalse(basemap.ensure())
        self.assertEqual(self.handler.hits, [])

    def test_downloads_can_be_turned_off_and_then_nothing_is_contacted(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_MAP_DOWNLOAD": "off"}):
            self.assertEqual(basemap.status()["state"], "off")
            self.assertFalse(basemap.ensure())
        self.assertEqual(self.handler.hits, [])

    def test_a_file_of_your_own_is_never_downloaded_over(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_MAP_FILE": os.path.join(self.dir.name, "mine.pmtiles")}):
            self.assertEqual(basemap.status()["state"], "missing")
            self.assertFalse(basemap.ensure())
        self.assertEqual(self.handler.hits, [])

    def test_a_failed_download_says_so_and_the_next_try_starts_cleanly(self):
        with mock.patch.object(protomaps, "HOSTS", protomaps.Hosts(builds="http://127.0.0.1:9/b.json", files="http://127.0.0.1:9/", allow_http=True)):
            self.assertFalse(basemap.ensure())
        failed = basemap.status()
        self.assertEqual(failed["state"], "failed")
        self.assertIn("Protomaps", failed["error"] or "")
        self.assertNotIn("127.0.0.1", failed["error"] or "")
        self.assertTrue(basemap.ensure())
        self.assertEqual(basemap.status()["state"], "ready")

    def test_a_disk_that_cant_be_written_is_a_plain_failure(self):
        with mock.patch.object(protomaps, "extract", side_effect=OSError(28, "No space left on device")):
            self.assertFalse(basemap.ensure())
        found = basemap.status()
        self.assertEqual(found["state"], "failed")
        self.assertIn("disk", found["error"] or "")

    def test_the_status_counts_up_while_it_downloads(self):
        seen = []

        def slow(url, dest, progress=None):
            progress(10, 100)
            seen.append(basemap.status())

        with mock.patch.object(protomaps, "extract", side_effect=slow):
            basemap.ensure()
        self.assertEqual((seen[0]["state"], seen[0]["bytes"], seen[0]["total"]), ("downloading", 10, 100))


class SignedOut(WithFile):

    def test_the_map_needs_a_session(self):
        with mock.patch.object(oidc, "enabled", return_value=True):
            for path in ("/api/map", "/api/map/tiles"):
                status, _, body = self.get(path, Range="bytes=0-9")
                self.assertEqual(status, 401, path)
                self.assertNotIn(b"PMTiles", body)


if __name__ == "__main__":
    unittest.main()
