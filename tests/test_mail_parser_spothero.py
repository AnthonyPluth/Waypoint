import base64
import unittest
from pathlib import Path
from unittest import mock

from tests.privacy import no_leaks
from tests.test_mail_scan import NOW, ScanCase
from waypoint.domain.mail import extract, parsers, query, triage
from waypoint.domain.mail.booking import Parsed
from waypoint.domain.mail.parsers import spothero

FIXTURES = Path(__file__).parent / "fixtures" / "mail" / "spothero"
LOT = "Example Plaza Garage"
CANARIES = ("CANARY-BODY-SPOTHERO-BOOKING-6P2D", "CANARY-BODY-SPOTHERO-CHANGE-8K4F", "CANARY-BODY-SPOTHERO-CANCEL-3W7R", "CANARY-PLATE-SPOTHERO-5M9X")


def raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.eml").read_bytes()


def read(data: bytes) -> extract.Message:
    return extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(data).decode().rstrip("=")})


def page(range_line: str, lot: str = LOT, extra: str = "") -> str:
    return f"{extra}Rental ID: 100200300\n{lot}\n{range_line}\n(555) 010-0100\nEnter at: 1 Example Avenue Get Directions\n"


class ParserTests(unittest.TestCase):
    def test_a_booking_is_a_parking_stay_with_the_year_worked_out_from_the_weekday(self):
        m = read(raw("booking"))
        self.assertEqual((m.sender_domain, m.received, m.unread, m.markup, m.broken), ("spothero.com", "2027-03-01", 0, True, False))
        [b] = m.bookings
        self.assertEqual((b.kind, b.status, b.confirmation, b.provider, b.origin, b.destination, b.start, b.end),
                         ("parking", "confirmed", "100200300", "SpotHero", LOT, None, "2027-03-05T15:00:00", "2027-03-09T15:00:00"))
        self.assertEqual((dict(b.details), b.start_zone, b.end_zone), ({"address": "1 Example Avenue", "phone": "(555) 010-0100"}, None, None))

    def test_the_vehicle_and_its_plate_are_not_kept(self):
        [b] = read(raw("booking")).bookings
        self.assertNotIn("CANARY-PLATE-SPOTHERO-5M9X", repr(b))
        self.assertNotIn("vehicle", dict(b.details))

    def test_a_change_is_the_same_booking_with_its_new_times(self):
        [b] = read(raw("change")).bookings
        self.assertEqual((b.status, b.confirmation, b.start, b.end), ("confirmed", "100200300", "2027-03-06T09:00:00", "2027-03-10T09:00:00"))

    def test_a_cancellation_comes_out_cancelled_and_a_cancellation_policy_does_not(self):
        self.assertEqual(read(raw("cancellation")).bookings[0].status, "cancelled")
        self.assertEqual(read(raw("booking")).bookings[0].status, "confirmed")

    def test_a_stay_over_the_new_year_ends_in_the_next_one(self):
        [b] = spothero.parse("", page("Wed Dec 30, 9:00 AM - Sat Jan 2, 9:00 AM"), "2026-12-01").bookings
        self.assertEqual((b.start, b.end), ("2026-12-30T09:00:00", "2027-01-02T09:00:00"))

    def test_a_weekday_that_does_not_fit_the_date_is_unread_not_guessed_at(self):
        self.assertEqual(spothero.parse("", page("Mon Dec 30, 9:00 AM - Sat Jan 2, 9:00 AM"), "2026-12-01"), Parsed((), 1))

    def test_without_the_day_the_email_came_the_year_cannot_be_told(self):
        for received in (None, "", "soon"):
            with self.subTest(received=received):
                self.assertEqual(spothero.parse("", page("Fri Mar 5, 3:00 PM - Tue Mar 9, 3:00 PM"), received), Parsed((), 1))

    def test_a_date_that_does_not_exist_or_an_exit_before_entry_is_unread(self):
        for line in ("Fri Feb 30, 3:00 PM - Tue Mar 9, 3:00 PM", "Fri Mar 5, 3:00 PM - Fri Mar 5, 3:00 PM", "Fri Mar 5, 13:00 PM - Tue Mar 9, 3:00 PM"):
            with self.subTest(line=line):
                self.assertEqual(spothero.parse("", page(line), "2027-03-01"), Parsed((), 1))

    def test_a_range_with_no_lot_above_it_is_unread(self):
        self.assertEqual(spothero.parse("", "Fri Mar 5, 3:00 PM - Tue Mar 9, 3:00 PM\n", "2027-03-01"), Parsed((), 1))
        self.assertEqual(spothero.parse("", page("Fri Mar 5, 3:00 PM - Tue Mar 9, 3:00 PM", lot="Rental ID: 100200300"), "2027-03-01"), Parsed((), 1))

    def test_a_very_long_line_above_the_range_is_cut_to_a_lot_name(self):
        [b] = spothero.parse("", page("Fri Mar 5, 3:00 PM - Tue Mar 9, 3:00 PM", lot="L" * 5000), "2027-03-01").bookings
        self.assertEqual(b.origin, "L" * spothero.LOT_LIMIT)

    def test_an_email_without_a_range_finds_nothing(self):
        self.assertEqual(spothero.parse("<p>Hello</p>", "", "2027-03-01"), Parsed())

    def test_a_parser_is_found_by_the_sender_domain_and_its_subdomains(self):
        for domain in ("spothero.com", "mail.spothero.com"):
            self.assertIs(parsers.for_sender(domain), spothero.parse)
        for domain in ("notspothero.com", "spothero.com.example", "privaterelay.appleid.com"):
            self.assertIsNone(parsers.for_sender(domain))


