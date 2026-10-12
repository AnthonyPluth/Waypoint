from sqlalchemy import select, update

from waypoint.domain import people, trippeople, trips, visibility
from waypoint.domain.visibility import Viewer
from waypoint.storage.models import Segment, SegmentTraveler, Trip, TripPerson
from tests.privacy import no_leaks
from tests.test_trips import BACK, HOTEL, OUT, Household, guest

SHIP = {"kind": "cruise", "origin": "Port Example", "destination": "Port Example", "start_local": "2026-06-02T15:00",
        "end_local": "2026-06-08T10:00", "start_zone": "Europe/London", "end_zone": "Europe/London"}

FAR = {**OUT, "start_local": "2026-09-10T19:00", "end_local": "2026-09-11T07:10"}


class TripPeopleCase(Household):

    def setUp(self):
        super().setUp()
        self.jid, self.sid = self.jane.person_id, self.sam.person_id

    def aboard(self, trip_id):
        return trippeople.of(self.c, [trip_id])[trip_id]

    def share(self, segment_id):
        self.c.execute(update(Segment).where(Segment.id == segment_id).values(travelers_from_trip=True))
        self.c.execute(SegmentTraveler.__table__.delete().where(SegmentTraveler.segment_id == segment_id))
        self.c.orm.expire_all()

    def hotel_for_everyone(self, *ids):
        flight = self.add(self.jane, OUT, None, self.on(*ids))
        stay = self.add(self.jane, HOTEL, flight["trip_id"], self.on(*ids))
        self.share(stay["id"])
        return flight["trip_id"], stay["id"]


class TheInvariant(TripPeopleCase):
    def test_a_trip_lists_everyone_named_on_its_bookings(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        self.assertEqual(trips.get(self.c, self.jane, flight["trip_id"])["people"], [self.jid, self.mia])
        self.add(self.jane, SHIP, flight["trip_id"], self.on(self.jid, self.sid))
        self.assertEqual(self.aboard(flight["trip_id"]), [self.jid, self.mia, self.sid])

    def test_a_name_as_printed_is_not_a_person_until_it_is_matched(self):
        seg = self.add(self.jane, OUT, None, [{"person_id": self.jid, "name": None}, {"person_id": None, "name": "DOE/JOAN MRS"}])
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid])
        printed = next(t for t in seg["travelers"] if t["person_id"] is None)
        trips.name_traveler(self.c, self.jane, printed["id"], self.joan)
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, self.joan])

    def test_editing_a_bookings_travellers_adds_them_and_taking_one_off_keeps_them_on_the_trip(self):
        seg = self.add(self.jane, SHIP, None, self.on(self.jid))
        trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": self.on(self.jid, self.joan)})
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, self.joan])
        trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": self.on(self.jid)})
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, self.joan])

    def test_a_person_an_email_adds_to_a_booking_joins_the_trip(self):
        seg = self.add(self.jane, {**HOTEL, "confirmation": "STAY123"}, None, self.on(self.jid))
        mail = {**HOTEL, "confirmation": "STAY123", "travelers": self.on(self.joan)}
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, mail), "updated")
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, self.joan])

    def test_a_booking_added_without_travellers_puts_the_person_adding_it_on_the_trip(self):
        seg = self.add(self.jane, OUT)
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid])

    def test_deleting_the_last_booking_of_a_grouped_trip_takes_its_people_with_it(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        trips.delete_segment(self.c, self.jane, seg["id"])
        self.assertEqual(self.c.orm.scalars(select(TripPerson)).all(), [])

    def test_a_person_removed_from_people_leaves_every_trip(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        self.assertTrue(people.remove_guest(self.c, self.mia))
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid])


