import unittest

from waypoint.domain.mail.places import zone_of


class PlaceZoneTests(unittest.TestCase):
    def test_an_airport_code_names_its_airports_zone(self):
        for text, zone in (("San Francisco Airport (SFO)", "America/Los_Angeles"), ("SFO", "America/Los_Angeles"),
                           ("SFO - San Francisco", "America/Los_Angeles"), ("LAX Airport", "America/Los_Angeles"),
                           ("Airport ZRH", "Europe/Zurich"), ("Lisboa (LIS)", "Europe/Lisbon")):
            with self.subTest(text):
                self.assertEqual(zone_of(text), zone)

    def test_a_country_or_a_word_that_happens_to_be_a_code_is_not_an_airport(self):
        self.assertIsNone(zone_of("Hotel THE Central"))
        self.assertIsNone(zone_of("Miami (USA)"))

    def test_codes_that_disagree_name_no_zone(self):
        self.assertIsNone(zone_of("Transfer (SFO) to (JFK)"))

    def test_a_city_name_gives_the_zone_when_only_one_can_be_meant(self):
        for text, zone in (("Zurich HB", "Europe/Zurich"), ("Milan Centrale", "Europe/Rome"), ("Paris Gare de Lyon", "Europe/Paris"),
                           ("Lyon Part-Dieu", "Europe/Paris"), ("Port of Southampton", "Europe/London"), ("London", "Europe/London"),
                           ("Rome", "Europe/Rome"), ("Cologne", "Europe/Berlin"), ("Tokyo Station", "Asia/Tokyo")):
            with self.subTest(text):
                self.assertEqual(zone_of(text), zone)

    def test_an_american_city_needs_a_state_or_country_to_be_believed(self):
        for text, zone in (("Boston", None), ("Venice", None), ("Dallas", None), ("Miami", None), ("Boston, MA", "America/New_York"),
                           ("Galveston, TX", "America/Chicago"), ("Seattle, WA", "America/Los_Angeles"), ("Venice, FL", "America/New_York"),
                           ("Miami, FL", "America/New_York"), ("Miami, OK", "America/Chicago"), ("Portland, ME", "America/New_York"),
                           ("Portland, OR", "America/Los_Angeles"), ("Portland", None), ("Paris, USA", "America/Chicago"), ("London, KY", "America/New_York")):
            with self.subTest(text):
                self.assertEqual(zone_of(text), zone)

    def test_a_named_country_keeps_a_namesake_out(self):
        self.assertEqual(zone_of("London, Canada"), "America/Toronto")
        self.assertEqual(zone_of("Southampton, UK"), "Europe/London")
        self.assertIsNone(zone_of("Venice, Italy"))
        self.assertIsNone(zone_of("Paris, France, USA"))

    def test_places_that_cannot_be_told_apart_or_are_unknown_have_no_zone(self):
        for text in ("Somewhere Plaza", "Springfield", "Union Station", "Central", "", "Zurich HB to Paris"):
            with self.subTest(text):
                self.assertIsNone(zone_of(text))
