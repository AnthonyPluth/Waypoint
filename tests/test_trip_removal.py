import json

from sqlalchemy import select, update

from waypoint.domain import people, trippeople, trips, visibility
from waypoint.domain.visibility import Viewer
from waypoint.storage.models import Segment, SegmentRecipient, SegmentTraveler, Trip, TripExclusion
from tests.privacy import no_leaks
from tests.test_trips import HOTEL, OUT, Household, guest

CANARY = "Zebulon Canarystone"
CODE = "CANARY77XQ"
FLIGHT = {**OUT, "confirmation": CODE, "provider": "American Airlines", "details": {"flight_number": "AA 4001"}}
FAR = {**OUT, "start_local": "2026-09-10T19:00", "end_local": "2026-09-11T07:10"}
FAR_FLIGHT = {**FLIGHT, "start_local": "2026-09-10T19:00", "end_local": "2026-09-11T07:10"}
PAST = {**OUT, "start_local": "2020-03-01T19:00", "end_local": "2020-03-02T07:10"}


class Removal(Household):
    def setUp(self):
        super().setUp()
        self.jid, self.sid = self.jane.person_id, self.sam.person_id

    def aboard(self, trip_id):
        return trippeople.of(self.c, [trip_id])[trip_id]

    def excluded(self, trip_id):
        return trippeople.excluded(self.c, trip_id)

    def email(self, who, *ids, fields=FLIGHT):
        return trips.merge_email_segment(self.c, who, {**fields, "travelers": self.on(*ids)})

    def take_off(self, who, trip_id, *gone):
        keep = [p for p in self.aboard(trip_id) if p not in gone]
        return trips.edit_trip(self.c, who, trip_id, {"people": keep})

    def put_on(self, who, trip_id, *added, confirmed=True):
        return trips.edit_trip(self.c, who, trip_id, {"people": [*self.aboard(trip_id), *added]}, confirmed)

    def booked_by_sam(self, fields=OUT):
        flight = self.add(self.sam, fields, None, self.on(self.sid, self.jid))
        trips.edit_segment(self.c, self.sam, flight["id"], {"travelers": self.on(self.jid)})
        self.assertCountEqual(self.aboard(flight["trip_id"]), [self.sid, self.jid])
        return flight

    def shared_with_sam(self, fields=OUT):
        flight = self.add(self.jane, fields, None, self.on(self.jid))
        self.put_on(self.jane, flight["trip_id"], self.sid)
        return flight

    def assertSeesNothing(self, who, trip_id, segment_ids):
        self.assertIsNone(trips.get(self.c, who, trip_id))
        self.assertIsNone(visibility.visible_trip(self.c, who, trip_id))
        for segment_id in segment_ids:
            self.assertIsNone(trips.get_segment(self.c, who, segment_id))
            self.assertIsNone(visibility.visible_segment(self.c, who, segment_id))
        self.assertEqual(trips.listing(self.c, who), [])
        self.assertEqual(visibility.visible_trips(self.c, who), [])
        self.assertEqual(visibility.visible_segments(self.c, who), [])
        self.assertEqual(visibility.visible_travelers(self.c, who, list(segment_ids)), [])
        self.assertEqual(trips.unmatched_count(self.c, who), 0)

    def assertStrangersSeeNothing(self, trip_id, segment_ids):
        for who in (Viewer(self.mia), Viewer(self.joan), Viewer(None)):
            with self.subTest(stranger=who.person_id):
                self.assertSeesNothing(who, trip_id, segment_ids)


