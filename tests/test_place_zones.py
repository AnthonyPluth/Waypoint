"""The time zone of a stay from its address (waypoint/domain/place_zones.py): read from the text alone, never looked up. All
addresses are made up; the state, ZIP and city names are real so the rules have something to settle."""
from tests.shared import DbCase
from waypoint.domain import place_zones


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
        for address, zone in (("100 King St W, Toronto, ON M5X 1A9", "America/Toronto"), ("1 Granville St, Vancouver, British Columbia", "America/Vancouver"),
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

    def test_a_two_letter_word_is_not_a_state_unless_it_stands_where_a_state_does(self):
        self.assertIsNone(self.zone("Unit 4 IN the back, 12 Road"))
        self.assertEqual(self.zone("12 Road, Chicago, IL 60601"), "America/Chicago")
