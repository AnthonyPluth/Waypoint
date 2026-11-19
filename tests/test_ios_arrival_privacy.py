import plistlib
import re
import unittest
from pathlib import Path

IOS = Path(__file__).resolve().parent.parent / "ios"
GEOCODING_FILE = IOS / "Waypoint" / "ArrivalPlaces.swift"
WATCH_FILE = IOS / "Waypoint" / "ArrivalWatch.swift"
HERE_FILE = IOS / "Waypoint" / "ArrivalHere.swift"
DESIGN = IOS.parent / "docs" / "design" / "arrival-codes" / "README.md"
LOCATION_FIXES = re.compile(
    r"\b(startUpdatingLocation|startMonitoringSignificantLocationChanges|allowsBackgroundLocationUpdates"
    r"|startRangingBeacons|CLLocationUpdate|CLServiceSession|CLMonitor)\b"
)
ONE_LOCATION_REQUEST = re.compile(r"\b(requestLocation|didUpdateLocations)\b")
KEPT_ANYWHERE = re.compile(r"\b(OfflineStore|UserDefaults|FileManager|saveArrival|savePlaces)\b|\.write\(")
LOCATION_PROPERTY = re.compile(r"\.location\b")
ARRIVAL_RECORD_DENIALS = re.compile(
    r"(where (you|the person|they) (was|were)|when (you|they) arrived|arrivals?)[^.;:]{0,40}\b(not|never)\b[^.;:]{0,20}\b(recorded|kept)\b"
    r"|(sent|logged)(, sent)? or kept|kept or logged|sent, kept|never kept|no place the person was at"
)
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

    def test_the_arrival_files_never_follow_the_phone(self):
        self.assertTrue(WATCH_FILE.is_file())
        for path in swift_files(IOS / "Waypoint"):
            if path.name.startswith("Arrival"):
                text = path.read_text()
                self.assertIsNone(LOCATION_FIXES.search(text), f"{path.name} follows the phone's location")
                if path != GEOCODING_FILE:
                    self.assertIsNone(LOCATION_PROPERTY.search(text), f"{path.name} reads the phone's location")

    def test_one_file_makes_the_single_location_request_for_the_card_and_keeps_nothing(self):
        asking = [p.name for p in swift_files(IOS) if ONE_LOCATION_REQUEST.search(p.read_text())]
        self.assertEqual(asking, ["ArrivalHere.swift"])
        text = HERE_FILE.read_text()
        self.assertEqual(len(re.findall(r"\.requestLocation\(\)", text)), 1)
        self.assertIsNone(KEPT_ANYWHERE.search(text), "ArrivalHere.swift stores something")
        self.assertIsNone(re.search(r"\b(requestWhenInUseAuthorization|requestAlwaysAuthorization)\b", text))
        self.assertIn("ArrivalHere", (IOS / "Waypoint" / "WaypointApp.swift").read_text())
        self.assertEqual(ONE_LOCATION_REQUEST.findall("manager.requestLocation()"), ["requestLocation"])

    def test_the_regions_are_named_arrival_and_the_segment_id_only(self):
        text = WATCH_FILE.read_text()
        self.assertEqual(re.findall(r'regionPrefix = "([^"]*)"', text), ["arrival-"])
        self.assertEqual(len(re.findall(r"CLCircularRegion\(", text)), 1)
        self.assertIn("identifier: id)", text)

    def test_the_arrival_file_keeps_exactly_the_fields_the_docs_say(self):
        def fields(source: str, struct: str) -> list[str]:
            body = re.search(rf"struct {struct}\b[^{{]*\{{(.*?)\n\}}", source, re.S).group(1)
            return re.findall(r"^\s+(?:let|var) (\w+):", body, re.M)

        places = (IOS / "Waypoint" / "ArrivalPlaces.swift").read_text()
        watch = WATCH_FILE.read_text()
        self.assertEqual(fields(places, "ArrivalPlace"), ["segmentId", "tripId", "kind", "latitude", "longitude", "radius", "opens", "closes"])
        self.assertEqual(fields(watch, "ArrivalWatched"), ["place", "notifiedAt"])
        self.assertEqual(fields(watch, "ArrivalFileContent"), ["version", "watched"])
        root = IOS.parent
        for name in ("AGENTS.md", "SECURITY.md", ".github/agent-review/invariants.md", "docs/src/content/docs/start/ios.md"):
            text = (root / name).read_text()
            self.assertIn("when its alert last fired", text, name)
            self.assertIn("issue #849 comment", text, name)
        for path in [root / "AGENTS.md", root / "SECURITY.md", root / ".github/agent-review/invariants.md", root / "docs/src/content/docs/start/ios.md",
                     DESIGN.parent / "README.md", *sorted((IOS / "Waypoint").glob("Arrival*.swift"))]:
            text = path.read_text()
            for match in ARRIVAL_RECORD_DENIALS.finditer(text):
                self.fail(f"{path.name} says {match.group(0)!r}: the arrival file keeps when each alert last fired, so arrivals are not unrecorded")

    def test_the_signed_off_phrase_about_the_location_is_allowed_and_the_denial_of_arrivals_is_not(self):
        allowed = "Your location is never sent anywhere and is not recorded."
        self.assertIsNone(ARRIVAL_RECORD_DENIALS.search(allowed))
        plist = plistlib.loads((IOS / "Waypoint" / "Info.plist").read_bytes())
        self.assertIn(allowed, plist["NSLocationAlwaysAndWhenInUseUsageDescription"])
        for denial in ("where you were or when you arrived is not recorded", "arrivals are never kept", "its arrivals are never logged, sent or kept",
                       "never sent, kept or logged", "when they arrived is not recorded", "no place the person was at"):
            self.assertIsNotNone(ARRIVAL_RECORD_DENIALS.search(denial), denial)

    def test_the_launch_opens_only_through_the_launch_gate(self):
        app = (IOS / "Waypoint" / "WaypointApp.swift").read_text()
        self.assertNotIn("task { await open() }", app)
        self.assertNotIn("task(id:", app)
        self.assertIn("launch.begin(", app)

    def test_a_launch_that_opened_the_shell_activates_the_arrival_watch_after_the_gate_allowed_it(self):
        app = (IOS / "Waypoint" / "WaypointApp.swift").read_text()
        start = app.index("private func openIfAllowed()")
        body = app[start : app.index("private func open()", start)]
        self.assertLess(body.index("launch.begin("), body.index("await open()"))
        self.assertLess(body.index("await open()"), body.index("LaunchGate.activatesArrival("))
        self.assertLess(body.index("LaunchGate.activatesArrival("), body.index("ArrivalWatch.shared.activated()"))

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
        self.assertIsNone(LOCATION_FIXES.search("manager.requestLocation()"))


if __name__ == "__main__":
    unittest.main()
