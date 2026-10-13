import unittest
from unittest import mock

from tests.privacy import no_leaks
from tests.test_trips import HOTEL, RouteCase
from waypoint.domain import tripmap
from waypoint.storage import roads

DENVER = {**HOTEL, "origin": "Mile High Inn", "destination": "Denver", "start_local": "2026-06-02T15:00", "end_local": "2026-06-04T10:00",
          "start_zone": "America/Denver", "end_zone": "America/Denver"}
SALT_LAKE = {**DENVER, "origin": "Salt Flat Inn", "destination": "Salt Lake City", "start_local": "2026-06-04T15:00", "end_local": "2026-06-08T10:00"}
BOULDER = {**DENVER, "origin": "Flatiron Inn", "destination": "Boulder", "start_local": "2026-06-04T15:00", "end_local": "2026-06-08T10:00"}
NOROADS = {"legs": [], "interstates": []}


class TripRoadsRouteTests(RouteCase):
    def places(self, trip, who="ana"):
        return self.ok(who, "GET", f"/api/trips/{trip}/places")

    def test_two_far_apart_stays_get_the_interstates_between_them(self):
        first = self.book("ana", DENVER)
        second = self.book("ana", SALT_LAKE, trip_id=first["trip_id"])
        got = self.places(first["trip_id"])["roads"]
        self.assertEqual(len(got["legs"]), 1)
        leg = got["legs"][0]
        self.assertEqual(sorted(leg), ["from_segment_id", "points", "refs", "to_segment_id"])
        self.assertEqual((leg["from_segment_id"], leg["to_segment_id"]), (first["id"], second["id"]))
        self.assertEqual(leg["refs"], ["I-25", "I-80"])
        self.assertGreater(len(leg["points"]), 20)
        self.assertTrue(all(len(p) == 2 and 37 < p[0] < 43 and -113 < p[1] < -104 for p in leg["points"]))
        self.assertTrue(got["interstates"])
        for line in got["interstates"]:
            self.assertEqual(sorted(line), ["points", "ref"])
            self.assertRegex(line["ref"], r"^(I|US|[A-Z]{2})-\d+[A-Z]?$")

    def test_a_flight_between_stays_is_not_a_road_leg(self):
        first = self.book("ana", DENVER)
        trip = first["trip_id"]
        self.book("ana", {"kind": "flight", "origin": "DEN", "destination": "SLC", "start_local": "2026-06-04T09:00", "end_local": "2026-06-04T10:30"}, trip_id=trip)
        self.book("ana", SALT_LAKE, trip_id=trip)
        self.assertEqual(self.places(trip)["roads"], NOROADS)

    def test_a_trip_of_flights_has_no_roads(self):
        out = self.book("ana")
        self.book("ana", {**HOTEL, "destination": "London"}, trip_id=out["trip_id"])
        self.assertEqual(self.places(out["trip_id"])["roads"], NOROADS)

    def test_stays_close_together_are_not_a_road_trip(self):
        first = self.book("ana", DENVER)
        self.book("ana", BOULDER, trip_id=first["trip_id"])
        self.assertEqual(self.places(first["trip_id"])["roads"], NOROADS)

    def test_a_cancelled_stay_is_stepped_over(self):
        first = self.book("ana", DENVER)
        trip = first["trip_id"]
        self.book("ana", {**SALT_LAKE, "destination": "Chicago", "start_local": "2026-06-04T12:00", "end_local": "2026-06-04T13:00", "status": "cancelled"}, trip_id=trip)
        last = self.book("ana", {**SALT_LAKE, "start_local": "2026-06-05T15:00", "end_local": "2026-06-08T10:00"}, trip_id=trip)
        legs = self.places(trip)["roads"]["legs"]
        self.assertEqual([(g["from_segment_id"], g["to_segment_id"]) for g in legs], [(first["id"], last["id"])])

    def test_stays_outside_the_united_states_fall_back_to_no_road(self):
        first = self.book("ana", {**HOTEL, "destination": "London"})
        self.book("ana", {**HOTEL, "destination": "Paris", "start_local": "2026-06-09T15:00", "end_local": "2026-06-12T10:00", "start_zone": "Europe/Paris", "end_zone": "Europe/Paris"}, trip_id=first["trip_id"])
        self.assertEqual(self.places(first["trip_id"])["roads"], NOROADS)

    def test_a_stranger_gets_no_roads_only_404(self):
        first = self.book("ana", DENVER)
        self.book("ana", SALT_LAKE, trip_id=first["trip_id"])
        self.assertEqual(self.call("ben", "GET", f"/api/trips/{first['trip_id']}/places")[0], 404)

    def test_the_roads_say_nothing_about_who_travels_or_what_was_booked(self):
        name, code = "Quentin Marlowe-Zzyx", "ZQXW7413"
        with no_leaks(self, name, code):
            first = self.book("ana", {**DENVER, "confirmation": code, "details": {"address": "100 Pearl Street, Denver, CO 80202"},
                                      "travelers": [{"person_id": None, "name": name}]})
            self.book("ana", {**SALT_LAKE, "confirmation": code, "travelers": [{"person_id": None, "name": name}]}, trip_id=first["trip_id"])
            got = self.places(first["trip_id"])
            self.assertTrue(got["roads"]["legs"])
            self.assertNotIn(name, repr(got))
            self.assertNotIn(code, repr(got))
            self.assertNotIn("Mile High Inn", repr(got["roads"]))
        self.assertEqual(sorted(got["roads"]), ["interstates", "legs"])

    def test_the_lookup_is_the_same_for_a_leg_in_either_direction(self):
        first = self.book("ana", {**SALT_LAKE, "start_local": "2026-06-01T15:00", "end_local": "2026-06-02T10:00"})
        self.book("ana", {**DENVER, "start_local": "2026-06-02T15:00", "end_local": "2026-06-04T10:00"}, trip_id=first["trip_id"])
        leg = self.places(first["trip_id"])["roads"]["legs"][0]
        self.assertEqual(leg["refs"], ["I-80", "I-25"])


