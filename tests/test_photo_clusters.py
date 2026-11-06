import unittest
from unittest import mock

from waypoint.domain import photos
from waypoint.domain.photomatch import CLUSTER
from waypoint.domain.stats import distance_km

KM_PER_DEGREE = 111.195


def row(ident, where=None, source="exif", local=None, hidden=False):
    lat, lon = where or (None, None)
    return {"id": ident, "person_id": 1, "kind": "image", "taken_local": local or f"2026-06-{1 + ident // 1440:02d}T{(ident // 60) % 24:02d}:{ident % 60:02d}",
            "zone": None, "latitude": lat, "longitude": lon, "location_source": source if where else None, "segment_id": None,
            "match": "place", "distance_km": None, "cluster": None, "hidden": hidden}


def along_a_line(count, spacing_km, start=(0.0, -170.0)):
    return [row(n, (start[0], start[1] + n * spacing_km / KM_PER_DEGREE)) for n in range(count)]


class ClusterTests(unittest.TestCase):
    def test_a_thousand_photos_along_a_line_make_the_expected_clusters(self):
        rows = along_a_line(1000, 1.8)
        found = photos.clusters(rows)
        self.assertEqual(len(found), 200)
        self.assertEqual([c["count"] for c in found], [5] * 200)
        self.assertEqual([r["cluster"] for r in rows], [n // 5 for n in range(1000)])
        self.assertEqual([c["cover"] for c in found[:3]], [0, 5, 10])
        self.assertEqual((found[0]["first"], found[0]["last"]), (rows[0]["taken_local"], rows[4]["taken_local"]))
        self.assertAlmostEqual(found[0]["longitude"], -170.0 + 2 * 1.8 / KM_PER_DEGREE, places=6)
        self.assertEqual(found[0]["latitude"], 0.0)
        self.assertFalse(any(c["inferred"] for c in found))

    def test_a_photo_joins_the_first_cluster_within_reach_and_the_centroid_follows(self):
        rows = [row(1, (39.0, -105.0)), row(2, (39.0, -105.0 + 4 / (KM_PER_DEGREE * 0.777))), row(3, (39.5, -105.0)), row(4, (39.0, -105.0 + 1 / KM_PER_DEGREE))]
        found = photos.clusters(rows)
        self.assertEqual([r["cluster"] for r in rows], [0, 0, 1, 0])
        self.assertEqual([c["count"] for c in found], [3, 1])
        self.assertEqual([c["cover"] for c in found], [1, 3])
        self.assertEqual((found[0]["first"], found[0]["last"]), (rows[0]["taken_local"], rows[3]["taken_local"]))
        self.assertLess(distance_km((found[0]["latitude"], found[0]["longitude"]), (39.0, -105.0)), 2.0)

    def test_photos_without_a_location_are_in_no_cluster(self):
        rows = [row(1), row(2, (39.0, -105.0)), row(3, (39.0, None)), row(4)]
        found = photos.clusters(rows)
        self.assertEqual([r["cluster"] for r in rows], [None, 0, None, None])
        self.assertEqual(found, [{"latitude": 39.0, "longitude": -105.0, "count": 1, "first": rows[1]["taken_local"], "last": rows[1]["taken_local"],
                                  "cover": 2, "inferred": False}])

    def test_a_cluster_is_inferred_only_when_every_photo_in_it_is(self):
        rows = [row(1, (39.0, -105.0), "inferred"), row(2, (39.001, -105.0), "inferred"), row(3, (45.0, -105.0), "inferred"), row(4, (45.001, -105.0))]
        found = photos.clusters(rows)
        self.assertEqual([c["inferred"] for c in found], [True, False])

    def test_the_cap_merges_the_smallest_cluster_into_its_nearest_neighbour(self):
        pairs = [r for n in range(401) for r in (row(2 * n, (0.0, -170.0 + n * 20.0 / KM_PER_DEGREE)), row(2 * n + 1, (0.0, -170.0 + n * 20.0 / KM_PER_DEGREE + 0.001)))]
        single = row(999, (0.0, -170.0 + 14 * 20.0 / KM_PER_DEGREE + 6.0 / KM_PER_DEGREE))
        ordered = sorted([*pairs, single], key=lambda r: r["longitude"])
        found = photos.clusters(ordered)
        self.assertEqual(len(found), 400)
        self.assertEqual(sum(c["count"] for c in found), 803)
        self.assertEqual([c["count"] for c in found if c["count"] != 2], [4, 3])
        members = {n: sorted(r["id"] for r in ordered if r["cluster"] == n) for n in range(400)}
        self.assertEqual(members[0], [0, 1, 2, 3])
        self.assertEqual(members[13], [28, 29, 999])
        self.assertEqual((found[0]["cover"], found[13]["cover"]), (0, 28))
        self.assertAlmostEqual(found[13]["longitude"], (2 * (-170.0 + 14 * 20.0 / KM_PER_DEGREE + 0.0005) + single["longitude"]) / 3, places=6)
        self.assertEqual(found[13]["latitude"], 0.0)
        self.assertEqual((found[13]["first"], found[13]["last"]), (pairs[28]["taken_local"], single["taken_local"]))
        with mock.patch.object(photos, "MAX_CLUSTERS", 1):
            everything = photos.clusters(ordered)
        self.assertEqual([c["count"] for c in everything], [803])
        self.assertEqual({r["cluster"] for r in ordered}, {0})

    def test_the_cap_keeps_the_clusters_in_time_order_and_every_photo_assigned(self):
        rows = along_a_line(1000, 10.0)
        found = photos.clusters(rows)
        self.assertEqual(len(found), 400)
        self.assertEqual(sum(c["count"] for c in found), 1000)
        self.assertEqual([c["first"] for c in found], sorted(c["first"] for c in found))
        self.assertTrue(all(r["cluster"] is not None and 0 <= r["cluster"] < 400 for r in rows))
        for number, c in enumerate(found):
            members = [r for r in rows if r["cluster"] == number]
            self.assertEqual(len(members), c["count"])
            self.assertEqual(c["cover"], members[0]["id"])
            self.assertEqual((c["first"], c["last"]), (members[0]["taken_local"], members[-1]["taken_local"]))
        self.assertEqual(photos.clusters(list(rows)), found)

    def test_near_the_poles_and_the_date_line_nearby_photos_still_share_a_pin(self):
        step = 3.0 / KM_PER_DEGREE
        rows = [row(1, (85.0, 10.0)), row(2, (85.0 + step, 10.0)), row(3, (70.0, -179.99)), row(4, (70.0 + step, -179.99)),
                row(5, (-33.9, 151.2)), row(6, (-33.9 - step, 151.2)), row(7, (0.0, 0.0)), row(8, (0.0, step))]
        photos.clusters(rows)
        self.assertEqual([r["cluster"] for r in rows], [0, 0, 1, 1, 2, 2, 3, 3])

    def test_a_photo_just_beyond_the_radius_starts_its_own_pin(self):
        rows = [row(1, (39.0, -105.0)), row(2, (39.0 + (CLUSTER + 0.01) / KM_PER_DEGREE, -105.0)), row(3, (39.0 + (CLUSTER - 0.01) / KM_PER_DEGREE, -105.0))]
        photos.clusters(rows)
        self.assertEqual([r["cluster"] for r in rows], [0, 1, 0])

    def test_no_photos_make_no_clusters(self):
        self.assertEqual(photos.clusters([]), [])

    def test_photos_either_side_of_the_date_line_share_a_pin_near_180(self):
        rows = [row(1, (10.0, 179.99)), row(2, (10.0, -179.99)), row(3, (0.0, 179.98)), row(4, (0.0, 179.99)), row(5, (0.0, -179.99))]
        found = photos.clusters(rows)
        self.assertEqual([r["cluster"] for r in rows], [0, 0, 1, 1, 1])
        self.assertEqual([c["count"] for c in found], [2, 3])
        self.assertAlmostEqual(abs(found[0]["longitude"]), 180.0, places=9)
        self.assertAlmostEqual(found[1]["longitude"], 179.99333333, places=6)
        self.assertEqual([c["latitude"] for c in found], [10.0, 0.0])

    def test_a_merge_across_the_date_line_keeps_the_centroid_near_180(self):
        rows = [row(1, (10.0, 179.9)), row(2, (10.0, -179.9)), row(3, (10.0, -179.9)), row(4, (10.0, 179.9))]
        self.assertEqual([c["count"] for c in photos.clusters(rows)], [2, 2])
        with mock.patch.object(photos, "MAX_CLUSTERS", 1):
            (only,) = photos.clusters(rows)
        self.assertEqual((only["count"], only["cover"], [r["cluster"] for r in rows]), (4, 1, [0, 0, 0, 0]))
        self.assertAlmostEqual(abs(only["longitude"]), 180.0, places=9)
        self.assertTrue(-180.0 <= only["longitude"] < 180.0)

    def test_near_the_pole_the_nearest_neighbour_wins_whatever_its_grid_column(self):
        rows = [row(1, (89.8, 180.0)), row(2, (89.8, 179.999)), row(3, (82.0, 0.0)), row(4, (82.0, 0.001)), row(5, (86.7, 0.0))]
        self.assertLess(distance_km((86.7, 0.0), (89.8, 180.0)), distance_km((86.7, 0.0), (82.0, 0.0)))
        with mock.patch.object(photos, "MAX_CLUSTERS", 2):
            found = photos.clusters(rows)
        self.assertEqual([r["cluster"] for r in rows], [0, 0, 1, 1, 0])
        self.assertEqual([c["count"] for c in found], [3, 2])
        self.assertAlmostEqual(found[0]["latitude"], (2 * 89.8 + 86.7) / 3, places=6)

    def test_the_cap_scans_neighbours_through_the_grid_rather_than_every_cluster(self):
        rows = [row(r * 50 + c, (r * 10.0 / KM_PER_DEGREE, -20.0 + c * 10.0 / KM_PER_DEGREE)) for r in range(60) for c in range(50)]
        with mock.patch.object(photos, "distance_km", wraps=distance_km) as measured:
            found = photos.clusters(rows)
        self.assertEqual((len(found), sum(c["count"] for c in found)), (400, 3000))
        self.assertLess(measured.call_count, 400_000)
        self.assertEqual([c["first"] for c in found], sorted(c["first"] for c in found))
        self.assertTrue(all(r["cluster"] is not None for r in rows))

    def test_an_isolated_cluster_still_finds_its_nearest_neighbour_far_away(self):
        rows = [row(2 * n + k, (n * 0.3 + k * 0.001, 10.0 + n * 0.3)) for n in range(30) for k in (0, 1)] + [row(99, (-20.0, 10.0))]
        with mock.patch.object(photos, "distance_km", wraps=distance_km) as measured, mock.patch.object(photos, "MAX_CLUSTERS", 30):
            found = photos.clusters(rows)
        self.assertEqual((len(found), rows[-1]["cluster"], found[0]["count"]), (30, 0, 3))
        self.assertAlmostEqual(found[0]["latitude"], -20.0 / 3 + 0.001 / 3, places=6)
        self.assertEqual([c["count"] for c in found[1:]], [2] * 29)
        self.assertLess(measured.call_count, 200)


if __name__ == "__main__":
    unittest.main()
