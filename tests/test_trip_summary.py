import unittest

from unittest import mock

from tests.privacy import no_leaks
from tests.test_trips import BACK, DENVER, HOTEL, OUT, SALT_LAKE, RouteCase
from waypoint.domain import tripstats
from waypoint.server import mcp_access, mcp_http

LATER = {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}


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

    def test_a_road_stored_on_another_trip_for_the_same_drive_is_never_counted(self):
        ana_first = self.book("ana", DENVER)
        self.book("ana", SALT_LAKE, trip_id=ana_first["trip_id"])
        ben_first = self.book("ben", DENVER)
        self.book("ben", SALT_LAKE, trip_id=ben_first["trip_id"])
        places = self.ok("ben", "GET", f"/api/trips/{ben_first['trip_id']}/places")
        start, end = ({"latitude": round(p["latitude"], 4), "longitude": round(p["longitude"], 4)} for p in places["stays"][:2])
        path = [[start["latitude"], start["longitude"]], [40.0, -108.0], [41.0, -110.0], [end["latitude"], end["longitude"]]]
        self.assertEqual(self.ok("ben", "PUT", f"/api/trips/{ben_first['trip_id']}/driving-routes", {"start": start, "end": end, "path": path}), {"stored": True})
        theirs, mine = self.summary(ben_first["trip_id"], "ben"), self.summary(ana_first["trip_id"])
        self.assertFalse(theirs["road_estimated"])
        self.assertTrue(mine["road_estimated"])
        self.assertLess(mine["road_km"], theirs["road_km"])

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


class TripSummariesRouteTests(RouteCase):
    def batch(self, who, *trips):
        return self.call(who, "GET", "/api/trip-summaries?" + "&".join(f"trip={t}" for t in trips))

    def road_trip(self, who="ana", fields=DENVER):
        first = self.book(who, fields)
        self.book(who, SALT_LAKE, trip_id=first["trip_id"])
        return first["trip_id"]

    def test_each_trip_gets_the_summary_the_trip_route_gives_in_the_order_asked(self):
        road, flight = self.road_trip(), self.book("ana", LATER)["trip_id"]
        status, got = self.batch("ana", flight, road)
        self.assertEqual(status, 200, got)
        self.assertEqual([s["trip_id"] for s in got["summaries"]], [flight, road])
        for entry in got["summaries"]:
            self.assertEqual(entry["summary"], self.ok("ana", "GET", f"/api/trips/{entry['trip_id']}/summary"))
        self.assertGreater(got["summaries"][0]["summary"]["flight_km"], 0)
        self.assertGreater(got["summaries"][1]["summary"]["road_km"], 0)

    def test_a_trip_you_cant_see_is_left_out_and_the_others_are_still_answered(self):
        mine, theirs = self.road_trip("ana"), self.road_trip("ben")
        status, got = self.batch("ana", theirs, mine)
        self.assertEqual(status, 200, got)
        self.assertEqual([s["trip_id"] for s in got["summaries"]], [mine])
        self.assertEqual(self.batch("ana", theirs), (200, {"summaries": []}))
        self.assertEqual(self.batch("ben", theirs, mine)[1]["summaries"][0]["trip_id"], theirs)

    def test_a_missing_trip_looks_the_same_as_one_you_cant_see(self):
        theirs, mine = self.road_trip("ben"), self.road_trip("ana")
        self.assertEqual(self.batch("ana", theirs, 99999, mine), self.batch("ana", 99999, mine))

    def test_someone_added_to_a_trip_gets_its_summary(self):
        first = self.book("ana", OUT)
        self.assertEqual(self.batch("ben", first["trip_id"]), (200, {"summaries": []}))
        self.ok("ana", "POST", f"/api/segments/{first['id']}", {"travelers": [{"person_id": self.person["ana"]}, {"person_id": self.person["ben"]}]})
        [got] = self.batch("ben", first["trip_id"])[1]["summaries"]
        self.assertEqual(got["summary"]["kinds"]["flight"], 1)

    def test_a_trip_named_twice_is_answered_once(self):
        trip = self.road_trip()
        self.assertEqual([s["trip_id"] for s in self.batch("ana", trip, trip)[1]["summaries"]], [trip])

    def test_twelve_trips_are_answered_and_thirteen_are_refused(self):
        trip = self.road_trip()
        self.assertEqual(self.batch("ana", *range(trip, trip + 12))[0], 200)
        status, got = self.batch("ana", *range(trip, trip + 13))
        self.assertEqual((status, got), (400, {"error": "Ask for at most 12 trips at a time"}))

    def test_a_request_that_names_no_trip_or_something_that_isnt_one_is_refused(self):
        for path in ("/api/trip-summaries", "/api/trip-summaries?trip=", "/api/trip-summaries?trip=x", "/api/trip-summaries?trip=-1", "/api/trip-summaries?trip=1.5"):
            with self.subTest(path):
                self.assertEqual(self.call("ana", "GET", path)[0], 400)

    def test_one_trip_that_cant_be_summarised_doesnt_hide_the_others(self):
        first, second = self.road_trip(), self.book("ana", LATER)["trip_id"]
        real = tripstats.summary
        with mock.patch.object(tripstats, "summary", side_effect=lambda conn, viewer, trip_id: None if trip_id == first else real(conn, viewer, trip_id)):
            self.assertEqual([s["trip_id"] for s in self.batch("ana", first, second)[1]["summaries"]], [second])

    def test_signed_out_it_is_refused(self):
        trip = self.road_trip()
        status, _ = self.req("GET", f"/api/trip-summaries?trip={trip}")
        self.assertIn(status, (401, 403))

    def test_an_assistant_cant_reach_it_though_the_trip_route_is_theirs_to_ask_for_nowhere(self):
        self.assertTrue(mcp_access.blocked("/api/trip-summaries"))
        self.assertTrue(mcp_access.blocked("/api/trip-summaries/anything"))
        self.assertIsNone(mcp_http.needs("GET", "/api/trip-summaries"))

    def test_nothing_of_a_trip_or_a_refused_request_is_logged_or_echoed(self):
        trip = self.book("ana", {**HOTEL, "destination": "Quillfeather Harbour", "confirmation": "CANARYCODE9"})["trip_id"]
        with no_leaks(self, "Quillfeather", "CANARYCODE9"):
            self.assertEqual(self.batch("ana", trip)[0], 200)
            status, got = self.batch("ana", "Quillfeather")
            self.assertEqual(status, 400)
            self.assertNotIn("Quillfeather", str(got))


if __name__ == "__main__":
    unittest.main()
