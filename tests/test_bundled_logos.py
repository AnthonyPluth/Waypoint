import json
import re
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from waypoint.storage import bundled_logos


class CatalogTests(unittest.TestCase):
    def test_every_catalog_entry_is_a_real_local_image_with_provenance(self):
        entries = json.loads((bundled_logos.ROOT / "manifest.json").read_text())
        self.assertGreaterEqual(len(entries), 120)
        self.assertEqual(len(entries), len({bundled_logos.normalize(e["name"]) for e in entries}))
        for entry in entries:
            with self.subTest(brand=entry["name"]):
                self.assertEqual(entry["file"], entry["file"].rsplit("/", 1)[-1])
                self.assertTrue(entry["source"].startswith(("https://github.com/", "https://commons.wikimedia.org/wiki/File:", "https://en.wikipedia.org/wiki/File:", "https://newsroom.hyatt.com/image/")))
                self.assertRegex(entry["sha"], r"^[a-f0-9]{40}$")
                body, content_type = bundled_logos.read(entry["name"])
                if content_type == "image/png":
                    self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
                else:
                    svg = ET.fromstring(body)
                    self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
                    for node in svg.iter():
                        self.assertNotIn(node.tag.rsplit("}", 1)[-1], {"script", "foreignObject", "image", "iframe"})
                        for attr, value in node.attrib.items():
                            self.assertFalse(attr.rsplit("}", 1)[-1].startswith("on"))
                            if attr.rsplit("}", 1)[-1] == "href":
                                self.assertTrue(value.startswith("#"))
                            self.assertIsNone(re.search(r"url\(\s*['\"]?(?:https?:|//)", value))
                        if node.tag.endswith("}style"):
                            self.assertNotIn("@import", node.text or "")
                            self.assertNotIn("http", node.text or "")

    def test_major_travel_brands_work_without_network_access(self):
        with mock.patch("waypoint.tls.urlopen", side_effect=AssertionError("Logos must be local")):
            for brand in ("United Airlines", "JetBlue", "Delta", "Hyatt Place", "Marriott", "Hilton", "IHG", "Avis", "Enterprise Rent-A-Car", "Hertz", "Sixt", "Carnival", "Royal Caribbean International", "Disney Cruise Line", "Viking Cruises", "Virgin Voyages"):
                with self.subTest(brand=brand):
                    self.assertIsNotNone(bundled_logos.read(brand))

    def test_normalized_names_and_unknown_brands(self):
        self.assertEqual(bundled_logos.read(" LE MÉRIDIEN "), bundled_logos.read("Le Meridien"))
        for name in (None, "", "Unknown Example Air", "../../secret.key", "Hiltonish"):
            self.assertIsNone(bundled_logos.read(name))
