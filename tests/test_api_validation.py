"""What the API's handlers do with values they can't use: each is refused with a message saying which (ApiError, a 400
or a 404), never left to fail as a bug would. Switches sent as text ("false", "0", "no") are off; whole numbers that
aren't whole, ids that aren't ids and texts that aren't text are refused."""
import unittest

from waypoint import validate
from waypoint.server.common import ApiError, clamped_int, query_int, row_id, text

OFF = ("false", "0", "no", "off", "", None, 0, False, [], {})


def q(**kw):
    return {k: [str(v)] for k, v in kw.items()}


class FlagTests(unittest.TestCase):
    def test_off_is_off(self):
        for off in OFF:
            with self.subTest(v=off):
                self.assertEqual(validate.flag(off), 0)
                self.assertFalse(validate.on(off))
        for on in (True, 1, "1", "true", "on"):
            self.assertTrue(validate.on(on))


class WholeNumberTests(unittest.TestCase):
    def test_query_numbers(self):
        for bad in ("abc", "2.5", "nan", "inf", "1e13", "true"):
            with self.subTest(v=bad):
                with self.assertRaisesRegex(ApiError, "^The limit must be a whole number$") as cm:
                    query_int(q(limit=bad), "limit", 200, 1, 1000)
                self.assertEqual(cm.exception.status, 400)
                with self.assertRaisesRegex(ApiError, "^The number of days must be a whole number$"):
                    query_int(q(days=bad), "days", 90, 14, 365, "number of days")
        self.assertEqual(query_int(q(limit="5000"), "limit", 200, 1, 1000), 1000)
        self.assertEqual(query_int(q(limit="-3"), "limit", 200, 1, 1000), 1)
        self.assertEqual(query_int(q(limit="3.0"), "limit", 200, 1, 1000), 3)
        self.assertEqual(query_int({}, "limit", 200, 1, 1000), 200)
        self.assertEqual(query_int(q(limit=""), "limit", 200, 1, 1000), 200)

    def test_clamped(self):
        for bad in ("abc", [], {}, True, "2.5", 2.5):
            with self.subTest(v=bad), self.assertRaisesRegex(ApiError, "^The days must be a whole number$"):
                clamped_int(bad, "days", 90, 14, 365)
        self.assertEqual(clamped_int(7, "days", 90, 14, 365), 14)
        self.assertEqual(clamped_int("1000", "days", 90, 14, 365), 365)
        self.assertEqual(clamped_int(None, "days", 90, 14, 365), 90)
        self.assertEqual(clamped_int("", "days", 900, 14, 365), 365)

    def test_ids_in_the_address(self):
        for bad in ("abc", "-1", "1.5", " 1", "99999999999999999999", "١٢", "", None, True, 1.5, [1], {"a": 1}):
            with self.subTest(id=bad):
                with self.assertRaisesRegex(ApiError, "^Not found$") as cm:
                    row_id(bad)
                self.assertEqual(cm.exception.status, 404)
                with self.assertRaisesRegex(ApiError, "^Unknown trip$") as cm:
                    row_id(bad, "Unknown trip", 400)
                self.assertEqual(cm.exception.status, 400)
        self.assertEqual(row_id("12"), 12)
        self.assertEqual(row_id(12), 12)
        self.assertEqual(row_id("007"), 7)


class TextTests(unittest.TestCase):
    """A field that should be text, sent as something else, is refused rather than taken as empty."""

    def test_not_text(self):
        for bad in ({"a": 1}, ["Lisbon"], 10 ** 30, True, 1.5):
            with self.subTest(v=bad), self.assertRaisesRegex(ApiError, '^Send "name" as text$') as cm:
                text(bad, "name")
            self.assertEqual(cm.exception.status, 400)

    def test_text(self):
        self.assertEqual(text(None, "name"), "")
        self.assertEqual(text("", "name"), "")
        self.assertEqual(text(" Lisbon ", "name"), " Lisbon ")


if __name__ == "__main__":
    unittest.main()
