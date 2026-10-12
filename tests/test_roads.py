import importlib.util
import io
from itertools import pairwise
import socket
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from waypoint.storage import roads

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("roads_tool", ROOT / "tools" / "roads.py")
assert _spec and _spec.loader
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def row(ref, a, b, *points):
    scaled = [(round(lat * roads.UNITS), round(lon * roads.UNITS)) for lat, lon in points]
    numbers = [*scaled[0]]
    for (lat1, lon1), (lat2, lon2) in pairwise(scaled):
        numbers += [lat2 - lat1, lon2 - lon1]
    return f"{ref}\t{a}\t{b}\t{' '.join(map(str, numbers))}\n"


FIXTURE = "".join([
    row("I-1", 0, 1, (40.0, -105.0), (40.3, -104.0), (40.0, -103.0)),
    row("I-1", 1, 2, (40.0, -103.0), (40.0, -101.0)),
    row("I-2", 1, 3, (40.0, -103.0), (41.5, -103.0)),
    row("I-3", 0, 4, (40.0, -105.0), (38.5, -103.0)),
    row("I-3", 4, 2, (38.5, -103.0), (40.0, -101.0)),
    row("I-4", 4, 1, (38.5, -103.0), (40.0, -103.0)),
    row("I-9", 8, 9, (35.0, -90.0), (35.0, -89.0)),
])


def graph():
    return roads.parse(FIXTURE.splitlines(keepends=True))


class FixtureGraphTests(unittest.TestCase):
    def test_rows_become_edges_with_their_points_and_length(self):
        g = graph()
        self.assertEqual(len(g.edges), 7)
        first = g.edges[0]
        self.assertEqual((first.ref, first.a, first.b), ("I-1", 0, 1))
        self.assertEqual(first.points, ((40.0, -105.0), (40.3, -104.0), (40.0, -103.0)))
        self.assertAlmostEqual(first.miles, 110, delta=10)

    def test_blank_and_broken_rows_are_skipped(self):
        g = roads.parse(["\n", "I-1\t0\t1\t\n", "I-1\t0\t1\t400000 -1050000\n", FIXTURE.splitlines()[0]])
        self.assertEqual(len(g.edges), 1)

    def test_a_point_snaps_to_the_nearest_spot_on_a_road(self):
        got = graph().snap((40.2, -102.0))
        assert got is not None
        self.assertEqual(graph().edges[got.edge].ref, "I-1")
        self.assertAlmostEqual(got.point[0], 40.0, places=3)
        self.assertAlmostEqual(got.point[1], -102.0, places=1)
        self.assertAlmostEqual(got.link_miles, 13.8, delta=1)

    def test_a_point_too_far_from_every_road_does_not_snap(self):
        self.assertIsNone(graph().snap((43.5, -103.0)))
        self.assertIsNotNone(graph().snap((43.5, -103.0), within=150))

    def test_a_road_cut_off_from_the_main_network_is_not_snapped_to(self):
        self.assertIsNone(graph().snap((35.0, -89.5)))

    def test_the_route_follows_the_shorter_way_round_the_graph(self):
        got = graph().route((40.0, -104.9), (40.0, -101.1))
        assert got is not None
        self.assertEqual(got.refs, ["I-1"])
        self.assertAlmostEqual(got.miles, 205, delta=15)
        self.assertAlmostEqual(got.points[0][0], 40.03, delta=0.02)
        self.assertAlmostEqual(got.points[0][1], -104.91, delta=0.02)
        self.assertLess(got.start_link_miles, 3)
        self.assertAlmostEqual(got.points[-1][1], -101.1, places=3)
        longer = graph().route((40.0, -104.99), (38.6, -102.5))
        assert longer is not None
        self.assertEqual(longer.refs, ["I-3"])

    def test_a_route_that_changes_road_names_each_road_in_order(self):
        got = graph().route((40.0, -104.9), (41.4, -103.0))
        assert got is not None
        self.assertEqual(got.refs, ["I-1", "I-2"])

    def test_a_short_stretch_of_a_road_is_not_named(self):
        got = graph().route((40.02, -103.0), (40.0, -104.9))
        assert got is not None
        self.assertEqual(got.refs, ["I-1"])

    def test_two_points_on_the_same_road_piece_follow_just_that_piece(self):
        forward = graph().route((40.0, -102.5), (40.0, -101.5))
        back = graph().route((40.0, -101.5), (40.0, -102.5))
        assert forward is not None and back is not None
        self.assertEqual(forward.refs, ["I-1"])
        self.assertAlmostEqual(forward.miles, 53, delta=3)
        self.assertEqual(forward.points[::-1], back.points)

    def test_a_route_with_an_end_off_the_roads_is_none(self):
        self.assertIsNone(graph().route((40.0, -104.9), (43.5, -103.0)))
        self.assertIsNone(graph().route((35.0, -89.5), (40.0, -104.9)))

    def test_the_road_network_near_a_route_is_cut_to_a_budget(self):
        g = graph()
        route = g.route((40.0, -104.9), (40.0, -101.1))
        assert route is not None
        near = g.near([route.points], rings=1)
        self.assertIn("I-1", [ref for ref, _ in near])
        self.assertNotIn("I-9", [ref for ref, _ in near])
        tight = g.near([route.points], rings=1, budget=2)
        self.assertTrue(tight)
        self.assertTrue(all(len(p) <= 2 for _, p in tight))
        self.assertLessEqual(sum(len(p) for _, p in g.near([route.points], rings=1, budget=3)), 3)
        self.assertEqual(g.near([[(40.0, -102.0)]], rings=0)[0][0], "I-1")

    def test_simplifying_keeps_the_ends_and_the_bends(self):
        line = [(40.0, -105.0), (40.0001, -104.5), (40.0, -104.0), (40.5, -103.5)]
        self.assertEqual(roads.simplified(line, 0.01), [(40.0, -105.0), (40.0, -104.0), (40.5, -103.5)])
        self.assertEqual(roads.simplified([(1.0, 2.0), (1.0, 2.0)], 0.1), [(1.0, 2.0), (1.0, 2.0)])


