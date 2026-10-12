import socket
import unittest
from datetime import UTC, datetime
from unittest import mock

from sqlalchemy import select

from waypoint.domain import stats, trips
from waypoint.domain.visibility import Viewer
from waypoint.storage import geocode, reference
from waypoint.storage.models import Segment
from tests.privacy import no_leaks
from tests.test_trips import Household

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
STAY = {"kind": "hotel", "origin": "Quay Inn", "destination": "Boulder", "provider": "Example Hotels",
        "start_local": "2026-06-02T15:00", "end_local": "2026-06-08T10:00", "start_zone": "America/Denver", "end_zone": "America/Denver",
        "details": {"address": "100 Pearl Street, Boulder, CO 80302"}}
CAR = {"kind": "car", "origin": "SFO airport", "destination": "SFO airport", "provider": "Example Rentals",
       "start_local": "2026-07-03T09:00", "end_local": "2026-07-05T09:00", "start_zone": "America/Los_Angeles", "end_zone": "America/Los_Angeles"}
FLIGHT = {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-06-01T19:00", "end_local": "2026-06-02T07:10"}


class LookupTests(unittest.TestCase):
    def test_a_us_zip_in_an_address_is_a_zip_centre(self):
        got = geocode.locate("hotel", "Quay Inn", "Boulder", "100 Pearl Street, Boulder, CO 80302")
        assert got is not None
        self.assertEqual(got.precision, "zip")
        self.assertAlmostEqual(got.latitude, 40.0, delta=0.15)
        self.assertAlmostEqual(got.longitude, -105.3, delta=0.15)

    def test_a_zip_with_a_plus_four_or_alone_after_the_country_is_found_and_a_street_number_is_not_one(self):
        zip_plus = geocode.locate("hotel", None, None, "100 Pearl Street, Boulder, CO 80302-1234")
        alone = geocode.locate("hotel", None, None, "100 Pearl Street, Boulder, 80302, USA")
        assert zip_plus is not None and alone is not None
        self.assertEqual((zip_plus.precision, alone.precision), ("zip", "zip"))
        self.assertEqual((zip_plus.latitude, zip_plus.longitude), (alone.latitude, alone.longitude))
        street = geocode.locate("hotel", None, None, "12345 Main Street, USA")
        self.assertIsNone(street)

    def test_canadian_and_british_postcodes(self):
        ca = geocode.locate("hotel", None, "Toronto", "100 King Street West, Toronto, ON M5X 1A9, Canada")
        gb = geocode.locate("hotel", None, "London", "10 High Street, London SW1A 1AA, UK")
        assert ca is not None and gb is not None
        self.assertEqual((ca.precision, gb.precision), ("zip", "zip"))
        self.assertAlmostEqual(ca.latitude, 43.65, delta=0.2)
        self.assertAlmostEqual(gb.latitude, 51.5, delta=0.2)
        self.assertAlmostEqual(gb.longitude, -0.13, delta=0.2)

    def test_a_city_with_no_address_is_a_city_centre(self):
        got = geocode.locate("hotel", "Quay Inn", "Boulder", None)
        assert got is not None
        self.assertEqual(got.precision, "city")
        self.assertAlmostEqual(got.latitude, 40.015, delta=0.05)

    def test_a_city_name_shared_by_places_of_alike_size_is_not_guessed_but_a_state_or_country_decides(self):
        self.assertIsNone(geocode.locate("hotel", None, "Springfield", None))
        illinois = geocode.locate("hotel", None, "Springfield, IL", None)
        missouri = geocode.locate("hotel", None, "Springfield", "1 Elm Street, Springfield, MO")
        assert illinois is not None and missouri is not None
        self.assertNotEqual((illinois.latitude, illinois.longitude), (missouri.latitude, missouri.longitude))
        self.assertAlmostEqual(illinois.latitude, 39.8, delta=0.2)
        self.assertAlmostEqual(missouri.latitude, 37.2, delta=0.2)

    def test_the_largest_place_of_a_name_wins_when_it_is_far_larger_and_the_country_narrows_it(self):
        paris = geocode.locate("hotel", None, "Paris", None)
        assert paris is not None
        self.assertAlmostEqual(paris.latitude, 48.85, delta=0.1)
        texas = geocode.locate("hotel", None, "Paris", "1 Main Street, Paris, TX")
        assert texas is not None
        self.assertAlmostEqual(texas.latitude, 33.7, delta=0.3)

    def test_a_city_in_an_address_with_a_leading_postal_code_is_found(self):
        got = geocode.locate("hotel", None, None, "5 Rue de Exemple, 75001 Paris, France")
        assert got is not None
        self.assertEqual(got.precision, "city")
        self.assertAlmostEqual(got.longitude, 2.35, delta=0.1)

    def test_a_car_at_an_airport_is_an_airport_point_by_code_or_by_words(self):
        by_words = geocode.locate("car", "SFO airport", None, None)
        by_code = geocode.locate("car", "SFO", "SFO", None)
        assert by_words is not None and by_code is not None
        self.assertEqual((by_words.precision, by_code.precision), ("airport", "airport"))
        self.assertAlmostEqual(by_words.latitude, 37.62, delta=0.05)
        self.assertEqual((by_words.latitude, by_words.longitude), (by_code.latitude, by_code.longitude))

    def test_a_train_is_located_at_its_arrival_and_a_cruise_at_its_port(self):
        train = geocode.locate("train", "Boulder", "Denver", None)
        cruise = geocode.locate("cruise", "Miami, FL", "Nassau", None)
        assert train is not None and cruise is not None
        self.assertAlmostEqual(train.latitude, 39.74, delta=0.1)
        self.assertAlmostEqual(cruise.latitude, 25.77, delta=0.1)

    def test_alaska_stays_rentals_and_trains_are_placed_by_zip_state_or_town(self):
        zip_hotel = geocode.locate("hotel", "Harbour Inn", "Anchorage", "1 Quay Street, Anchorage, AK 99501")
        state_hotel = geocode.locate("hotel", "Harbour Inn", None, "1 Quay Street, Anchorage, AK")
        car = geocode.locate("car", "Example Rentals", "Fairbanks", None)
        seward = geocode.locate("car", "Example Rentals", "Seward", None)
        train = geocode.locate("train", "Anchorage", "Fairbanks", None)
        assert zip_hotel is not None and state_hotel is not None and car is not None and seward is not None and train is not None
        self.assertEqual(zip_hotel.precision, "zip")
        for point in (zip_hotel, state_hotel, car, seward, train):
            self.assertGreater(point.latitude, 59.0)
            self.assertLess(point.longitude, -145.0)

    def test_a_port_of_call_is_placed_by_name_and_one_that_is_unknown_or_shared_is_left_out(self):
        for name, lat in (("Juneau", 58.3), ("Skagway", 59.46), ("Ketchikan", 55.34), ("Sitka, Alaska", 57.05)):
            got = geocode.locate_port(name)
            assert got is not None
            self.assertAlmostEqual(got.latitude, lat, delta=0.1)
        for name in ("Nowhere Bay", "Whittier", "", "  "):
            self.assertIsNone(geocode.locate_port(name))

    def test_a_visit_with_a_state_is_placed_inside_that_state_and_without_one_at_the_country(self):
        alaska = geocode.locate("visit", None, "US", None, "ak")
        country = geocode.locate("visit", None, "US", None)
        assert alaska is not None and country is not None
        self.assertEqual((alaska.latitude, alaska.longitude), reference.us_state_points()["AK"])
        self.assertAlmostEqual(alaska.latitude, 61.2, delta=0.1)
        self.assertNotEqual((alaska.latitude, alaska.longitude), (country.latitude, country.longitude))
        self.assertEqual(geocode.locate("visit", None, "JP", None, "AK"), geocode.locate("visit", None, "JP", None))
        self.assertEqual(set(reference.us_state_points()), set(geocode.US_STATES))

    def test_a_flight_and_a_place_that_cannot_be_read_have_no_point(self):
        self.assertIsNone(geocode.locate("flight", "JFK", "LHR", "1 Main Street, Boulder, CO 80302"))
        self.assertIsNone(geocode.locate("hotel", "Quay Inn", "Nowhereville", None))
        self.assertIsNone(geocode.locate("hotel", None, None, None))
        self.assertIsNone(geocode.locate("hotel", "Quay Inn", "  ", "  "))

    def test_a_zip_that_is_not_in_the_data_falls_back_to_the_city(self):
        got = geocode.locate("hotel", None, "Boulder", "1 Pearl Street, Boulder, CO 00001")
        assert got is not None
        self.assertEqual(got.precision, "city")

    def test_the_data_is_bundled_and_nothing_opens_a_connection(self):
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("network")):
            self.assertIsNotNone(geocode.locate("hotel", None, "Boulder", "1 Pearl Street, Boulder, CO 80302"))
        self.assertGreater(len(reference.postal_points()), 30000)
        self.assertGreater(len(reference.city_points()), 20000)


