import base64
import unittest
from pathlib import Path

from tests.privacy import no_leaks
from tests.test_mail_scan import ScanCase
from waypoint.domain.mail import extract, parsers
from waypoint.domain.mail.booking import Parsed, Passenger
from waypoint.domain.mail.parsers import disneycruise

FIXTURES = Path(__file__).parent / "fixtures" / "mail" / "disneycruise"
CANARIES = ("CANARY-BODY-DISNEY-BOOKING-6T2K", "CANARY-BODY-DISNEY-CHANGE-8W3N", "CANARY-BODY-DISNEY-CANCEL-5F9D")
LOYALTY = ("77700099911", "77700099922")

HEAD = ("Reservation Number: 4455667\nEmbark Date: Mon, Nov 16, 2026\nDebark Date: Sat, Nov 21, 2026\nShip: Disney Example\n"
        "Stateroom: 8052\nDeck: 8\nGuest 1: JANE DOE\nCastaway Club Number: 77700099911\nCruise Itinerary\n")
FIRST = "Monday, Nov 16\nFORT LAUDERDALE, FLORIDA\nOnboard: 4:30 PM\n"
LAST = "Saturday, Nov 21\nFORT LAUDERDALE, FLORIDA\nAshore: 7:15 AM\n"
SEA = "{day}\nAT SEA\n"
PORT = "{day}\n{port}\nAshore: 8:00 AM\nOnboard: 4:30 PM\n"


def short(middle: str) -> str:
    return (HEAD.replace("Sat, Nov 21", "Wed, Nov 18") + FIRST + middle + LAST.replace("Saturday, Nov 21", "Wednesday, Nov 18"))


def raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.eml").read_bytes()


def read(data: bytes) -> extract.Message:
    return extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(data).decode().rstrip("=")})


def text_mail(body: str) -> bytes:
    return ("From: Disney Cruise Line <reservations@familyvacations-disneycruise.com>\nSubject: x\nDate: Tue, 06 Oct 2026 10:00:00 -0500\n"
            f"MIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n{body}").encode()


