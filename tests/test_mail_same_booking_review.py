from tests.privacy import no_leaks
from tests.test_mail_same_booking import SameBookingCase
from waypoint.domain import trips
from waypoint.domain.mail import review

FLIGHT = {"kind": "flight", "confirmation": "ZZ9Y8X", "provider": "Example Air", "origin": "BOS", "destination": "DEN",
          "start_local": "2027-01-02T07:15", "end_local": "2027-01-02T10:05", "details": {"flight_number": "EX 202"}}


class SameBookingReviewTests(SameBookingCase):
    def waiting(self) -> int:
        self.put("no_markup")
        self.scan()
        [item] = self.items()
        return int(item["id"])

    def by_hand(self, viewer=None, **swaps) -> int:
        seg = self.read(lambda conn: trips.add_segment(conn, viewer or self.jane, {**FLIGHT, **swaps}))
        assert seg is not None
        return int(seg["id"])

    def same(self, item: int, viewer=None, owner="u-jane", **swaps):
        return self.read(lambda conn: review.same_booking(conn, owner, viewer or self.jane, item, {**FLIGHT, **swaps}))

    def test_a_suggestion_that_is_a_booking_the_person_can_see_is_named_so_the_confirm_step_can_say_it(self):
        item = self.waiting()
        segment = self.by_hand()
        seen, found = self.same(item)
        self.assertTrue(seen)
        assert found is not None
        self.assertEqual((found["segment_id"], found["kind"], found["origin"], found["start_local"], found["provider"]),
                         (segment, "flight", "BOS", "2027-01-02T07:15", "Example Air"))
        self.assertTrue(found["trip_name"])

    def test_nothing_is_named_when_the_time_the_place_the_code_or_the_kind_differs(self):
        item = self.waiting()
        self.by_hand()
        for swaps in ({"start_local": "2027-01-02T07:20"}, {"destination": "SFO"}, {"confirmation": "ZZ9Y8Y"}, {"details": {"flight_number": "EX 203"}}):
            with self.subTest(swaps):
                self.assertEqual(self.same(item, **swaps), (True, None))
        hotel = {"kind": "hotel", "origin": "Harbour Hotel", "destination": None, "start_zone": "Europe/London", "end_zone": "Europe/London"}
        self.assertEqual(self.same(item, **hotel), (True, None))

    def test_a_cancelled_booking_is_not_named(self):
        item = self.waiting()
        segment = self.by_hand()
        self.read(lambda conn: trips.edit_segment(conn, self.jane, segment, {"status": "cancelled"}))
        self.assertEqual(self.same(item), (True, None))

    def test_a_booking_the_person_cannot_see_is_not_named_and_cannot_be_attached_to(self):
        item = self.waiting()
        self.by_hand(self.sam)
        self.assertEqual(self.same(item), (True, None))
        before = self.counts()
        with self.assertRaises(trips.Invalid):
            self.read(lambda conn: review.attach(conn, "u-jane", self.jane, item, FLIGHT))
        self.assertEqual(self.counts(), before)

    def test_an_item_the_person_cannot_see_is_unknown_to_both_steps(self):
        item = self.waiting()
        self.by_hand()
        self.assertEqual(self.same(item, owner="u-sam"), (False, None))
        self.assertIsNone(self.read(lambda conn: review.attach(conn, "u-sam", self.sam, item, FLIGHT)))

    def test_attaching_adds_the_email_to_the_existing_booking_fills_blanks_and_keeps_what_is_there(self):
        item = self.waiting()
        segment = self.by_hand(details={"flight_number": "EX 202", "seat": "12A"}, manage_url="https://example-air.example/manage/ZZ9Y8X")
        before = self.counts()
        body = {**FLIGHT, "details": {"flight_number": "EX 202", "seat": "30F", "cabin": "Economy"}, "manage_url": "https://example-air.example/other"}
        self.assertEqual(self.read(lambda conn: review.attach(conn, "u-jane", self.jane, item, body)), segment)
        [seg] = self.segments()
        self.assertEqual((seg["details"]["seat"], seg["details"]["flight_number"], seg["details"]["cabin"]), ("12A", "EX 202", "Economy"))
        self.assertEqual(seg["manage_url"], "https://example-air.example/manage/ZZ9Y8X")
        self.assertEqual(self.counts()[:2], before[:2])
        shown = self.read(lambda conn: trips.emails_of(conn, self.jane, segment))
        assert shown is not None
        self.assertEqual(len(shown), 1)
        self.assertEqual(len(self.items()), 1)

    def test_attaching_and_then_dismissing_with_the_booking_keeps_the_email_on_it_and_makes_no_second_booking(self):
        item = self.waiting()
        segment = self.by_hand()
        self.read(lambda conn: review.attach(conn, "u-jane", self.jane, item, FLIGHT))
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", item, (self.jane, [segment]))))
        self.assertEqual(self.items(), [])
        self.assertEqual(self.counts(), (1, 1, 1, 1))

    def test_attaching_leaves_locked_fields_alone(self):
        item = self.waiting()
        segment = self.by_hand()
        self.read(lambda conn: trips.edit_segment(conn, self.jane, segment, {"details": {"flight_number": "EX 202", "seat": "1A"}}))
        self.read(lambda conn: review.attach(conn, "u-jane", self.jane, item, {**FLIGHT, "details": {"flight_number": "EX 202", "seat": "30F", "cabin": "Economy"}}))
        [seg] = self.segments()
        self.assertEqual(seg["details"], {"flight_number": "EX 202", "seat": "1A"})

    def test_the_steps_keep_the_messages_canaries_out_of_logs_and_rows(self):
        item = self.waiting()
        self.by_hand()
        with no_leaks(self, "CANARY-BODY-NOMARKUP-6H9C", "CANARY-SUBJECT-NOMARKUP-8B3F", database=self.path):
            self.same(item)
            self.read(lambda conn: review.attach(conn, "u-jane", self.jane, item, FLIGHT))
