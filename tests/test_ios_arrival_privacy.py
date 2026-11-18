import re
import unittest
from pathlib import Path

IOS = Path(__file__).resolve().parent.parent / "ios"
GEOCODING_FILE = IOS / "Waypoint" / "ArrivalPlaces.swift"
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

    def test_the_checks_do_catch_what_they_look_for(self):
        self.assertIsNotNone(NETWORK.search("let s = URLSession.shared"))
        self.assertIsNotNone(LOGGING.search('print("near \\(place)")'))
        self.assertIsNotNone(LOGGING.search("Logger(subsystem: x)"))
        self.assertIsNone(LOGGING.search("let blueprint = 1"))


if __name__ == "__main__":
    unittest.main()
