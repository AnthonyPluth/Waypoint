import gzip
import importlib.util
import io
import socket
import struct
import tempfile
import unittest
import zipfile
from itertools import pairwise
from pathlib import Path
from unittest import mock

from waypoint.storage import states

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("states_tool", ROOT / "tools" / "states.py")
assert _spec and _spec.loader
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def box(south, west, north, east):
    return [(south, west), (north, west), (north, east), (south, east), (south, west)]


RINGS = {
    "AA": [box(40.0, -105.0, 41.0, -104.0)],
    "BB": [box(40.0, -104.0, 41.0, -103.0)],
    "CC": [box(41.0, -105.0, 42.0, -104.0)],
}


def row(a, b, *points):
    scaled = [(round(lat * states.UNITS), round(lon * states.UNITS)) for lat, lon in points]
    numbers = [*scaled[0]]
    for (lat1, lon1), (lat2, lon2) in pairwise(scaled):
        numbers += [lat2 - lat1, lon2 - lon1]
    return f"{a}\t{b}\t{' '.join(map(str, numbers))}\n"


FIXTURE = "".join([
    row("AA", "BB", (40.0, -104.0), (40.5, -104.0), (41.0, -104.0)),
    row("AA", "CC", (41.0, -105.0), (41.0, -104.0)),
    row("XX", "YY", (30.0, -90.0), (30.0, -89.0)),
])
LONG = row("AA", "BB", *[(30.0 + n * 0.5, -100.0) for n in range(40)])


def graph(text=FIXTURE):
    return states.parse(text.splitlines(keepends=True))