class TriageTests(unittest.TestCase):
    def test_spothero_mail_is_read_on_its_sender_alone(self):
        self.assertIn("spothero.com", query.SENDERS)
        for domain in ("spothero.com", extract._domain("x_at_spothero_com_ab12cd34ef_a1b2c3d4@privaterelay.appleid.com")):
            self.assertEqual(triage.decide(triage.Head("Reservation Confirmed", domain, "Happy Parking!", frozenset())), "read")


class RelayTests(unittest.TestCase):
    def test_a_hide_my_email_address_gives_the_domain_it_forwards_for(self):
        for address, domain in (("support_at_spothero_com_ab12cd34ef_a1b2c3d4@privaterelay.appleid.com", "spothero.com"),
                                ("no-reply_at_info_email_aa_com_zz99yy88xx_q1w2e3r4@privaterelay.appleid.com", "info.email.aa.com")):
            with self.subTest(address=address):
                self.assertEqual(extract._domain(f"Someone <{address}>"), domain)

    def test_an_address_that_only_looks_like_a_relay_keeps_its_own_domain(self):
        for address, domain in (("support_at_spothero_com_ab12cd34ef_a1b2c3d4@evil.example", "evil.example"),
                                ("friend@privaterelay.appleid.com", "privaterelay.appleid.com"),
                                ("a_at_spothero_com@privaterelay.appleid.com", "privaterelay.appleid.com")):
            with self.subTest(address=address):
                self.assertEqual(extract._domain(address), domain)

    def test_an_ordinary_sender_is_unchanged(self):
        self.assertEqual(extract._domain("SpotHero <hello@spothero.com>"), "spothero.com")


class ExtractTests(unittest.TestCase):
    def test_a_parser_that_raises_leaves_the_message_unread_and_reports_without_its_values(self):
        with mock.patch.dict(parsers.PARSERS, {"spothero.com": mock.Mock(side_effect=RuntimeError("CANARY-PARSER-BUG-7H3Q"))}), \
                mock.patch.object(extract.monitoring, "report") as report:
            m = read(raw("booking"))
        self.assertEqual((m.bookings, m.unread), ((), 1))
        report.assert_called_once()
        self.assertEqual(report.call_args.kwargs, {"values": False})


class ScanTests(ScanCase):
    def test_a_booking_without_a_city_waits_in_review_for_the_missing_zone(self):
        self.put("spothero/booking")
        result = self.scan()
        self.assertEqual((result.messages, result.bookings, result.review), (1, 0, 1))
        self.assertEqual(self.segments(), [])
        [item] = self.items()
        self.assertEqual((item["reason"], item["sender_domain"]), ("incomplete", "spothero.com"))

    def test_a_booking_whose_address_names_its_state_is_filed_in_the_lots_zone(self):
        self.add_mail("with-state", raw("booking").replace(b"1 Example Avenue", b"1 Example Avenue, Austin, TX 78701"))
        result = self.scan()
        self.assertEqual((result.bookings, result.review), (1, 0))
        [s] = self.segments()
        self.assertEqual((s["kind"], s["origin"], s["start_local"], s["start_zone"], s["end_local"], s["confirmation"]),
                         ("parking", LOT, "2027-03-05T15:00", "America/Chicago", "2027-03-09T15:00", "100200300"))

    def test_a_change_then_a_cancellation_update_the_same_booking(self):
        state = b"1 Example Avenue, Austin, TX 78701"
        self.add_mail("a", raw("booking").replace(b"1 Example Avenue", state))
        self.scan()
        self.add_mail("b", raw("change").replace(b"1 Example Avenue", state))
        self.scan(now=NOW + 3600)
        [s] = self.segments()
        self.assertEqual((s["start_local"], s["status"]), ("2027-03-06T09:00", "changed"))
        self.add_mail("c", raw("cancellation").replace(b"1 Example Avenue", state))
        self.scan(now=NOW + 7200)
        [s] = self.segments()
        self.assertEqual(s["status"], "cancelled")

    def test_nothing_of_the_email_is_kept_logged_or_sent(self):
        self.put("spothero/booking")
        self.add_mail("change", raw("change"))
        self.add_mail("cancel", raw("cancellation"))
        with no_leaks(self, *CANARIES, database=self.path):
            result = self.scan()
        self.assertEqual((result.state, result.messages), ("done", 3))

    def test_the_canaries_are_really_in_the_fixtures(self):
        text = "".join(p.read_text() for p in FIXTURES.glob("*.eml"))
        for canary in CANARIES:
            self.assertIn(canary, text)


if __name__ == "__main__":
    unittest.main()
