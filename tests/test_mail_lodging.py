import unittest

from waypoint.domain.mail.parsers import lodging


def read(body: str):
    parsed, why = lodging.read(f"<html><body>{body}</body></html>", "")
    return parsed.bookings, why


class LodgingReaderTests(unittest.TestCase):
    def test_labelled_values_in_table_cells_and_lines(self):
        [b], why = read("<table><tr><td>Check-in</td><td>2026-11-21 3:00 PM</td></tr><tr><td>Check-out</td><td>2026-11-24</td></tr></table>"
                        "<p>Hotel: Harbour Inn</p><p>Address: 1 Quay Street, London</p><p>Reservation number: ab12cd34</p>")
        self.assertIsNone(why)
        self.assertEqual((b.kind, b.provider, b.confirmation, b.start, b.end), ("hotel", "Harbour Inn", "AB12CD34", "2026-11-21T15:00", "2026-11-24T11:00"))
        self.assertEqual(dict(b.details), {"address": "1 Quay Street, London", "time_unknown": "yes"})
        self.assertEqual(dict(b.generic)["start_local"], "check-in")

    def test_a_stay_with_both_times_is_not_marked_untimed(self):
        [b], _ = read("<p>Hotel: Inn</p><p>Check-in: 2026-11-21 14:00</p><p>Check-out: 2026-11-22 10:30</p>")
        self.assertEqual((b.start, b.end, dict(b.details)), ("2026-11-21T14:00", "2026-11-22T10:30", {}))

    def test_japanese_labels_and_dates(self):
        [b], _ = read("<p>ホテル名: テストホテル</p><p>チェックイン: 2026年11月21日 15時</p><p>チェックアウト: 2026年11月23日 10:00</p><p>予約番号: JP12345</p>")
        self.assertEqual((b.provider, b.start, b.end, b.confirmation), ("テストホテル", "2026-11-21T15:00", "2026-11-23T10:00", "JP12345"))

    def test_a_package_gives_a_start_date_and_nights(self):
        [b], _ = read("<p>Hotel: Inn</p><p>Check-in: Nov 21, 2026</p><p>3 nights</p>")
        self.assertEqual(b.end[:10], "2026-11-24")
        [b], _ = read("<p>ホテル名: テストホテル</p><p>チェックイン: 2026/11/21</p><p>宿泊数: 2泊</p>")
        self.assertEqual(b.end[:10], "2026-11-23")

    def test_dates_in_cancellation_text_are_ignored(self):
        [b], _ = read("<p>Check-out by noon. Cancel free before Check-in 2026-10-01</p><p>Hotel: Inn</p><p>Check-in: 2026-11-21</p><p>Check-out: 2026-11-22</p>")
        self.assertEqual((b.start[:10], b.end[:10]), ("2026-11-21", "2026-11-22"))

    def test_what_cannot_be_read_gets_a_reason(self):
        for body, why in (("<p>Check-in: 2026-11-21</p><p>Check-out: 2026-11-22</p>", "no hotel name found"),
                          ("<p>Hotel: Inn</p><p>Check-in: someday</p>", "check-in isn't a date"),
                          ("<p>Hotel: Inn</p><p>Check-in: 2026-11-21</p>", "no check-out date found"),
                          ("<p>Hotel: Inn</p><p>Check-in: 2026-11-21</p><p>Check-out: 2026-11-21</p>", "check-out isn't after check-in"),
                          ("<p>Hotel: Inn</p><p>Check-in: 2026-11-01</p><p>Check-out: 2027-01-02</p>", "stay is longer than 60 nights"),
                          ("<p>Hotel: Inn</p><p>Check-in: 2026-02-31</p><p>Check-out: 2026-03-02</p>", "check-in isn't a date")):
            with self.subTest(why):
                self.assertEqual(read(body), ((), why))

    def test_mail_with_no_check_in_is_not_a_lodging_mail(self):
        self.assertEqual(read("<p>Hello, here is your newsletter</p>"), ((), ""))
