"""The Southwest parser (waypoint/domain/mail/parsers/southwest.py) and what a scan does with its bookings, change and
cancellation emails, from synthetic emails in tests/fixtures/mail/southwest (invented names, codes and numbers; real
airports). The parser registry and `extract.read`'s use of it are held here too."""
import base64
import unittest
from pathlib import Path
from unittest import mock

from tests.privacy import no_leaks
from tests.test_mail_scan import NOW, ScanCase
from waypoint.domain import trips
from waypoint.domain.mail import extract, parsers
from waypoint.domain.mail.booking import Passenger
from waypoint.domain.mail.parsers import southwest

FIXTURES = Path(__file__).parent / "fixtures" / "mail" / "southwest"
CANARIES = ("CANARY-BODY-SOUTHWEST-BOOKING-4D8Q", "CANARY-BODY-SOUTHWEST-CHANGE-9H3T", "CANARY-BODY-SOUTHWEST-CANCEL-2M6V")
OUTBOUND, RETURN = "2026-11-16T08:05:00", "2026-11-20T23:50:00"


def raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.eml").read_bytes()


def read(data: bytes) -> extract.Message:
    return extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(data).decode().rstrip("=")})


def mail(body: str, sender: str = "Southwest Airlines <southwestairlines@luv.southwest.com>", ctype: str = "text/html") -> bytes:
    return (f"From: {sender}\nSubject: x\nDate: Tue, 06 Oct 2026 10:00:00 -0500\nMIME-Version: 1.0\n"
            f"Content-Type: {ctype}; charset=utf-8\n\n{body}").encode()


