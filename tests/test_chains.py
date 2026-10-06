import unittest

from waypoint.domain import chains


class HotelChainTests(unittest.TestCase):
    def test_a_brand_in_the_hotels_name_gives_its_chain_whoever_sold_the_stay(self):
        for provider, hotel, chain in (
            ("Capital One Travel", "The Westin Example City", "Marriott"),
            ("Hotwire", "Courtyard by Marriott Example City", "Marriott"),
            ("Expedia", "Grand Hyatt Example City", "Hyatt"),
            ("Booking.com", "Hampton Inn & Suites Example City", "Hilton"),
            ("Hyatt", "Hyatt Place Example City", "Hyatt"),
            (None, "Holiday Inn Express Example City", "IHG"),
            ("Costco Travel", "Le Méridien Example City", "Marriott"),
            ("Priceline", "W Example City", None),
        ):
            self.assertEqual(chains.hotel_chain(provider, hotel), chain, f"{provider} / {hotel}")

    def test_a_provider_that_is_the_chain_is_kept(self):
        self.assertEqual(chains.hotel_chain("Hilton", "Example Harbour Hotel"), "Hilton")
        self.assertEqual(chains.hotel_chain("Example Hotels", "Harbour Hotel"), "Example Hotels")

    def test_a_booking_site_is_not_a_chain_and_neither_is_a_hotel_that_is_in_none(self):
        self.assertIsNone(chains.hotel_chain("Capital One Travel", "Harbour Hotel"))
        self.assertIsNone(chains.hotel_chain("Hotwire", None))
        self.assertIsNone(chains.hotel_chain("Harbour Hotel", "Harbour Hotel"))
        self.assertIsNone(chains.hotel_chain(None, "Harbour Hotel"))

    def test_rental_platforms_stay_as_they_are_named(self):
        self.assertEqual(chains.hotel_chain("Airbnb", "Cosy flat near the quay"), "Airbnb")
        self.assertEqual(chains.hotel_chain("Vrbo", "Lake house"), "VRBO")

    def test_a_word_inside_another_is_not_a_brand(self):
        self.assertIsNone(chains.hotel_chain(None, "Hiltonia Guest House"))
        self.assertIsNone(chains.hotel_chain(None, "Hamptons Guest House"))

    def test_a_generic_word_alone_is_not_a_brand(self):
        for hotel in ("The Courtyard Guest House", "Old Country Inn", "Signia Lodge", "Moxy Cottage"):
            self.assertIsNone(chains.hotel_chain(None, hotel), hotel)
        self.assertEqual(chains.hotel_chain(None, "Courtyard by Marriott Example City"), "Marriott")
        self.assertEqual(chains.hotel_chain(None, "Country Inn Suites Example City"), "Radisson")


class CleanTests(unittest.TestCase):
    def test_the_booking_site_and_number_in_brackets_are_dropped(self):
        self.assertEqual(chains.clean("Hertz (booked via Hotwire 1234567890)"), "Hertz")
        self.assertEqual(chains.clean("Thrifty (booked via Hotwire 1234567891)"), "Thrifty")
        self.assertEqual(chains.clean("Sixt [via Costco Travel]"), "Sixt")

    def test_a_plain_name_is_kept_and_nothing_is_nothing(self):
        self.assertEqual(chains.clean("Budget"), "Budget")
        self.assertIsNone(chains.clean(""))
        self.assertIsNone(chains.clean(None))
        self.assertIsNone(chains.clean("(booked via Hotwire)"))
