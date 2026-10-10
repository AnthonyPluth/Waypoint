import unittest
from unittest import mock
from urllib.parse import urlsplit

from waypoint.domain import app_links, links
from waypoint.domain.mail import query


class ManageLinks(unittest.TestCase):
    def test_every_table_entry_builds_its_url_for_a_sample_booking(self):
        for provider, (host, _path) in links.MANAGE.items():
            url = links.manage_link(provider, "ABC123", "Doe")
            self.assertTrue(url and url.startswith(f"https://{host}/"), provider)

    def test_awkward_codes_and_names_are_encoded_and_stay_on_the_providers_host(self):
        with mock.patch.dict(links.MANAGE, {"example air": ("www.example.com", "/manage?code={code}&name={name}")}):
            url = links.manage_link(" Example  AIR ", "A&B=1#x", "O'Neil/../evil.com?")
            self.assertEqual(url, "https://www.example.com/manage?code=A%26B%3D1%23x&name=O%27Neil%2F..%2Fevil.com%3F")
            self.assertIsNone(links.manage_link("Example Air", None, "Doe"))
            self.assertIsNone(links.manage_link("Example Air", "ABC123", ""))

    def test_a_provider_without_an_entry_has_no_prefilled_link(self):
        self.assertIsNone(links.manage_link("Nobody Air", "ABC123", "Doe"))
        self.assertIsNone(links.manage_link(None, "ABC123", "Doe"))


class LastName(unittest.TestCase):
    def test_the_signed_in_travellers_own_name_wins_over_the_first(self):
        travellers = [(1, "Mia Doe"), (2, "Sam Roe")]
        self.assertEqual(links.last_name(travellers, 2), "Roe")
        self.assertEqual(links.last_name(travellers, 1), "Doe")

    def test_otherwise_the_first_traveller_is_used(self):
        travellers = [(1, "Mia Doe"), (2, "Sam Roe")]
        self.assertEqual(links.last_name(travellers, 9), "Doe")
        self.assertEqual(links.last_name(travellers, None), "Doe")

    def test_a_printed_name_uses_its_last_word(self):
        self.assertEqual(links.last_name([(None, "MS MIA VAN DER DOE")], None), "DOE")
        self.assertEqual(links.last_name([(None, "  Doe  ")], 3), "Doe")

    def test_nobody_with_a_name_gives_nothing(self):
        self.assertIsNone(links.last_name([], 1))
        self.assertIsNone(links.last_name([(1, ""), (None, "   ")], 1))

    def test_a_nameless_traveller_is_skipped_for_the_next(self):
        self.assertEqual(links.last_name([(1, ""), (2, "Sam Roe")], 1), "Roe")