class BookingsForEveryone(TripPeopleCase):
    def test_a_booking_for_everyone_shows_the_trips_people_as_its_travellers(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        got = trips.get_segment(self.c, self.jane, stay_id)
        self.assertEqual([(t["person_id"], t["name"], t["seat"], t["id"]) for t in got["travelers"]],
                         [(self.jid, "Jane Doe", None, 0), (self.mia, "Mia Doe", None, 0)])
        trip = trips.get(self.c, self.jane, trip_id)
        self.assertEqual([[t["person_id"] for t in s["travelers"]] for s in trip["segments"] if s["kind"] == "hotel"], [[self.jid, self.mia]])
        seg = self.c.orm.get(Segment, stay_id)
        self.assertEqual(trips.effective_travelers(self.c, seg), [{"person_id": self.jid, "name": None, "seat": None},
                                                                  {"person_id": self.mia, "name": None, "seat": None}])

    def test_a_booking_for_everyone_follows_the_trip_when_someone_joins(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid)
        trips.edit_trip(self.c, self.jane, trip_id, {"people": [self.jid, self.joan]}, True)
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay_id)["travelers"]], [self.jid, self.joan])

    def test_sending_back_the_travellers_it_shows_leaves_it_for_everyone(self):
        _, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        shown = trips.get_segment(self.c, self.jane, stay_id)["travelers"]
        trips.edit_segment(self.c, self.jane, stay_id, {"travelers": [{"person_id": t["person_id"], "name": None} for t in shown],
                                                         "details": {"room": "4B"}})
        self.assertTrue(self.c.orm.get(Segment, stay_id).travelers_from_trip)
        self.assertEqual(self.c.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == stay_id)).all(), [])

    def test_a_list_sent_for_a_booking_for_everyone_is_ignored(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        trips.edit_segment(self.c, self.jane, stay_id, {"travelers": self.on(self.jid)})
        self.assertTrue(self.c.orm.get(Segment, stay_id).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay_id)["travelers"]], [self.jid, self.mia])
        self.assertEqual(self.aboard(trip_id), [self.jid, self.mia])

    def test_an_email_naming_someone_new_freezes_the_list_and_adds_them(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        self.c.orm.get(Segment, stay_id).confirmation = "STAY999"
        self.c.orm.flush()
        trips.merge_email_segment(self.c, self.jane, {**HOTEL, "confirmation": "STAY999", "travelers": self.on(self.joan)})
        self.c.orm.expire_all()
        self.assertFalse(self.c.orm.get(Segment, stay_id).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay_id)["travelers"]], [self.jid, self.mia, self.joan])
        self.assertEqual(self.aboard(trip_id), [self.jid, self.mia, self.joan])

    def test_loading_a_bookings_travellers_does_not_need_rows_of_its_own(self):
        _, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        self.assertEqual(self.c.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == stay_id)).all(), [])
        self.assertEqual(len(trips.get_segment(self.c, self.jane, stay_id)["travelers"]), 2)