class FixtureLoaderTests(unittest.TestCase):
    def test_rows_become_borders_with_their_points(self):
        g = graph()
        self.assertEqual(len(g.borders), 3)
        self.assertEqual((g.borders[0].a, g.borders[0].b), ("AA", "BB"))
        self.assertEqual(g.borders[0].points, ((40.0, -104.0), (40.5, -104.0), (41.0, -104.0)))

    def test_blank_and_broken_rows_are_skipped(self):
        g = states.parse(["\n", "AA\tBB\t\n", "AA\tBB\t400000 -1050000\n", "AA\tBB\n", FIXTURE.splitlines()[0]])
        self.assertEqual(len(g.borders), 1)

    def test_only_the_lines_inside_the_extent_come_back(self):
        inside = graph().within((40.4, -104.5, 40.6, -103.5))
        self.assertEqual(inside, [[(40.0, -104.0), (40.5, -104.0), (41.0, -104.0)]])
        self.assertEqual(graph().within((29.0, -91.0, 31.0, -88.0)), [[(30.0, -90.0), (30.0, -89.0)]])
        self.assertEqual(graph().within((49.0, 9.0, 51.0, 11.0)), [])

    def test_an_extent_collects_every_line_across_it(self):
        got = graph().within((29.0, -105.0, 42.0, -88.0))
        self.assertEqual(len(got), 3)
        self.assertIn([(30.0, -90.0), (30.0, -89.0)], got)
        self.assertIn([(40.0, -104.0), (40.5, -104.0), (41.0, -104.0)], got)

    def test_a_line_is_cut_to_the_part_inside_the_extent(self):
        got = graph(LONG).within((35.0, -101.0, 36.0, -99.0))
        self.assertEqual(len(got), 1)
        self.assertLess(len(got[0]), 10)
        self.assertTrue(all(34 <= lat <= 37 for lat, _ in got[0]))

    def test_a_line_running_through_the_extent_is_kept_from_edge_to_edge(self):
        got = graph(LONG).within((29.0, -101.0, 51.0, -99.0))
        self.assertEqual(got, [[(30.0 + n * 0.5, -100.0) for n in range(40)]])

    def test_over_the_budget_every_piece_stays_and_the_points_are_thinned(self):
        zigzag = row("AA", "BB", *[(30.0 + n * 0.01, -100.0 + (0.0003 if n % 2 else 0.0)) for n in range(300)])
        text = LONG + zigzag + row("CC", "DD", (35.0, -95.0), (35.5, -95.2), (36.0, -95.0))
        full = graph(text).within((29.0, -102.0, 51.0, -94.0), budget=10_000)
        got = graph(text).within((29.0, -102.0, 51.0, -94.0), budget=50)
        self.assertEqual(len(got), len(full))
        self.assertLessEqual(states.steps(got), 50)
        self.assertGreater(states.steps(full), 300)
        for before, after in zip(full, got, strict=True):
            self.assertEqual((before[0], before[-1]), (after[0], after[-1]))

    def test_a_budget_smaller_than_the_pieces_leaves_each_as_a_straight_line(self):
        got = graph(LONG + FIXTURE).within((29.0, -106.0, 51.0, -88.0), budget=1)
        self.assertTrue(all(len(line) == 2 for line in got))
        self.assertEqual(len(got), 4)

    def test_thinning_keeps_a_corner_and_drops_a_wobble(self):
        bent = [(0.0, 0.0), (0.0001, 0.5), (0.0, 1.0), (1.0, 1.0)]
        self.assertEqual(states.simplify(bent, 0.01), [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)])
        self.assertEqual(states.simplify([(0.0, 0.0), (1.0, 1.0)], 0.5), [(0.0, 0.0), (1.0, 1.0)])

    def test_the_bundled_file_is_small_and_has_the_real_lines(self):
        self.assertLess((ROOT / "waypoint" / "storage" / states.FILE).stat().st_size, 100_000)
        g = states.load()
        pairs = {(b.a, b.b) for b in g.borders}
        every = {s for pair in pairs for s in pair}
        self.assertEqual({"CO", "UT", "WY", "NM", "NE", "KS", "OK", "AZ"} - every, set())
        self.assertIn(("CO", "UT"), pairs)
        self.assertNotIn("PR", every)
        for border in (b for b in g.borders if (b.a, b.b) == ("CO", "UT")):
            self.assertTrue(all(abs(lon + 109.05) < 0.1 for _, lon in border.points))
        total = sum(len(b.points) for b in g.borders)
        self.assertTrue(1000 < total < 6000)

    def test_around_denver_the_real_lines_are_found_and_around_london_none(self):
        found = states.state_lines().within((36.0, -110.0, 43.0, -100.0))
        self.assertTrue(found)
        self.assertTrue(all(25 < lat < 50 and -125 < lon < -85 for line in found for lat, lon in line))
        self.assertEqual(states.state_lines().within((50.0, -5.0, 53.0, 3.0)), [])

    def test_the_whole_country_fits_the_budget_without_losing_a_border(self):
        g = states.state_lines()
        whole = g.within((24.0, -125.0, 50.0, -66.0), budget=10_000)
        capped = g.within((24.0, -125.0, 50.0, -66.0))
        self.assertEqual(len(capped), len(whole))
        self.assertLessEqual(states.steps(capped), states.BUDGET)

    def test_the_lookup_opens_no_connection(self):
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("network")):
            states.state_lines.cache_clear()
            self.assertTrue(states.state_lines().within((40.0, -90.0, 43.0, -85.0)))
        states.state_lines.cache_clear()


def dbf(codes):
    fields = [("STATEFP", 2), ("STUSPS", 2), ("NAME", 20)]
    head = b"".join(name.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([size]) + b"\0" * 15 for name, size in fields)
    length = 1 + sum(size for _, size in fields)
    out = struct.pack("<BBBBIHH", 3, 0, 0, 0, len(codes), 32 + len(head) + 1, length) + b"\0" * 20 + head + b"\r"
    for code in codes:
        out += b" " + b"00" + code.encode().ljust(2) + b"Name".ljust(20)
    return out