class RoadLegRuleTests(unittest.TestCase):
    def stay(self, ident, start="2026-06-02T15:00", kind="hotel"):
        return {"id": ident, "kind": kind, "start_local": start, "start_zone": "America/Denver"}

    def test_a_stay_without_a_stored_point_breaks_the_chain(self):
        live = [self.stay(1), self.stay(2, "2026-06-03T15:00"), self.stay(3, "2026-06-04T15:00")]
        located = {1: (39.74, -104.99), 3: (40.76, -111.89)}
        self.assertEqual(tripmap.road_legs(live, located)["legs"], [])
        located[2] = (39.74, -104.99)
        self.assertEqual([(g["from_segment_id"], g["to_segment_id"]) for g in tripmap.road_legs(live, located)["legs"]], [(2, 3)])

    def test_legs_follow_the_order_of_time_not_of_ids(self):
        live = [self.stay(9, "2026-06-02T15:00"), self.stay(2, "2026-06-04T15:00")]
        located = {9: (39.74, -104.99), 2: (40.76, -111.89)}
        legs = tripmap.road_legs(live, located)["legs"]
        self.assertEqual([(g["from_segment_id"], g["to_segment_id"]) for g in legs], [(9, 2)])

    def test_trains_cruises_and_parking_are_not_road_legs(self):
        located = {1: (39.74, -104.99), 2: (40.76, -111.89), 3: (39.74, -104.99)}
        for kind in ("train", "cruise"):
            live = [self.stay(1), self.stay(5, "2026-06-03T15:00", kind), self.stay(2, "2026-06-04T15:00")]
            self.assertEqual(tripmap.road_legs(live, located)["legs"], [], kind)
        live = [self.stay(1), self.stay(3, "2026-06-03T15:00", "parking"), self.stay(2, "2026-06-04T15:00")]
        self.assertEqual(len(tripmap.road_legs(live, located)["legs"]), 1)

    def test_a_route_far_longer_than_the_straight_line_is_not_used(self):
        live = [self.stay(1), self.stay(2, "2026-06-04T15:00")]
        located = {1: (39.74, -104.99), 2: (40.76, -111.89)}
        winding = roads.Route([(39.8, -105.0), (40.7, -111.8)], ["I-25"], 3000.0, 1.0, 1.0)
        with mock.patch.object(tripmap.roads, "highways", return_value=mock.Mock(route=mock.Mock(return_value=winding), near=mock.Mock(return_value=[]))):
            self.assertEqual(tripmap.road_legs(live, located)["legs"], [])
        direct = roads.Route([(39.8, -105.0), (40.7, -111.8)], ["I-25"], 600.0, 1.0, 1.0)
        with mock.patch.object(tripmap.roads, "highways", return_value=mock.Mock(route=mock.Mock(return_value=direct), near=mock.Mock(return_value=[]))):
            self.assertEqual(tripmap.road_legs(live, located)["legs"][0]["refs"], ["I-25"])


