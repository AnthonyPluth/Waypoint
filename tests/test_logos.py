import unittest
from datetime import UTC, datetime

from tests.shared import fetch
from tests.test_trips import HOTEL, OUT, RouteCase
from waypoint.domain import logos
from waypoint.storage import bundled_logos, db
from waypoint.storage.models import BrandLogo

PNG = b"\x89PNG\r\n\x1a\n" + b"made-up image bytes"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class BrandTests(unittest.TestCase):
    AIRLINES = {"EX": "Example Air"}

    def test_a_brand_is_the_provider_else_a_flights_airline(self):
        got = logos.brands_of([("hotel", "Harbour  Hotels", None), ("flight", None, "EX 101"), ("flight", "Other Air", "EX 101"),
                               ("flight", None, "ZZ9"), ("car", None, None), ("cruise", "Sea Line", None)], self.AIRLINES)
        self.assertEqual(got, ["Harbour Hotels", "Example Air", "Other Air", None, None, "Sea Line"])

    def test_a_hotel_is_asked_about_by_its_own_brand_first_without_the_rest_of_its_name(self):
        for hotel, brand in (("Hyatt Place Chicago River North", "Hyatt Place"), ("Hyatt Regency O'Hare", "Hyatt Regency"),
                             ("hyatt  regency chicago", "Hyatt Regency"), ("Courtyard Denver Downtown", "Courtyard by Marriott"),
                             ("Holiday Inn Express & Suites Reno", "Holiday Inn Express"), ("Holiday Inn Reno", "Holiday Inn"),
                             ("Hampton Inn Boston", "Hampton by Hilton"), ("The Westin Chicago River North", "Westin"),
                             ("Le Méridien Paris Etoile", "Le Méridien"), ("W Hotel Barcelona", "W Hotels"),
                             ("The Ritz-Carlton, Amelia Island", "The Ritz-Carlton"), ("Radisson Blu Edwardian", "Radisson Blu")):
            with self.subTest(hotel=hotel):
                self.assertEqual(logos.sub_brand(hotel), brand)
                self.assertEqual(logos.brands_of([("hotel", "Hyatt", None, hotel)], {}), [brand])
        for hotel in ("Harbour Hotel", "Hyatt", "Hyattsville Inn", "Placeholder Hyatt Place", "W Motel", "Glo Inn", "Vib Lodge",
                      "Thompson Street Inn", "Element Lodge", "Clarion Call Cottage", "Ibis Point Hotel", "Conrad Inn", "", None):
            with self.subTest(hotel=hotel):
                self.assertIsNone(logos.sub_brand(hotel))
                self.assertEqual(logos.brands_of([("hotel", "Hyatt", None, hotel)], {}), ["Hyatt"])
        self.assertEqual(logos.brands_of([("car", "Hertz", None, "Hyatt Place Chicago")], {}), ["Hertz"])

    def test_a_hotel_of_a_known_brand_falls_back_to_its_group_not_to_the_booking_site(self):
        self.assertEqual(logos._candidates("hotel", "Booking.com", None, "Hyatt Regency Chicago", {}), ["Hyatt Regency", "Hyatt"])
        self.assertEqual(logos._candidates("hotel", None, None, "Courtyard Denver", {}), ["Courtyard by Marriott", "Marriott"])
        self.assertEqual(logos._candidates("hotel", "Booking.com", None, "Harbour Hotel", {}), ["Booking.com"])
        self.assertEqual(logos._candidates("car", "Hertz", None, "Hyatt Regency Chicago", {}), ["Hertz"])

    def test_every_brand_has_a_group_and_each_start_is_listed_once(self):
        starts = [start for start, _ in logos.SUB_BRANDS]
        self.assertEqual(len(starts), len(set(starts)))
        for start, brand in logos.SUB_BRANDS:
            self.assertEqual(start, logos._plain(start), start)
            self.assertIn(logos.key(brand), logos.GROUP_OF, brand)
        self.assertEqual(logos.GROUP_OF[logos.key("Hyatt Regency")], "Hyatt")
        self.assertGreater(len(logos.SUB_BRANDS), 140)

    def test_a_chip_names_the_brand_without_its_group_tail(self):
        for brand, label in (("Courtyard by Marriott", "Courtyard"), ("Hyatt Regency", "Hyatt Regency"), ("Kimpton Hotels", "Kimpton"),
                             ("Bvlgari Hotels & Resorts", "Bvlgari"), ("Hampton by Hilton", "Hampton"), ("The Ritz-Carlton", "The Ritz-Carlton")):
            self.assertEqual(logos.chip_label(brand), label, brand)

    def test_a_hotel_shows_a_chip_only_when_the_logo_is_its_groups(self):
        self.assertEqual(logos.chip("hotel", "Hyatt Regency Chicago", "Hyatt"), "Hyatt Regency")
        self.assertIsNone(logos.chip("hotel", "Hyatt Regency Chicago", "Hyatt Regency"))
        self.assertIsNone(logos.chip("hotel", "Harbour Hotel", "Harbour Hotels"))
        self.assertIsNone(logos.chip("car", "Hyatt Regency Chicago", "Hertz"))
        self.assertIsNone(logos.chip("hotel", "Hyatt Regency Chicago", None))

    def test_a_provider_that_is_not_a_name_is_not_asked_about(self):
        for odd in ("", " ", "A", "12", "x" * 101):
            self.assertEqual(logos.brands_of([("hotel", odd, None)], {}), [None], odd)

    def test_keys_ignore_case_and_spacing(self):
        self.assertEqual(logos.key("  Harbour   HOTELS "), logos.key("harbour hotels"))