class CreatingAndEditingPeople(TripPeopleCase):
    def test_a_trip_made_with_people_lists_them_and_asks_before_anyone_but_the_maker_is_added(self):
        with self.assertRaises(trips.NeedsConfirmation) as asked:
            trips.create_trip(self.c, self.jane, {"name": "Road trip", "people": [self.jid, self.mia]})
        self.assertEqual(asked.exception.see_trip, [{"id": self.mia, "name": "Mia Doe"}])
        self.assertEqual(asked.exception.see_booking, [])
        self.assertEqual(self.c.orm.scalars(select(Trip)).all(), [])
        made = trips.create_trip(self.c, self.jane, {"name": "Road trip", "people": [self.jid, self.mia]}, True)
        self.assertEqual(made["people"], [self.jid, self.mia])
        alone = trips.create_trip(self.c, self.jane, {"name": "Solo", "people": [self.jid]})
        self.assertEqual(alone["people"], [self.jid])
        self.assertEqual(trips.create_trip(self.c, self.jane, {"name": "Nobody"})["people"], [])

    def test_the_household_view_adds_people_without_asking(self):
        everyone = Viewer(self.jid, household=True)
        self.assertEqual(trips.create_trip(self.c, everyone, {"name": "Reunion", "people": [self.mia, self.joan, self.mia]})["people"],
                         [self.mia, self.joan])

    def test_someone_who_is_not_in_people_is_refused(self):
        with self.assertRaisesRegex(trips.Invalid, "isn’t in People"):
            trips.create_trip(self.c, self.jane, {"name": "Road trip", "people": [99999]})
        seg = self.add(self.jane, OUT, None, self.on(self.jid))
        with self.assertRaisesRegex(trips.Invalid, "isn’t in People"):
            trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, 99999]}, True)
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid])

    def test_adding_someone_who_already_sees_the_trip_needs_no_confirmation(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid, self.sid))
        self.c.execute(TripPerson.__table__.delete().where(TripPerson.person_id == self.sid))
        got = trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, self.sid]})
        self.assertEqual(got["people"], [self.jid, self.sid])

    def test_adding_someone_who_cannot_see_the_trip_yet_asks_first_and_names_them(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid))
        with self.assertRaises(trips.NeedsConfirmation) as asked:
            trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, self.mia, self.joan]})
        self.assertEqual([p["name"] for p in asked.exception.see_trip], ["Grandma Joan", "Mia Doe"])
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid])
        got = trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, self.mia, self.joan]}, True)
        self.assertEqual(got["people"], [self.jid, self.mia, self.joan])

    def test_a_trip_someone_cannot_see_does_not_give_up_its_people(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        self.assertIsNone(trips.edit_trip(self.c, self.sam, seg["trip_id"], {"people": []}))
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, self.mia])
        self.assertIsNone(trips.get(self.c, self.sam, seg["trip_id"]))

    def test_taking_someone_off_removes_them_from_the_other_bookings_but_not_the_other_people(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid))
        trip_id = flight["trip_id"]
        stay = self.add(self.jane, SHIP, trip_id, self.on(self.jid, self.mia))
        car = self.add(self.jane, {**SHIP, "start_local": "2026-06-03T09:00", "end_local": "2026-06-07T09:00"}, trip_id, self.on(self.mia, self.joan))
        got = trips.edit_trip(self.c, self.jane, trip_id, {"people": [self.jid, self.joan]})
        self.assertEqual(got["people"], [self.jid, self.joan])
        by_id = {s["id"]: [t["person_id"] for t in s["travelers"]] for s in got["segments"]}
        self.assertEqual((by_id[stay["id"]], by_id[car["id"]], by_id[flight["id"]]), ([self.jid], [self.joan], [self.jid]))

    def test_taking_someone_off_is_refused_while_they_are_on_a_flight_and_names_it(self):
        out = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        back = self.add(self.jane, BACK, out["trip_id"], self.on(self.jid))
        self.assertTrue(back)
        with self.assertRaisesRegex(trips.Invalid, r"Mia Doe is on a flight in this trip \(JFK to LHR\)"):
            trips.edit_trip(self.c, self.jane, out["trip_id"], {"people": [self.jid]})
        self.assertEqual(self.aboard(out["trip_id"]), [self.jid, self.mia])
        trips.edit_segment(self.c, self.jane, out["id"], {"travelers": self.on(self.jid)})
        got = trips.edit_trip(self.c, self.jane, out["trip_id"], {"people": [self.jid]})
        self.assertEqual(got["people"], [self.jid])

    def test_the_refusal_leaves_the_other_removals_undone(self):
        out = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        stay = self.add(self.jane, SHIP, out["trip_id"], self.on(self.jid, self.joan))
        with self.assertRaises(trips.Invalid):
            trips.edit_trip(self.c, self.jane, out["trip_id"], {"people": [self.jid]})
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay["id"])["travelers"]], [self.jid, self.joan])
        self.assertEqual(self.aboard(out["trip_id"]), [self.jid, self.mia, self.joan])

    def test_a_booking_for_everyone_drops_someone_taken_off_the_trip(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        self.c.execute(SegmentTraveler.__table__.delete().where(SegmentTraveler.person_id == self.mia))
        trips.edit_trip(self.c, self.jane, trip_id, {"people": [self.jid]})
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay_id)["travelers"]], [self.jid])

    def test_nothing_about_the_people_is_logged_or_sent(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid))
        who = people.add_guest(self.c, guest("Zebulon Canarystone"))["id"]
        with no_leaks(self, "Zebulon Canarystone", "Canarystone"):
            with self.assertRaises(trips.NeedsConfirmation):
                trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, who]})
            trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, who]}, True)
            trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid]})


