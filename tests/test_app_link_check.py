import unittest

from tools import app_link_check


class ClaimedTests(unittest.TestCase):
    def test_a_production_app_and_its_paths_are_read_and_internal_builds_are_left_out(self):
        document = {"applinks": {"details": [
            {"appIDs": ["ABCDE12345.com.example.air", "ABCDE12345.com.example.air.beta", "ABCDE12345.com.example.air.dev"],
             "components": [{"/": "/my-trips"}, {"/": "/secret", "exclude": True}], "paths": ["/home"]}]}}
        self.assertEqual(app_link_check.claimed(document), [("ABCDE12345.com.example.air", ["/home", "/my-trips"])])

    def test_the_older_shapes_are_read_too(self):
        by_app = {"applinks": {"details": {"ABCDE12345.com.example.hotel": {"paths": ["/account/*"]}, "ABCDE12345.com.example.hotel.qa1": {"paths": ["/x"]}}}}
        self.assertEqual(app_link_check.claimed(by_app), [("ABCDE12345.com.example.hotel", ["/account/*"])])
        single = {"applinks": {"details": [{"appID": "ABCDE12345.com.example.car", "paths": ["/homepage*"]}]}}
        self.assertEqual(app_link_check.claimed(single), [("ABCDE12345.com.example.car", ["/homepage*"])])

    def test_nothing_useful_is_nothing(self):
        for document in (None, [], {}, {"applinks": {}}, {"applinks": {"details": "x"}}, {"webcredentials": {"apps": ["A.b"]}}):
            self.assertEqual(app_link_check.claimed(document), [])


if __name__ == "__main__":
    unittest.main()