class TakenOffLosesWhatTheyOnlyHadByBooking(Removal):
    def test_the_booker_of_the_trip_loses_it(self):
        flight = self.booked_by_sam()
        trip_id = flight["trip_id"]
        self.assertIsNotNone(trips.get(self.c, self.sam, trip_id))
        self.take_off(self.jane, trip_id, self.sid)
        self.assertEqual(self.aboard(trip_id), [self.jid])
        self.assertSeesNothing(self.sam, trip_id, [flight["id"]])
        self.assertStrangersSeeNothing(trip_id, [flight["id"]])
        self.assertIsNotNone(trips.get(self.c, self.jane, trip_id))
        self.assertEqual(self.excluded(trip_id), {self.sid})

    def test_the_booker_of_a_booking_on_the_trip_loses_the_trip(self):
        flight = self.shared_with_sam()
        trip_id = flight["trip_id"]
        stay = self.add(self.sam, HOTEL, trip_id)
        self.assertEqual(self.c.orm.get(Segment, stay["id"]).booked_by, self.sid)
        self.take_off(self.jane, trip_id, self.sid)
        self.assertSeesNothing(self.sam, trip_id, [flight["id"], stay["id"]])
        self.assertStrangersSeeNothing(trip_id, [flight["id"], stay["id"]])
        self.assertEqual([t["id"] for t in trips.listing(self.c, self.jane)], [trip_id])
        self.assertIsNone(trips.add_segment(self.c, self.sam, HOTEL, trip_id))
        self.assertIsNone(trips.edit_trip(self.c, self.sam, trip_id, {"people": [self.sid]}, True))
        self.assertEqual(self.aboard(trip_id), [self.jid])

    def test_the_mailbox_a_confirmation_came_to_loses_the_trip(self):
        self.email(self.jane, self.jid)
        trip_id = self.c.orm.scalars(select(Segment.trip_id)).one()
        seg_id = self.c.orm.scalars(select(Segment.id)).one()
        self.email(self.sam, self.jid)
        self.assertEqual(len(self.c.orm.scalars(select(SegmentRecipient)).all()), 1)
        self.assertIsNotNone(trips.get(self.c, self.sam, trip_id))
        self.put_on(self.jane, trip_id, self.sid, confirmed=False)
        self.take_off(self.jane, trip_id, self.sid)
        self.assertSeesNothing(self.sam, trip_id, [seg_id])
        self.assertStrangersSeeNothing(trip_id, [seg_id])

    def test_the_same_confirmation_arriving_again_in_their_mailbox_does_not_give_it_back_or_touch_the_booking(self):
        self.email(self.jane, self.jid)
        trip_id = self.c.orm.scalars(select(Segment.trip_id)).one()
        seg_id = self.c.orm.scalars(select(Segment.id)).one()
        self.email(self.sam, self.jid)
        self.put_on(self.jane, trip_id, self.sid, confirmed=False)
        self.take_off(self.jane, trip_id, self.sid)
        before = trips.get_segment(self.c, self.jane, seg_id)
        with no_leaks(self, CODE, CANARY):
            changed = {**FLIGHT, "end_local": "2026-06-02T09:30", "travelers": self.on(self.jid, self.sid)}
            for _ in range(2):
                trips.merge_email_segment(self.c, self.sam, changed)
        self.assertEqual(trips.get_segment(self.c, self.jane, seg_id), before)
        self.assertEqual(self.aboard(trip_id), [self.jid])
        self.assertIsNone(trips.get(self.c, self.sam, trip_id))
        self.assertIsNone(trips.get_segment(self.c, self.sam, seg_id))
        mine = [t["id"] for t in trips.listing(self.c, self.sam)]
        self.assertEqual(len(mine), 1)
        self.assertNotIn(trip_id, mine)
        self.assertStrangersSeeNothing(trip_id, [seg_id])

    def test_a_trip_that_has_ended_is_the_same(self):
        flight = self.booked_by_sam(PAST)
        trip_id = flight["trip_id"]
        self.c.execute(update(Trip).where(Trip.id == trip_id).values(done_at=1_600_000_000.0))
        self.c.orm.expire_all()
        self.assertTrue(trips.get(self.c, self.jane, trip_id)["end_date"].startswith("2020"))
        self.take_off(self.jane, trip_id, self.sid)
        self.assertSeesNothing(self.sam, trip_id, [flight["id"]])
        self.assertStrangersSeeNothing(trip_id, [flight["id"]])
        self.assertIsNotNone(trips.get(self.c, self.jane, trip_id))