class RouteTests(RouteCase):

    def setUp(self):
        super().setUp()
        self.forget()
        self.addCleanup(self.forget)

    def forget(self):
        with db.session() as conn:
            conn.execute(BrandLogo.__table__.delete())

    def keep(self, brand="Harbour Hotels"):
        with db.session() as conn:
            conn.execute(BrandLogo.__table__.insert().values(key=logos.key(brand), name=brand, logo=PNG, logo_type="image/png",
                                                              checked=NOW.isoformat()))

    def test_a_segment_with_a_brand_that_has_a_logo_links_to_it_and_serves_it(self):
        self.keep()
        seg = self.book("ana", HOTEL, provider="Harbour Hotels", travelers=[{"person_id": self.person["ana"]}])
        self.assertEqual(seg["logo"], f"/api/segments/{seg['id']}/logo")
        status, headers, body = fetch(self.base, "GET", seg["logo"], headers={"X-Waypoint": "1", **self.who["ana"]})
        self.assertEqual((status, headers["Content-Type"], body), (200, "image/png", PNG))
        self.assertIn("private", headers["Cache-Control"])

    def test_a_hotel_shows_its_bundled_brand_and_falls_back_to_its_group(self):
        hyatt = self.book("ana", HOTEL, provider="Booking.com", origin="Hyatt Place Harbour", travelers=[{"person_id": self.person["ana"]}])
        self.assertEqual(hyatt["logo"], f"/api/segments/{hyatt['id']}/logo")
        expected = bundled_logos.read("Hyatt Place")
        self.assertEqual(fetch(self.base, "GET", hyatt["logo"], headers={"X-Waypoint": "1", **self.who["ana"]})[2], expected[0])
        centric = self.book("ana", {**HOTEL, "confirmation": "CENTRIC123"}, provider="Booking.com", origin="Hyatt Centric Harbour", travelers=[{"person_id": self.person["ana"]}])
        self.assertEqual(fetch(self.base, "GET", centric["logo"], headers={"X-Waypoint": "1", **self.who["ana"]})[2], bundled_logos.read("Hyatt")[0])

    def test_no_logo_link_without_a_logo(self):
        seg = self.book("ana", OUT, provider="Unknown Example Air", travelers=[{"person_id": self.person["ana"]}])
        self.assertIsNone(seg["logo"])
        self.assertEqual(self.call("ana", "GET", f"/api/segments/{seg['id']}/logo")[0], 404)

    def test_a_stranger_gets_the_same_404_as_for_a_segment_that_isnt_there(self):
        self.keep()
        seg = self.book("ana", HOTEL, provider="Harbour Hotels", travelers=[{"person_id": self.person["ana"]}])
        stranger = self.req("GET", f"/api/segments/{seg['id']}/logo", None, self.who["ben"])
        missing = self.req("GET", "/api/segments/99999/logo", None, self.who["ben"])
        self.assertEqual(stranger, missing)
        self.assertEqual(stranger[0], 404)