class WhoSeesATrip(TripPeopleCase):
    def stranger(self):
        return Viewer(self.joan)

    def test_someone_added_to_a_trips_people_sees_the_trip_its_bookings_and_travellers(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid))
        stay = self.add(self.jane, HOTEL, seg["trip_id"])
        self.assertIsNone(trips.get(self.c, self.sam, seg["trip_id"]))
        trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, self.sid]}, True)
        seen = trips.get(self.c, self.sam, seg["trip_id"])
        assert seen
        self.assertEqual(sorted(s["id"] for s in seen["segments"]), sorted([seg["id"], stay["id"]]))
        self.assertEqual([t.id for t in visibility.visible_trips(self.c, self.sam)], [seg["trip_id"]])
        self.assertEqual(len(trips.listing(self.c, self.sam)), 1)
        self.assertIsNotNone(trips.get_segment(self.c, self.sam, stay["id"]))
        self.assertEqual([s.id for s in visibility.visible_segments(self.c, self.sam)], [seg["id"], stay["id"]])
        self.assertEqual([t.person_id for t in visibility.visible_travelers(self.c, self.sam, [seg["id"]])], [self.jid])

    def test_a_person_on_a_booking_for_everyone_sees_the_trip_without_a_row_on_any_booking(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid, self.sid)
        self.c.execute(SegmentTraveler.__table__.delete())
        self.c.orm.expire_all()
        self.assertEqual(self.aboard(trip_id), [self.jid, self.sid])
        self.assertIsNotNone(trips.get(self.c, self.sam, trip_id))
        self.assertIsNotNone(trips.get_segment(self.c, self.sam, stay_id))

    def test_taking_someone_off_the_trip_ends_their_access_and_a_stranger_never_gains_any(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid))
        trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, self.sid]}, True)
        self.assertIsNotNone(trips.get(self.c, self.sam, seg["trip_id"]))
        trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid]})
        self.assertIsNone(trips.get(self.c, self.sam, seg["trip_id"]))
        self.assertIsNone(trips.get_segment(self.c, self.sam, seg["id"]))
        self.assertEqual(trips.listing(self.c, self.sam), [])

    def test_a_stranger_sees_nothing_of_a_trip_with_a_people_list(self):
        canary = "Zebulon Canarystone"
        who = people.add_guest(self.c, guest(canary))["id"]
        seg = self.add(self.jane, {**OUT, "confirmation": "CANARY77XQ"}, None, self.on(self.jid, who))
        trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, who, self.sid]}, True)
        with no_leaks(self, canary, "CANARY77XQ"):
            stranger = self.stranger()
            self.assertIsNone(trips.get(self.c, stranger, seg["trip_id"]))
            self.assertIsNone(trips.get_segment(self.c, stranger, seg["id"]))
            self.assertEqual(trips.listing(self.c, stranger), [])
            self.assertEqual(visibility.visible_segments(self.c, stranger), [])
            self.assertEqual(visibility.visible_travelers(self.c, stranger, [seg["id"]]), [])
            self.assertEqual(trips.unmatched_count(self.c, stranger), 0)
            self.assertIsNone(trips.merge(self.c, stranger, seg["trip_id"], seg["trip_id"] + 1000))
            self.assertIsNone(trips.edit_trip(self.c, stranger, seg["trip_id"], {"people": [self.joan]}, True))
            self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, who, self.sid])

    def test_someone_who_only_sees_a_trip_through_its_people_cannot_change_who_else_is_on_it_without_asking(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid))
        trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, self.sid]}, True)
        with self.assertRaises(trips.NeedsConfirmation):
            trips.edit_trip(self.c, self.sam, seg["trip_id"], {"people": [self.jid, self.sid, self.mia]})
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, self.sid])

    def test_moving_a_booking_into_a_trip_gives_its_travellers_the_trip_and_the_trips_people_the_booking(self):
        a = self.add(self.jane, OUT, None, self.on(self.jid))
        b = self.add(self.jane, FAR, None, self.on(self.jid, self.sid))
        with self.assertRaises(trips.NeedsConfirmation):
            trips.move_segment(self.c, self.jane, a["id"], b["trip_id"])
        trips.move_segment(self.c, self.jane, a["id"], b["trip_id"], True)
        self.assertIsNotNone(trips.get_segment(self.c, self.sam, a["id"]))

    def test_merging_gives_each_trips_people_the_other_trips_bookings_and_a_stranger_nothing(self):
        a = self.add(self.jane, OUT, None, self.on(self.jid, self.sid))
        b = self.add(self.jane, FAR, None, self.on(self.jid, self.mia))
        with self.assertRaises(trips.NeedsConfirmation) as asked:
            trips.merge(self.c, self.jane, a["trip_id"], b["trip_id"])
        self.assertEqual([p["id"] for p in asked.exception.see_booking], [self.mia])
        self.assertEqual([p["id"] for p in asked.exception.see_trip], [self.sid])
        trips.merge(self.c, self.jane, a["trip_id"], b["trip_id"], True)
        self.assertEqual(sorted(self.aboard(a["trip_id"])), sorted([self.jid, self.sid, self.mia]))
        self.assertIsNotNone(trips.get_segment(self.c, self.sam, b["id"]))
        self.assertIsNone(trips.get_segment(self.c, self.stranger(), b["id"]))
        self.assertIsNone(trips.get(self.c, self.stranger(), a["trip_id"]))