class ParserTests(unittest.TestCase):
    def test_a_booking_is_two_flights_at_their_airports_wall_clock_times(self):
        m = read(raw("booking"))
        self.assertEqual((m.sender_domain, m.received, m.unread, m.markup, m.broken), ("luv.southwest.com", "2026-10-06", 0, True, False))
        out, back = m.bookings
        self.assertEqual((out.kind, out.status, out.confirmation, out.provider, out.origin, out.destination, out.start, out.end),
                         ("flight", "confirmed", "K7QW2N", "Southwest Airlines", "DAL", "HOU", OUTBOUND, "2026-11-16T09:10:00"))
        self.assertEqual(dict(out.details), {"flight_number": "WN 1234"})
        self.assertEqual(out.passengers, (Passenger("JANE DOE", "55512340011"),))
        self.assertEqual((back.origin, back.destination, back.start, back.end), ("HOU", "DAL", RETURN, "2026-11-21T00:55:00"))   # (+1 day)

    def test_a_change_is_the_same_booking_with_its_new_times(self):
        out, back = read(raw("change")).bookings
        self.assertEqual((out.status, out.confirmation, out.start, out.end), ("confirmed", "K7QW2N", "2026-11-16T09:30:00", "2026-11-16T10:35:00"))
        self.assertEqual((back.start, back.end), (RETURN, "2026-11-21T00:55:00"))

    def test_a_cancellation_comes_out_cancelled_for_each_flight(self):
        found = read(raw("cancellation")).bookings
        self.assertEqual([(b.status, b.confirmation, b.start) for b in found],
                         [("cancelled", "K7QW2N", "2026-11-16T09:30:00"), ("cancelled", "K7QW2N", RETURN)])

    def test_cancellation_words_in_a_footer_dont_cancel_a_booking(self):
        text = ("Your trip is confirmed\nConfirmation #: K7QW2N\nPassenger: JANE DOE\nFlight 77 Mon, Nov 16, 2026\n"
                "Dallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM\n"
                "If your flight has been canceled, we will rebook you.\nCancellation confirmation numbers are sent separately.\n")
        [b] = read(mail(text, ctype="text/plain")).bookings
        self.assertEqual(b.status, "confirmed")

    def test_a_plain_text_email_is_read_the_same_way(self):
        text = ("Your reservation has been canceled.\nConfirmation #: K7QW2N\nPassenger: JANE DOE\nFlight 77 Mon, Nov 16, 2026\n"
                "Dallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM\n")
        [b] = read(mail(text, ctype="text/plain")).bookings
        self.assertEqual((b.status, b.start, dict(b.details)), ("cancelled", OUTBOUND, {"flight_number": "WN 77"}))

    def test_a_rewards_number_is_kept_only_for_a_booking_with_one_traveller(self):
        text = ("Confirmation #: K7QW2N\nPassenger 1: JANE DOE\nPassenger 2: SAM DOE\nRapid Rewards #: 55512340011\nFlight 77 Mon, Nov 16, 2026\n"
                "Dallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM\n")
        [b] = read(mail(text, ctype="text/plain")).bookings
        self.assertEqual(b.passengers, (Passenger("JANE DOE"), Passenger("SAM DOE")))

    def test_a_leg_that_doesnt_fit_is_counted_unread_not_guessed_at(self):
        for leg in ("Flight 77 Mon, Foo 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM",   # no such month
                    "Flight 77 Mon, Feb 31, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM",   # no such day
                    "Flight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 13:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM",   # no such time
                    "Flight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM",   # no arrival
                    "Flight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX 8:05 AM\nHouston (Hobby), TX 9:10 AM"):   # no airports
            with self.subTest(leg=leg):
                self.assertEqual(southwest.parse("", f"Confirmation #: K7QW2N\n{leg}\n"), parsers.Parsed((), 1))

    def test_an_arrival_that_would_come_before_the_departure_is_unread(self):
        leg = "Flight 77 Mon, Nov 16, 2026\nHouston (Hobby), TX (HOU) 11:50 PM\nDallas (Love Field), TX (DAL) 12:55 AM{}\n"
        self.assertEqual(southwest.parse("", "Confirmation #: K7QW2N\n" + leg.format("")), parsers.Parsed((), 1))
        [b] = southwest.parse("", "Confirmation #: K7QW2N\n" + leg.format(" (+1 day)")).bookings
        self.assertEqual((b.start, b.end), ("2026-11-16T23:50:00", "2026-11-17T00:55:00"))

    def test_a_leg_without_a_confirmation_code_is_unread(self):
        self.assertEqual(southwest.parse("", "Flight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\n"
                                             "Houston (Hobby), TX (HOU) 9:10 AM\n"), parsers.Parsed((), 1))

    def test_the_same_leg_twice_is_one_booking(self):
        leg = "Flight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM\n"
        self.assertEqual(len(southwest.parse("", f"Confirmation #: K7QW2N\n{leg}{leg}").bookings), 1)

    def test_an_email_without_flights_finds_nothing_and_a_flood_of_them_is_capped(self):
        self.assertEqual(southwest.parse("<p>Hello</p>", ""), parsers.Parsed())
        leg = "Flight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM\n"
        found = southwest.parse("", "Confirmation #: K7QW2N\n" + leg.replace("Nov 16", "Foo 16") * 200)
        self.assertEqual((found.bookings, found.unread), ((), southwest.MAX_LEGS))

    def test_html_that_cannot_be_parsed_finds_nothing(self):
        with mock.patch.object(southwest, "lines", side_effect=lambda h, t: []):
            self.assertEqual(southwest.parse("<<<", ""), parsers.Parsed())
        self.assertEqual(southwest.parse("<table><tr><td>", ""), parsers.Parsed())

    def test_a_parser_is_found_by_the_sender_domain_and_its_subdomains(self):
        for domain in ("southwest.com", "luv.southwest.com"):
            self.assertIs(parsers.for_sender(domain), southwest.parse)
        for domain in ("notsouthwest.com", "southwest.com.example", "example.com", "", None):
            self.assertIsNone(parsers.for_sender(domain))


