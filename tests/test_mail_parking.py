import base64
import unittest

from tests.privacy import no_leaks
from waypoint.domain.mail import extract, parking, triage

CANARY = "CANARY-BODY-PARKING-4R8T"
BODY = ("<p>Dear Pat Example,</p><p>Your parking reservation at Example Airport is confirmed.</p>"
        "<table><tr><td>Booking ID: </td><td>EXP-77-1234567</td></tr><tr><td>Entry Date: </td><td>06:30 AM 03/04/2027</td></tr>"
        "<tr><td>Exit Date: </td><td>10:30 AM 03/11/2027</td></tr><tr><td>Booking Date: </td><td>07:44 PM 02/20/2027</td></tr>"
        "<tr><td>Parking Ramp: </td><td>Terminal 2 Garage</td></tr><tr><td>Total: </td><td>$150.00</td></tr></table>"
        "<p>The parking ramp address is Terminal 2, 100 Example Way, St. Paul, MN 55111</p>")

PLAIN = ("Your parking reservation at Example Airport is confirmed.\nBooking ID: EXP-77-1234567\nEntry Date: 06:30 AM 03/04/2027\n"
         "Exit Date: 10:30 AM 03/11/2027\nBooking Date: 07:44 PM 02/20/2027\nParking Ramp: Terminal 2 Garage\n"
         "The parking ramp address is Terminal 2, 100 Example Way, St. Paul, MN 55111\n")