class GuestsClaimed(TripPeopleCase):
    def test_a_claimed_guest_is_replaced_by_the_member_on_every_trip(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        other = self.add(self.jane, BACK, None, self.on(self.mia, self.sid))
        self.assertNotEqual(seg["trip_id"], other["trip_id"])
        people.claim_guest(self.c, self.sid, self.mia, "2026-10-05")
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, self.sid])
        self.assertEqual(self.aboard(other["trip_id"]), [self.sid])
        self.assertEqual(self.c.orm.scalars(select(TripPerson).where(TripPerson.person_id == self.mia)).all(), [])

    def test_a_member_already_on_the_trip_is_not_listed_twice(self):
        seg = self.add(self.jane, OUT, None, self.on(self.sid, self.mia))
        people.claim_guest(self.c, self.sid, self.mia, "2026-10-05")
        self.assertEqual(self.aboard(seg["trip_id"]), [self.sid])
        self.assertEqual(len(self.c.orm.scalars(select(TripPerson)).all()), 1)

    def test_a_guest_listed_only_on_the_trip_still_gives_the_member_their_place(self):
        seg = self.add(self.jane, OUT, None, self.on(self.jid))
        trips.edit_trip(self.c, self.jane, seg["trip_id"], {"people": [self.jid, self.mia]}, True)
        people.claim_guest(self.c, self.sid, self.mia, "2026-10-05")
        self.assertEqual(self.aboard(seg["trip_id"]), [self.jid, self.sid])


