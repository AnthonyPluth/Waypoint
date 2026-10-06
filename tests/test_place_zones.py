"""The time zone of a stay from its address (waypoint/domain/place_zones.py): read from the text alone, never looked up. All
addresses are made up; the state, ZIP and city names are real so the rules have something to settle."""
import unittest

from tests.shared import DbCase
from waypoint.domain import place_zones


class Tables(unittest.TestCase):
    def test_every_state_has_zip_prefixes_and_its_exceptions_are_among_them(self):
        self.assertEqual(set(place_zones.US_STATES), set(place_zones.ZIP_RANGES))
        for state, (_zone, exceptions) in place_zones.US_STATES.items():
            for prefix in exceptions:
                with self.subTest(state=state, prefix=prefix):
                    self.assertTrue(place_zones._zip_in_state(state, prefix))   # (a typo in either table fails here)

    def test_no_two_states_claim_the_same_zip_prefix_except_where_they_really_overlap(self):
        owners: dict[int, list[str]] = {}
        for state in place_zones.ZIP_RANGES:
            for n in range(1000):
                if place_zones._zip_in_state(state, f"{n:03d}"):
                    owners.setdefault(n, []).append(state)
        shared = {n: s for n, s in owners.items() if len(s) > 1}
        self.assertEqual(shared, {}, "a ZIP prefix in two states' ranges")


