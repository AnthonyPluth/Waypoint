import tempfile
import unittest
from pathlib import Path
from unittest import mock

from waypoint import pmtiles
from waypoint.providers import protomaps
from tests import pmtiles_fixture as fx


def tiles_of(path: Path) -> tuple[pmtiles.Header, dict[int, bytes]]:
    raw = path.read_bytes()
    h = pmtiles.parse_header(raw)
    found: dict[int, bytes] = {}
    entries = pmtiles.read_directory(raw[h.root_offset:h.root_offset + h.root_length], h.internal_compression)
    flat: list[pmtiles.Entry] = []
    for e in entries:
        if e.run_length:
            flat.append(e)
        else:
            flat += pmtiles.read_directory(raw[h.leaf_offset + e.offset:h.leaf_offset + e.offset + e.length], h.internal_compression)
    for e in flat:
        for tid in range(e.tile_id, e.tile_id + e.run_length):
            found[tid] = raw[h.data_offset + e.offset:h.data_offset + e.offset + e.length]
    return h, found


class Local(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in self.dir.iterdir()] and self.dir.rmdir())
        sleep = mock.patch.object(protomaps.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def source(self, body=None, listing=None, **flags):
        base = fx.serve(self, body if body is not None else fx.build(6), listing, **flags)
        hosts = mock.patch.object(protomaps, "HOSTS", protomaps.Hosts(builds=base + "builds.json", files=base, allow_http=True))
        hosts.start()
        self.addCleanup(hosts.stop)
        return base


class Extract(Local):

    def test_only_the_wanted_zooms_come_across_with_their_exact_bytes(self):
        base = self.source()
        dest = self.dir / "map.pmtiles"
        seen: list[tuple[int, int]] = []
        protomaps.extract(base + "x.pmtiles", dest, lambda done, total: seen.append((done, total)), max_zoom=3)
        header, found = tiles_of(dest)
        self.assertEqual(sorted(found), list(range(pmtiles.zoom_end(3))))
        for tid, body in found.items():
            self.assertEqual(body, fx.tile_bytes(0 if tid % 11 == 0 and tid >= 11 else tid), tid)
        self.assertEqual((header.min_zoom, header.max_zoom, header.clustered), (0, 3, 1))
        self.assertEqual(header.addressed_tiles, pmtiles.zoom_end(3))
        self.assertEqual(dest.stat().st_size, seen[-1][1])
        self.assertEqual(seen[-1][0], seen[-1][1])
        self.assertFalse((self.dir / "map.pmtiles.part").exists())

    def test_the_download_never_asks_for_the_rest_of_the_file(self):
        base = self.source()
        protomaps.extract(base + "x.pmtiles", self.dir / "map.pmtiles", max_zoom=2)
        self.assertLess(self.handler.sent, len(self.handler.body) // 2)

    def test_a_connection_that_drops_part_way_carries_on_from_where_it_stopped(self):
        base = self.source(fail_after=500)
        dest = self.dir / "map.pmtiles"
        protomaps.extract(base + "x.pmtiles", dest, max_zoom=4)
        _, found = tiles_of(dest)
        self.assertEqual(sorted(found), list(range(pmtiles.zoom_end(4))))

    def test_an_interrupted_download_resumes_instead_of_starting_over(self):
        base = self.source()
        wanted = protomaps.plan(base + "x.pmtiles", 4)
        part = self.dir / "map.pmtiles.part"
        whole = fx.build(6)
        first = wanted.runs[0]
        part.write_bytes(wanted.prefix + whole[first[0]:first[0] + 700])
        self.handler.hits.clear()
        self.handler.sent = 0
        dest = self.dir / "map.pmtiles"
        protomaps.extract(base + "x.pmtiles", dest, max_zoom=4)
        self.assertEqual(dest.stat().st_size, wanted.total)
        self.assertLessEqual(self.handler.sent, wanted.data_length - 700 + len(whole[:16384]))
        _, found = tiles_of(dest)
        self.assertEqual(sorted(found), list(range(pmtiles.zoom_end(4))))

    def test_a_leftover_part_of_a_different_file_is_started_over(self):
        base = self.source()
        (self.dir / "map.pmtiles.part").write_bytes(b"not the same file" * 100)
        protomaps.extract(base + "x.pmtiles", self.dir / "map.pmtiles", max_zoom=2)
        _, found = tiles_of(self.dir / "map.pmtiles")
        self.assertEqual(sorted(found), list(range(pmtiles.zoom_end(2))))

    def test_a_server_that_ignores_byte_ranges_is_refused(self):
        base = self.source(ignore_ranges=True)
        with self.assertRaises(protomaps.Unavailable):
            protomaps.extract(base + "x.pmtiles", self.dir / "map.pmtiles", max_zoom=2)
        self.assertFalse((self.dir / "map.pmtiles").exists())

    def test_something_that_is_not_a_map_is_refused(self):
        base = self.source(body=b"<html>nope</html>" * 20)
        with self.assertRaises(protomaps.Unavailable):
            protomaps.extract(base + "x.pmtiles", self.dir / "map.pmtiles", max_zoom=2)

    def test_an_address_nobody_answers_is_unavailable(self):
        with mock.patch.object(protomaps, "HOSTS", protomaps.Hosts(files="http://127.0.0.1:9/", allow_http=True)):
            with self.assertRaises(protomaps.Unavailable):
                protomaps.extract("http://127.0.0.1:9/x.pmtiles", self.dir / "map.pmtiles", max_zoom=2)

    def test_a_deduplicated_tile_is_stored_once(self):
        base = self.source()
        dest = self.dir / "map.pmtiles"
        protomaps.extract(base + "x.pmtiles", dest, max_zoom=3)
        header, _ = tiles_of(dest)
        self.assertLess(header.tile_contents, header.tile_entries)


class Builds(Local):

    def test_the_newest_listed_build_is_used_and_odd_entries_are_skipped(self):
        self.source(listing=[{"key": "20260101.pmtiles"}, {"key": "20261012.pmtiles"}, {"key": "../evil.pmtiles"}, {"key": 5}, "x", {"key": "20261013.txt"}])
        self.assertEqual(protomaps.latest_build(), "20261012.pmtiles")

    def test_an_empty_or_broken_list_is_unavailable(self):
        self.source(listing=[])
        with self.assertRaises(protomaps.Unavailable):
            protomaps.latest_build()
        self.source(listing=[{"key": "nope"}])
        with self.assertRaises(protomaps.Unavailable):
            protomaps.latest_build()

    def test_only_a_dated_build_name_makes_an_address(self):
        base = self.source()
        self.assertEqual(protomaps.build_url("20261012.pmtiles"), base + "20261012.pmtiles")
        for bad in ("../x.pmtiles", "20261012", "20261012.pmtiles/../x", "https://evil.example/20261012.pmtiles"):
            with self.assertRaises(protomaps.Unavailable):
                protomaps.build_url(bad)


if __name__ == "__main__":
    unittest.main()