class BundledRoadsTests(unittest.TestCase):
    def test_the_bundled_interstates_load_once(self):
        g = roads.interstates()
        self.assertIs(g, roads.interstates())
        self.assertGreater(len(g.edges), 5000)
        self.assertTrue({"I-5", "I-10", "I-80", "I-95"} <= {e.ref for e in g.edges})
        self.assertGreater(sum(e.miles for e in g.edges), 40000)

    def test_a_cross_country_route_follows_interstates_in_order(self):
        got = roads.interstates().route((39.74, -104.99), (40.76, -111.89))
        assert got is not None
        self.assertEqual(got.refs, ["I-25", "I-80"])
        self.assertAlmostEqual(got.miles, 520, delta=60)
        coast = roads.interstates().route((47.61, -122.33), (34.05, -118.24))
        assert coast is not None
        self.assertEqual(coast.refs, ["I-5"])
        self.assertAlmostEqual(coast.miles, 1135, delta=60)

    def test_outside_the_united_states_there_is_no_route(self):
        self.assertIsNone(roads.interstates().route((51.5, -0.12), (48.85, 2.35)))
        self.assertIsNone(roads.interstates().route((43.65, -79.38), (45.5, -73.57)))

    def test_the_lookup_opens_no_connection(self):
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("network")):
            roads.interstates.cache_clear()
            got = roads.interstates().route((39.74, -104.99), (41.88, -87.63))
            assert got is not None
            self.assertTrue(roads.interstates().near([got.points]))
        roads.interstates.cache_clear()


def dbf(rows):
    fields = [("SIGN1", 6), ("SIGNT1", 6), ("FCLASS", 12)]
    head = b"".join(name.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([size]) + b"\0" * 15 for name, size in fields)
    length = 1 + sum(size for _, size in fields)
    out = struct.pack("<BBBBIHH", 3, 0, 0, 0, len(rows), 32 + len(head) + 1, length) + b"\0" * 20 + head + b"\r"
    for r in rows:
        out += b" " + b"".join(value.encode().ljust(size) for value, (_, size) in zip(r, fields, strict=True))
    return out


