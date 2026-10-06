import unittest

from waypoint import validate


class Oops(ValueError):
    pass


class ParseNumberTests(unittest.TestCase):
    def test_drops_commas_and_dollars(self):
        self.assertEqual(validate.parse_number("1,234.50"), 1234.5)
        self.assertEqual(validate.parse_number("$5"), 5.0)
        self.assertEqual(validate.parse_number(" 7 "), 7.0)
        self.assertEqual(validate.parse_number("12%", drop=",$%"), 12.0)
        with self.assertRaises(ValueError):
            validate.parse_number("12%")

    def test_refuses_what_db_number_refuses(self):
        for bad in ("nan", "inf", "-inf", "1e13", "abc", ""):
            with self.subTest(v=bad), self.assertRaises(ValueError):
                validate.parse_number(bad)

    def test_bools_are_refused_unless_passed_as_is(self):
        with self.assertRaises(ValueError):
            validate.parse_number(True)
        self.assertEqual(validate.parse_number(True, drop=""), 1.0)

    def test_as_is(self):
        with self.assertRaises(TypeError):
            validate.parse_number(None, drop="")
        with self.assertRaises(ValueError):
            validate.parse_number("1,000", drop="")
        self.assertEqual(validate.parse_number(2.5, drop=""), 2.5)


class ParseExternalTests(unittest.TestCase):
    def test_a_number_in_another_systems_reply(self):
        self.assertEqual(validate.parse_external("-12.34"), -12.34)
        self.assertEqual(validate.parse_external(5), 5.0)
        self.assertEqual(validate.parse_external(" 7.5 "), 7.5)
        self.assertEqual(validate.parse_external("$1,234.50", drop=",$"), 1234.5)

    def test_anything_else_is_none(self):
        for bad in (None, "", "nan", "NaN", "inf", "-Infinity", float("nan"), float("inf"), "1e13", 1e300, 10 ** 400,
                    "abc", "1,000", True, False, {"amount": 1}, [1]):
            with self.subTest(v=bad):
                self.assertIsNone(validate.parse_external(bad))


class NumberTests(unittest.TestCase):
    v = validate.Validator(Oops)

    def test_empty(self):
        self.assertIsNone(self.v.number(None, "fee"))
        self.assertIsNone(self.v.number("", "fee"))
        for empty in (None, ""):
            with self.subTest(v=empty), self.assertRaisesRegex(Oops, "^Enter the fee$"):
                self.v.number(empty, "fee", required=True)

    def test_blank_is_not_empty(self):
        with self.assertRaisesRegex(Oops, "^The fee must be a number$"):
            self.v.number("  ", "fee")

    def test_not_a_number(self):
        for bad in ("abc", True, False, "nan", "1e13"):
            with self.subTest(v=bad), self.assertRaisesRegex(Oops, "^The fee must be a number$") as cm:
                self.v.number(bad, "fee")
            self.assertIsNone(cm.exception.__cause__)
            self.assertTrue(cm.exception.__suppress_context__)

    def test_bounds_are_inclusive(self):
        self.assertEqual(self.v.number("0", "fee", 0, 100), 0.0)
        self.assertEqual(self.v.number("$100", "fee", 0, 100), 100.0)
        self.assertEqual(self.v.number(0, "fee", 0, 100), 0.0)
        for bad in ("-0.01", "100.01"):
            with self.subTest(v=bad), self.assertRaisesRegex(Oops, r"^The fee must be between 0 and 100$"):
                self.v.number(bad, "fee", 0, 100)
        with self.assertRaisesRegex(Oops, r"^The fee must be between 0 and 1e\+09$"):
            self.v.number("2e9", "fee", 0, 1e9)

    def test_unbounded_by_default(self):
        self.assertEqual(self.v.number("-1,000", "fee"), -1000.0)
        self.assertEqual(self.v.number("1e12", "fee"), 1e12)

    def test_no_rounding(self):
        self.assertEqual(self.v.number("0.1", "fee"), 0.1)
        self.assertEqual(self.v.number("1.005", "fee"), 1.005)

    def test_custom_templates_and_error(self):
        v = validate.Validator(KeyError, drop="", missing="{label} is missing", not_number="{label}: not a number",
                               out_of_range="{label} is out of range")
        with self.assertRaisesRegex(KeyError, "Rate is missing"):
            v.number(None, "Rate", 0, 1, required=True)
        with self.assertRaisesRegex(KeyError, "Rate: not a number"):
            v.number("1,000", "Rate", 0, 1)
        with self.assertRaisesRegex(KeyError, "Rate is out of range"):
            v.number(2, "Rate", 0, 1)
        self.assertEqual(v.number(True, "Rate", 0, 1), 1.0)

    def test_label_with_braces_is_not_a_template(self):
        with self.assertRaisesRegex(Oops, r"^The \{x\} must be a number$"):
            self.v.number("abc", "{x}")