class ExtractTests(unittest.TestCase):
    def test_markup_that_gives_a_booking_is_used_instead_of_the_parser(self):
        jsonld = ('<script type="application/ld+json">{"@type":"FlightReservation","reservationNumber":"ZZ9999",'
                  '"reservationFor":{"@type":"Flight","flightNumber":"WN 5","airline":{"iataCode":"WN","name":"Southwest Airlines"},'
                  '"departureAirport":{"iataCode":"DAL"},"departureTime":"2026-11-16T08:05:00",'
                  '"arrivalAirport":{"iataCode":"HOU"},"arrivalTime":"2026-11-16T09:10:00"}}</script>'
                  "Confirmation #: K7QW2N\nFlight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM")
        with mock.patch.dict(parsers.PARSERS, {"southwest.com": mock.Mock(side_effect=AssertionError("the parser isn't needed"))}):
            [b] = read(mail(f"<html><head>{jsonld}</head><body></body></html>")).bookings
        self.assertEqual(b.confirmation, "ZZ9999")

    def test_a_sender_without_a_parser_is_left_alone(self):
        text = "Confirmation #: K7QW2N\nFlight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\nHouston (Hobby), TX (HOU) 9:10 AM\n"
        m = read(mail(text, sender="Someone <a@other.example>", ctype="text/plain"))
        self.assertEqual((m.bookings, m.markup, m.unread), ((), False, 0))

    def test_a_parser_that_raises_leaves_the_message_unread_and_reports_without_its_values(self):
        with mock.patch.dict(parsers.PARSERS, {"southwest.com": mock.Mock(side_effect=RuntimeError("CANARY-PARSER-BUG-5J2X"))}), \
                mock.patch.object(extract.monitoring, "report") as report:
            m = read(raw("booking"))
        self.assertEqual((m.bookings, m.unread, m.markup), ((), 1, True))
        report.assert_called_once()
        self.assertEqual(report.call_args.kwargs, {"values": False})

    def test_a_southwest_email_with_a_leg_that_doesnt_fit_is_recognised_but_unread(self):
        m = read(mail("Confirmation #: K7QW2N\nFlight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\n", ctype="text/plain"))
        self.assertEqual((m.bookings, m.unread, m.markup), ((), 1, True))


