import plistlib
import re
import unittest
from pathlib import Path

IOS = Path(__file__).resolve().parent.parent / "ios"
GEOCODING_FILE = IOS / "Waypoint" / "ArrivalPlaces.swift"
WATCH_FILE = IOS / "Waypoint" / "ArrivalWatch.swift"
DESIGN = IOS.parent / "docs" / "design" / "arrival-codes" / "README.md"
LOCATION_FIXES = re.compile(
    r"\b(startUpdatingLocation|startMonitoringSignificantLocationChanges|requestLocation|didUpdateLocations|allowsBackgroundLocationUpdates"
    r"|startRangingBeacons|CLLocationUpdate|CLServiceSession|CLMonitor)\b"
)
LOCATION_PROPERTY = re.compile(r"\.location\b")
NETWORK = re.compile(r"\b(URLSession|ServerClient|ServerAPI|URLRequest|NWConnection|WKWebView)\b")
LOGGING = re.compile(r"\b(os_log|Logger|NSLog|OSLog)\b|\bprint\s*\(|\bdebugPrint\s*\(|\bdump\s*\(")


def swift_files(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.swift"))


class ArrivalPrivacyTests(unittest.TestCase):
    def test_the_arrival_files_exist(self):
        self.assertTrue(GEOCODING_FILE.is_file())

    def test_the_geocoder_is_named_in_one_file_only(self):
        users = [p.relative_to(IOS).as_posix() for p in swift_files(IOS) if "CLGeocoder" in p.read_text()]
        self.assertEqual(users, ["Waypoint/ArrivalPlaces.swift"])

    def test_the_arrival_files_make_no_request_of_their_own(self):
        for path in swift_files(IOS / "Waypoint"):
            if path.name.startswith("Arrival"):
                self.assertIsNone(NETWORK.search(path.read_text()), f"{path.name} names a network type")

    def test_the_arrival_files_log_nothing(self):
        for path in swift_files(IOS / "Waypoint"):
            if path.name.startswith("Arrival"):
                self.assertIsNone(LOGGING.search(path.read_text()), f"{path.name} writes a log line")

    def test_the_arrival_files_never_ask_for_a_location_fix(self):
        self.assertTrue(WATCH_FILE.is_file())
        for path in swift_files(IOS / "Waypoint"):
            if path.name.startswith("Arrival"):
                text = path.read_text()
                self.assertIsNone(LOCATION_FIXES.search(text), f"{path.name} asks for a location fix")
                if path != GEOCODING_FILE:
                    self.assertIsNone(LOCATION_PROPERTY.search(text), f"{path.name} reads the phone's location")

    def test_the_regions_are_named_arrival_and_the_segment_id_only(self):
        text = WATCH_FILE.read_text()
        self.assertEqual(re.findall(r'regionPrefix = "([^"]*)"', text), ["arrival-"])
        self.assertEqual(len(re.findall(r"CLCircularRegion\(", text)), 1)
        self.assertIn("identifier: id)", text)

    def test_the_launch_opens_only_through_the_launch_guard(self):
        app = (IOS / "Waypoint" / "WaypointApp.swift").read_text()
        self.assertNotIn("task { await open() }", app)
        self.assertIn("LaunchGuard.mayOpen(", app)

    def test_the_usage_strings_are_the_signed_off_ones_and_no_background_mode_is_declared(self):
        plist = plistlib.loads((IOS / "Waypoint" / "Info.plist").read_bytes())
        design = DESIGN.read_text()
        for key in ("NSLocationWhenInUseUsageDescription", "NSLocationAlwaysAndWhenInUseUsageDescription"):
            signed_off = re.search(rf"`{key}`: \"([^\"]+)\"", design)
            self.assertIsNotNone(signed_off, key)
            self.assertEqual(plist[key], signed_off.group(1), key)
        self.assertNotIn("UIBackgroundModes", plist)

    def test_the_checks_do_catch_what_they_look_for(self):
        self.assertIsNotNone(NETWORK.search("let s = URLSession.shared"))
        self.assertIsNotNone(LOGGING.search('print("near \\(place)")'))
        self.assertIsNotNone(LOGGING.search("Logger(subsystem: x)"))
        self.assertIsNone(LOGGING.search("let blueprint = 1"))
        self.assertIsNotNone(LOCATION_FIXES.search("manager.startUpdatingLocation()"))
        self.assertIsNotNone(LOCATION_PROPERTY.search("let here = manager.location"))
        self.assertIsNone(LOCATION_FIXES.search("let place = ArrivalPlace(kind: .parking)"))


if __name__ == "__main__":
    unittest.main()
