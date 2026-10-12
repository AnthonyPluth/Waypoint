import dataclasses
from datetime import UTC, datetime

from sqlalchemy import select

from waypoint.domain import offline, stats, trippeople, trips, visibility
from waypoint.domain.mail import ingest
from waypoint.domain.visibility import Viewer
from waypoint.storage.models import Segment, SegmentTraveler
from tests.privacy import no_leaks
from tests.test_mail_extract import FIXTURES, message
from tests.test_trip_people import TripPeopleCase
from tests.test_trips import BACK, OUT
from waypoint.domain.mail import extract

LEAD_CANARY = "Zebulon Canaryfield"
NOW = datetime(2027, 1, 12, 12, 0, tzinfo=UTC)


def booking(name, replace=None):
    raw = (FIXTURES / f"{name}.eml").read_bytes()
    for old, new in (replace or {}).items():
        raw = raw.replace(old.encode(), new.encode())
    [b] = extract.read(message(raw)).bookings
    return b


class IngestCase(TripPeopleCase):
    def file(self, viewer, b, **kw):
        outcome = ingest.file_booking(self.c, viewer, b, **kw)
        self.assertIn(outcome, ("added", "updated", "unchanged", "attached"))
        return outcome

    def stays(self):
        return list(self.c.orm.scalars(select(Segment).where(Segment.kind == "hotel").order_by(Segment.id)).all())

    def rows(self, segment_id):
        return list(self.c.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == segment_id).order_by(SegmentTraveler.id)).all())


class EmailBookingsForEveryone(IngestCase):
    def test_a_hotel_email_naming_a_household_member_is_for_everyone_on_the_trip_with_no_traveller_row(self):
        self.file(self.jane, booking("hotel_jsonld"))
        [stay] = self.stays()
        self.assertTrue(stay.travelers_from_trip)
        self.assertEqual(self.rows(stay.id), [])
        self.assertEqual(self.aboard(stay.trip_id), [self.jid])
        shown = trips.get_segment(self.c, self.jane, stay.id)["travelers"]
        self.assertEqual([(t["person_id"], t["name"]) for t in shown], [(self.jid, "Jane Doe")])

    def test_a_lead_guest_nobody_knows_leaves_no_stray_row_and_is_not_shown(self):
        with no_leaks(self, LEAD_CANARY):
            self.file(self.jane, booking("hotel_jsonld", {"Jane Doe": LEAD_CANARY}))
        [stay] = self.stays()
        self.assertTrue(stay.travelers_from_trip)
        self.assertEqual(self.c.orm.scalars(select(SegmentTraveler)).all(), [])
        self.assertEqual(trips.unmatched_count(self.c, self.jane), 0)
        self.assertEqual(trips.get_segment(self.c, self.jane, stay.id)["travelers"], [])

    def test_a_flight_email_keeps_its_travellers_and_seats(self):
        b = booking("flight_jsonld")
        self.file(self.jane, b)
        flight = self.c.orm.scalars(select(Segment).where(Segment.kind == "flight")).first()
        self.assertFalse(flight.travelers_from_trip)
        self.assertEqual([(t.person_id, t.seat) for t in self.rows(flight.id)], [(self.jid, None)])

    def test_a_cruise_email_keeps_its_travellers_including_a_name_nobody_matches(self):
        cruise = dataclasses.replace(booking("hotel_jsonld"), kind="cruise", start_zone="Europe/London", end_zone="Europe/London",
                                     origin="Example Line", destination="Example Line",
                                     passengers=(extract.Passenger("Jane Doe"), extract.Passenger(LEAD_CANARY)))
        self.file(self.jane, cruise)
        ship = self.c.orm.scalars(select(Segment).where(Segment.kind == "cruise")).first()
        self.assertFalse(ship.travelers_from_trip)
        self.assertEqual([(t.person_id, t.name) for t in self.rows(ship.id)], [(self.jid, None), (None, LEAD_CANARY)])
        self.assertEqual(self.aboard(ship.trip_id), [self.jid])

    def test_a_car_email_is_for_everyone_too(self):
        self.file(self.sam, booking("car_jsonld"))
        car = self.c.orm.scalars(select(Segment).where(Segment.kind == "car")).first()
        self.assertTrue(car.travelers_from_trip)

    def test_someone_named_who_could_not_otherwise_see_the_trip_keeps_their_row_so_visibility_is_unchanged(self):
        self.file(self.sam, booking("hotel_jsonld", {"Jane Doe": "Mia Doe"}))
        [stay] = self.stays()
        self.assertFalse(stay.travelers_from_trip)
        self.assertEqual([t.person_id for t in self.rows(stay.id)], [self.mia])
        self.assertIsNotNone(trips.get(self.c, Viewer(self.mia), stay.trip_id))
        self.assertIsNone(trips.get(self.c, self.jane, stay.trip_id))

    def test_who_sees_the_trip_is_what_it_was_before_the_booking_was_for_everyone(self):
        self.file(self.jane, booking("hotel_jsonld"))
        [stay] = self.stays()
        self.assertEqual([t.id for t in visibility.visible_trips(self.c, self.jane)], [stay.trip_id])
        self.assertEqual(visibility.visible_trips(self.c, self.sam), [])
        self.assertEqual(visibility.visible_trips(self.c, Viewer(self.mia)), [])

    def test_the_same_email_read_again_changes_nothing(self):
        self.file(self.jane, booking("hotel_jsonld"))
        self.assertEqual(self.file(self.jane, booking("hotel_jsonld"), again=True), "unchanged")
        [stay] = self.stays()
        self.assertTrue(stay.travelers_from_trip)
        self.assertEqual(self.rows(stay.id), [])

    def test_a_later_email_naming_someone_new_freezes_the_list_and_adds_them(self):
        self.file(self.jane, booking("hotel_jsonld"))
        self.file(self.jane, booking("hotel_jsonld", {"Jane Doe": "Mia Doe"}))
        [stay] = self.stays()
        self.c.orm.refresh(stay)
        self.assertFalse(stay.travelers_from_trip)
        self.assertEqual(sorted(t.person_id for t in self.rows(stay.id)), sorted([self.jid, self.mia]))
        self.assertEqual(sorted(self.aboard(stay.trip_id)), sorted([self.jid, self.mia]))

    def test_editing_a_booking_for_everyone_by_hand_keeps_it_that_way_and_ignores_a_list(self):
        self.file(self.jane, booking("hotel_jsonld"))
        [stay] = self.stays()
        shown = trips.get_segment(self.c, self.jane, stay.id)["travelers"]
        trips.edit_segment(self.c, self.jane, stay.id, {"details": {"room": "9"}, "travelers": [{"person_id": t["person_id"], "name": None} for t in shown]})
        self.c.orm.refresh(stay)
        self.assertTrue(stay.travelers_from_trip)
        trips.edit_segment(self.c, self.jane, stay.id, {"travelers": self.on(self.jid, self.joan)})
        self.c.orm.refresh(stay)
        self.assertTrue(stay.travelers_from_trip)
        self.assertEqual(self.aboard(stay.trip_id), [self.jid])