class Others(unittest.TestCase):
    def test_https_only(self):
        self.assertEqual(links.https_only("https://example.com/m"), "https://example.com/m")
        for bad in (None, "", "http://example.com", "javascript:alert(1)", "https://", "//example.com", "shoebox://"):
            self.assertIsNone(links.https_only(bad), bad)

    def test_directions_and_call(self):
        self.assertEqual(links.directions_link("1 Quay St, London & more"), "https://maps.apple.com/?q=1%20Quay%20St%2C%20London%20%26%20more")
        self.assertIsNone(links.directions_link("  "))
        self.assertEqual(links.call_link("+44 (20) 7946-0000"), "tel:+442079460000")
        self.assertEqual(links.call_link("800 555 0100"), "tel:8005550100")
        self.assertIsNone(links.call_link("n/a"))
        self.assertIsNone(links.call_link(None))

    def test_the_emails_manage_link_comes_before_the_airlines_page(self):
        built = links.segment_links("flight", "United Airlines", "ABC123", "Doe", "https://mail.example.org/m", {}, "JFK")
        self.assertEqual(built["app"], "https://mail.example.org/m")

    def test_a_flight_without_a_manage_link_gets_the_airlines_page(self):
        built = links.segment_links("flight", "United Airlines", "ABC123", "Doe", None, {}, "JFK")
        self.assertEqual(built["app"], "https://www.united.com/en/us/manageres/mytrips")
        insecure = links.segment_links("flight", "Delta", "ABC123", "Doe", "http://example.com/m", {}, "JFK")
        self.assertEqual(insecure["app"], "https://www.delta.com/my-trips/search")

    def test_only_a_flight_gets_the_airlines_page(self):
        self.assertIsNone(links.segment_links("hotel", "Delta", "H1", "Doe", None, {}, "Harbour")["app"])
        self.assertIsNone(links.segment_links("flight", "Nobody Air", "ABC123", "Doe", None, {}, "JFK")["app"])

    def test_the_airlines_page_carries_nothing_from_the_booking(self):
        code, name = "ZQXJ7K", "Quillfeather"
        for provider in links.MANAGE:
            built = links.segment_links("flight", provider, code, name, None, {}, "JFK")["app"]
            self.assertTrue(built and built.startswith("https://") and "?" not in built, provider)
            self.assertNotIn(code.lower(), built.lower())
            self.assertNotIn(name.lower(), built.lower())

    def test_each_airline_is_known_by_its_common_names(self):
        expected = {
            "united airlines": "https://www.united.com/en/us/manageres/mytrips",
            "united": "https://www.united.com/en/us/manageres/mytrips",
            "delta air lines": "https://www.delta.com/my-trips/search",
            "delta": "https://www.delta.com/my-trips/search",
            "alaska airlines": "https://www.alaskaair.com/booking/reservation-lookup",
            "american airlines": "https://www.aa.com/reservation/view/find-your-reservation",
            "southwest airlines": "https://www.southwest.com/air/check-in/",
        }
        self.assertEqual(set(links.MANAGE), set(expected))
        for provider, url in expected.items():
            self.assertEqual(links.manage_link(provider, None, None), url, provider)
            self.assertEqual(links.manage_link(provider.upper(), "ABC123", "Doe"), url, provider)

    def test_a_flight_without_a_last_name_keeps_the_emails_manage_link(self):
        with mock.patch.dict(links.MANAGE, {"example air": ("www.example.com", "/m?c={code}&n={name}")}):
            for name in ("Doe", None):
                built = links.segment_links("flight", "Example Air", "ABC123", name, "https://mail.example.org/m", {}, "JFK")
                self.assertEqual(built["app"], "https://mail.example.org/m")
            self.assertEqual(links.segment_links("flight", "Example Air", "ABC123", "Doe", None, {}, "JFK")["app"], "https://www.example.com/m?c=ABC123&n=Doe")
            self.assertIsNone(links.segment_links("flight", "Example Air", "ABC123", None, None, {}, "JFK")["app"])

    def test_segment_links(self):
        hotel = links.segment_links("hotel", "Hilton", "H1", "Doe", "https://example.com/m", {"address": "1 Quay St", "phone": "+1 555 010 0100"}, "Harbour")
        self.assertEqual(hotel, {"app": "https://example.com/m", "open": None, "open_kind": None, "directions": "https://maps.apple.com/?q=1%20Quay%20St", "call": "tel:+15550100100"})
        flight = links.segment_links("flight", "Example Air", "ABC123", "Doe", "http://example.com/m", {}, "JFK")
        self.assertEqual(flight, {"app": None, "open": None, "open_kind": None, "directions": None, "call": None})
        car = links.segment_links("car", "Hertz", "C1", None, None, {}, "SFO airport")
        self.assertEqual(car["directions"], "https://maps.apple.com/?q=SFO%20airport")