class BacktrackingRuleTests(unittest.TestCase):
    DENVER = (39.74, -104.99)
    SALT_LAKE = (40.76, -111.89)
    PARK_CITY = (40.65, -111.50)
    BOISE = (43.6, -116.2)

    def stays(self, *where):
        live = [{"id": n + 1, "kind": "hotel", "start_local": f"2026-06-{n + 2:02d}T15:00", "start_zone": "America/Denver"} for n in range(len(where))]
        return live, {n + 1: at for n, at in enumerate(where)}

    def legs(self, *where):
        return tripmap.road_legs(*self.stays(*where))["legs"]

    def test_the_way_back_to_where_the_trip_started_retraces_the_line_already_drawn(self):
        out, back = self.legs(self.DENVER, self.SALT_LAKE, (39.70, -104.95))
        self.assertEqual((back["from_segment_id"], back["to_segment_id"]), (2, 3))
        self.assertEqual(back["points"][1:-1], out["points"][-2:0:-1])
        self.assertEqual(back["refs"], list(reversed(out["refs"])))

    def test_a_short_hop_after_a_long_drive_follows_the_road_it_just_drove(self):
        out, hop = self.legs(self.DENVER, self.SALT_LAKE, self.PARK_CITY)
        self.assertEqual((hop["from_segment_id"], hop["to_segment_id"]), (2, 3))
        self.assertGreater(len(hop["points"]), 2)
        self.assertTrue(all(p in out["points"] for p in hop["points"][1:-1]))
        self.assertEqual(hop["refs"], ["I-80"])

    def test_a_stop_back_along_the_road_is_reached_by_the_section_between_the_two_points(self):
        rock_springs = (41.59, -109.2)
        out, back, onward = self.legs(self.DENVER, self.SALT_LAKE, rock_springs, self.PARK_CITY)
        self.assertEqual([(g["from_segment_id"], g["to_segment_id"]) for g in (out, back, onward)], [(1, 2), (2, 3), (3, 4)])
        self.assertTrue(all(p in out["points"] for p in back["points"][1:-1]))
        self.assertTrue(all(p in out["points"] for p in onward["points"][1:-1]))
        self.assertEqual(onward["refs"], ["I-80"])

    def test_a_return_judged_too_winding_to_route_still_uses_the_line_already_drawn(self):
        direct = roads.Route([(39.8, -105.0), (40.2, -108.0), (40.7, -111.8)], ["I-25"], 600.0, 1.0, 1.0, ["I-25", "I-25", "I-25"])
        winding = roads.Route([(40.7, -111.8), (39.8, -105.0)], ["I-25"], 3000.0, 1.0, 1.0, ["I-25", "I-25"])
        route = mock.Mock(side_effect=[direct, winding])
        live, located = self.stays(self.DENVER, self.SALT_LAKE, self.DENVER)
        with mock.patch.object(tripmap.roads, "highways", return_value=mock.Mock(route=route, near=mock.Mock(return_value=[]))):
            out, back = tripmap.road_legs(live, located)["legs"]
        self.assertEqual(route.call_count, 1)
        self.assertEqual(back["points"][1:-1], out["points"][-2:0:-1])
        self.assertEqual(back["refs"], ["I-25"])

    def test_a_new_stretch_is_still_routed_and_a_far_stop_is_not_retraced(self):
        out, onward = self.legs(self.DENVER, self.SALT_LAKE, self.BOISE)
        self.assertFalse(all(p in out["points"] for p in onward["points"][1:-1]))
        self.assertEqual(len(self.legs(self.DENVER, self.SALT_LAKE, (40.23, -111.66))), 1)

    def test_a_line_without_marks_is_not_retraced(self):
        bare = roads.Route([(39.8, -105.0), (40.7, -111.8)], ["I-25"], 600.0, 1.0, 1.0)
        self.assertIsNone(tripmap._section(bare, self.DENVER, self.SALT_LAKE))
        self.assertIsNone(tripmap._retrace([], self.DENVER, self.SALT_LAKE))


if __name__ == "__main__":
    unittest.main()
