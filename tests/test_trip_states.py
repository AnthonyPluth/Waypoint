import unittest

from tests.privacy import no_leaks
from tests.test_trip_roads import DENVER, SALT_LAKE
from tests.test_trips import HOTEL, RouteCase
from waypoint.domain import tripmap


class TripStateLinesTests(RouteCase):
    def places(self, trip, who="ana"):
        return self.ok(who, "GET", f"/api/trips/{trip}/places")

    def test_a_stay_in_the_united_states_gets_the_state_lines_around_it(self):
        first = self.book("ana", DENVER)
        got = self.places(first["trip_id"])["boundaries"]
        self.assertTrue(got)
        for line in got:
            self.assertEqual(sorted(line), ["points"])
            self.assertGreaterEqual(len(line["points"]), 2)
            self.assertTrue(all(len(p) == 2 and 25 < p[0] < 50 and -125 < p[1] < -85 for p in line["points"]))
        self.assertTrue(any(abs(p[1] + 109.05) < 0.1 for line in got for p in line["points"]))

    def test_a_drive_between_two_stays_gets_the_lines_along_the_whole_road(self):
        first = self.book("ana", DENVER)
        single = self.places(first["trip_id"])["boundaries"]
        self.book("ana", SALT_LAKE, trip_id=first["trip_id"])
        both = self.places(first["trip_id"])["boundaries"]
        self.assertGreater(sum(len(line["points"]) for line in both), sum(len(line["points"]) for line in single))
        self.assertTrue(any(p[1] < -112 for line in both for p in line["points"]))

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
