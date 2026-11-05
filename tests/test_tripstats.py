import time
import unittest

from sqlalchemy import insert, select

from tests.test_trips import Household
from waypoint.domain import stats, trips, tripstats
from waypoint.storage.models import Airport, Photo, PhotoSource

MOUNTAIN = {"start_zone": "America/Denver", "end_zone": "America/Denver"}
SFO_DEN = {"kind": "flight", "origin": "SFO", "destination": "DEN", "start_local": "2026-06-01T08:00", "end_local": "2026-06-01T11:30",
           "start_zone": "America/Los_Angeles", "end_zone": "America/Denver"}
SLC_SFO = {"kind": "flight", "origin": "SLC", "destination": "SFO", "start_local": "2026-06-06T17:00", "end_local": "2026-06-06T18:30",
           "start_zone": "America/Denver", "end_zone": "America/Los_Angeles"}
DENVER = {"kind": "hotel", "origin": "Mile High Inn", "destination": "Denver", "start_local": "2026-06-01T15:00", "end_local": "2026-06-03T10:00",
          "details": {"address": "1 Example Street, Denver, CO 80202"}, **MOUNTAIN}
CAR = {"kind": "car", "origin": "DEN", "destination": "SLC", "provider": "Example Rentals", "start_local": "2026-06-03T11:00",
       "end_local": "2026-06-06T15:00", **MOUNTAIN}
SALT_LAKE = {"kind": "hotel", "origin": "Salt Flat Inn", "destination": "Salt Lake City", "start_local": "2026-06-03T20:00",
             "end_local": "2026-06-05T10:00", "details": {"address": "2 Example Avenue, Salt Lake City, UT 84101"}, **MOUNTAIN}
SALT_LAKE_AGAIN = {"kind": "hotel", "origin": "Temple View Lodge", "destination": "Salt Lake City", "start_local": "2026-06-04T15:00",
                   "end_local": "2026-06-06T10:00", **MOUNTAIN}
VANCOUVER = {"kind": "hotel", "origin": "Harbour Hotel", "destination": "Vancouver", "start_local": "2026-06-02T15:00", "end_local": "2026-06-05T10:00",
             "status": "cancelled", "details": {"address": "3 Example Road, Vancouver, BC V6B 1A1, Canada"},
             "start_zone": "America/Vancouver", "end_zone": "America/Vancouver"}
CANCELLED_FLIGHT = {**SFO_DEN, "destination": "NRT", "status": "cancelled", "end_local": "2026-06-02T15:00", "end_zone": "Asia/Tokyo"}
BOULDER = {**DENVER, "origin": "Flatiron Inn", "destination": "Boulder", "start_local": "2026-06-03T15:00", "end_local": "2026-06-04T10:00",
           "details": {"address": "4 Example Lane, Boulder, CO 80302"}}
SALT_LAKE_DRIVE = {**SALT_LAKE, "details": {}, "start_local": "2026-06-03T20:00"}
NOWHERE = {"kind": "hotel", "origin": "Harbour Hotel", "destination": "Nowhere At All Zzyx", "start_local": "2026-06-02T15:00",
           "end_local": "2026-06-04T10:00", "start_zone": "America/Denver", "end_zone": "America/Denver"}
NO_KINDS = {"flight": 0, "hotel": 0, "car": 0, "train": 0, "cruise": 0, "parking": 0, "visit": 0}


class TripSummaryCase(Household):
    def setUp(self):
        super().setUp()
        self.asset = 0

    def mine(self, fields, trip_id=None):
        return self.add(self.jane, fields, trip_id, self.on(self.jane.person_id))

    def library(self, person_id):
        url = f"https://photos{person_id}.example.com"
        return self.c.execute(insert(PhotoSource).values(person_id=person_id, owner_sub="u-jane", url=url, immich_user_id="u-1",
                                                         api_key="enc:v1:made-up", status="ok", created=time.time())).lastrowid

    def photo(self, source, trip_id, state=None, country=None, match="place", inferred=False, hidden=False, decided_by="auto"):
        self.asset += 1
        self.c.execute(insert(Photo).values(source_id=source, asset_id=f"asset-{self.asset}", asset_updated="2026-06-02T00:00:00Z", kind="image",
                                            taken_utc="2026-06-02T18:00:00Z", taken_local="2026-06-02T12:00", latitude=40.0, longitude=-105.0,
                                            location_source="inferred" if inferred else "exif", state=state, country=country, trip_id=trip_id,
                                            match=match, decided_by=decided_by, hidden=hidden, seen=time.time()))

    def summary(self, trip_id, who=None):
        got = tripstats.summary(self.c, who or self.jane, trip_id)
        assert got is not None
        return got

    def great_circle(self, *legs):
        known = {a.code: a for a in self.c.orm.scalars(select(Airport)).all()}
        return sum(stats.distance_km((known[a].latitude, known[a].longitude), (known[b].latitude, known[b].longitude)) for a, b in legs)


