import unittest

from tests.test_trips import BACK, DENVER, HOTEL, OUT, SALT_LAKE, RouteCase


class TripSummaryRouteTests(RouteCase):
    def summary(self, trip, who="ana"):
        return self.ok(who, "GET", f"/api/trips/{trip}/summary")

    def test_a_trip_on_the_road_gets_its_numbers(self):
        first = self.book("ana", DENVER)
        self.book("ana", SALT_LAKE, trip_id=first["trip_id"])
        got = self.summary(first["trip_id"])
        self.assertEqual((got["days"], got["nights"]), (7, 6))
        self.assertEqual(got["kinds"]["hotel"], 2)
        self.assertGreater(got["road_km"], 0)
        self.assertTrue(got["road_estimated"])
        self.assertEqual(got["flight_km"], 0.0)
        self.assertEqual(got["countries"], ["United States"])
        self.assertEqual(got["photos"], {"total": 0, "inferred": 0})

    def test_a_drive_is_a_straight_line_marked_estimated_until_a_road_is_stored_and_then_the_roads_length(self):
        first = self.book("ana", DENVER)
        trip = first["trip_id"]
        self.book("ana", SALT_LAKE, trip_id=trip)
        straight = self.summary(trip)
        self.assertTrue(straight["road_estimated"])
        self.assertEqual(straight["distance_km"], straight["road_km"])
        places = self.ok("ana", "GET", f"/api/trips/{trip}/places")
        a, b = places["stays"][0], places["stays"][1]
        start, end = ({"latitude": round(p["latitude"], 4), "longitude": round(p["longitude"], 4)} for p in (a, b))
        path = [[start["latitude"], start["longitude"]], [40.0, -108.0], [41.0, -110.0], [end["latitude"], end["longitude"]]]
        self.assertEqual(self.ok("ana", "PUT", f"/api/trips/{trip}/driving-routes", {"start": start, "end": end, "path": path}), {"stored": True})
        got = self.summary(trip)
        self.assertFalse(got["road_estimated"])
        self.assertGreater(got["road_km"], straight["road_km"])
        self.assertEqual(got["distance_km"], got["road_km"])

    def test_flights_count_their_distance_and_countries(self):
        first = self.book("ana", OUT)
        self.book("ana", BACK, trip_id=first["trip_id"])
        got = self.summary(first["trip_id"])
        self.assertGreater(got["flight_km"], 10000)
        self.assertEqual(got["distance_km"], got["flight_km"])
        self.assertEqual(got["countries"], ["United Kingdom", "United States"])
        self.assertEqual(got["kinds"]["flight"], 2)

    def test_a_trip_with_no_placed_booking_answers_zeros(self):
        first = self.book("ana", {**HOTEL, "destination": "Nowhere At All Zzyx"})
        got = self.summary(first["trip_id"])
        self.assertEqual((got["distance_km"], got["road_estimated"], got["states"], got["countries"]), (0.0, False, [], []))

    def test_a_stranger_gets_404_like_a_missing_trip(self):
        first = self.book("ana", DENVER)
        for who, trip in (("ben", first["trip_id"]), ("ana", 99999)):
            with self.subTest(who=who, trip=trip):
                status, got = self.call(who, "GET", f"/api/trips/{trip}/summary")
                self.assertEqual((status, got), (404, {"error": "No such trip"}))

    def test_someone_added_to_the_trip_sees_it(self):
        first = self.book("ana", OUT)
        self.assertEqual(self.call("ben", "GET", f"/api/trips/{first['trip_id']}/summary")[0], 404)
        self.ok("ana", "POST", f"/api/segments/{first['id']}", {"travelers": [{"person_id": self.person["ana"]}, {"person_id": self.person["ben"]}]})
        self.assertEqual(self.summary(first["trip_id"], "ben")["kinds"]["flight"], 1)


if __name__ == "__main__":
    unittest.main()
