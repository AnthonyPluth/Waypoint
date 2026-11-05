import unittest

from tests.test_trip_roads import DENVER, SALT_LAKE
from tests.test_trips import BACK, HOTEL, OUT, RouteCase


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
        self.assertEqual(got["flight_km"], 0.0)
        self.assertEqual(got["countries"], ["United States"])
        self.assertEqual(got["photos"], {"total": 0, "inferred": 0})

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