class MergingSplittingMoving(TripPeopleCase):
    def test_merging_joins_the_people_and_freezes_a_booking_for_everyone_whose_group_grew(self):
        everyone = Viewer(self.jid, household=True)
        trip_id, stay_id = self.hotel_for_everyone(self.jid)
        other = self.add(self.jane, FAR, None, self.on(self.jid, self.mia))
        merged = trips.merge(self.c, everyone, trip_id, other["trip_id"])
        self.assertEqual(merged["people"], [self.jid, self.mia])
        self.assertFalse(self.c.orm.get(Segment, stay_id).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay_id)["travelers"]], [self.jid])
        self.assertEqual(self.c.orm.scalars(select(TripPerson).where(TripPerson.trip_id == other["trip_id"])).all(), [])

    def test_merging_trips_of_the_same_people_keeps_a_booking_for_everyone_that_way(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        other = self.add(self.jane, FAR, None, self.on(self.jid, self.mia))
        merged = trips.merge(self.c, self.jane, trip_id, other["trip_id"])
        self.assertEqual(merged["people"], [self.jid, self.mia])
        self.assertTrue(self.c.orm.get(Segment, stay_id).travelers_from_trip)

    def test_merging_keeps_a_bookings_own_list_inside_the_trip(self):
        everyone = Viewer(self.jid, household=True)
        a = self.add(self.jane, OUT, None, self.on(self.jid))
        b = self.add(self.jane, FAR, None, self.on(self.joan))
        merged = trips.merge(self.c, everyone, a["trip_id"], b["trip_id"])
        self.assertEqual(merged["people"], [self.jid, self.joan])

    def test_splitting_gives_the_new_trip_the_people_on_the_bookings_it_took(self):
        out = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        stay = self.add(self.jane, SHIP, out["trip_id"], self.on(self.jid, self.joan))
        new = trips.split(self.c, self.jane, out["trip_id"], [stay["id"]])
        self.assertEqual(new["people"], [self.jid, self.joan])
        self.assertEqual(self.aboard(out["trip_id"]), [self.jid, self.mia])

    def test_splitting_off_a_booking_for_everyone_takes_the_whole_group_with_it(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        new = trips.split(self.c, self.jane, trip_id, [stay_id])
        self.assertEqual(new["people"], [self.jid, self.mia])
        self.assertTrue(self.c.orm.get(Segment, stay_id).travelers_from_trip)

    def test_splitting_a_booking_for_everyone_off_with_a_smaller_one_still_takes_the_whole_group(self):
        trip_id, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        seg = self.add(self.jane, {**BACK, "start_local": "2026-06-09T11:00", "end_local": "2026-06-09T14:05"}, trip_id, self.on(self.jid))
        trips.edit_trip(self.c, self.jane, trip_id, {"people": [self.jid, self.mia, self.joan]}, True)
        new = trips.split(self.c, self.jane, trip_id, [stay_id, seg["id"]])
        self.assertEqual(new["people"], [self.jid, self.mia, self.joan])
        self.assertTrue(self.c.orm.get(Segment, stay_id).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay_id)["travelers"]], [self.jid, self.mia, self.joan])
        self.assertEqual(self.aboard(trip_id), [self.jid, self.mia])

    def test_moving_a_booking_puts_its_travellers_on_the_target_trip(self):
        a = self.add(self.jane, OUT, None, self.on(self.jid))
        b = self.add(self.jane, BACK, None, self.on(self.jid, self.mia))
        trips.move_segment(self.c, self.jane, a["id"], b["trip_id"], True)
        self.assertEqual(self.aboard(b["trip_id"]), [self.jid, self.mia])
        c = self.add(self.jane, {**OUT, "start_local": "2026-08-01T19:00", "end_local": "2026-08-02T07:10"}, None, self.on(self.jid, self.joan))
        trips.move_segment(self.c, self.jane, c["id"], b["trip_id"], True)
        self.assertEqual(self.aboard(b["trip_id"]), [self.jid, self.mia, self.joan])

    def test_moving_a_booking_out_to_a_new_trip_gives_that_trip_its_people(self):
        a = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        b = self.add(self.jane, BACK, a["trip_id"], self.on(self.jid))
        moved = trips.move_segment(self.c, self.jane, b["id"], None)
        self.assertEqual(moved["people"], [self.jid])
        self.assertEqual(self.aboard(a["trip_id"]), [self.jid, self.mia])

    def test_a_booking_for_everyone_moved_to_a_trip_of_other_people_keeps_its_own_group(self):
        _, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        elsewhere = self.add(self.jane, {**OUT, "start_local": "2026-09-10T19:00", "end_local": "2026-09-11T07:10"}, None,
                             self.on(self.jid, self.sid))
        asked = None
        try:
            trips.move_segment(self.c, self.jane, stay_id, elsewhere["trip_id"])
        except trips.NeedsConfirmation as e:
            asked = e
        assert asked
        self.assertEqual([p["id"] for p in asked.see_booking], [self.sid])
        self.assertEqual([p["id"] for p in asked.see_trip], [self.mia])
        trips.move_segment(self.c, self.jane, stay_id, elsewhere["trip_id"], True)
        self.assertFalse(self.c.orm.get(Segment, stay_id).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay_id)["travelers"]], [self.jid, self.mia])
        self.assertEqual(self.aboard(elsewhere["trip_id"]), [self.jid, self.sid, self.mia])

    def test_a_booking_for_everyone_moved_to_a_trip_of_the_same_people_stays_that_way(self):
        _, stay_id = self.hotel_for_everyone(self.jid, self.mia)
        elsewhere = self.add(self.jane, {**OUT, "start_local": "2026-09-10T19:00", "end_local": "2026-09-11T07:10"}, None,
                             self.on(self.jid, self.mia))
        trips.move_segment(self.c, self.jane, stay_id, elsewhere["trip_id"])
        self.assertTrue(self.c.orm.get(Segment, stay_id).travelers_from_trip)

    def test_grouping_a_new_booking_counts_the_trips_people_not_only_its_bookings(self):
        a = self.add(self.jane, OUT, None, self.on(self.jid))
        trips.edit_trip(self.c, self.jane, a["trip_id"], {"people": [self.jid, self.mia]}, True)
        self.add(self.jane, HOTEL, None, self.on(self.jid, self.mia))
        self.assertEqual(len(trips.listing(self.c, self.jane)), 1)


