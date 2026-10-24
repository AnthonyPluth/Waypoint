import json
import re
import struct
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
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
                source = urlsplit(entry["source"])
                self.assertEqual(source.scheme, "https")
                self.assertTrue(source.hostname and "." in source.hostname)
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

    def test_each_brand_shows_its_mark_cut_from_its_logo(self):
        def png_size(path):
            width, height = struct.unpack(">II", path.read_bytes()[16:24])
            return width, height

        for entry in json.loads((bundled_logos.ROOT / "manifest.json").read_text()):
            with self.subTest(brand=entry["name"]):
                x, y, w, h = entry["mark"]
                self.assertTrue(x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= 1.0001 and y + h <= 1.0001)
                mark = bundled_logos.ROOT / "marks" / entry["file"]
                self.assertEqual(bundled_logos.read(entry["name"])[0], mark.read_bytes())
                if entry["file"].endswith(".png"):
                    whole, cut = png_size(bundled_logos.ROOT / entry["file"]), png_size(mark)
                    self.assertLessEqual(abs(cut[0] - w * whole[0]), 1)
                    self.assertLessEqual(abs(cut[1] - h * whole[1]), 1)
                else:
                    outer = ET.fromstring(mark.read_bytes())
                    inner = outer.find("{http://www.w3.org/2000/svg}svg")
                    full = (float(inner.get("width")), float(inner.get("height")))
                    shown = [float(v) for v in outer.get("viewBox").split()]
                    for got, want in zip(shown, (x * full[0], y * full[1], w * full[0], h * full[1]), strict=True):
                        self.assertAlmostEqual(got, want, delta=0.01)

    def test_major_travel_brands_work_without_network_access(self):
        with mock.patch("waypoint.tls.urlopen", side_effect=AssertionError("Logos must be local")):
            for brand in ("United Airlines", "JetBlue", "Delta", "Hyatt Place", "Marriott", "Hilton", "IHG", "Avis", "Enterprise Rent-A-Car", "Hertz", "Sixt", "Carnival", "Royal Caribbean International", "Disney Cruise Line", "Viking Cruises", "Virgin Voyages"):
                with self.subTest(brand=brand):
                    self.assertIsNotNone(bundled_logos.read(brand))

    def test_normalized_names_and_unknown_brands(self):
        self.assertEqual(bundled_logos.read(" LE MÉRIDIEN "), bundled_logos.read("Le Meridien"))
        for name in (None, "", "Unknown Example Air", "../../secret.key", "Hiltonish"):
            self.assertIsNone(bundled_logos.read(name))
