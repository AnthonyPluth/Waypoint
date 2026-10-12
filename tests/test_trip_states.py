import unittest

from tests.privacy import no_leaks
from tests.test_trip_roads import DENVER, SALT_LAKE
from tests.test_trips import HOTEL, OUT, RouteCase
from waypoint.domain import tripmap
from waypoint.storage import states


FLY = {**OUT, "start_local": "2026-06-02T08:00", "end_local": "2026-06-02T14:00"}


class TripStateLinesTests(RouteCase):
    def places(self, trip, who="ana"):
        return self.ok(who, "GET", f"/api/trips/{trip}/places")

    def steps(self, lines):
        return sum(len(line["points"]) - 1 for line in lines)

    def test_a_stay_in_the_united_states_gets_the_state_lines_around_it(self):
        first = self.book("ana", DENVER)
        got = self.places(first["trip_id"])["boundaries"]
        self.assertTrue(got)
        for line in got:
            self.assertEqual(sorted(line), ["points"])
            self.assertGreaterEqual(len(line["points"]), 2)
            self.assertTrue(all(len(p) == 2 and 24 < p[0] < 50 and -130 < p[1] < -75 for p in line["points"]))
        self.assertTrue(any(abs(p[1] + 109.05) < 0.1 for line in got for p in line["points"]))

    def test_a_drive_between_two_stays_gets_the_lines_along_the_whole_road(self):
        first = self.book("ana", DENVER)
        self.book("ana", SALT_LAKE, trip_id=first["trip_id"])
        both = self.places(first["trip_id"])["boundaries"]
        points = [p for line in both for p in line["points"]]
        self.assertTrue(any(p[1] < -112 for p in points))
        self.assertTrue(any(abs(p[1] + 109.05) < 0.1 for p in points))
        self.assertTrue(any(abs(p[1] + 111.05) < 0.1 for p in points))

    def test_a_long_flight_gets_the_borders_between_its_two_ends(self):
        first = self.book("ana", {**FLY, "origin": "SEA", "destination": "MIA"})
        got = self.places(first["trip_id"])["boundaries"]
        points = [p for line in got for p in line["points"]]
        for lon in (-110.0, -100.0, -90.0, -85.0):
            self.assertTrue(any(abs(p[1] - lon) < 1.0 and 28 < p[0] < 46 for p in points), lon)
        self.assertTrue(any(30.0 < p[0] < 31.2 and -88 < p[1] < -81 for p in points))
        self.assertTrue(any(33.5 < p[0] < 35.2 and -85 < p[1] < -75 for p in points))
        self.assertLessEqual(self.steps(got), 1500)

    def test_a_flight_with_a_stop_gets_the_borders_under_each_leg(self):
        first = self.book("ana", {**FLY, "origin": "MSP", "destination": "ATL"})
        self.book("ana", {**FLY, "origin": "ATL", "destination": "FLL", "start_local": "2026-06-02T09:00", "end_local": "2026-06-02T11:00"}, trip_id=first["trip_id"])
        points = [p for line in self.places(first["trip_id"])["boundaries"] for p in line["points"]]
        self.assertTrue(any(33.5 < p[0] < 35.2 and -86 < p[1] < -82 for p in points))
        self.assertTrue(any(30.0 < p[0] < 31.2 and -88 < p[1] < -81 for p in points))

    def test_a_trip_in_one_state_stays_small_and_leaves_out_the_far_coasts(self):
        first = self.book("ana", DENVER)
        got = self.places(first["trip_id"])["boundaries"]
        self.assertLess(self.steps(got), 1400)
        self.assertLess(len(repr(got)), 32_000)
        points = [p for line in got for p in line["points"]]
        self.assertFalse(any(p[1] > -80 for p in points))
        self.assertFalse(any(p[0] < 27 for p in points))

    def test_a_cross_country_trip_is_smaller_than_the_whole_file(self):
        first = self.book("ana", {**FLY, "origin": "SEA", "destination": "MIA"})
        got = self.places(first["trip_id"])["boundaries"]
        self.assertLess(len(repr(got)), 45_000)

    def test_the_lines_are_capped(self):
        first = self.book("ana", DENVER)
        self.book("ana", SALT_LAKE, trip_id=first["trip_id"])
        got = self.places(first["trip_id"])["boundaries"]
        self.assertLessEqual(sum(len(line["points"]) - 1 for line in got), 1500)

    def test_a_trip_with_no_located_points_has_none(self):
        first = self.book("ana", {**HOTEL, "destination": "Nowhere At All Zzyx"})
        got = self.places(first["trip_id"])
        self.assertEqual(got["boundaries"], [])
        self.assertEqual(got["stays"], [])

    def test_stays_outside_the_united_states_have_none(self):
        first = self.book("ana", {**HOTEL, "destination": "London"})
        self.book("ana", {**HOTEL, "destination": "Paris", "start_local": "2026-06-09T15:00", "end_local": "2026-06-12T10:00", "start_zone": "Europe/Paris", "end_zone": "Europe/Paris"}, trip_id=first["trip_id"])
        self.assertEqual(self.places(first["trip_id"])["boundaries"], [])

    def test_a_stranger_gets_404_and_no_lines(self):
        first = self.book("ana", DENVER)
        status, body = self.call("ben", "GET", f"/api/trips/{first['trip_id']}/places")
        self.assertEqual(status, 404)
        self.assertNotIn("boundaries", repr(body))

    def test_the_lines_say_nothing_about_who_travels_or_what_was_booked(self):
        name, code = "Quentin Marlowe-Zzyx", "ZQXW7413"
        with no_leaks(self, name, code):
            first = self.book("ana", {**DENVER, "confirmation": code, "details": {"address": "100 Pearl Street, Denver, CO 80202"},
                                      "travelers": [{"person_id": None, "name": name}]})
            got = self.places(first["trip_id"])
            self.assertTrue(got["boundaries"])
            for text in (name, code, "Mile High Inn", "Pearl Street"):
                self.assertNotIn(text, repr(got["boundaries"]))
        self.assertTrue(all(sorted(line) == ["points"] for line in got["boundaries"]))