CAR = {"kind": "car", "origin": "LHR", "destination": "LHR", "start_local": "2026-06-02T09:00", "end_local": "2026-06-08T09:00",
       "start_zone": "Europe/London", "end_zone": "Europe/London"}
LOT = {"kind": "parking", "origin": "Example Lot", "start_local": "2026-06-01T12:00", "end_local": "2026-06-09T12:00", "start_zone": "Europe/London"}
FAR = {**OUT, "start_local": "2026-09-10T19:00", "end_local": "2026-09-11T07:10"}


class AddedByHand(TripPeopleCase):
    def test_a_hotel_car_or_parking_spot_added_by_hand_is_for_everyone_whatever_list_is_sent(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        for fields in (HOTEL, CAR, LOT):
            with self.subTest(kind=fields["kind"]):
                got = self.add(self.jane, fields, flight["trip_id"], self.on(self.sid, self.joan))
                seg = self.c.orm.get(Segment, got["id"])
                self.assertTrue(seg.travelers_from_trip)
                self.assertEqual(self.c.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == got["id"])).all(), [])
                self.assertEqual([t["person_id"] for t in got["travelers"]], [self.jid, self.mia])
        self.assertEqual(self.aboard(flight["trip_id"]), [self.jid, self.mia])
        self.assertIsNone(trips.get(self.c, self.sam, flight["trip_id"]))

    def test_the_names_sent_with_a_hotel_are_not_kept_anywhere(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid))
        with no_leaks(self, "Quentin Canaryfield"):
            got = self.add(self.jane, HOTEL, flight["trip_id"], [{"person_id": None, "name": "Quentin Canaryfield"}])
        self.assertEqual(self.c.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.name == "Quentin Canaryfield")).all(), [])
        self.assertTrue(self.c.orm.get(Segment, got["id"]).travelers_from_trip)

    def test_a_new_trip_from_a_hotel_alone_lists_the_person_who_added_it(self):
        got = self.add(self.jane, HOTEL)
        self.assertEqual(self.aboard(got["trip_id"]), [self.jid])
        self.assertEqual([t["person_id"] for t in got["travelers"]], [self.jid])

    def test_a_flight_or_cruise_added_by_hand_keeps_the_travellers_sent(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        ship = self.add(self.jane, SHIP, flight["trip_id"], self.on(self.jid, self.joan))
        self.assertFalse(self.c.orm.get(Segment, ship["id"]).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in ship["travelers"]], [self.jid, self.joan])
        self.assertEqual(self.aboard(flight["trip_id"]), [self.jid, self.mia, self.joan])

    def test_editing_one_keeps_it_for_everyone_and_changing_it_to_a_train_gives_it_the_current_list(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        stay = self.add(self.jane, HOTEL, flight["trip_id"])
        trips.edit_segment(self.c, self.jane, stay["id"], {"details": {"room": "9"}, "travelers": self.on(self.joan)})
        self.assertTrue(self.c.orm.get(Segment, stay["id"]).travelers_from_trip)
        changed = trips.edit_segment(self.c, self.jane, stay["id"], {"kind": "train", "origin": "A", "destination": "B"})
        self.assertFalse(self.c.orm.get(Segment, stay["id"]).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in changed["travelers"]], [self.jid, self.mia])

    def test_a_flight_edited_into_a_hotel_becomes_for_everyone_when_everyone_on_it_still_sees_the_trip(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        other = self.add(self.jane, BACK, flight["trip_id"], self.on(self.jid, self.mia))
        changed = trips.edit_segment(self.c, self.jane, other["id"], {"kind": "hotel", "origin": "Harbour Hotel", "destination": None,
                                                                    "start_zone": "Europe/London", "end_zone": "Europe/London"})
        seg = self.c.orm.get(Segment, other["id"])
        self.assertTrue(seg.travelers_from_trip)
        self.assertEqual(self.c.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == other["id"])).all(), [])
        self.assertEqual([t["person_id"] for t in changed["travelers"]], [self.jid, self.mia])
        self.assertEqual(self.aboard(flight["trip_id"]), [self.jid, self.mia])

    def test_a_flight_edited_into_a_hotel_keeps_its_list_when_someone_on_it_would_lose_the_trip(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        changed = trips.edit_segment(self.c, self.jane, flight["id"], {"kind": "hotel", "origin": "Harbour Hotel", "destination": None,
                                                                     "start_zone": "Europe/London", "end_zone": "Europe/London"})
        self.assertFalse(self.c.orm.get(Segment, flight["id"]).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in changed["travelers"]], [self.jid, self.mia])
        self.assertIsNotNone(trips.get(self.c, Viewer(self.mia), flight["trip_id"]))

    def test_an_existing_hotel_with_its_own_travellers_is_left_as_it_is(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        seg = Segment(trip_id=flight["trip_id"], kind="hotel", status="confirmed", source="manual", booked_by=self.jid, origin="Old Hotel",
                      start_local="2026-06-02T15:00", start_zone="Europe/London", end_local="2026-06-08T10:00", end_zone="Europe/London")
        self.c.orm.add(seg)
        self.c.orm.flush()
        self.c.orm.add(SegmentTraveler(segment_id=seg.id, person_id=self.jid))
        self.c.orm.flush()
        got = trips.edit_segment(self.c, self.jane, seg.id, {"details": {"room": "2"}})
        self.assertFalse(self.c.orm.get(Segment, seg.id).travelers_from_trip)
        self.assertEqual([t["person_id"] for t in got["travelers"]], [self.jid])

    def test_moving_one_into_a_trip_keeps_it_for_everyone_when_the_people_match_and_asks_when_they_do_not(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        stay = self.add(self.jane, HOTEL, flight["trip_id"])
        same = self.add(self.jane, FAR, None, self.on(self.jid, self.mia))
        trips.move_segment(self.c, self.jane, stay["id"], same["trip_id"])
        self.assertTrue(self.c.orm.get(Segment, stay["id"]).travelers_from_trip)
        other = self.add(self.jane, {**FAR, "start_local": "2027-03-01T19:00", "end_local": "2027-03-02T07:10"}, None, self.on(self.jid, self.sid))
        with self.assertRaises(trips.NeedsConfirmation):
            trips.move_segment(self.c, self.jane, stay["id"], other["trip_id"])
        trips.move_segment(self.c, self.jane, stay["id"], other["trip_id"], True)
        self.assertFalse(self.c.orm.get(Segment, stay["id"]).travelers_from_trip)
        self.assertEqual(sorted(self.aboard(other["trip_id"])), sorted([self.jid, self.sid, self.mia]))
