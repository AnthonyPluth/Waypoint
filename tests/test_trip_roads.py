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
            self.assertTrue(line["ref"].startswith("I-"))

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
        with mock.patch.object(tripmap.roads, "interstates", return_value=mock.Mock(route=mock.Mock(return_value=winding), near=mock.Mock(return_value=[]))):
            self.assertEqual(tripmap.road_legs(live, located)["legs"], [])
        direct = roads.Route([(39.8, -105.0), (40.7, -111.8)], ["I-25"], 600.0, 1.0, 1.0)
        with mock.patch.object(tripmap.roads, "interstates", return_value=mock.Mock(route=mock.Mock(return_value=direct), near=mock.Mock(return_value=[]))):
            self.assertEqual(tripmap.road_legs(live, located)["legs"][0]["refs"], ["I-25"])


if __name__ == "__main__":
    unittest.main()