class NothingGivesItBack(Removal):
    def test_an_email_naming_them_on_a_booking_does_not_put_them_back_on_the_trip(self):
        self.email(self.jane, self.jid)
        trip_id = self.c.orm.scalars(select(Segment.trip_id)).one()
        seg_id = self.c.orm.scalars(select(Segment.id)).one()
        self.put_on(self.jane, trip_id, self.sid)
        self.take_off(self.jane, trip_id, self.sid)
        self.email(self.jane, self.jid, self.sid)
        self.assertEqual(self.aboard(trip_id), [self.jid])
        self.assertEqual(self.excluded(trip_id), {self.sid})
        self.assertSeesNothing(self.sam, trip_id, [seg_id])
        self.assertStrangersSeeNothing(trip_id, [seg_id])

    def test_naming_a_printed_traveller_as_them_does_not_put_them_back_on_the_trip(self):
        seg = self.add(self.jane, OUT, None, [{"person_id": self.jid, "name": None}, {"person_id": None, "name": "DOE/SAM MR"}])
        trip_id = seg["trip_id"]
        self.put_on(self.jane, trip_id, self.sid)
        self.take_off(self.jane, trip_id, self.sid)
        printed = next(t for t in seg["travelers"] if t["person_id"] is None)
        with self.assertRaisesRegex(trips.Invalid, "Sam Doe was taken off this trip"):
            trips.name_traveler(self.c, self.jane, printed["id"], self.sid)
        self.assertEqual(self.aboard(trip_id), [self.jid])
        self.assertSeesNothing(self.sam, trip_id, [seg["id"]])
        self.assertStrangersSeeNothing(trip_id, [seg["id"]])

    def test_a_booking_of_theirs_moved_into_the_trip_is_refused_and_says_why(self):
        flight = self.shared_with_sam()
        trip_id = flight["trip_id"]
        self.take_off(self.jane, trip_id, self.sid)
        elsewhere = self.add(self.jane, FAR, None, self.on(self.jid, self.sid))
        for confirmed in (False, True):
            with self.assertRaisesRegex(trips.Invalid, "Sam Doe was taken off this trip. Add them to the trip’s people first"):
                trips.move_segment(self.c, self.jane, elsewhere["id"], trip_id, confirmed)
        self.assertEqual(self.c.orm.get(Segment, elsewhere["id"]).trip_id, elsewhere["trip_id"])
        self.assertEqual(self.aboard(trip_id), [self.jid])
        self.assertSeesNothing(self.sam, trip_id, [flight["id"]])

    def test_naming_them_on_a_booking_of_the_trip_by_hand_is_refused_and_says_why(self):
        flight = self.shared_with_sam()
        trip_id = flight["trip_id"]
        self.take_off(self.jane, trip_id, self.sid)
        with self.assertRaisesRegex(trips.Invalid, "Sam Doe was taken off this trip"):
            trips.add_segment(self.c, self.jane, {**FAR, "travelers": self.on(self.jid, self.sid)}, trip_id)
        with self.assertRaisesRegex(trips.Invalid, "Sam Doe was taken off this trip"):
            trips.edit_segment(self.c, self.jane, flight["id"], {"travelers": self.on(self.jid, self.sid)})
        self.assertEqual(self.aboard(trip_id), [self.jid])

    def test_a_booking_moved_out_to_a_trip_of_its_own_keeps_them_off_it(self):
        self.email(self.jane, self.jid)
        flight_id = self.c.orm.scalars(select(Segment.id)).one()
        trip_id = self.c.orm.get(Segment, flight_id).trip_id
        self.email(self.sam, self.jid)
        stay = self.add(self.jane, HOTEL, trip_id)
        self.put_on(self.jane, trip_id, self.sid)
        self.take_off(self.jane, trip_id, self.sid)
        with no_leaks(self, CODE, CANARY):
            new = trips.move_segment(self.c, self.jane, flight_id, None)
        self.assertEqual(self.excluded(new["id"]), {self.sid})
        self.assertIsNone(trips.get(self.c, self.sam, new["id"]))
        self.assertIsNone(trips.get_segment(self.c, self.sam, flight_id))
        self.assertIsNone(trips.get(self.c, self.sam, trip_id))
        self.assertEqual(visibility.visible_trips(self.c, self.sam), [])
        self.assertIsNotNone(trips.get_segment(self.c, self.jane, stay["id"]))

    def test_merging_another_trip_into_it_carries_the_exclusion_on_the_trip_they_were_taken_off(self):
        mine = self.add(self.jane, OUT, None, self.on(self.jid))
        self.email(self.jane, self.jid, fields=FAR_FLIGHT)
        other_id = self.c.orm.scalars(select(Segment.id).where(Segment.id != mine["id"])).one()
        other_trip = self.c.orm.get(Segment, other_id).trip_id
        self.put_on(self.jane, other_trip, self.sid)
        self.take_off(self.jane, other_trip, self.sid)
        trips.merge(self.c, self.jane, mine["trip_id"], other_trip)
        self.assertEqual(self.excluded(mine["trip_id"]), {self.sid})
        self.email(self.sam, self.jid, fields=FAR_FLIGHT)
        self.assertEqual(self.c.orm.scalars(select(SegmentRecipient)).all(), [])
        self.assertIsNone(trips.get(self.c, self.sam, mine["trip_id"]))
        self.assertIsNone(trips.get_segment(self.c, self.sam, other_id))
        self.assertStrangersSeeNothing(mine["trip_id"], [mine["id"], other_id])

    def test_merging_in_a_trip_someone_still_sees_names_them_and_keeps_what_they_had(self):
        mine = self.booked_by_sam()
        other = self.add(self.jane, FAR, None, self.on(self.jid))
        self.put_on(self.jane, other["trip_id"], self.sid)
        self.take_off(self.jane, other["trip_id"], self.sid)
        with self.assertRaises(trips.NeedsConfirmation) as asked:
            trips.merge(self.c, self.jane, mine["trip_id"], other["trip_id"])
        self.assertEqual([p["id"] for p in asked.exception.see_trip], [self.sid])
        trips.merge(self.c, self.jane, mine["trip_id"], other["trip_id"], True)
        self.assertEqual(self.excluded(mine["trip_id"]), set())
        self.assertIsNotNone(trips.get(self.c, self.sam, mine["trip_id"]))

    def test_merging_in_a_trip_they_see_only_by_mailbox_gives_them_the_merged_trip_they_were_asked_about(self):
        mine = self.shared_with_sam()
        self.take_off(self.jane, mine["trip_id"], self.sid)
        self.email(self.jane, self.jid, fields=FAR_FLIGHT)
        self.email(self.sam, self.jid, fields=FAR_FLIGHT)
        other_id = self.c.orm.scalars(select(Segment.id).where(Segment.id != mine["id"])).one()
        other_trip = self.c.orm.get(Segment, other_id).trip_id
        self.assertIsNotNone(trips.get(self.c, self.sam, other_trip))
        with self.assertRaises(trips.NeedsConfirmation) as asked:
            trips.merge(self.c, self.jane, mine["trip_id"], other_trip)
        self.assertEqual([p["id"] for p in asked.exception.see_booking], [self.sid])
        trips.merge(self.c, self.jane, mine["trip_id"], other_trip, True)
        self.assertEqual(self.excluded(mine["trip_id"]), set())
        self.assertIsNotNone(trips.get(self.c, self.sam, mine["trip_id"]))

    def test_splitting_a_booking_off_carries_the_exclusion_and_leaves_someone_named_on_it_off_the_new_trip(self):
        self.email(self.jane, self.jid)
        flight_id = self.c.orm.scalars(select(Segment.id)).one()
        trip_id = self.c.orm.get(Segment, flight_id).trip_id
        stay = self.add(self.jane, HOTEL, trip_id)
        self.put_on(self.jane, trip_id, self.sid)
        self.take_off(self.jane, trip_id, self.sid)
        self.email(self.jane, self.jid, self.sid)
        self.assertEqual(self.aboard(trip_id), [self.jid])
        new = trips.split(self.c, self.jane, trip_id, [flight_id])
        self.assertEqual(self.aboard(new["id"]), [self.jid])
        self.assertEqual(self.excluded(new["id"]), {self.sid})
        self.assertEqual(self.excluded(trip_id), {self.sid})
        self.assertSeesNothing(self.sam, new["id"], [flight_id])
        self.assertSeesNothing(self.sam, trip_id, [stay["id"]])
        trips.merge_email_segment(self.c, self.sam, {**FLIGHT, "travelers": self.on(self.jid)})
        self.assertEqual(self.c.orm.scalars(select(SegmentRecipient)).all(), [])