class IntegerTests(unittest.TestCase):
    v = validate.Validator(Oops)

    def test_whole(self):
        self.assertEqual(self.v.integer("12", "count", 0, 100), 12)
        self.assertIsInstance(self.v.integer("12", "count", 0, 100), int)
        self.assertEqual(self.v.integer("3.0", "count", 0, 100), 3)
        self.assertIsNone(self.v.integer(None, "count", 0, 100))
        self.assertIsNone(self.v.integer("", "count", 0, 100))

    def test_not_whole_is_refused_not_rounded(self):
        with self.assertRaisesRegex(Oops, "^The count must be a whole number$"):
            self.v.integer(1.5, "count", 0, 100)

    def test_range_before_whole(self):
        with self.assertRaisesRegex(Oops, "^The count must be between 0 and 100$"):
            self.v.integer("100.5", "count", 0, 100)
        with self.assertRaisesRegex(Oops, "^The count must be a number$"):
            self.v.integer("x", "count", 0, 100)

    def test_required(self):
        with self.assertRaisesRegex(Oops, "^Enter the count$"):
            self.v.integer(None, "count", 0, 100, required=True)


class TextTests(unittest.TestCase):
    v = validate.Validator(Oops)

    def test_text(self):
        self.assertEqual(self.v.text("  Sapphire  ", "name", 10), "Sapphire")
        self.assertIsNone(self.v.text("   ", "name", 10))
        self.assertIsNone(self.v.text(None, "name", 10))
        self.assertIsNone(self.v.text(0, "name", 10))
        self.assertEqual(self.v.text(12, "name", 10), "12")
        self.assertEqual(self.v.text("a’b – c", "name", 10), "a’b – c")

    def test_limit(self):
        self.assertEqual(self.v.text("x" * 10, "name", 10), "x" * 10)
        with self.assertRaisesRegex(Oops, r"^The name is too long \(at most 10 characters\)$"):
            self.v.text("x" * 11, "name", 10)

    def test_required(self):
        for empty in (None, "", "   ", 0):
            with self.subTest(v=empty), self.assertRaisesRegex(Oops, "^Enter the name$"):
                self.v.text(empty, "name", 10, required=True)


class DayTests(unittest.TestCase):
    v = validate.Validator(Oops)

    def test_day(self):
        self.assertEqual(self.v.day("2026-03-01", "day"), "2026-03-01")
        self.assertEqual(self.v.day(" 2026-03-01 ", "day"), "2026-03-01")
        self.assertIsNone(self.v.day("", "day"))
        self.assertIsNone(self.v.day(None, "day"))

    def test_not_a_day(self):
        for bad in ("2026-13-01", "soon", "2026-02-30"):
            with self.subTest(v=bad), self.assertRaisesRegex(Oops, r"^The day must be a date \(YYYY-MM-DD\)$") as cm:
                self.v.day(bad, "day")
            self.assertIsNone(cm.exception.__cause__)

    def test_required(self):
        for empty in (None, "", "  "):
            with self.subTest(v=empty), self.assertRaisesRegex(Oops, "^Enter the day$"):
                self.v.day(empty, "day", required=True)


class AmountTests(unittest.TestCase):
    v = validate.Validator(Oops, drop="")

    def test_an_amount(self):
        self.assertEqual(self.v.amount("-12.345", "amount"), -12.35)
        self.assertEqual(self.v.amount("-12.345", "amount", cents=False), -12.345)
        self.assertEqual(self.v.amount(999_999_999.99, "amount"), 999_999_999.99)
        self.assertIsNone(self.v.amount("", "amount"))
        with self.assertRaisesRegex(Oops, "^Enter the amount$"):
            self.v.amount(None, "amount", required=True)

    def test_not_an_amount(self):
        for bad in ("nan", "inf", float("nan"), float("-inf"), "abc", True, False, [], {}, "$5"):
            with self.subTest(v=bad), self.assertRaisesRegex(Oops, "^The amount must be a number$"):
                self.v.amount(bad, "amount")

    def test_too_large(self):
        for bad in (validate.MAX_AMOUNT, -validate.MAX_AMOUNT, "1e300", 10 ** 30):
            with self.subTest(v=bad), self.assertRaisesRegex(Oops, "^The amount (is too large|must be a number)$"):
                self.v.amount(bad, "amount")
        with self.assertRaisesRegex(Oops, "^The amount is too large$"):
            self.v.amount("1e10", "amount")


class FlagTests(unittest.TestCase):
    def test_on(self):
        for on in (True, 1, "1", "true", "on", 1.0):
            with self.subTest(v=on):
                self.assertEqual(validate.flag(on), 1)

    def test_off(self):
        for off in (False, 0, "0", "", None, "True", "yes", "ON", "false", 2):
            with self.subTest(v=off):
                self.assertEqual(validate.flag(off), 0)

    def test_on_is_flag_as_a_bool(self):
        for v in (True, 1, "1", "true", "on", False, 0, "0", "false", "no", "off", None, [], {"a": 1}):
            with self.subTest(v=v):
                self.assertIs(validate.on(v), validate.flag(v) == 1)


if __name__ == "__main__":
    unittest.main()