class ScanTests(ScanCase):
    def times(self, viewer=None):
        return sorted((s["start_local"], s["status"]) for s in self.segments(viewer))

    def test_a_booking_becomes_two_segments_in_the_airports_zones_for_the_traveller_it_names(self):
        self.put("southwest/booking")
        result = self.scan()
        self.assertEqual((result.state, result.messages, result.bookings, result.review), ("done", 1, 2, 0))
        out, back = sorted(self.segments(), key=lambda s: s["start_local"])
        self.assertEqual((out["start_local"], out["start_zone"], out["end_local"], out["end_zone"], out["origin"], out["destination"]),
                         ("2026-11-16T08:05", "America/Chicago", "2026-11-16T09:10", "America/Chicago", "DAL", "HOU"))
        self.assertEqual((back["start_local"], back["end_local"], back["confirmation"], back["source"]),
                         ("2026-11-20T23:50", "2026-11-21T00:55", "K7QW2N", "email"))
        self.assertEqual(out["details"], {"flight_number": "WN 1234"})
        self.assertEqual([t["person_id"] for t in out["travelers"]], [self.jane.person_id])   # (JANE DOE is Jane, by name)

    def test_a_change_moves_the_times_and_marks_the_flight_changed_but_not_the_one_that_didnt_move(self):
        self.put("southwest/booking")
        self.scan()
        self.add_mail("change", raw("change"))
        self.scan(now=NOW + 3600)
        self.assertEqual(self.times(), [("2026-11-16T09:30", "changed"), ("2026-11-20T23:50", "confirmed")])

    def test_a_change_keeps_what_a_person_edited(self):
        self.put("southwest/booking")
        self.scan()
        out = min(self.segments(), key=lambda s: s["start_local"])
        edited = self.read(lambda conn: trips.edit_segment(conn, self.jane, out["id"], {
            "start_local": "2026-11-16T07:45", "details": {"flight_number": "WN 1234", "seat": "12A"}}))
        assert edited is not None
        self.assertEqual(edited["locked_fields"], ["details", "start_local"])
        self.add_mail("change", raw("change"))
        self.scan(now=NOW + 3600)
        after = next(s for s in self.segments() if s["id"] == out["id"])
        self.assertEqual((after["start_local"], after["details"]["seat"], after["end_local"], after["status"]),
                         ("2026-11-16T07:45", "12A", "2026-11-16T10:35", "confirmed"))   # (the email moved the arrival only)

    def test_a_cancellation_after_a_change_cancels_both_flights_and_keeps_the_changed_times(self):
        self.put("southwest/booking")
        self.scan()
        self.add_mail("change", raw("change"))
        self.scan(now=NOW + 3600)
        self.add_mail("cancel", raw("cancellation"))
        result = self.scan(now=NOW + 7200)
        self.assertEqual((result.bookings, result.review), (2, 0))
        self.assertEqual(self.times(), [("2026-11-16T09:30", "cancelled"), ("2026-11-20T23:50", "cancelled")])
        self.assertEqual(len(self.segments()), 2)   # (cancelled, not added again)

    def test_a_cancellation_leaves_a_status_a_person_set_alone(self):
        self.put("southwest/booking")
        self.scan()
        out = min(self.segments(), key=lambda s: s["start_local"])
        self.read(lambda conn: trips.edit_segment(conn, self.jane, out["id"], {"status": "changed"}))
        self.add_mail("cancel", raw("cancellation"))
        self.scan(now=NOW + 3600)
        after = {s["id"]: s["status"] for s in self.segments()}
        self.assertEqual(after[out["id"]], "changed")
        self.assertEqual(sorted(after.values()), ["cancelled", "changed"])

    def test_a_cancellation_in_another_household_mailbox_cancels_the_same_booking_and_shows_it_to_that_owner(self):
        self.put("southwest/booking")
        self.scan()
        before = self.segments(self.jane)
        sam_box = self.connect("u-sam", "sam@gmail.example", "refresh-sam-1")
        self.google.matches[:] = ["msg-cancel"]   # (Sam is sent only the cancellation)
        self.google.mail["msg-cancel"] = raw("cancellation")
        self.assertEqual(self.scan(sam_box).state, "done")
        ours = {s["id"] for s in before}
        mine = self.segments(self.sam)
        self.assertEqual({s["id"] for s in mine}, ours)   # the same two flights, not copies: he got their confirmation, so he sees them
        self.assertEqual([s["status"] for s in mine], ["cancelled", "cancelled"])
        self.assertEqual([s["status"] for s in self.segments(self.jane)], ["cancelled", "cancelled"])
        self.assertTrue(all(s["booked_by"] == self.jane.person_id for s in mine))
        self.assertEqual(len(self.segments(self.jane)), 2)   # (and nothing was added for anyone)

    def test_mail_the_parser_cant_read_goes_to_the_review_queue(self):
        self.add_mail("odd", mail("Confirmation #: K7QW2N\nFlight 77 Mon, Nov 16, 2026\nDallas (Love Field), TX (DAL) 8:05 AM\n", ctype="text/plain"))
        result = self.scan()
        self.assertEqual((result.messages, result.bookings, result.review), (1, 0, 1))
        [item] = self.items()
        self.assertEqual((item["sender_domain"], item["reason"]), ("luv.southwest.com", "incomplete"))

    def test_nothing_of_the_email_is_kept_logged_or_sent(self):
        self.put("southwest/booking")
        self.add_mail("change", raw("change"))
        self.add_mail("cancel", raw("cancellation"))
        with no_leaks(self, *CANARIES, "55512340011", database=self.path):
            result = self.scan()
        self.assertEqual((result.state, result.messages), ("done", 3))

    def test_the_canaries_are_really_in_the_fixtures(self):
        text = "".join(p.read_text() for p in FIXTURES.glob("*.eml"))
        for canary in CANARIES:
            self.assertIn(canary, text)


if __name__ == "__main__":
    unittest.main()