def forwarded(body: str) -> dict:
    raw = ("From: Pat Example <pat@example.test>\nSubject: Fwd: Example Airport Parking Confirmation - EXP-77-1234567\n"
           "Date: Mon, 01 Mar 2027 11:41:48 +0000\nMIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n"
           "---------- Forwarded message ---------\nFrom: <no-reply@parking.example.test>\nDate: Sat, Feb 20, 2027 at 7:45 PM\n"
           "Subject: Example Airport Parking Confirmation - EXP-77-1234567\nTo: Pat Example <pat@example.test>\n\n"
           + body).encode()
    return {"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


class ParkingReaderTests(unittest.TestCase):
    def test_entry_and_exit_rows_give_a_parking_booking_in_the_lots_zone(self):
        with no_leaks(self, CANARY):
            parsed, why = parking.read(f"<html><body>{BODY}<p>{CANARY}</p></body></html>", "")
        self.assertIsNone(why)
        [b] = parsed.bookings
        self.assertEqual((b.kind, b.status, b.confirmation, b.origin, b.destination, b.start, b.end),
                         ("parking", "confirmed", "EXP-77-1234567", "Terminal 2 Garage", None, "2027-03-04T06:30", "2027-03-11T10:30"))
        self.assertEqual((b.start_zone, b.end_zone, dict(b.details)), ("America/Chicago", "America/Chicago", {"address": "Terminal 2, 100 Example Way, St. Paul, MN 55111"}))

    def test_the_booking_date_is_not_taken_for_the_confirmation_code(self):
        [b] = parking.read(f"<html><body>{BODY}</body></html>", "")[0].bookings
        self.assertEqual(b.confirmation, "EXP-77-1234567")

    def test_a_slashed_date_outside_the_us_is_left_unread(self):
        body = BODY.replace("St. Paul, MN 55111", "Toronto, Canada")
        parsed, why = parking.read(f"<html><body>{body}</body></html>", "")
        self.assertEqual(parsed.bookings, ())
        self.assertEqual(why, "no entry date found")

    def test_a_lot_with_no_zone_is_unreadable(self):
        body = BODY.replace("Terminal 2, 100 Example Way, St. Paul, MN 55111", "somewhere").replace("Terminal 2 Garage", "Annex")
        parsed, why = parking.read(f"<html><body>{body}</body></html>", "")
        self.assertEqual((parsed.bookings, why), ((), "parking lot's time zone unknown"))

    def test_a_missing_lot_exit_or_an_exit_before_entry_is_unreadable(self):
        for body, reason in ((BODY.replace("Parking Ramp:", "Spot:"), "no parking lot found"),
                             (BODY.replace("Exit Date: </td><td>10:30 AM 03/11/2027", "Exit Date: </td><td>soon"), "no exit date found"),
                             (BODY.replace("03/11/2027", "03/01/2027"), "exit isn't after entry")):
            with self.subTest(reason=reason):
                parsed, why = parking.read(f"<html><body>{body}</body></html>", "")
                self.assertEqual((parsed.bookings, why), ((), reason))

    def test_a_date_with_a_month_over_twelve_is_unreadable(self):
        parsed, why = parking.read(f"<html><body>{BODY.replace('03/04/2027', '13/45/2027')}</body></html>", "")
        self.assertEqual((parsed.bookings, why), ((), "no entry date found"))

    def test_a_cancellation_gives_a_cancelled_booking_and_a_cancellation_policy_does_not(self):
        cancelled = BODY.replace("is confirmed", "has been cancelled")
        self.assertEqual(parking.read(f"<html><body>{cancelled}</body></html>", "")[0].bookings[0].status, "cancelled")
        policy = BODY + "<p>See our cancellation policy for refunds.</p>"
        self.assertEqual(parking.read(f"<html><body>{policy}</body></html>", "")[0].bookings[0].status, "confirmed")

    def test_separate_entry_and_exit_time_rows_are_used(self):
        body = (BODY.replace("06:30 AM 03/04/2027", "03/04/2027").replace("10:30 AM 03/11/2027", "03/11/2027")
                .replace("<tr><td>Booking Date", "<tr><td>Entry Time: </td><td>06:30 AM</td></tr><tr><td>Exit Time: </td><td>10:30 AM</td></tr><tr><td>Booking Date"))
        [b] = parking.read(f"<html><body>{body}</body></html>", "")[0].bookings
        self.assertEqual((b.start, b.end), ("2027-03-04T06:30", "2027-03-11T10:30"))

    def test_a_bare_lot_label_and_a_lot_address_on_the_next_row_are_read(self):
        body = (BODY.replace("Parking Ramp:", "Lot:").replace("Terminal 2 Garage", "Economy").replace("<p>The parking ramp address is Terminal 2, 100 Example Way, St. Paul, MN 55111</p>", "")
                .replace("Dear Pat Example", "Pat").replace("Your parking reservation at Example Airport is confirmed.", "Booked.")
                + "<table><tr><td>Lot address:</td></tr><tr><td>100 Example Way, St. Paul, MN 55111</td></tr></table>")
        [b] = parking.read(f"<html><body>{body}</body></html>", "")[0].bookings
        self.assertEqual((b.origin, b.start_zone, dict(b.details)["address"]), ("Economy", "America/Chicago", "100 Example Way, St. Paul, MN 55111"))

    def test_an_impossible_us_date_is_unreadable_not_an_error(self):
        parsed, why = parking.read(f"<html><body>{BODY.replace('03/04/2027', '02/30/2027')}</body></html>", "")
        self.assertEqual((parsed.bookings, why), ((), "no entry date found"))

    def test_a_hotel_stay_with_a_parking_garage_is_not_a_parking_booking(self):
        html = ("<p>Check-in date: Mar 4, 2027</p><p>Check-out date: Mar 6, 2027</p><p>Parking garage: Main Street Garage</p>"
                "<p>Garage address: 100 Example Way, St. Paul, MN 55111</p>")
        self.assertEqual(parking.read(html, ""), (parking.Parsed(), ""))

    def test_a_hotel_email_that_mentions_parking_is_not_a_parking_booking(self):
        html = "<p>Your stay</p><p>Check-in: Mar 4, 2027</p><p>Check-out: Mar 6, 2027</p><p>Free parking on site.</p>"
        self.assertEqual(parking.read(html, ""), (parking.Parsed(), ""))

    def test_a_forwarded_confirmation_is_read_from_the_original(self):
        message = extract.read(forwarded(PLAIN))
        self.assertEqual([b.kind for b in message.bookings], ["parking"])
        self.assertEqual(message.forwarded_by, "example.test")


class ParkingTriageTests(unittest.TestCase):
    def test_a_parking_confirmation_from_an_unknown_sender_is_read(self):
        head = triage.Head("Fwd: Example Airport Parking Confirmation - EXP-77-1234567", "example.test", "Forwarded message Booking Confirmation", frozenset())
        self.assertEqual(triage.decide(head), "read")

    def test_a_parking_confirmation_is_a_strong_signal_so_an_unreadable_one_reaches_review(self):
        head = triage.Head("Parking reservation confirmation", "example.test", "", frozenset())
        self.assertTrue(triage.strong(head))

    def test_a_parking_ticket_notice_is_still_skipped(self):
        head = triage.Head("Your parking ticket", "example.test", "Pay your fine online", frozenset())
        self.assertEqual(triage.decide(head), "skip")


if __name__ == "__main__":
    unittest.main()