class PutBackOnTheTrip(Removal):
    def test_adding_them_to_the_trips_people_again_asks_first_and_gives_the_trip_back(self):
        flight = self.booked_by_sam()
        trip_id = flight["trip_id"]
        self.take_off(self.jane, trip_id, self.sid)
        with self.assertRaises(trips.NeedsConfirmation) as asked:
            self.put_on(self.jane, trip_id, self.sid, confirmed=False)
        self.assertEqual([p["id"] for p in asked.exception.see_trip], [self.sid])
        self.assertEqual(self.excluded(trip_id), {self.sid})
        self.assertSeesNothing(self.sam, trip_id, [flight["id"]])
        got = self.put_on(self.jane, trip_id, self.sid)
        self.assertEqual(got["people"], [self.jid, self.sid])
        self.assertEqual(self.excluded(trip_id), set())
        self.assertEqual(self.c.orm.scalars(select(TripExclusion)).all(), [])
        self.assertIsNotNone(trips.get(self.c, self.sam, trip_id))
        self.assertIsNotNone(trips.get_segment(self.c, self.sam, flight["id"]))
        self.assertEqual(self.c.orm.get(Trip, trip_id).booked_by, self.sid)
        self.assertEqual(self.c.orm.get(Segment, flight["id"]).booked_by, self.sid)

    def test_taking_the_last_person_off_is_refused_so_the_trip_never_ends_up_seen_by_nobody(self):
        stay = self.add(self.jane, HOTEL)
        trip_id = stay["trip_id"]
        with self.assertRaisesRegex(trips.Invalid, "A trip needs someone on it"):
            trips.edit_trip(self.c, self.jane, trip_id, {"people": []})
        self.assertEqual(self.aboard(trip_id), [self.jid])
        self.assertEqual(self.excluded(trip_id), set())
        self.assertIsNotNone(trips.get(self.c, self.jane, trip_id))
        trips.edit_trip(self.c, Viewer(self.jid, household=True), trip_id, {"people": []})
        self.assertEqual(self.aboard(trip_id), [])

    def test_adding_them_and_taking_them_off_again_keeps_one_record_and_the_last_change_wins(self):
        self.email(self.jane, self.jid)
        trip_id = self.c.orm.scalars(select(Segment.trip_id)).one()
        self.put_on(self.jane, trip_id, self.sid)
        self.take_off(self.jane, trip_id, self.sid)
        self.put_on(self.jane, trip_id, self.sid)
        self.take_off(self.jane, trip_id, self.sid)
        self.assertEqual(self.excluded(trip_id), {self.sid})
        self.assertEqual(len(self.c.orm.scalars(select(TripExclusion)).all()), 1)
        self.put_on(self.jane, trip_id, self.sid)
        self.assertEqual(self.aboard(trip_id), [self.jid, self.sid])
        self.assertIsNotNone(trips.get(self.c, self.sam, trip_id))