class SaveTests(Household):
    def seg(self, got):
        return self.c.orm.get(Segment, got["id"])

    def where(self, got):
        s = self.seg(got)
        return (s.latitude, s.longitude, s.geo_precision)

    def test_a_stay_added_by_hand_is_located_from_its_address(self):
        got = self.add(self.jane, STAY, None, self.on(self.jane.person_id))
        lat, lon, how = self.where(got)
        self.assertEqual(how, "zip")
        self.assertAlmostEqual(lat, 40.0, delta=0.15)
        self.assertAlmostEqual(lon, -105.3, delta=0.15)

    def test_a_flight_has_no_stored_point_and_a_stay_it_cannot_read_has_none(self):
        flight = self.add(self.jane, FLIGHT, None, self.on(self.jane.person_id))
        stay = self.add(self.jane, {**STAY, "destination": "Nowhereville", "details": {}}, None, self.on(self.jane.person_id))
        self.assertEqual(self.where(flight), (None, None, None))
        self.assertEqual(self.where(stay), (None, None, None))

    def test_a_car_at_an_airport_is_located(self):
        got = self.add(self.jane, CAR, None, self.on(self.jane.person_id))
        self.assertEqual(self.where(got)[2], "airport")

    def test_editing_the_address_relocates_and_clearing_it_falls_back_to_the_city_and_then_to_nothing(self):
        got = self.add(self.jane, STAY, None, self.on(self.jane.person_id))
        first = self.where(got)
        trips.edit_segment(self.c, self.jane, got["id"], {"details": {"address": "1 Elm Street, Austin, TX 78701"}})
        moved = self.where(got)
        self.assertEqual(moved[2], "zip")
        self.assertNotEqual(moved[:2], first[:2])
        self.assertAlmostEqual(moved[0], 30.27, delta=0.1)
        trips.edit_segment(self.c, self.jane, got["id"], {"details": {}})
        self.assertEqual(self.where(got)[2], "city")
        self.assertAlmostEqual(self.where(got)[0], 40.015, delta=0.05)
        trips.edit_segment(self.c, self.jane, got["id"], {"destination": "Nowhereville"})
        self.assertEqual(self.where(got), (None, None, None))

    def test_editing_something_else_keeps_the_point(self):
        got = self.add(self.jane, STAY, None, self.on(self.jane.person_id))
        before = self.where(got)
        trips.edit_segment(self.c, self.jane, got["id"], {"provider": "Other Hotels"})
        self.assertEqual(self.where(got), before)

    def test_an_email_adds_a_located_booking_and_a_later_email_with_an_address_locates_one_without(self):
        bare = {**STAY, "confirmation": "ABCD1234", "details": {}}
        added: list[int] = []
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, bare, touched=added), "added")
        seg = self.c.orm.get(Segment, added[0])
        self.assertEqual(seg.geo_precision, "city")
        later: list[int] = []
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, {**STAY, "confirmation": "ABCD1234"}, touched=later), "updated")
        self.assertEqual(later, added)
        self.c.orm.refresh(seg)
        self.assertEqual(seg.geo_precision, "zip")

    def test_an_email_that_changes_the_address_moves_the_point(self):
        added: list[int] = []
        trips.merge_email_segment(self.c, self.jane, {**STAY, "confirmation": "ABCD1234"}, touched=added)
        seg = self.c.orm.get(Segment, added[0])
        trips.merge_email_segment(self.c, self.jane, {**STAY, "confirmation": "ABCD1234",
                                                     "details": {"address": "9 Elm Street, Boulder, CO 80301"}})
        self.c.orm.refresh(seg)
        self.assertEqual(seg.geo_precision, "zip")
        self.assertEqual((seg.latitude, seg.longitude), tuple(reference.postal_points()[("US", "80301")]))

    def test_a_filled_in_email_keeps_an_address_set_by_hand(self):
        got = self.add(self.jane, {**STAY, "confirmation": "ABCD1234"}, None, self.on(self.jane.person_id))
        before = self.where(got)
        trips.merge_email_segment(self.c, self.jane, {**STAY, "confirmation": "ABCD1234", "details": {"address": "9 Elm Street, Boulder, CO 80301"}},
                                  fill_only=True)
        self.assertEqual(self.where(got), before)

    def test_moving_merging_and_splitting_keep_the_point(self):
        a = self.add(self.jane, STAY, None, self.on(self.jane.person_id))
        b = self.add(self.jane, {**FLIGHT, "start_local": "2026-02-01T19:00", "end_local": "2026-02-02T07:10"}, None, self.on(self.jane.person_id))
        before = self.where(a)
        self.assertNotEqual(a["trip_id"], b["trip_id"])
        trips.move_segment(self.c, self.jane, a["id"], b["trip_id"])
        self.assertEqual(self.where(a), before)
        trips.split(self.c, self.jane, b["trip_id"], [a["id"]])
        self.assertEqual(self.where(a), before)
        trip = trips.get_segment(self.c, self.jane, a["id"])
        assert trip is not None
        trips.merge(self.c, self.jane, b["trip_id"], trip["trip_id"])
        self.assertEqual(self.where(a), before)