def shp(shapes, kind=5):
    out = b""
    for n, rings in enumerate(shapes, 1):
        flat = [c for ring in rings for lat, lon in ring for c in (lon, lat)]
        total = sum(len(r) for r in rings)
        starts = [sum(len(r) for r in rings[:k]) for k in range(len(rings))]
        body = struct.pack("<i4d2i", kind, 0, 0, 0, 0, len(rings), total) + struct.pack(f"<{len(rings)}i", *starts) + struct.pack(f"<{len(flat)}d", *flat)
        out += struct.pack(">ii", n, len(body) // 2) + body
    return b"\0" * 100 + out


def archive_in(tmp):
    archive = Path(tmp) / "states.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("cb/cb.dbf", dbf(["AA", "BB", "CC"]))
        z.writestr("cb/cb.shp", shp([RINGS["AA"], RINGS["BB"], RINGS["CC"]]))
    return archive


class BuildToolTests(unittest.TestCase):
    def test_only_edges_two_states_share_become_lines(self):
        shared = tool.shared_edges(RINGS)
        self.assertEqual(len(shared), 2)
        self.assertEqual({frozenset(who) for who in shared.values()}, {frozenset({"AA", "BB"}), frozenset({"AA", "CC"})})

    def test_a_shared_border_is_one_line_from_end_to_end_and_corners_stay_apart(self):
        by = {(a, b): points for a, b, points in tool.build(RINGS)}
        self.assertEqual(sorted(by), [("AA", "BB"), ("AA", "CC")])
        self.assertEqual(sorted(by[("AA", "BB")]), [(40.0, -104.0), (41.0, -104.0)])
        self.assertEqual(sorted(by[("AA", "CC")]), [(41.0, -105.0), (41.0, -104.0)])

    def test_a_border_with_many_points_is_chained_and_simplified(self):
        wavy = [(n / 10, 1.0 + (0.0001 if n % 2 else 0.0)) for n in range(11)]
        west = [[(0.0, 0.0), (1.0, 0.0), *reversed(wavy), (0.0, 0.0)]]
        east = [[*wavy, (1.0, 2.0), (0.0, 2.0), wavy[0]]]
        borders = tool.build({"AA": west, "BB": east})
        self.assertEqual(len(borders), 1)
        self.assertEqual(borders[0][2], [(0.0, 1.0), (1.0, 1.0)])
        self.assertEqual(len(tool.build({"AA": west, "BB": east}, tolerance=0.00001)[0][2]), 11)

    def test_the_shapefile_is_read_with_each_state_s_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = tool.states(archive_in(tmp))
        self.assertEqual(sorted(found), ["AA", "BB", "CC"])
        self.assertEqual(found["BB"], RINGS["BB"])

    def test_a_shape_that_is_not_a_polygon_is_ignored(self):
        self.assertEqual(tool.shape_rings(struct.pack("<i", 3) + b"\0" * 40), [])

    def test_a_table_without_state_codes_is_refused(self):
        table = dbf(["AA"]).replace(b"STUSPS", b"OTHER\0")
        with self.assertRaises(ValueError):
            tool.dbf_codes(io.BytesIO(table))

    def test_the_written_rows_read_back_into_the_same_lines_whatever_their_order(self):
        borders = tool.build(RINGS)
        text = tool.encode(borders)
        self.assertEqual(text, tool.encode(list(reversed(borders))))
        g = states.parse(io.StringIO(text))
        self.assertEqual([(b.a, b.b) for b in g.borders], [("AA", "BB"), ("AA", "CC")])
        self.assertEqual(sorted(g.borders[0].points), [(40.0, -104.0), (41.0, -104.0)])

    def test_the_tool_writes_the_same_bytes_for_the_same_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = archive_in(tmp)
            outputs = []
            for name in ("one.gz", "two.gz"):
                with mock.patch.object(tool, "OUT", Path(tmp) / name), mock.patch("builtins.print"):
                    self.assertEqual(tool.main(["states.py", str(archive)]), 0)
                outputs.append((Path(tmp) / name).read_bytes())
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(len(gzip.decompress(outputs[0]).decode().splitlines()), 2)

    def test_the_tool_needs_the_path_of_the_download(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(tool.main(["states.py"]), 2)


if __name__ == "__main__":
    unittest.main()