class VendorLinkTests(unittest.TestCase):
    def test_a_delta_flight_with_no_manage_link_opens_deltas_app_page(self):
        built = links.segment_links("flight", "Delta Air Lines", None, None, None, {}, "JFK")
        self.assertEqual(built["app"], "https://www.delta.com/my-trips/search")

    def test_a_vendor_with_an_app_page_gets_it_marked_as_the_app(self):
        built = links.segment_links("hotel", "Marriott", "H1", "Doe", None, {}, "Harbour Hotel")
        self.assertEqual((built["app"], built["open"], built["open_kind"]), (None, "https://www.marriott.com/", "app"))

    def test_a_vendor_with_no_neutral_app_page_gets_its_website_marked_as_such(self):
        built = links.segment_links("car", "Avis", "C1", "Doe", None, {}, "Harbour Depot")
        self.assertEqual((built["open"], built["open_kind"]), ("https://www.avis.com/", "website"))

    def test_a_vendor_not_in_the_table_gets_nothing(self):
        built = links.segment_links("hotel", "Harbour Hotels", "H1", "Doe", None, {}, "Harbour Hotels")
        self.assertEqual((built["open"], built["open_kind"]), (None, None))

    def test_a_booking_link_wins_over_the_vendors(self):
        built = links.segment_links("hotel", "Marriott", "H1", "Doe", "https://mail.example.org/m", {}, "Harbour Hotel")
        self.assertEqual((built["app"], built["open"], built["open_kind"]), ("https://mail.example.org/m", None, None))

    def test_a_hotel_brand_finds_its_group_and_a_group_only_serves_its_own_kinds(self):
        found = links.segment_links("hotel", "Courtyard by Marriott", "H1", "Doe", None, {}, "Courtyard by Marriott Harbour")
        self.assertEqual(found["open"], "https://www.marriott.com/")
        self.assertIsNone(links.segment_links("car", "Marriott", "H1", "Doe", None, {}, "x")["open"])
        self.assertIsNone(links.segment_links("hotel", "Delta", "H1", "Doe", None, {}, "x")["open"])

    def test_each_kind_of_booking_can_get_a_vendor_link(self):
        for kind, provider in (("flight", "Southwest Airlines"), ("hotel", "Hyatt"), ("car", "Hertz"), ("train", "Amtrak"), ("cruise", "Carnival")):
            with self.subTest(kind=kind):
                built = links.segment_links(kind, provider, "X1", "Doe", None, {}, "Place")
                self.assertTrue((built["app"] or built["open"] or "").startswith("https://"))

    def test_every_sender_domain_is_covered_and_every_link_is_https_on_the_vendors_own_domain(self):
        for domain in query.SENDERS:
            self.assertIn(domain, app_links.BY_DOMAIN, domain)
        for vendor in app_links.ALL_VENDORS:
            host = urlsplit(vendor["url"]).hostname or ""
            self.assertEqual(urlsplit(vendor["url"]).scheme, "https", vendor["url"])
            self.assertTrue(any(host == d or host.endswith("." + d) for d in vendor["domains"]), vendor["url"])
            self.assertIn(vendor["kind"], ("app", "website"))
            self.assertTrue(vendor["source"] and vendor["checked"], vendor["url"])
            self.assertFalse(set(vendor["kinds"]) - set(app_links.ALL), vendor["url"])

    def test_no_link_ever_uses_a_custom_scheme_and_names_are_unique(self):
        names = [n for v in app_links.ALL_VENDORS for n in v["names"]]
        self.assertEqual(len(names), len(set(names)))
        for vendor in app_links.ALL_VENDORS:
            self.assertFalse(links.https_only(vendor["url"]) is None, vendor["url"])
            self.assertNotIn("delta://", vendor["url"])

    def test_the_link_carries_nothing_from_the_booking(self):
        built = links.segment_links("hotel", "Hyatt", "ZQXJ7K", "Quillfeather", None, {}, "Harbour")
        self.assertNotIn("zqxj7k", (built["open"] or "").lower())
        self.assertNotIn("quillfeather", (built["open"] or "").lower())


if __name__ == "__main__":
    unittest.main()