class AddressZones(DbCase):
    def zone(self, address):
        return place_zones.zone_for_address(self.c, address)

    def test_a_us_state_with_one_zone_settles_it(self):
        for address, zone in (("1 Ocean Ave, Honolulu, HI 96815", "Pacific/Honolulu"), ("9 Elm St, Phoenix, AZ 85001", "America/Phoenix"),
                              ("5 Pine Rd, Boston, MA 02108", "America/New_York"), ("8 Oak Ln, Denver, CO 80202", "America/Denver"),
                              ("5 Elm, Dallas, Texas 75201", "America/Chicago"), ("2 Bay St, Seattle WA 98101", "America/Los_Angeles")):
            with self.subTest(address=address):
                self.assertEqual(self.zone(address), zone)

    def test_a_state_that_spans_zones_is_settled_by_the_zip_prefix(self):
        for address, zone in (("12 Main St, Pensacola, FL 32501", "America/Chicago"), ("12 Main St, Miami, FL 33101", "America/New_York"),
                              ("9 Calle, El Paso, TX 79901", "America/Denver"), ("3 Lake Rd, Gary, IN 46402", "America/Chicago"),
                              ("3 Lake Rd, Indianapolis, IN 46204", "America/New_York"), ("7 Hill, Paducah, KY 42001", "America/Chicago"),
                              ("7 Hill, Louisville, KY 40202", "America/New_York"), ("4 Peak Rd, Knoxville, TN 37902", "America/New_York"),
                              ("4 Peak Rd, Nashville, TN 37201", "America/Chicago"), ("6 Bay, Lewiston, ID 83501", "America/Los_Angeles"),
                              ("6 Bay, Boise, ID 83702", "America/Boise"), ("2 Dune, Detroit, MI 48201", "America/New_York")):
            with self.subTest(address=address):
                self.assertEqual(self.zone(address), zone)

    def test_a_state_whose_zones_split_mid_state_is_left_to_the_person_unless_a_city_settles_it(self):
        self.assertIsNone(self.zone("1 Farm Rd, Smalltown, ND 58001"))   # (nothing here says which)
        self.assertIsNone(self.zone("1 Farm Rd, Smalltown, KS 66001"))

    def test_canadian_provinces_and_countries_with_one_zone(self):
        for address, zone in (("100 King St W, Toronto, ON M5X 1A9", "America/Toronto"), ("1 Granville St, Vancouver, BC V6C 1A1", "America/Vancouver"),
                              ("10 Rue de Rivoli, Paris, France", "Europe/Paris"), ("221B Baker St, London, UK", "Europe/London"),
                              ("1-1 Marunouchi, Tokyo, Japan", "Asia/Tokyo")):
            with self.subTest(address=address):
                self.assertEqual(self.zone(address), zone)

    def test_a_country_with_several_zones_and_no_other_hint_is_left_to_the_person(self):
        self.assertIsNone(self.zone("1 Beach Rd, Somewhere, Australia"))
        self.assertIsNone(self.zone("12 Calle, Algun Lugar, Mexico"))

    def test_a_city_the_airport_list_knows_by_one_zone_settles_it(self):
        self.assertEqual(self.zone("Hotel Foo, 3 Strand, Sydney, Australia"), "Australia/Sydney")
        self.assertIsNone(self.zone("Hotel Foo, 3 Strand, Sydney"))   # (a name that is also another country's city settles nothing)

    def test_nothing_to_go_on_is_none(self):
        for address in (None, "", "   ", "Hotel Foo, 1 Road", "1 Road"):
            with self.subTest(address=address):
                self.assertIsNone(self.zone(address))

    def test_a_bare_two_letter_code_is_not_a_us_state_unless_the_address_says_it_is_in_the_us(self):
        for address in ("10115 Berlin, DE", "Bogotá, CO", "Tel Aviv, IL", "Buenos Aires, AR", "Mumbai, IN", "Lima, PE", "Amsterdam, NL", "Kigali, MA"):
            with self.subTest(address=address):
                self.assertNotIn(self.zone(address), ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Toronto", "America/Halifax"))
        self.assertIsNone(self.zone("Berlin, DE"))   # (nothing here says which country: better none than a US zone)
        self.assertEqual(self.zone("1 Ocean Ave, Honolulu, HI, USA"), "Pacific/Honolulu")   # (the address says it is in the US)
        self.assertEqual(self.zone("1 Ocean Ave, Honolulu, Hawaii, United States"), "Pacific/Honolulu")
        self.assertIsNone(self.zone("Somewhere, Georgia"))   # (the country or the state: it doesn't say)

    def test_a_state_and_zip_must_agree_when_no_country_is_named(self):
        for address in ("Berlin, DE 10115", "Casablanca, MA 20000", "Jakarta, ID 10110", "Panama, PA 08001"):
            with self.subTest(address=address):
                self.assertFalse((self.zone(address) or "").startswith("America/"), address)   # (never a US zone for them)
        self.assertIsNone(self.zone("Smalltown, DE 10115"))
        self.assertEqual(self.zone("12 Main St, Dover, DE 19901"), "America/New_York")
        self.assertEqual(self.zone("12 Main St, Boise, ID 83702"), "America/Boise")

    def test_places_where_a_split_state_mixes_zones_are_left_to_the_person(self):
        for address in ("1 Bay Rd, Smalltown, FL 32456", "1 Main St, Smalltown, KY 42701", "9 Oak, Smalltown, KY 42501", "9 Oak, Smalltown, TN 37388", "2 Pine, Smalltown, MI 49855"):
            with self.subTest(address=address):
                self.assertIsNone(self.zone(address))   # (a ZIP prefix that mixes zones, and no city the airport list knows)
        self.assertEqual(self.zone("1 Main St, Elizabethtown, KY 42701"), "America/New_York")   # (a city it knows settles it)
        self.assertEqual(self.zone("9 Oak, Tullahoma, TN 37388"), "America/Chicago")
        self.assertEqual(self.zone("9 Oak, Paducah, KY 42001"), "America/Chicago")
        self.assertEqual(self.zone("9 Oak, Pensacola, FL 32501"), "America/Chicago")
        self.assertEqual(self.zone("9 Oak, Chattanooga, TN 37402"), "America/New_York")

    def test_a_province_needs_a_canadian_postal_code_or_canada(self):
        self.assertEqual(self.zone("1 King St, Toronto, ON M5X 1A9"), "America/Toronto")
        self.assertEqual(self.zone("5 Rue X, Somewhere, QC J2A 1B1"), "America/Toronto")
        self.assertEqual(self.zone("5 Rue X, Somewhere, AB, Canada"), "America/Edmonton")
        self.assertIsNone(self.zone("5 Rue X, Somewhere, QC, Canada"))   # (QC's Îles-de-la-Madeleine are on Atlantic time: a postal code decides)
        self.assertIsNone(self.zone("1 Lakeshore Rd, Smalltown, ON P7B 1A1"))   # (northern Ontario spans zones)
        self.assertIsNone(self.zone("1 Main St, Smalltown, BC V1C 1A1"))   # (the East Kootenay is on Mountain time)
        self.assertEqual(self.zone("1 Main St, Cranbrook, BC V1C 1A1"), "America/Edmonton")   # (a city the airport list knows)
        self.assertEqual(self.zone("1 Granville St, Vancouver, BC V6C 1A1"), "America/Vancouver")
        self.assertIsNone(self.zone("5 Straat, Somewhere, NL"))

    def test_a_two_letter_word_is_not_a_state_unless_it_stands_where_a_state_does(self):
        self.assertIsNone(self.zone("Unit 4 IN the back, 12 Road"))
        self.assertEqual(self.zone("12 Road, Chicago, IL 60601"), "America/Chicago")