def shp(lines):
    out = b""
    for n, pts in enumerate(lines, 1):
        flat = [c for lat, lon in pts for c in (lon, lat)]
        body = struct.pack("<i4d2i", 3, 0, 0, 0, 0, 1, len(pts)) + struct.pack("<i", 0) + struct.pack(f"<{len(flat)}d", *flat)
        out += struct.pack(">ii", n, len(body) // 2) + body
    return b"\0" * 100 + out


class BuildToolTests(unittest.TestCase):
    def test_signs_become_route_refs(self):
        refs = {s: tool.ref_of(s) for s in ("I80", "I35W", "IH1", "i5", "I20B", "US40", "", "I")}
        self.assertEqual(refs, {"I80": "I-80", "I35W": "I-35W", "IH1": "I-H1", "i5": "I-5", "I20B": None, "US40": None, "": None, "I": None})

    def test_only_signed_interstates_are_read_from_the_shapefile(self):
        rows = [("I80", "I", "1"), ("I80", "I", "3"), ("US40", "U", "1"), ("I25", "I", "1")]
        lines = [[(41.0, -100.0), (41.0, -99.0)], [(1.0, 1.0), (2.0, 2.0)], [(3.0, 3.0), (4.0, 4.0)], [(40.0, -105.0), (40.5, -105.0), (41.0, -105.0)]]
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "nhs.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("NHS/nhs.dbf", dbf(rows))
                z.writestr("NHS/nhs.shp", shp(lines))
            found = tool.interstates(archive)
        self.assertEqual([ref for ref, _ in found], ["I-80", "I-25"])
        self.assertEqual(found[1][1], [(40.0, -105.0), (40.5, -105.0), (41.0, -105.0)])

    def test_pieces_meeting_at_a_point_share_a_node_and_a_crossing_road_is_cut(self):
        lines = [("I-1", [(40.0, -105.0), (40.0, -104.0)]), ("I-1", [(40.0, -104.0), (40.0, -103.0)]),
                 ("I-2", [(39.0, -104.0), (39.5, -104.0), (40.001, -104.0)])]
        edges = tool.node_lines(lines)
        nodes = {n for _, a, b, _ in edges for n in (a, b)}
        self.assertEqual(len(nodes), 4)
        self.assertEqual(len(edges), 3)
        by = {(ref, len(p)) for ref, _, _, p in edges}
        self.assertIn(("I-2", 3), by)

    def test_a_piece_that_ends_beside_the_middle_of_another_road_splits_it(self):
        lines = [("I-1", [(40.0, -105.0), (40.0, -104.0), (40.0, -103.0)]), ("I-2", [(39.0, -104.0), (40.001, -104.0)])]
        edges = tool.node_lines(lines)
        self.assertEqual(sorted((ref, len(p)) for ref, _, _, p in edges), [("I-1", 2), ("I-1", 2), ("I-2", 2)])
        joined = {n for ref, a, b, _ in edges if ref == "I-1" for n in (a, b)}
        far = {n for ref, a, b, _ in edges if ref == "I-2" for n in (a, b)}
        self.assertEqual(len(joined & far), 1)

    def test_a_road_cut_in_two_pieces_with_nothing_else_there_is_joined_again(self):
        edges = [("I-1", 0, 1, [(40.0, -105.0), (40.0, -104.0)]), ("I-1", 1, 2, [(40.0, -104.0), (40.0, -103.0)]),
                 ("I-2", 1, 3, [(40.0, -104.0), (41.0, -104.0)])]
        self.assertEqual(len(tool.chain_edges(edges)), 3)
        plain = tool.chain_edges(edges[:2])
        self.assertEqual(len(plain), 1)
        self.assertEqual(plain[0][3], [(40.0, -105.0), (40.0, -104.0), (40.0, -103.0)])
        flipped = tool.chain_edges([edges[0], ("I-1", 2, 1, [(40.0, -103.0), (40.0, -104.0)])])
        self.assertEqual(flipped[0][3], [(40.0, -105.0), (40.0, -104.0), (40.0, -103.0)])

    def test_the_written_rows_read_back_into_the_same_graph(self):
        edges = tool.thin([("I-1", 0, 1, [(40.0, -105.0), (40.00001, -104.5), (40.0, -104.0)]), ("I-2", 1, 2, [(40.0, -104.0), (41.0, -104.0)])])
        self.assertEqual(len(edges[0][3]), 2)
        g = roads.parse(io.StringIO(tool.encode(edges)))
        self.assertEqual([(e.ref, e.a, e.b) for e in g.edges], [("I-1", 0, 1), ("I-2", 1, 2)])
        self.assertEqual(g.edges[1].points, ((40.0, -104.0), (41.0, -104.0)))
