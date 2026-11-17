import unittest
from pathlib import Path

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.test_mail_ai import ScanAiCase
from tests.test_mail_scan import NOW
from waypoint.domain.mail import ingest, review
from waypoint.domain.mail.booking import Booking
from waypoint.storage.models import ReviewItem

FIXTURE = Path(__file__).parent / "fixtures" / "mail" / "spothero" / "booking.eml"
CANARIES = ("CANARY-BODY-SPOTHERO-BOOKING-6P2D", "CANARY-PLATE-SPOTHERO-5M9X")
LOT = "Example Plaza Garage"


def stay(**extra) -> Booking:
    return Booking(**{"kind": "parking", "status": "confirmed", "confirmation": "100200300", "provider": "SpotHero", "start": "2027-03-05T15:00:00",
                      "end": "2027-03-09T15:00:00", "origin": LOT, "destination": None, **extra})


class RuleTests(unittest.TestCase):
    def test_a_stay_or_parking_lot_with_plain_local_times_in_order_may_be_suggested(self):
        for kind in ("hotel", "parking"):
            with self.subTest(kind=kind):
                self.assertTrue(ingest.only_the_zone_is_missing(stay(kind=kind)))
        self.assertTrue(ingest.only_the_zone_is_missing(stay(start="2027-03-05T15:00", end="2027-03-09T15:00")))

    def test_a_cancelled_booking_is_not_suggested(self):
        self.assertFalse(ingest.only_the_zone_is_missing(stay(status="cancelled")))

    def test_kinds_with_two_places_are_not_suggested(self):
        for kind in ("flight", "car", "train", "cruise"):
            with self.subTest(kind=kind):
                self.assertFalse(ingest.only_the_zone_is_missing(stay(kind=kind)))

    def test_times_with_an_offset_or_a_bad_range_are_not_suggested(self):
        for start, end in (("2027-03-05T15:00:00Z", "2027-03-09T15:00:00Z"), ("2027-03-05T15:00:00+01:00", "2027-03-09T15:00:00+01:00"),
                           ("2027-03-09T15:00:00", "2027-03-05T15:00:00"), ("2027-03-05T15:00:00", "2027-03-05T15:00:00"),
                           ("2027-02-30T15:00:00", "2027-03-09T15:00:00"), ("2027-03-05", "2027-03-09"), ("soon", "later")):
            with self.subTest(start=start, end=end):
                self.assertFalse(ingest.only_the_zone_is_missing(stay(start=start, end=end)))


def fixed(code, name, day):
    return {"kind": "hotel", "confirmation": code, "origin": name, "start_local": f"2027-03-{day:02d}T15:00", "end_local": f"2027-03-{day + 2:02d}T11:00", "parsed": True}


def said(code, name, day, zone="Europe/London"):
    return {"kind": "hotel", "confirmation": code, "origin": name, "start_local": f"2027-03-{day:02d}T15:00", "end_local": f"2027-03-{day + 2:02d}T11:00",
            "start_zone": zone, "address": f"{name} street"}


class KeepingFixedTests(unittest.TestCase):
    def test_the_readers_values_win_and_the_ai_fills_what_it_left_empty(self):
        [got] = review.keeping_fixed([{**fixed("AB12", "", 5), "origin": "", "phone": "555"}], [said("AB12", "Harbour Inn", 6)])
        self.assertEqual((got["confirmation"], got["start_local"], got["phone"], got["origin"], got["start_zone"]),
                         ("AB12", "2027-03-05T15:00", "555", "Harbour Inn", "Europe/London"))
        self.assertNotIn("parsed", got)

    def test_two_reservations_answered_in_the_other_order_are_each_paired_with_their_own_by_confirmation(self):
        one, two = fixed("AB12", "Inn One", 5), fixed("CD34", "Inn Two", 10)
        first, second = review.keeping_fixed([one, two], [said("CD34", "", 10, "America/Denver"), said("AB12", "", 5)])
        self.assertEqual((first["confirmation"], first["origin"], first["start_zone"], first["address"]), ("CD34", "Inn Two", "America/Denver", " street"))
        self.assertEqual((second["confirmation"], second["origin"], second["start_zone"]), ("AB12", "Inn One", "Europe/London"))

    def test_reservations_that_cannot_be_told_apart_are_not_paired_by_position_and_stay_for_a_person(self):
        one, two = fixed(None, "Inn One", 5), fixed(None, "Inn Two", 10)
        out = review.keeping_fixed([one, two], [said("CD34", "Inn Two", 10, "America/Denver"), said("AB12", "Inn One", 5)])
        self.assertEqual([(x.get("confirmation"), x.get("origin"), bool(x.get("parsed"))) for x in out],
                         [("CD34", "Inn Two", False), ("AB12", "Inn One", False), (None, "Inn One", True), (None, "Inn Two", True)])
        self.assertEqual([x["start_zone"] for x in out[:2]], ["America/Denver", "Europe/London"])

    def test_a_partial_answer_keeps_the_reservation_the_reader_found_that_the_ai_left_out(self):
        one, two = fixed("AB12", "Inn One", 5), fixed("CD34", "Inn Two", 10)
        out = review.keeping_fixed([one, two], [said("AB12", "", 5)])
        self.assertEqual([(x["confirmation"], bool(x.get("parsed"))) for x in out], [("AB12", False), ("CD34", True)])

    def test_an_answer_with_nothing_keeps_everything_the_reader_found(self):
        one = fixed("AB12", "Inn One", 5)
        self.assertEqual(review.keeping_fixed([one], []), [one])


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

    def test_the_email_is_sent_to_the_ai_to_fill_the_zone_and_a_failed_call_keeps_what_the_parser_read(self):
        self.turn_on()
        self.fake.status = 500
        self.add_mail("spot", FIXTURE.read_bytes())
        with no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
            result = self.scan()
        self.assertEqual(result.review, 1)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(self.waiting(), ["waiting"])
        [item] = self.items()
        self.assertEqual([(s["origin"], s["parsed"]) for s in item["suggestions"]], [(LOT, True)])

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

    def test_a_cancellation_that_cannot_be_placed_waits_without_a_suggestion(self):
        self.add_mail("cancel", (FIXTURE.parent / "cancellation.eml").read_bytes())
        result = self.scan()
        self.assertEqual((result.bookings, result.review), (0, 1))
        [item] = self.items()
        self.assertEqual(item["suggestions"], [])

    def test_a_booking_that_files_straight_in_leaves_no_item(self):
        self.add_mail("spot", FIXTURE.read_bytes().replace(b"1 Example Avenue", b"1 Example Avenue, Austin, TX 78701"))
        result = self.scan()
        self.assertEqual((result.bookings, result.review), (1, 0))
        self.assertEqual(self.items(), [])


if __name__ == "__main__":
    unittest.main()