class ReadingThemNow(IngestCase):
    def setup_trip(self):
        out = self.add(self.jane, {**OUT, "start_local": "2026-11-20T19:00", "end_local": "2026-11-21T07:10"}, None, self.on(self.jid, self.mia))
        self.file(self.jane, booking("hotel_jsonld"))
        stay = self.stays()[0]
        self.assertEqual(stay.trip_id, out["trip_id"])
        self.assertTrue(stay.travelers_from_trip)
        return out, stay

    def test_a_trip_shows_the_stay_for_everyone_the_trip_has(self):
        out, _ = self.setup_trip()
        got = trips.get(self.c, self.jane, out["trip_id"])
        who = [[t["person_id"] for t in s["travelers"]] for s in got["segments"] if s["kind"] == "hotel"]
        self.assertEqual(who, [[self.jid, self.mia]])

    def test_each_person_on_the_trip_has_the_stay_in_their_own_stats(self):
        self.setup_trip()
        everyone = Viewer(self.jid, household=True)
        for person in (self.jid, self.mia):
            got = stats.compute(self.c, everyone, person, None, NOW)
            self.assertEqual(got["stays"]["count"], 1, person)
        self.assertEqual(stats.compute(self.c, everyone, self.joan, None, NOW)["stays"]["count"], 0)

    def test_the_offline_copy_carries_the_travellers_of_a_stay_for_everyone(self):
        out, _ = self.setup_trip()
        saved = offline.projection(self.c, self.jane, datetime(2026, 11, 22).date())
        self.assertEqual(saved["trip"]["id"], out["trip_id"])
        hotel = next(s for s in saved["trip"]["segments"] if s["kind"] == "hotel")
        self.assertEqual([t["person_id"] for t in hotel["travelers"]], [self.jid, self.mia])

    def test_splitting_the_stay_off_takes_the_group_and_leaves_the_flights_people(self):
        out, stay = self.setup_trip()
        new = trips.split(self.c, self.jane, out["trip_id"], [stay.id])
        self.assertEqual(new["people"], [self.jid, self.mia])
        self.c.orm.refresh(stay)
        self.assertTrue(stay.travelers_from_trip)
        self.assertEqual(self.aboard(out["trip_id"]), [self.jid, self.mia])

    def test_moving_the_stay_to_a_trip_of_other_people_freezes_it_to_its_own_group(self):
        _, stay = self.setup_trip()
        elsewhere = self.add(self.jane, {**BACK, "start_local": "2027-01-10T11:00", "end_local": "2027-01-10T14:05"}, None,
                             self.on(self.jid, self.joan))
        trips.move_segment(self.c, self.jane, stay.id, elsewhere["trip_id"], True)
        self.c.orm.refresh(stay)
        self.assertFalse(stay.travelers_from_trip)
        self.assertEqual(sorted(t.person_id for t in self.rows(stay.id)), sorted([self.jid, self.mia]))
        self.assertEqual(sorted(self.aboard(elsewhere["trip_id"])), sorted([self.jid, self.joan, self.mia]))

    def test_merging_into_a_bigger_trip_freezes_the_stay_to_its_old_group(self):
        out, stay = self.setup_trip()
        other = self.add(self.jane, {**BACK, "start_local": "2027-01-10T11:00", "end_local": "2027-01-10T14:05"}, None,
                         self.on(self.jid, self.joan))
        trips.merge(self.c, Viewer(self.jid, household=True), out["trip_id"], other["trip_id"])
        self.c.orm.refresh(stay)
        self.assertFalse(stay.travelers_from_trip)
        self.assertEqual([t["person_id"] for t in trips.get_segment(self.c, self.jane, stay.id)["travelers"]], [self.jid, self.mia])

    def test_the_assistant_view_reads_the_same_travellers(self):
        out, stay = self.setup_trip()
        seen = trips.get_segment(self.c, self.jane, stay.id)
        self.assertEqual([t["name"] for t in seen["travelers"]], ["Jane Doe", "Mia Doe"])
        self.assertEqual(trippeople.of(self.c, [out["trip_id"]])[out["trip_id"]], [self.jid, self.mia])