class StatsPinTests(Household):
    def pins(self, who=None):
        got = stats.compute(self.c, who or self.jane, None, None, NOW)
        assert got is not None
        return got["stays"]["pins"]

    def test_a_stay_with_a_stored_zip_is_pinned_there_and_another_zip_in_the_city_is_its_own_pin(self):
        self.add(self.jane, STAY, None, self.on(self.jane.person_id))
        self.add(self.jane, {**STAY, "origin": "Other Inn", "start_local": "2026-08-02T15:00", "end_local": "2026-08-04T10:00",
                             "details": {"address": "1 Walnut Street, Boulder, CO 80301"}}, None, self.on(self.jane.person_id))
        got = self.pins()
        self.assertEqual({(p["city"], p["stays"]) for p in got}, {("Boulder", 1)})
        self.assertEqual(len(got), 2)
        self.assertEqual({(p["latitude"], p["longitude"]) for p in got},
                         {tuple(reference.postal_points()[("US", z)]) for z in ("80302", "80301")})

    def test_two_stays_in_one_zip_are_one_pin(self):
        self.add(self.jane, STAY, None, self.on(self.jane.person_id))
        self.add(self.jane, {**STAY, "start_local": "2026-08-02T15:00", "end_local": "2026-08-04T10:00"}, None, self.on(self.jane.person_id))
        (pin,) = self.pins()
        self.assertEqual((pin["stays"], pin["nights"]), (2, 8))

    def test_a_stay_in_a_city_with_an_airport_and_no_address_keeps_the_airport_city_pin(self):
        self.add(self.jane, {**STAY, "destination": "London", "details": {}, "start_zone": "Europe/London", "end_zone": "Europe/London"},
                 None, self.on(self.jane.person_id))
        (pin,) = self.pins()
        self.assertEqual((pin["city"], pin["country"]), ("London", "GB"))

    def test_a_stay_in_a_town_with_no_airport_is_pinned_by_its_stored_point(self):
        self.add(self.jane, {**STAY, "destination": "Longmont", "details": {}},
                 None, self.on(self.jane.person_id))
        (pin,) = self.pins()
        self.assertEqual(pin["city"], "Longmont")
        self.assertIsNone(pin["country"])
        self.assertAlmostEqual(pin["latitude"], 40.17, delta=0.1)

    def test_a_pin_carries_no_one_s_name_and_a_stranger_sees_none(self):
        canary_name, canary_code = "Quentin Marlowe-Zzyx", "ZQXW7413"
        with no_leaks(self, canary_name, canary_code):
            self.add(self.jane, {**STAY, "confirmation": canary_code}, None,
                     [{"person_id": None, "name": canary_name}, {"person_id": self.jane.person_id, "name": None}])
            got = stats.compute(self.c, self.jane, None, None, NOW)
            assert got is not None
            self.assertEqual(len(got["stays"]["pins"]), 1)
            self.assertEqual(set(got["stays"]["pins"][0]), {"city", "country", "latitude", "longitude", "stays", "nights", "trips"})
            self.assertNotIn(canary_name, repr(got))
            self.assertNotIn(canary_code, repr(got))
            self.assertEqual(self.pins(Viewer(self.mia)), [])

    def test_a_cancelled_stay_has_no_pin(self):
        self.add(self.jane, {**STAY, "status": "cancelled"}, None, self.on(self.jane.person_id))
        self.assertEqual(self.pins(), [])

    def test_the_stored_columns_are_not_part_of_a_booking_reply(self):
        got = self.add(self.jane, STAY, None, self.on(self.jane.person_id))
        self.assertFalse({"latitude", "longitude", "geo_precision"} & set(got))
        self.assertIsNotNone(self.c.execute(select(Segment.latitude).where(Segment.id == got["id"])).scalar())


if __name__ == "__main__":
    unittest.main()
