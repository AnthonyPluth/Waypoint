import unittest
from unittest import mock

from waypoint.domain import links


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

    def test_segment_links(self):
        hotel = links.segment_links("hotel", "Hilton", "H1", "Doe", "https://example.com/m", {"address": "1 Quay St", "phone": "+1 555 010 0100"}, "Harbour")
        self.assertEqual(hotel, {"app": "https://example.com/m", "directions": "https://maps.apple.com/?q=1%20Quay%20St", "call": "tel:+15550100100"})
        flight = links.segment_links("flight", "Example Air", "ABC123", "Doe", "http://example.com/m", {}, "JFK")
        self.assertEqual(flight, {"app": None, "directions": None, "call": None})
        car = links.segment_links("car", "Hertz", "C1", None, None, {}, "SFO airport")
        self.assertEqual(car["directions"], "https://maps.apple.com/?q=SFO%20airport")


if __name__ == "__main__":
    unittest.main()
