import unittest
from pathlib import Path

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.test_mail_ai import ScanAiCase
from tests.test_mail_scan import NOW
from waypoint.domain.mail import review
from waypoint.storage.models import ReviewItem

FIXTURE = Path(__file__).parent / "fixtures" / "mail" / "spothero" / "booking.eml"
CANARIES = ("CANARY-BODY-SPOTHERO-BOOKING-6P2D", "CANARY-PLATE-SPOTHERO-5M9X")
LOT = "Example Plaza Garage"


class ReadSuggestionTests(ScanAiCase):
    def waiting(self):
        return self.read(lambda conn: list(conn.execute(select(ReviewItem.auto_state)).scalars()))

    def test_a_booking_missing_only_its_zone_waits_with_the_fields_the_email_gave(self):
        self.add_mail("spot", FIXTURE.read_bytes())
        result = self.scan()
        self.assertEqual((result.bookings, result.review), (0, 1))
        [item] = self.items()
        self.assertEqual(item["reason"], "incomplete")
        [s] = item["suggestions"]
        self.assertEqual((s["kind"], s["origin"], s["start_local"], s["end_local"], s["confirmation"], s["provider"], s["address"], s["phone"], s["parsed"]),
                         ("parking", LOT, "2027-03-05T15:00:00", "2027-03-09T15:00:00", "100200300", "SpotHero", "1 Example Avenue", "(555) 010-0100", True))
        self.assertNotIn("start_zone", s)

    def test_the_email_is_not_sent_to_the_ai_when_the_parser_already_read_it(self):
        self.turn_on()
        self.add_mail("spot", FIXTURE.read_bytes())
        with no_leaks(self, *CANARIES, database=self.path):
            result = self.scan()
        self.assertEqual(result.review, 1)
        self.assertEqual(self.fake.requests, [])
        self.assertEqual(self.waiting(), [None])

    def test_scanning_again_keeps_one_item_with_one_suggestion(self):
        self.add_mail("spot", FIXTURE.read_bytes())
        self.scan()
        self.scan(now=NOW + 3600, again=True)
        [item] = self.items()
        self.assertEqual(len(item["suggestions"]), 1)

    def test_a_suggestion_the_ai_made_is_not_replaced_by_the_parsers(self):
        self.add_mail("spot", FIXTURE.read_bytes())
        self.scan()
        asked = {"kind": "parking", "start_local": "2027-03-05T14:00:00", "end_local": "2027-03-09T14:00:00", "origin": "Asked Lot"}
        self.read(lambda conn: review.set_suggestions(conn, self.mailbox, "spot", [asked], None))
        self.read(lambda conn: review.set_read_suggestions(conn, self.mailbox, "spot", [{**asked, "origin": LOT, "parsed": True}]))
        [item] = self.items()
        self.assertEqual([s["origin"] for s in item["suggestions"]], ["Asked Lot"])

    def test_a_suggestion_the_parser_made_is_replaced_by_a_newer_one(self):
        self.add_mail("spot", FIXTURE.read_bytes())
        self.scan()
        self.read(lambda conn: review.set_read_suggestions(conn, self.mailbox, "spot", [{"kind": "parking", "start_local": "2027-03-06T09:00:00",
                                                                                          "end_local": "2027-03-10T09:00:00", "origin": LOT, "parsed": True}]))
        [item] = self.items()
        self.assertEqual(item["suggestions"][0]["start_local"], "2027-03-06T09:00:00")

    def test_a_booking_that_files_straight_in_leaves_no_item(self):
        self.add_mail("spot", FIXTURE.read_bytes().replace(b"1 Example Avenue", b"1 Example Avenue, Austin, TX 78701"))
        result = self.scan()
        self.assertEqual((result.bookings, result.review), (1, 0))
        self.assertEqual(self.items(), [])


if __name__ == "__main__":
    unittest.main()