class SplittingKeepsOnlyThePeopleStillOnBookings(IngestCase):
    def test_someone_on_no_remaining_booking_leaves_the_source_trips_people(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        stay = self.add(self.jane, {**OUT, "kind": "hotel", "origin": "Harbour Hotel", "destination": None, "start_zone": "Europe/London",
                                    "end_zone": "Europe/London"}, flight["trip_id"], self.on(self.jid, self.joan))
        trips.split(self.c, self.jane, flight["trip_id"], [stay["id"]])
        self.assertEqual(self.aboard(flight["trip_id"]), [self.jid, self.mia])

    def test_someone_on_a_remaining_flight_stays(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        back = self.add(self.jane, BACK, flight["trip_id"], self.on(self.jid, self.joan))
        trips.split(self.c, self.jane, flight["trip_id"], [flight["id"]])
        self.assertEqual(self.aboard(back["trip_id"]), [self.jid, self.joan])

    def test_a_trip_listing_people_nobody_is_booked_for_loses_them_on_a_split(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid))
        back = self.add(self.jane, BACK, flight["trip_id"], self.on(self.jid))
        trips.edit_trip(self.c, self.jane, flight["trip_id"], {"people": [self.jid, self.joan]}, True)
        trips.split(self.c, self.jane, flight["trip_id"], [back["id"]])
        self.assertEqual(self.aboard(flight["trip_id"]), [self.jid])

    def test_a_trip_left_with_a_stay_for_everyone_keeps_its_whole_group(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid, self.mia))
        trips.edit_trip(self.c, self.jane, flight["trip_id"], {"people": [self.jid, self.mia, self.joan]}, True)
        stay = self.add(self.jane, {**OUT, "kind": "hotel", "origin": "Harbour Hotel", "destination": None, "start_zone": "Europe/London",
                                    "end_zone": "Europe/London"}, flight["trip_id"], self.on(self.jid))
        self.share(stay["id"])
        trips.split(self.c, self.jane, flight["trip_id"], [flight["id"]])
        self.assertEqual(self.aboard(flight["trip_id"]), [self.jid, self.mia, self.joan])
