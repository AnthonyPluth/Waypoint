import unittest
from itertools import pairwise

from waypoint import pmtiles
from tests import pmtiles_fixture as fx


class Format(unittest.TestCase):

    def test_a_header_survives_a_round_trip(self):
        raw = fx.tiny()
        header = pmtiles.parse_header(raw)
        self.assertEqual(pmtiles.build_header(header), raw[:pmtiles.HEADER_LENGTH])
        self.assertEqual((header.min_zoom, header.max_zoom, header.tile_type), (0, 2, 1))

    def test_something_that_is_not_a_pmtiles_file_is_refused(self):
        for bad in (b"", b"PMTiles", b"x" * 200, b"PMTiles\x02" + b"\0" * 130):
            with self.assertRaises(pmtiles.FormatError):
                pmtiles.parse_header(bad)

    def test_a_directory_survives_a_round_trip_with_runs_and_shared_tiles(self):
        entries = [pmtiles.Entry(0, 0, 10, 1), pmtiles.Entry(1, 10, 5, 3), pmtiles.Entry(9, 0, 10, 1), pmtiles.Entry(300, 15, 70000, 1)]
        for compression in (pmtiles.GZIP, pmtiles.NO_COMPRESSION):
            self.assertEqual(pmtiles.read_directory(pmtiles.write_directory(entries, compression), compression), entries)

    def test_a_truncated_directory_is_a_format_error(self):
        raw = pmtiles.write_directory([pmtiles.Entry(0, 0, 10, 1)], pmtiles.NO_COMPRESSION)
        with self.assertRaises(pmtiles.FormatError):
            pmtiles.read_directory(raw[:-1] if len(raw) > 3 else b"", pmtiles.NO_COMPRESSION)
        with self.assertRaises(pmtiles.FormatError):
            pmtiles.read_directory(b"x", 9)

    def test_tile_ids_follow_the_hilbert_curve_and_round_trip(self):
        self.assertEqual([pmtiles.tile_id(1, x, y) for x, y in ((0, 0), (0, 1), (1, 1), (1, 0))], [1, 2, 3, 4])
        for z in range(6):
            first = pmtiles.zoom_end(z - 1) if z else 0
            walk = [pmtiles.tile_zxy(t) for t in range(first, pmtiles.zoom_end(z))]
            self.assertEqual({t[0] for t in walk}, {z})
            for (_, ax, ay), (_, bx, by) in pairwise(walk):
                self.assertEqual(abs(ax - bx) + abs(ay - by), 1)
            self.assertEqual([pmtiles.tile_id(*t) for t in walk], list(range(first, pmtiles.zoom_end(z))))

    def test_a_tile_outside_the_world_is_refused(self):
        with self.assertRaises(pmtiles.FormatError):
            pmtiles.tile_id(1, 2, 0)

    def test_zoom_end_counts_the_tiles_up_to_a_zoom(self):
        self.assertEqual([pmtiles.zoom_end(z) for z in range(4)], [1, 5, 21, 85])


if __name__ == "__main__":
    unittest.main()