class OtherTripsAndOtherViewers(Removal):
    def test_taking_them_off_one_trip_leaves_what_they_booked_on_another(self):
        a = self.booked_by_sam(OUT)
        b = self.booked_by_sam(FAR)
        self.assertNotEqual(a["trip_id"], b["trip_id"])
        self.take_off(self.jane, a["trip_id"], self.sid)
        self.assertIsNone(trips.get(self.c, self.sam, a["trip_id"]))
        self.assertIsNotNone(trips.get(self.c, self.sam, b["trip_id"]))
        self.assertEqual([t.id for t in visibility.visible_trips(self.c, self.sam)], [b["trip_id"]])
        self.assertEqual(self.c.orm.get(Trip, b["trip_id"]).booked_by, self.sid)
        self.assertEqual(self.c.orm.get(Segment, b["id"]).booked_by, self.sid)
        self.assertEqual(self.excluded(b["trip_id"]), set())
        self.assertEqual(self.excluded(a["trip_id"]), {self.sid})

    def test_a_viewer_with_sign_in_off_still_sees_everything(self):
        flight = self.booked_by_sam()
        trip_id = flight["trip_id"]
        everyone = Viewer(self.sid, household=True)
        self.take_off(self.jane, trip_id, self.sid)
        self.assertIsNotNone(trips.get(self.c, everyone, trip_id))
        self.assertEqual([t["id"] for t in trips.listing(self.c, everyone)], [trip_id])
        self.assertIsNotNone(trips.get_segment(self.c, everyone, flight["id"]))
        self.assertIsNone(trips.get(self.c, self.sam, trip_id))

    def test_the_household_view_takes_someone_off_completely_without_asking(self):
        flight = self.booked_by_sam()
        trip_id = flight["trip_id"]
        everyone = Viewer(self.jid, household=True)
        trips.edit_trip(self.c, everyone, trip_id, {"people": [self.jid]})
        self.assertIsNone(trips.get(self.c, self.sam, trip_id))
        self.assertEqual(self.excluded(trip_id), {self.sid})

    def test_a_claimed_guests_exclusions_move_to_the_member_unless_the_member_is_on_the_trip(self):
        mine = self.add(self.jane, OUT, None, self.on(self.jid))
        other = self.add(self.jane, FAR, None, self.on(self.jid))
        self.put_on(self.jane, mine["trip_id"], self.mia, self.sid)
        self.take_off(self.jane, mine["trip_id"], self.mia, self.sid)
        self.put_on(self.jane, other["trip_id"], self.sid, self.mia)
        self.take_off(self.jane, other["trip_id"], self.mia)
        people.claim_guest(self.c, self.sid, self.mia, "2026-10-05")
        rows = {(r.trip_id, r.person_id) for r in self.c.orm.scalars(select(TripExclusion)).all()}
        self.assertEqual(rows, {(mine["trip_id"], self.sid)})
        self.assertIsNotNone(trips.get(self.c, self.sam, other["trip_id"]))
        self.assertIsNone(trips.get(self.c, self.sam, mine["trip_id"]))

    def test_taking_yourself_off_a_trip_you_booked_leaves_you_nothing_and_the_answer_says_nothing_of_it(self):
        stay = self.add(self.jane, HOTEL)
        trip_id = stay["trip_id"]
        trips.edit_trip(self.c, self.jane, trip_id, {"people": [self.jid, self.sid], "name": "Canarystone reunion", "notes": CANARY}, True)
        with no_leaks(self, CANARY, "Canarystone reunion"):
            left = trips.edit_trip(self.c, self.jane, trip_id, {"people": [self.sid]})
            self.assertEqual((left["id"], left["name"], left["notes"], left["people"], left["segments"], left["booked_by"]),
                             (trip_id, "", None, [], [], None))
            self.assertNotIn("Canarystone", json.dumps(left))
            self.assertSeesNothing(self.jane, trip_id, [stay["id"]])
        self.assertEqual(self.aboard(trip_id), [self.sid])
        self.assertEqual(trips.get(self.c, self.sam, trip_id)["name"], "Canarystone reunion")

    def test_nothing_of_a_removed_persons_trip_reaches_them_or_anyone_else(self):
        who = people.add_guest(self.c, guest(CANARY))["id"]
        flight = self.add(self.sam, {**OUT, "confirmation": CODE}, None, self.on(self.sid, self.jid, who))
        trips.edit_segment(self.c, self.sam, flight["id"], {"travelers": self.on(self.jid, who)})
        trip_id = flight["trip_id"]
        with no_leaks(self, CANARY, CODE):
            self.take_off(self.jane, trip_id, self.sid)
            self.assertSeesNothing(self.sam, trip_id, [flight["id"]])
            self.assertStrangersSeeNothing(trip_id, [flight["id"]])
            self.assertIsNone(trips.merge(self.c, self.sam, trip_id, trip_id + 1000))
            self.assertIsNone(trips.edit_trip(self.c, self.sam, trip_id, {"people": [self.sid, who]}, True))
            self.assertIsNone(trips.move_segment(self.c, self.sam, flight["id"], None))
            self.assertFalse(trips.delete_segment(self.c, self.sam, flight["id"]))
            self.assertFalse(trips.delete_trip(self.c, self.sam, trip_id))
        self.assertEqual(self.aboard(trip_id), [self.jid, who])
        self.assertEqual(self.c.orm.scalars(select(SegmentTraveler.person_id).where(SegmentTraveler.person_id == self.sid)).all(), [])
