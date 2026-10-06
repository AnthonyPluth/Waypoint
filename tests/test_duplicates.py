from sqlalchemy import func, select

from waypoint.domain import trips, visibility
from waypoint.domain.visibility import Viewer
from waypoint.storage.models import Segment, SegmentRecipient
from tests.test_trips import Household

FLIGHT = {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-06-01T19:00", "end_local": "2026-06-02T07:10",
          "confirmation": "ZQ4PXD", "provider": "American Airlines", "details": {"flight_number": "AA 4001"}}


class Merging(Household):
    def merge(self, who, fields=None, travelers=None):
        body = {**(fields or FLIGHT)}
        if travelers is not None:
            body["travelers"] = travelers
        return trips.merge_email_segment(self.c, who, body)

    def count(self):
        return self.c.orm.scalar(select(func.count()).select_from(Segment))


class HouseholdWide(Merging):
    def test_the_same_confirmation_in_two_mailboxes_is_one_segment_both_owners_see(self):
        self.assertEqual(self.merge(self.jane, travelers=self.on(self.jane.person_id)), "added")
        self.assertEqual(self.merge(self.sam, travelers=self.on(self.jane.person_id, self.sam.person_id)), "updated")
        self.assertEqual(self.count(), 1)
        for who in (self.jane, self.sam):
            [seg] = [s for t in trips.listing(self.c, who) for s in t["segments"]]
            self.assertEqual({t["person_id"] for t in seg["travelers"]}, {self.jane.person_id, self.sam.person_id})

    def test_a_recipient_not_on_the_booking_still_sees_it(self):
        self.merge(self.jane, travelers=self.on(self.jane.person_id, self.mia))
        self.merge(self.sam, travelers=self.on(self.jane.person_id, self.mia))
        self.assertEqual(self.count(), 1)
        [seg] = [s for t in trips.listing(self.c, self.sam) for s in t["segments"]]
        self.assertEqual([t["person_id"] for t in seg["travelers"]], [self.jane.person_id, self.mia])

    def test_receiving_a_confirmation_shows_that_trip_to_its_recipient_and_nobody_else(self):
        self.merge(self.jane, travelers=self.on(self.jane.person_id))
        [seg] = [s for t in trips.listing(self.c, self.jane) for s in t["segments"]]
        self.assertIsNone(visibility.visible_segment(self.c, self.sam, seg["id"]))
        self.merge(self.sam, travelers=self.on(self.jane.person_id))
        for who, sees in ((self.jane, True), (self.sam, True), (Viewer(self.mia), False), (Viewer(self.joan), False), (Viewer(None), False)):
            with self.subTest(person=who.person_id):
                self.assertEqual(visibility.visible_trip(self.c, who, seg["trip_id"]) is not None, sees)
                self.assertEqual(visibility.visible_segment(self.c, who, seg["id"]) is not None, sees)
                self.assertEqual(len(visibility.visible_trips(self.c, who)), 1 if sees else 0)
                self.assertEqual(len(visibility.visible_travelers(self.c, who, [seg["id"]])), 1 if sees else 0)

    def test_the_recipient_is_noted_once_however_many_copies_arrive(self):
        self.merge(self.jane, travelers=self.on(self.jane.person_id))
        for _ in range(3):
            self.merge(self.sam, travelers=self.on(self.jane.person_id))
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(SegmentRecipient)), 1)

    def test_someone_who_can_see_the_segment_is_not_noted_as_a_recipient(self):
        self.merge(self.jane, travelers=self.on(self.jane.person_id, self.sam.person_id))
        self.merge(self.sam, travelers=self.on(self.jane.person_id, self.sam.person_id))
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(SegmentRecipient)), 0)

    def test_a_recipient_goes_with_the_segment_and_with_the_person(self):
        self.merge(self.jane, travelers=self.on(self.jane.person_id))
        self.merge(self.sam, travelers=self.on(self.jane.person_id))
        [seg] = [s for t in trips.listing(self.c, self.sam) for s in t["segments"]]
        self.assertTrue(trips.delete_segment(self.c, self.sam, seg["id"]))
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(SegmentRecipient)), 0)

    def test_the_same_email_twice_in_one_mailbox_is_one_segment(self):
        self.merge(self.jane)
        self.assertEqual(self.merge(self.jane), "unchanged")
        self.assertEqual(self.count(), 1)

    def test_a_different_confirmation_on_the_same_flight_is_another_segment(self):
        self.merge(self.jane)
        self.assertEqual(self.merge(self.sam, {**FLIGHT, "confirmation": "QW9ERT"}), "added")
        self.assertEqual(self.count(), 2)

    def test_a_confirmation_written_with_spaces_or_other_case_is_the_same(self):
        self.merge(self.jane)
        self.assertEqual(self.merge(self.sam, {**FLIGHT, "confirmation": " zq4 pxd "}), "updated")
        self.assertEqual(self.count(), 1)


class Spellings(Merging):
    def assertSame(self, **swap):
        self.merge(self.jane)
        self.assertEqual(self.merge(self.jane, {**FLIGHT, **swap}), "unchanged", swap)
        self.assertEqual(self.count(), 1, swap)

    def test_flight_numbers_written_another_way_match(self):
        for n in ("AA4001", "AA04001", "aa 4001", "AA  4001", "AA 004001"):
            with self.subTest(number=n):
                self.setUp()
                self.assertSame(details={"flight_number": n})

    def test_a_different_flight_number_on_the_same_day_is_another_leg(self):
        self.merge(self.jane)
        self.assertEqual(self.merge(self.jane, {**FLIGHT, "details": {"flight_number": "AA 4002"}}), "added")

    def test_the_same_number_of_another_airline_is_another_leg(self):
        self.merge(self.jane)
        self.assertEqual(self.merge(self.jane, {**FLIGHT, "details": {"flight_number": "BA 4001"}, "provider": "British Airways"}), "added")

    def test_an_airline_written_another_way_matches(self):
        for name in ("American Airlines Inc.", "AMERICAN AIRLINES", "American Airlines, Inc", "american  airlines", None):
            with self.subTest(provider=name):
                self.setUp()
                self.assertSame(provider=name)

    def test_an_airline_given_as_its_code_matches_by_the_flight_numbers_carrier(self):
        self.assertSame(provider="AA")

    def test_providers_of_stays_are_compared_after_normalizing(self):
        hotel = {"kind": "hotel", "origin": "Harbour Hotel", "destination": None, "start_local": "2026-06-02T15:00",
                 "end_local": "2026-06-08T10:00", "start_zone": "Europe/London", "end_zone": "Europe/London",
                 "confirmation": "H88231", "provider": "Marriott International, Inc."}
        self.merge(self.jane, hotel)
        self.assertEqual(self.merge(self.jane, {**hotel, "provider": "marriott international"}), "unchanged")
        self.assertEqual(self.count(), 1)
