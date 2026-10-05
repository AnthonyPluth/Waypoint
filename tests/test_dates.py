"""Calendar arithmetic (waypoint/dates.py): months of different lengths, leap years, going back, and year ends."""
import unittest
from datetime import date

from waypoint import dates


class ParseTests(unittest.TestCase):
    def test_a_date_or_the_date_a_timestamp_starts_with(self):
        self.assertEqual(dates.parse_day("2026-09-23"), date(2026, 9, 23))
        self.assertEqual(dates.parse_day("2026-09-23T23:59:59Z"), date(2026, 9, 23))
        self.assertEqual(dates.parse_day("2026-09-23 08:00:00"), date(2026, 9, 23))
        for bad in ("", "2026-9-3", "2026-02-30", "soon"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dates.parse_day(bad)


class ClampTests(unittest.TestCase):
    def test_a_day_the_month_doesnt_have_is_its_last(self):
        self.assertEqual(dates.clamp_day(2026, 2, 31), date(2026, 2, 28))
        self.assertEqual(dates.clamp_day(2028, 2, 31), date(2028, 2, 29))
        self.assertEqual(dates.clamp_day(2028, 2, 29), date(2028, 2, 29))
        self.assertEqual(dates.clamp_day(2027, 2, 29), date(2027, 2, 28))
        self.assertEqual(dates.clamp_day(2100, 2, 29), date(2100, 2, 28))
        self.assertEqual(dates.clamp_day(2000, 2, 29), date(2000, 2, 29))
        self.assertEqual(dates.clamp_day(2026, 4, 31), date(2026, 4, 30))
        self.assertEqual(dates.clamp_day(2026, 12, 31), date(2026, 12, 31))
        self.assertEqual(dates.clamp_day(2026, 6, 1), date(2026, 6, 1))

    def test_month_end(self):
        self.assertEqual([dates.month_end(date(2026, m, 15)).day for m in range(1, 13)],
                         [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
        self.assertEqual(dates.month_end(date(2028, 2, 1)), date(2028, 2, 29))
        self.assertEqual(dates.month_end(date(2026, 1, 31)), date(2026, 1, 31))


class MonthLengthAndGapTests(unittest.TestCase):
    def test_days_in_month(self):
        self.assertEqual([dates.days_in_month(date(2026, m, 1)) for m in range(1, 13)],
                         [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
        self.assertEqual(dates.days_in_month(date(2028, 2, 10)), 29)

    def test_months_between_counts_calendar_months_whatever_the_days(self):
        self.assertEqual(dates.months_between(date(2026, 1, 31), date(2026, 3, 1)), 2)
        self.assertEqual(dates.months_between(date(2025, 11, 15), date(2026, 2, 1)), 3)
        self.assertEqual(dates.months_between(date(2026, 5, 1), date(2026, 5, 31)), 0)
        self.assertEqual(dates.months_between(date(2026, 3, 1), date(2025, 12, 31)), -3)


class AddMonthsTests(unittest.TestCase):
    def test_the_same_day_or_the_months_last(self):
        self.assertEqual(dates.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(dates.add_months(date(2028, 1, 31), 1), date(2028, 2, 29))
        self.assertEqual(dates.add_months(date(2026, 1, 31), 2), date(2026, 3, 31))
        self.assertEqual(dates.add_months(date(2026, 3, 31), 1), date(2026, 4, 30))
        self.assertEqual(dates.add_months(date(2028, 2, 29), 12), date(2029, 2, 28))
        self.assertEqual(dates.add_months(date(2028, 2, 29), 48), date(2032, 2, 29))
        self.assertEqual(dates.add_months(date(2026, 9, 23), 0), date(2026, 9, 23))

    def test_across_the_year_end(self):
        self.assertEqual(dates.add_months(date(2026, 12, 15), 1), date(2027, 1, 15))
        self.assertEqual(dates.add_months(date(2026, 11, 30), 3), date(2027, 2, 28))
        self.assertEqual(dates.add_months(date(2026, 12, 31), 14), date(2028, 2, 29))
        self.assertEqual(dates.add_months(date(2026, 1, 10), 24), date(2028, 1, 10))

    def test_going_back(self):
        self.assertEqual(dates.add_months(date(2026, 3, 31), -1), date(2026, 2, 28))
        self.assertEqual(dates.add_months(date(2028, 3, 31), -1), date(2028, 2, 29))
        self.assertEqual(dates.add_months(date(2026, 1, 15), -1), date(2025, 12, 15))
        self.assertEqual(dates.add_months(date(2026, 1, 31), -13), date(2024, 12, 31))
        self.assertEqual(dates.add_months(date(2026, 5, 31), -3), date(2026, 2, 28))

    def test_on_another_day(self):
        self.assertEqual(dates.add_months(date(2026, 1, 5), 1, 31), date(2026, 2, 28))
        self.assertEqual(dates.add_months(date(2026, 2, 28), 1, 31), date(2026, 3, 31))
        self.assertEqual(dates.add_months(date(2026, 12, 5), 1, 10), date(2027, 1, 10))
        self.assertEqual(dates.add_months(date(2026, 3, 5), -1, 30), date(2026, 2, 28))

    def test_the_calendars_ends(self):
        self.assertEqual(dates.add_months(date(9999, 11, 30), 1), date(9999, 12, 30))
        with self.assertRaises(ValueError):
            dates.add_months(date(9999, 12, 1), 1)
        with self.assertRaises(ValueError):
            dates.add_months(date(1, 1, 1), -1)


class MonthStartTests(unittest.TestCase):
    def test_the_first_of_a_month_before_or_after(self):
        self.assertEqual(dates.month_start(date(2026, 9, 23)), date(2026, 9, 1))
        self.assertEqual(dates.month_start(date(2026, 1, 31), 1), date(2026, 2, 1))
        self.assertEqual(dates.month_start(date(2026, 12, 31), 1), date(2027, 1, 1))
        self.assertEqual(dates.month_start(date(2026, 1, 31), -1), date(2025, 12, 1))
        self.assertEqual(dates.month_start(date(2026, 3, 15), -6), date(2025, 9, 1))
        self.assertEqual(dates.month_start(date(2026, 3, 15), 1200).year, 2126)


class NextAfterTests(unittest.TestCase):
    def test_strictly_after(self):
        self.assertEqual(dates.next_after(date(2026, 9, 5), 2), date(2026, 10, 2))
        self.assertEqual(dates.next_after(date(2026, 9, 5), 5), date(2026, 10, 5))
        self.assertEqual(dates.next_after(date(2026, 9, 5), 30), date(2026, 9, 30))
        self.assertEqual(dates.next_after(date(2026, 1, 31), 31), date(2026, 2, 28))
        self.assertEqual(dates.next_after(date(2026, 2, 28), 31), date(2026, 3, 31))
        self.assertEqual(dates.next_after(date(2028, 2, 28), 31), date(2028, 2, 29))
        self.assertEqual(dates.next_after(date(2026, 12, 20), 10), date(2027, 1, 10))
        self.assertEqual(dates.next_after(date(2026, 12, 31), 31), date(2027, 1, 31))


class MonthKeyTests(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(dates.month_key(date(2026, 9, 23)), "2026-09")
        self.assertEqual(dates.key_start("2026-09"), date(2026, 9, 1))
        self.assertEqual(dates.next_month_key("2026-09"), "2026-10")
        self.assertEqual(dates.next_month_key("2026-12"), "2027-01")

    def test_the_months_ending_with_one(self):
        self.assertEqual(dates.month_keys(date(2026, 2, 28), 4), ["2025-11", "2025-12", "2026-01", "2026-02"])
        self.assertEqual(dates.month_keys(date(2026, 12, 31), 1), ["2026-12"])
        self.assertEqual(dates.month_keys(date(2026, 3, 31), 0), [])
        keys = dates.month_keys(date(2026, 9, 1), 24)
        self.assertEqual((len(keys), keys[0], keys[-1]), (24, "2024-10", "2026-09"))
        self.assertEqual(keys, sorted(set(keys)))