class TripSummaryTests(TripSummaryCase):
    def full_trip(self):
        trip = self.add(self.jane, SFO_DEN, None, self.on(self.jane.person_id, self.sam.person_id))["trip_id"]
        for fields in (DENVER, CAR, SALT_LAKE, SALT_LAKE_AGAIN, SLC_SFO, VANCOUVER, CANCELLED_FLIGHT):
            self.mine(fields, trip)
        mine, sams = self.library(self.jane.person_id), self.library(self.sam.person_id)
        self.photo(mine, trip, "Utah", "United States of America")
        self.photo(mine, trip, "Utah", "United States of America")
        self.photo(mine, trip, "Idaho", "United States of America", match="time", inferred=True)
        self.photo(mine, trip, "British Columbia", "Canada")
        self.photo(mine, trip, "Wyoming", "United States of America", match="far")
        self.photo(mine, trip, "Montana", "United States of America", match="far", decided_by="owner")
        self.photo(mine, trip, "Nevada", "United States of America", match="ambiguous")
        self.photo(mine, None, "Oregon", "United States of America", match="none")
        self.photo(sams, trip, "Arizona", "Mexico", hidden=True)
        self.photo(mine, trip, "New Mexico", "United States of America", hidden=True, inferred=True)
        return trip

    def test_a_trip_gets_its_days_nights_distance_places_and_photos(self):
        trip = self.full_trip()
        got = self.summary(trip)
        self.assertEqual((got["days"], got["nights"]), (6, 5))
        self.assertAlmostEqual(got["flight_km"], self.great_circle(("SFO", "DEN"), ("SLC", "SFO")), delta=0.1)
        self.assertTrue(got["road_estimated"])
        self.assertGreater(got["road_km"], 600)
        self.assertLess(got["road_km"], 1300)
        self.assertAlmostEqual(got["distance_km"], got["flight_km"] + got["road_km"], delta=0.2)
        self.assertEqual(got["states"], ["Colorado", "Idaho", "Montana", "New Mexico", "Utah"])
        self.assertEqual(got["countries"], ["Canada", "United States"])
        self.assertEqual(got["photos"], {"total": 7, "inferred": 2})
        self.assertEqual(got["kinds"], {**NO_KINDS, "flight": 2, "hotel": 3, "car": 1})

    def test_hidden_photos_count_only_for_their_person(self):
        trip = self.full_trip()
        got = self.summary(trip, self.sam)
        self.assertEqual(got["photos"], {"total": 7, "inferred": 1})
        self.assertEqual(got["countries"], ["Canada", "Mexico", "United States"])
        self.assertEqual(got["states"], ["Colorado", "Idaho", "Montana", "Utah"])

    def test_cancelled_bookings_count_for_nothing(self):
        trip = self.mine(VANCOUVER)["trip_id"]
        self.mine(CANCELLED_FLIGHT, trip)
        got = self.summary(trip)
        self.assertEqual((got["days"], got["nights"], got["distance_km"], got["flight_km"], got["road_km"]), (0, 0, 0.0, 0.0, 0.0))
        self.assertEqual((got["states"], got["countries"], got["kinds"]), ([], [], NO_KINDS))

    def test_a_stay_in_a_town_the_airport_table_lacks_still_adds_its_address_country(self):
        small_town = {**NOWHERE, "details": {"address": "5 Example Road, Examplesville, ID 83201"}}
        got = self.summary(self.mine(small_town)["trip_id"])
        self.assertEqual((got["states"], got["countries"]), (["Idaho"], ["United States"]))

    def test_two_reservations_for_one_flight_count_its_distance_once(self):
        flight = {**SFO_DEN, "details": {"flight_number": "UA 100"}}
        trip = self.mine({**flight, "confirmation": "ABC123"})["trip_id"]
        self.mine({**flight, "confirmation": "XYZ789"}, trip)
        got = self.summary(trip)
        self.assertAlmostEqual(got["flight_km"], self.great_circle(("SFO", "DEN")), delta=0.1)
        self.assertEqual(got["kinds"]["flight"], 2)

    def test_a_highway_drive_is_measured_along_the_road(self):
        trip = self.mine(DENVER)["trip_id"]
        self.mine(SALT_LAKE_DRIVE, trip)
        got = self.summary(trip)
        straight = stats.distance_km((39.75, -104.99), (40.76, -111.89))
        self.assertFalse(got["road_estimated"])
        self.assertGreater(got["road_km"], straight)
        self.assertLess(got["road_km"], 2.5 * straight)
        self.assertEqual(got["distance_km"], got["road_km"])

    def test_a_short_hop_with_no_highway_is_a_straight_line_and_estimated(self):
        trip = self.mine(DENVER)["trip_id"]
        self.mine(BOULDER, trip)
        segs = {s["destination"]: s for s in trips.get(self.c, self.jane, trip)["segments"]}
        self.assertEqual(set(segs), {"Denver", "Boulder"})
        got = self.summary(trip)
        self.assertTrue(got["road_estimated"])
        self.assertGreater(got["road_km"], 10)
        self.assertLess(got["road_km"], 60)
        self.assertEqual(got["states"], ["Colorado"])
        self.assertEqual(got["countries"], ["United States"])

    def test_a_flight_between_stays_breaks_the_drive(self):
        trip = self.mine(DENVER)["trip_id"]
        self.mine({**SFO_DEN, "start_local": "2026-06-03T12:00", "end_local": "2026-06-03T15:00", "origin": "DEN", "destination": "SLC"}, trip)
        self.mine(SALT_LAKE_DRIVE, trip)
        got = self.summary(trip)
        self.assertEqual((got["road_km"], got["road_estimated"]), (0.0, False))
        self.assertAlmostEqual(got["flight_km"], self.great_circle(("DEN", "SLC")), delta=0.1)

    def test_visits_add_their_country_and_state(self):
        trip = self.mine({"kind": "visit", "destination": "us", "start_local": "2006-04-02T00:00", "end_local": "2006-04-05T00:00",
                          "details": {"state": "ak"}})["trip_id"]
        self.mine({"kind": "visit", "destination": "jp", "start_local": "2006-04-06T00:00", "end_local": "2006-04-08T00:00"}, trip)
        got = self.summary(trip)
        self.assertEqual(got["states"], ["Alaska"])
        self.assertEqual(got["countries"], ["Japan", "United States"])
        self.assertEqual((got["days"], got["nights"], got["kinds"]["visit"]), (7, 0, 2))

    def test_a_trip_with_no_placed_booking_has_zeros_and_empty_lists(self):
        trip = self.mine(NOWHERE)["trip_id"]
        got = self.summary(trip)
        self.assertEqual((got["distance_km"], got["flight_km"], got["road_km"], got["road_estimated"]), (0.0, 0.0, 0.0, False))
        self.assertEqual((got["states"], got["countries"], got["photos"]), ([], [], {"total": 0, "inferred": 0}))
        self.assertEqual(got["nights"], 2)

    def test_a_dated_trip_with_no_bookings_keeps_its_days(self):
        trip = trips.create_trip(self.c, self.jane, {"name": "Cabin weekend", "start_date": "2026-07-01", "end_date": "2026-07-04"})["id"]
        self.assertEqual(self.summary(trip)["days"], 4)

    def test_an_accented_photo_country_is_the_same_country_as_its_plain_name(self):
        trip = self.mine({"kind": "visit", "destination": "mx", "start_local": "2026-07-01T00:00", "end_local": "2026-07-03T00:00"})["trip_id"]
        self.photo(self.library(self.jane.person_id), trip, None, "México")
        self.assertEqual(self.summary(trip)["countries"], ["Mexico"])

    def test_a_trip_with_no_bookings_is_all_zeros(self):
        trip = trips.create_trip(self.c, self.jane, {"name": "Cabin weekend"})["id"]
        self.assertEqual(self.summary(trip), {"days": 0, "nights": 0, "distance_km": 0.0, "flight_km": 0.0, "road_km": 0.0, "road_estimated": False,
                                              "states": [], "countries": [], "photos": {"total": 0, "inferred": 0}, "kinds": NO_KINDS})

    def test_someone_not_on_the_trip_gets_nothing(self):
        trip = self.add(self.jane, DENVER, None, self.on(self.jane.person_id))["trip_id"]
        self.assertIsNone(tripstats.summary(self.c, self.sam, trip))
        self.assertIsNone(tripstats.summary(self.c, self.jane, 99999))


if __name__ == "__main__":
    unittest.main()