class StateLineRuleTests(unittest.TestCase):
    def test_nothing_to_look_near_gives_nothing(self):
        self.assertEqual(tripmap.state_lines([], []), [])

    def test_the_extent_covers_a_flight_s_great_circle_and_the_view_around_it(self):
        sea, mia = (47.45, -122.31), (25.79, -80.29)
        south, west, north, east = tripmap.map_extent([sea, mia], [], [(sea, mia)])
        self.assertLessEqual(south, 25.79)
        self.assertGreaterEqual(north, 47.45)
        self.assertLessEqual(west, -122.31)
        self.assertGreaterEqual(east, -80.29)
        bulge = tripmap.map_extent([sea, mia], [], [(sea, mia)])
        self.assertEqual(bulge, tripmap.map_extent([sea, mia], [], [(mia, sea)]))

    def test_a_flight_over_the_pole_side_bulges_the_extent_beyond_its_ends(self):
        a, b = (40.0, -120.0), (40.0, -60.0)
        flat = tripmap.map_extent([a, b], [], [])
        arced = tripmap.map_extent([a, b], [], [(a, b)])
        self.assertGreater(arced[2], flat[2])

    def test_a_small_trip_still_gets_the_view_around_it(self):
        south, west, north, east = tripmap.map_extent([(39.74, -104.99)], [], [])
        self.assertGreater(north - south, 10)
        self.assertGreater(east - west, 10)
        self.assertLess(east - west, 60)

    def test_the_extent_stays_on_the_globe(self):
        south, west, north, east = tripmap.map_extent([(-84.0, 179.0), (84.0, -179.0)], [], [((-84.0, 179.0), (84.0, -179.0))])
        self.assertTrue(south >= -85 and north <= 85 and west >= -180 and east <= 180)

    def test_a_flight_between_the_same_place_or_opposite_places_does_not_break_the_arc(self):
        here = (39.74, -104.99)
        self.assertEqual(tripmap._arc(here, here), [here, here])
        self.assertEqual(len(tripmap._arc((10.0, 0.0), (-10.0, 180.0))), tripmap.ARC_STEPS + 1)
        self.assertEqual(tripmap._arc((0.0, 0.0), (0.0, 180.0)), [(0.0, 0.0), (0.0, 180.0)])

    def test_a_long_flight_s_extent_gives_the_borders_between_its_ends(self):
        sea, mia = (47.45, -122.31), (25.79, -80.29)
        lines = tripmap.state_lines([sea, mia], [], [(sea, mia)])
        self.assertTrue(any(abs(p[1] + 100) < 1 for line in lines for p in line["points"]))
        self.assertEqual([line for line in tripmap.state_lines([sea, mia], [])], tripmap.state_lines([sea, mia], []))

    def test_the_lines_stay_inside_the_step_budget(self):
        lines = tripmap.state_lines([(47.45, -122.31), (25.79, -80.29)], [], [((47.45, -122.31), (25.79, -80.29))])
        self.assertLessEqual(sum(len(line["points"]) - 1 for line in lines), states.BUDGET)

    def test_the_points_are_rounded_to_about_a_hundred_metres(self):
        lines = tripmap.state_lines([(39.74, -104.99)], [])
        self.assertTrue(lines)
        for line in lines:
            for lat, lon in line["points"]:
                self.assertEqual((lat, lon), (round(lat, 3), round(lon, 3)))

    def test_a_road_leg_s_own_points_count_as_places_to_look_near(self):
        leg = {"from_segment_id": 1, "to_segment_id": 2, "refs": ["I-80"], "points": [[41.2, -107.5], [40.75, -111.85]]}
        with_leg = tripmap.state_lines([], [leg])
        self.assertTrue(with_leg)
        self.assertTrue(any(p[1] < -110 for line in with_leg for p in line["points"]))


if __name__ == "__main__":
    unittest.main()