class ParserTests(unittest.TestCase):
    def test_a_sailing_is_one_cruise_with_its_ports_at_their_own_zones(self):
        m = read(raw("booking"))
        self.assertEqual((m.sender_domain, m.unread, m.broken), ("familyvacations-disneycruise.com", 0, False))
        [b] = m.bookings
        self.assertEqual((b.kind, b.status, b.confirmation, b.provider, b.origin, b.destination, b.start, b.end),
                         ("cruise", "confirmed", "4455667", "Disney Cruise Line", "Fort Lauderdale", "Fort Lauderdale",
                          "2026-11-16T16:30:00", "2026-11-21T07:15:00"))
        self.assertEqual((b.start_zone, b.end_zone), ("America/New_York", "America/New_York"))
        self.assertEqual(dict(b.details), {"ship": "Disney Example", "room": "8052", "deck": "8"})
        self.assertEqual([(p.name, p.zone, p.arrive_local, p.depart_local) for p in b.ports],
                         [("Nassau", "America/Nassau", "2026-11-18T08:00:00", "2026-11-18T16:30:00"),
                          ("Castaway Cay", "America/Nassau", "2026-11-19T08:30:00", "2026-11-19T16:45:00")])
        self.assertEqual(b.passengers, (Passenger("JANE DOE"), Passenger("SAM DOE")))

    def test_a_short_sailing_with_no_port_of_call_has_no_ports(self):
        body = short(SEA.format(day="Tuesday, Nov 17"))
        [b] = disneycruise.parse("", body).bookings
        self.assertEqual((b.ports, b.start, b.end), ((), "2026-11-16T16:30:00", "2026-11-18T07:15:00"))

    def test_a_port_with_one_time_keeps_that_one(self):
        [b] = disneycruise.parse("", short(PORT.format(day="Tuesday, Nov 17", port="NASSAU, BAHAMAS").replace("Onboard: 4:30 PM\n", ""))).bookings
        self.assertEqual([(p.arrive_local, p.depart_local) for p in b.ports], [("2026-11-17T08:00:00", None)])

    def test_the_embark_and_disembark_times_are_the_only_ones_used_and_never_invented(self):
        for body in (HEAD + FIRST.replace("Onboard: 4:30 PM\n", "") + LAST,
                     HEAD + FIRST + LAST.replace("Ashore: 7:15 AM\n", "")):
            with self.subTest(body=body):
                self.assertEqual(disneycruise.parse("", body), Parsed((), 1))

    def test_an_unknown_port_sends_the_message_to_review_instead_of_guessing(self):
        self.assertEqual(disneycruise.parse("", short(PORT.format(day="Tuesday, Nov 17", port="ATLANTIS, NOWHERE"))), Parsed((), 1))
        unknown_embark = HEAD + FIRST.replace("FORT LAUDERDALE", "ATLANTIS") + LAST
        self.assertEqual(disneycruise.parse("", unknown_embark), Parsed((), 1))

    def test_a_port_day_with_no_times_cant_be_placed_so_it_goes_to_review(self):
        self.assertEqual(disneycruise.parse("", short("Tuesday, Nov 17\nNASSAU, BAHAMAS\n")), Parsed((), 1))

    def test_dates_that_dont_fit_are_unread(self):
        for body in (HEAD.replace("Sat, Nov 21, 2026", "Sat, Nov 21") + FIRST + LAST,
                     HEAD.replace("Nov 21, 2026", "Foo 21, 2026") + FIRST + LAST,
                     HEAD.replace("Nov 21, 2026", "Nov 15, 2026") + FIRST + LAST,
                     HEAD + FIRST + LAST.replace("Nov 21", "Nov 22"),
                     HEAD + FIRST + SEA.format(day="Tuesday, Nov 17") + SEA.format(day="Tuesday, Nov 17") + LAST,
                     HEAD + FIRST + PORT.format(day="Tuesday, Nov 17", port="NASSAU").replace("8:00", "13:00") + LAST,
                     HEAD.replace("Cruise Itinerary\n", "") + FIRST + LAST):
            with self.subTest(body=body):
                self.assertEqual(disneycruise.parse("", body), Parsed((), 1))

    def test_a_year_less_day_after_new_year_belongs_to_the_next_year(self):
        body = ("Reservation Number: 4455667\nEmbark Date: Mon, Dec 28, 2026\nDebark Date: Sat, Jan 2, 2027\nCruise Itinerary\n"
                "Monday, Dec 28\nPORT CANAVERAL, FLORIDA\nOnboard: 4:30 PM\nSaturday, Jan 2\nPORT CANAVERAL, FLORIDA\nAshore: 7:15 AM\n")
        [b] = disneycruise.parse("", body).bookings
        self.assertEqual((b.start, b.end), ("2026-12-28T16:30:00", "2027-01-02T07:15:00"))

    def test_an_email_without_a_reservation_finds_nothing_and_the_tally_says_so(self):
        self.assertEqual(disneycruise.parse("<p>Hello</p>", ""), Parsed())
        m = read(text_mail("Thanks for sailing with us."))
        self.assertEqual((m.bookings, m.gaps), ((), ("sender-specific parser found no booking",)))

    def test_the_change_and_cancellation_emails_are_left_out_for_now(self):
        self.assertEqual(read(raw("change")).bookings, ())
        self.assertEqual(read(raw("cancellation")).bookings, ())
        self.assertEqual(read(raw("change")).unread, 1)

    def test_a_loyalty_number_is_never_read(self):
        [b] = disneycruise.parse("", HEAD + FIRST + LAST).bookings
        self.assertEqual(b.passengers, (Passenger("JANE DOE", None),))
        self.assertNotIn("77700099911", repr(b))

    def test_a_parser_is_found_by_the_sender_domain_and_its_subdomains(self):
        for domain in ("familyvacations-disneycruise.com", "mail.familyvacations-disneycruise.com"):
            self.assertIs(parsers.for_sender(domain), disneycruise.parse)
        self.assertIsNone(parsers.for_sender("notfamilyvacations-disneycruise.com"))


class ScanTests(ScanCase):
    def test_a_sailing_becomes_a_cruise_with_ports_that_show_as_days_with_a_sea_day(self):
        self.put("disneycruise/booking")
        result = self.scan()
        self.assertEqual((result.state, result.messages, result.bookings, result.review), ("done", 1, 1, 0))
        [cruise] = self.segments()
        self.assertEqual((cruise["kind"], cruise["provider"], cruise["confirmation"], cruise["source"], cruise["origin"], cruise["destination"]),
                         ("cruise", "Disney Cruise Line", "4455667", "email", "Fort Lauderdale", "Fort Lauderdale"))
        self.assertEqual((cruise["start_local"], cruise["start_zone"], cruise["end_local"], cruise["end_zone"]),
                         ("2026-11-16T16:30", "America/New_York", "2026-11-21T07:15", "America/New_York"))
        self.assertEqual(cruise["details"], {"ship": "Disney Example", "room": "8052", "deck": "8"})
        self.assertIn(self.jane.person_id, [t["person_id"] for t in cruise["travelers"]])
        days = cruise["days"]
        self.assertEqual([(d["day"], d["date"], d["sea"], [s["name"] for s in d["stops"]]) for d in days],
                         [(1, "2026-11-16", False, ["Fort Lauderdale"]), (2, "2026-11-17", True, []), (3, "2026-11-18", False, ["Nassau"]),
                          (4, "2026-11-19", False, ["Castaway Cay"]), (5, "2026-11-20", True, []), (6, "2026-11-21", False, ["Fort Lauderdale"])])
        nassau = days[2]["stops"][0]
        self.assertEqual((nassau["zone"], nassau["arrive_local"], nassau["depart_local"]), ("America/Nassau", "2026-11-18T08:00", "2026-11-18T16:30"))

    def test_the_same_confirmation_sent_again_updates_the_one_booking(self):
        self.put("disneycruise/booking")
        self.scan()
        self.add_mail("again", raw("booking"))
        result = self.scan(now=3600 + 1_790_000_000.0)
        self.assertEqual((result.messages, result.bookings, result.review), (1, 0, 0))
        [cruise] = self.segments()
        self.assertEqual(len(cruise["days"]), 6)

    def test_a_sailing_with_an_unknown_port_waits_in_review_as_unread(self):
        self.add_mail("odd", text_mail(short(PORT.format(day="Tuesday, Nov 17", port="ATLANTIS"))))
        result = self.scan()
        self.assertEqual((result.messages, result.bookings, result.review), (1, 0, 1))
        [item] = self.items()
        self.assertEqual((item["sender_domain"], item["reason"]), ("familyvacations-disneycruise.com", "incomplete"))

    def test_nothing_of_the_email_or_a_guests_loyalty_number_is_kept_logged_or_sent(self):
        self.put("disneycruise/booking")
        self.add_mail("change", raw("change"))
        self.add_mail("cancel", raw("cancellation"))
        with no_leaks(self, *CANARIES, *LOYALTY, database=self.path):
            result = self.scan()
        self.assertEqual((result.state, result.messages), ("done", 3))

    def test_a_change_or_cancellation_email_is_not_read_and_leaves_the_booking_as_it_was(self):
        self.put("disneycruise/booking")
        self.scan()
        before = self.segments()
        self.add_mail("change", raw("change"))
        self.add_mail("cancel", raw("cancellation"))
        result = self.scan(now=1_790_000_000.0 + 3600)
        self.assertEqual((result.messages, result.bookings, result.review), (2, 0, 2))
        self.assertEqual(self.segments(), before)
        self.assertEqual(before[0]["status"], "confirmed")

    def test_the_canaries_are_really_in_the_fixtures(self):
        text = "".join(p.read_text() for p in FIXTURES.glob("*.eml"))
        for canary in CANARIES:
            self.assertIn(canary, text)
        self.assertIn(LOYALTY[0], text)


if __name__ == "__main__":
    unittest.main()
