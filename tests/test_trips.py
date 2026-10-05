"""Trips and segments: who sees them (AGENTS.md, "You see the trips you're on"), times kept where they happen ("Times are
where they happen"), grouping, merging and splitting, and the routes that do it. Names, codes and itineraries are made up;
the airports are real."""
import secrets
import urllib.parse
import time
import unittest
from datetime import date

from sqlalchemy import delete, func, insert, select

from waypoint import oidc
from waypoint.domain import airports, demo, people, trips, visibility
from waypoint.domain.visibility import Viewer
from waypoint.server import ROUTES
from waypoint.server.api import trips as api
from waypoint.server.common import ApiError
from waypoint.storage import backup, db
from waypoint.storage.models import AuthSession, Person, Segment, SegmentTraveler, Trip, User
from tests.shared import DbCase, ServerCase, add_database

AUCKLAND_LA = {"kind": "flight", "origin": "AKL", "destination": "LAX", "start_local": "2026-03-01T22:15",
               "end_local": "2026-03-01T15:10", "confirmation": "ZQ4PXD", "details": {"flight_number": "NZ6", "seat": "34K"}}
OUT = {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-06-01T19:00",
       "end_local": "2026-06-02T07:10"}
BACK = {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": "2026-06-08T11:00",
        "end_local": "2026-06-08T14:05"}
HOTEL = {"kind": "hotel", "origin": "Harbour Hotel", "destination": None, "start_local": "2026-06-02T15:00",
         "end_local": "2026-06-08T10:00", "start_zone": "Europe/London", "end_zone": "Europe/London"}


def guest(name):
    return {"display_name": name, "first_name": None, "legal_name": None, "aliases": []}


class Household(DbCase):
    """Two members (Jane, Sam) and two guests (Mia, Joan), each with their person row."""

    def setUp(self):
        super().setUp()
        for sub, name in (("u-jane", "Jane Doe"), ("u-sam", "Sam Doe")):
            oidc.remember_user(self.c, sub, f"{sub}@example.com", name, None)
        self.jane = Viewer(people.person_for_sub(self.c, "u-jane"))
        self.sam = Viewer(people.person_for_sub(self.c, "u-sam"))
        self.mia = people.add_guest(self.c, guest("Mia Doe"))["id"]
        self.joan = people.add_guest(self.c, guest("Grandma Joan"))["id"]

    def add(self, who, fields, trip_id=None, travelers=None):
        got = trips.add_segment(self.c, who, {**fields, **({} if travelers is None else {"travelers": travelers})}, trip_id)
        assert got is not None
        return got

    def on(self, *ids):
        return [{"person_id": i, "name": None} for i in ids]


class VisibilityTests(Household):
    def test_a_traveller_and_the_booker_see_a_trip_and_nobody_else(self):
        seg = self.add(self.jane, OUT, travelers=self.on(self.jane.person_id, self.mia))
        for who, sees in ((self.jane, True), (Viewer(self.mia), True), (self.sam, False), (Viewer(self.joan), False),
                          (Viewer(None), False)):
            with self.subTest(person=who.person_id):
                self.assertEqual(visibility.visible_trip(self.c, who, seg["trip_id"]) is not None, sees)
                self.assertEqual(visibility.visible_segment(self.c, who, seg["id"]) is not None, sees)
                self.assertEqual(len(visibility.visible_trips(self.c, who)), 1 if sees else 0)
                self.assertEqual(len(visibility.visible_segments(self.c, who)), 1 if sees else 0)
                self.assertEqual(len(visibility.visible_travelers(self.c, who, [seg["id"]])), 2 if sees else 0)
                self.assertEqual(trips.get(self.c, who, seg["trip_id"]) is not None, sees)
                self.assertEqual(trips.get_segment(self.c, who, seg["id"]) is not None, sees)

    def test_whoever_booked_a_guests_trip_sees_it(self):
        seg = self.add(self.jane, OUT, travelers=self.on(self.mia))   # Jane isn't on it: she booked it
        self.assertIsNotNone(trips.get(self.c, self.jane, seg["trip_id"]))
        self.assertIsNone(trips.get(self.c, self.sam, seg["trip_id"]))
        self.assertEqual([t["name"] for t in trips.listing(self.c, self.jane)[0]["segments"][0]["travelers"]], ["Mia Doe"])

    def test_whoever_booked_one_segment_of_a_trip_sees_the_trip(self):
        first = self.add(self.jane, OUT, travelers=self.on(self.jane.person_id))
        trip = visibility.visible_trip(self.c, self.jane, first["trip_id"])
        assert trip is not None
        self.c.orm.add(Segment(trip_id=trip.id, kind="car", status="confirmed", start_local="2026-06-02T09:00",
                               start_zone="Europe/London", end_local="2026-06-03T09:00", end_zone="Europe/London",
                               source="manual", booked_by=self.sam.person_id))
        self.c.orm.flush()
        self.assertEqual(len(trips.listing(self.c, self.sam)), 1)   # Sam booked a leg of it, and isn't travelling

    def test_adding_a_traveller_shares_the_trip(self):
        seg = self.add(self.jane, OUT, travelers=self.on(self.mia))
        self.assertIsNone(trips.get_segment(self.c, self.sam, seg["id"]))
        trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": self.on(self.mia, self.sam.person_id)})
        self.assertIsNotNone(trips.get_segment(self.c, self.sam, seg["id"]))
        self.assertEqual(len(trips.listing(self.c, self.sam)), 1)
        trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": self.on(self.mia)})   # and taking them off unshares it
        self.assertEqual(trips.listing(self.c, self.sam), [])

    def test_the_local_household_sees_every_trip(self):
        self.add(self.jane, OUT)
        self.add(self.sam, {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"})
        self.assertEqual(len(trips.listing(self.c, Viewer(None, household=True))), 2)

    def test_what_isnt_visible_cannot_be_changed(self):
        seg = self.add(self.jane, OUT, travelers=self.on(self.jane.person_id))
        trip_id, other = seg["trip_id"], self.add(self.sam, BACK)
        self.assertIsNone(trips.edit_segment(self.c, self.sam, seg["id"], {"status": "cancelled"}))
        self.assertFalse(trips.delete_segment(self.c, self.sam, seg["id"]))
        self.assertIsNone(trips.edit_trip(self.c, self.sam, trip_id, {"name": "Mine now"}))
        self.assertFalse(trips.delete_trip(self.c, self.sam, trip_id))
        self.assertIsNone(trips.add_segment(self.c, self.sam, HOTEL, trip_id))
        self.assertIsNone(trips.merge(self.c, self.sam, other["trip_id"], trip_id))
        self.assertIsNone(trips.merge(self.c, self.sam, trip_id, other["trip_id"]))
        self.assertIsNone(trips.split(self.c, self.sam, trip_id, [seg["id"]]))
        again = trips.get(self.c, self.jane, trip_id)
        assert again
        self.assertEqual(again["segments"][0]["status"], "confirmed")
        self.assertNotEqual(again["name"], "Mine now")

    def test_a_viewer_with_no_person_sees_nothing_even_when_nobody_booked(self):
        trip = Trip(name="Nobody’s", auto=False, booked_by=None)
        self.c.orm.add(trip)
        self.c.orm.flush()
        self.assertEqual(trips.listing(self.c, Viewer(None)), [])
        self.assertEqual(trips.listing(self.c, self.jane), [])


class TimeZoneTests(Household):
    """A flight's times stay what was typed, with the zone of the airport, through saving, reading and a backup."""

    def keeps(self, segments):
        shown = {s["id"]: (s["start_local"], s["start_zone"], s["end_local"], s["end_zone"])
                 for t in trips.listing(self.c, self.jane) for s in t["segments"]}
        return shown, [(s["start_local"], s["start_zone"], s["end_local"], s["end_zone"]) for s in segments]

    def test_a_flight_across_the_date_line_arrives_earlier_on_the_clock(self):
        seg = self.add(self.jane, AUCKLAND_LA)
        self.assertEqual((seg["start_local"], seg["start_zone"], seg["end_local"], seg["end_zone"]),
                         ("2026-03-01T22:15", "Pacific/Auckland", "2026-03-01T15:10", "America/Los_Angeles"))
        row = self.c.orm.get(Segment, seg["id"])
        assert row
        self.assertEqual((row.start_local, row.start_zone, row.end_local, row.end_zone),
                         ("2026-03-01T22:15", "Pacific/Auckland", "2026-03-01T15:10", "America/Los_Angeles"))
        trip = trips.get(self.c, self.jane, seg["trip_id"])
        assert trip
        self.assertEqual((trip["start_date"], trip["end_date"]), ("2026-03-01", "2026-03-01"))   # local dates

    def test_clocks_changing_do_not_move_the_times(self):
        london = {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": "2026-03-29T00:45",
                  "end_local": "2026-03-29T03:30"}   # the night UK clocks go forward
        stay = {**HOTEL, "start_local": "2026-03-07T15:00", "end_local": "2026-03-08T11:00",
                "start_zone": "America/New_York", "end_zone": "America/New_York"}   # the night US clocks do
        made = [self.add(self.jane, london), self.add(self.jane, stay)]
        shown, typed = self.keeps(made)
        self.assertEqual(sorted(shown.values()), sorted(typed))
        self.assertEqual(typed[0], ("2026-03-29T00:45", "Europe/London", "2026-03-29T03:30", "America/New_York"))
        self.assertEqual(typed[1], ("2026-03-07T15:00", "America/New_York", "2026-03-08T11:00", "America/New_York"))

    def test_the_times_survive_a_backup_and_restore(self):
        made = [self.add(self.jane, AUCKLAND_LA), self.add(self.jane, OUT)]
        other = add_database(self, self.path + ".restored")
        dst = db.connect(other)
        self.addCleanup(dst.close)
        backup.restore(dst, backup.load(backup.dump(self.c)))
        dst.commit()
        every = Viewer(None, household=True)
        restored = {s["id"]: s for t in trips.listing(dst, every) for s in t["segments"]}
        for seg in made:
            self.assertEqual(restored[seg["id"]], trips.get_segment(self.c, every, seg["id"]))
        self.assertEqual(restored[made[0]["id"]]["end_zone"], "America/Los_Angeles")
        self.assertEqual(restored[made[0]["id"]]["details"], {"flight_number": "NZ6", "seat": "34K"})
        self.assertEqual(dst.execute(select(func.count()).select_from(Person)).scalar(), 4)

    def test_the_airports_are_not_part_of_a_backup(self):
        self.assertNotIn("airports", backup.load(backup.dump(self.c))["tables"])

    def test_an_arrival_before_the_departure_is_refused_by_the_moment_not_the_clock(self):
        with self.assertRaisesRegex(trips.Invalid, "ends before it starts"):
            self.add(self.jane, {**OUT, "origin": "JFK", "destination": "BOS", "start_local": "2026-06-01T10:00",
                                 "end_local": "2026-06-01T09:00"})
        # 09:00 in Los Angeles is later than 10:00 in New York: fine.
        ok = self.add(self.jane, {**OUT, "destination": "LAX", "start_local": "2026-06-01T10:00", "end_local": "2026-06-01T09:00"})
        self.assertEqual((ok["end_local"], ok["end_zone"]), ("2026-06-01T09:00", "America/Los_Angeles"))

    def test_times_are_local_times_without_an_offset(self):
        for bad in ("2026-03-01T22:15Z", "2026-03-01T22:15+13:00", "2026-03-01", "2026-03-01 22:15", "yesterday",
                    "2026-02-30T10:00", "2026-03-01T25:00", None, ""):
            with self.subTest(bad=bad), self.assertRaisesRegex(trips.Invalid, "local time|real date"):
                self.add(self.jane, {**AUCKLAND_LA, "start_local": bad})
        seconds = self.add(self.jane, {**OUT, "start_local": "2026-06-01T19:00:30"})
        self.assertEqual(seconds["start_local"], "2026-06-01T19:00:30")

    def test_zones_come_from_airports_unless_given_and_must_be_real(self):
        given = self.add(self.jane, {**OUT, "start_zone": "America/Chicago"})
        self.assertEqual((given["start_zone"], given["end_zone"]), ("America/Chicago", "Europe/London"))
        for fields, why in (({"origin": "ZZZ"}, "start time zone"), ({"destination": "ZZZ"}, "end time zone"),
                            ({"start_zone": "Mars/Olympus"}, "isn’t one"), ({"end_zone": "../etc/passwd"}, "isn’t one")):
            with self.subTest(fields=fields), self.assertRaisesRegex(trips.Invalid, why):
                self.add(self.jane, {**OUT, **fields})
        unlisted = self.add(self.jane, {**OUT, "origin": "ZZZ", "start_zone": "Pacific/Fiji"})   # a code the list lacks, given a zone
        self.assertEqual(unlisted["origin"], "ZZZ")


class SegmentTests(Household):
    def test_what_a_segment_must_be(self):
        for fields, why in (({"kind": "boat"}, "Choose what"), ({"kind": None}, "Choose what"),
                            ({"status": "maybe"}, "status must be"), ({"origin": "New York"}, "airport code"),
                            ({"destination": None}, "airport code"), ({"details": {"mood": "good"}}, "Details can hold")):
            with self.subTest(fields=fields), self.assertRaisesRegex(trips.Invalid, why):
                self.add(self.jane, {**OUT, **fields})
        with self.assertRaisesRegex(trips.Invalid, "isn’t in People"):
            self.add(self.jane, OUT, travelers=self.on(9999))
        with self.assertRaisesRegex(trips.Invalid, "Name each traveller"):
            self.add(self.jane, OUT, travelers=[{"person_id": None, "name": None}])

    def test_a_new_segment_is_confirmed_manual_and_for_the_booker(self):
        seg = self.add(self.jane, {**OUT, "origin": "jfk"})
        self.assertEqual((seg["status"], seg["source"], seg["booked_by"], seg["origin"], seg["locked_fields"]),
                         ("confirmed", "manual", self.jane.person_id, "JFK", []))
        self.assertEqual([t["person_id"] for t in seg["travelers"]], [self.jane.person_id])
        nobody = self.add(self.jane, {**OUT, "start_local": "2026-08-01T19:00", "end_local": "2026-08-02T07:10"}, travelers=[])
        self.assertEqual(nobody["travelers"], [])

    def test_travellers_are_people_or_names_as_printed_each_once(self):
        seg = self.add(self.jane, OUT, travelers=[{"person_id": self.mia, "name": "DOE/MIA MISS"}, {"person_id": self.mia, "name": None},
                                                  {"person_id": None, "name": "SMITH/PAT MR"}, {"person_id": None, "name": "smith/pat mr"}])
        self.assertEqual([(t["person_id"], t["name"]) for t in seg["travelers"]], [(self.mia, "Mia Doe"), (None, "SMITH/PAT MR")])
        self.assertTrue(all(isinstance(t["id"], int) for t in seg["travelers"]))

    def test_removing_a_guest_takes_them_off_their_segments(self):
        seg = self.add(self.jane, OUT, travelers=self.on(self.jane.person_id, self.mia))
        self.assertTrue(people.remove_guest(self.c, self.mia))
        self.assertEqual([t["person_id"] for t in (trips.get_segment(self.c, self.jane, seg["id"]) or {})["travelers"]],
                         [self.jane.person_id])

    def test_an_edit_locks_what_it_changed_and_only_that(self):
        seg = self.add(self.jane, OUT)
        same = trips.edit_segment(self.c, self.jane, seg["id"], {"status": "confirmed", "confirmation": None})
        assert same
        self.assertEqual(same["locked_fields"], [])   # nothing changed, nothing locked
        edited = trips.edit_segment(self.c, self.jane, seg["id"], {"confirmation": "QW3RTY", "details": {"seat": "12A"},
                                                                   "status": "changed", "travelers": self.on(self.sam.person_id)})
        assert edited
        self.assertEqual((edited["confirmation"], edited["details"], edited["status"], edited["start_local"]),
                         ("QW3RTY", {"seat": "12A"}, "changed", "2026-06-01T19:00"))
        self.assertEqual(edited["locked_fields"], ["confirmation", "details", "status", "travelers"])
        more = trips.edit_segment(self.c, self.jane, seg["id"], {"provider": "Example Air"})
        assert more
        self.assertEqual(more["locked_fields"], ["confirmation", "details", "provider", "status", "travelers"])
        email = {"confirmation": "FROMMAIL", "provider": "Example Air", "status": "confirmed", "origin": "JFK"}
        self.assertEqual(trips.unlocked(email, more["locked_fields"]), {"origin": "JFK"})

    def test_moving_a_flights_airport_takes_its_zone_along_unless_given(self):
        seg = self.add(self.jane, OUT)
        moved = trips.edit_segment(self.c, self.jane, seg["id"], {"origin": "ORD", "start_local": "2026-06-01T18:00"})
        assert moved
        self.assertEqual((moved["origin"], moved["start_zone"], moved["end_zone"]), ("ORD", "America/Chicago", "Europe/London"))
        self.assertEqual(sorted(moved["locked_fields"]), ["origin", "start_local", "start_zone"])
        with self.assertRaisesRegex(trips.Invalid, "start time zone"):
            trips.edit_segment(self.c, self.jane, seg["id"], {"origin": "ZZZ"})
        given = trips.edit_segment(self.c, self.jane, seg["id"], {"origin": "ZZZ", "start_zone": "Pacific/Fiji", "start_local": "2026-06-01T09:00"})
        assert given
        self.assertEqual(given["start_zone"], "Pacific/Fiji")
        with self.assertRaisesRegex(trips.Invalid, "ends before"):   # the whole segment is checked again
            trips.edit_segment(self.c, self.jane, seg["id"], {"end_local": "2026-05-01T00:00"})

    def test_deleting_the_last_segment_of_a_grouped_trip_removes_it_but_not_a_made_one(self):
        grouped = self.add(self.jane, OUT)
        self.assertTrue(trips.delete_segment(self.c, self.jane, grouped["id"]))
        self.assertIsNone(trips.get(self.c, self.jane, grouped["trip_id"]))
        mine = trips.create_trip(self.c, self.jane, {"name": "Cabin weekend"})
        inside = self.add(self.jane, OUT, trip_id=mine["id"])
        self.assertTrue(trips.delete_segment(self.c, self.jane, inside["id"]))
        self.assertIsNotNone(trips.get(self.c, self.jane, mine["id"]))
        self.assertFalse(trips.delete_segment(self.c, self.jane, inside["id"]))

    def test_the_trip_dates_follow_its_segments(self):
        a = self.add(self.jane, OUT)
        b = self.add(self.jane, BACK)
        trip = trips.get(self.c, self.jane, a["trip_id"])
        assert trip
        self.assertEqual((b["trip_id"], trip["start_date"], trip["end_date"]), (a["trip_id"], "2026-06-01", "2026-06-08"))
        trips.edit_segment(self.c, self.jane, b["id"], {"status": "cancelled"})
        trip = trips.get(self.c, self.jane, a["trip_id"])
        assert trip
        self.assertEqual(trip["end_date"], "2026-06-02")   # a cancelled one doesn't stretch it
        trips.edit_segment(self.c, self.jane, a["id"], {"status": "cancelled"})
        trip = trips.get(self.c, self.jane, a["trip_id"])
        assert trip
        self.assertEqual((trip["start_date"], trip["end_date"]), ("2026-06-01", "2026-06-08"))   # all cancelled: all count

    def test_segments_come_by_start_moment_not_by_clock(self):
        late = self.add(self.jane, BACK)
        early = self.add(self.jane, OUT, trip_id=late["trip_id"])
        got = trips.get(self.c, self.jane, early["trip_id"])
        assert got
        self.assertEqual([s["id"] for s in got["segments"]], [early["id"], late["id"]])

    def test_decoding_what_is_stored(self):
        self.assertEqual(trips.decode_details('{"seat": "1A", "n": 3}'), {"seat": "1A"})
        for raw in (None, "", "nope", "[1]"):
            self.assertEqual(trips.decode_details(raw), {})
            self.assertEqual(trips.decode_locked(raw), [])
        self.assertEqual(trips.decode_locked('["a", 1, "b"]'), ["a", "b"])


class TripTests(Household):
    def test_a_trip_made_by_hand(self):
        made = trips.create_trip(self.c, self.jane, {"name": "Cabin weekend", "destination": "Lake", "notes": "Bring skates",
                                                     "start_date": "2026-12-04", "end_date": "2026-12-06"})
        self.assertEqual((made["auto"], made["booked_by"], made["start_date"], made["segments"]),
                         (False, self.jane.person_id, "2026-12-04", []))
        self.assertEqual(len(trips.listing(self.c, self.jane)), 1)   # empty, and still the booker's
        self.assertEqual(trips.listing(self.c, self.sam), [])
        for fields, why in (({"name": "x", "start_date": "2026-12-04"}, "both dates"),
                            ({"name": "x", "start_date": "2026-12-06", "end_date": "2026-12-04"}, "before it starts")):
            with self.subTest(fields=fields), self.assertRaisesRegex(trips.Invalid, why):
                trips.create_trip(self.c, self.jane, fields)

    def test_rename_and_describe_a_trip_but_not_its_dates(self):
        trip = self.add(self.jane, OUT)["trip_id"]
        edited = trips.edit_trip(self.c, self.jane, trip, {"name": "Summer in London", "destination": None, "notes": "Pack light"})
        assert edited
        self.assertEqual((edited["name"], edited["destination"], edited["notes"], edited["auto"]), ("Summer in London", None, "Pack light", True))
        with self.assertRaisesRegex(trips.Invalid, "come from its segments"):
            trips.edit_trip(self.c, self.jane, trip, {"start_date": "2026-01-01"})

    def test_deleting_a_trip_takes_its_segments(self):
        seg = self.add(self.jane, OUT)
        self.assertTrue(trips.delete_trip(self.c, self.jane, seg["trip_id"]))
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(Segment)), 0)
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(SegmentTraveler)), 0)
        self.assertFalse(trips.delete_trip(self.c, self.jane, seg["trip_id"]))

    def test_merging_folds_one_trip_into_another_made_by_hand(self):
        a = self.add(self.jane, OUT)
        b = self.add(self.jane, {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"})
        self.assertNotEqual(a["trip_id"], b["trip_id"])
        merged = trips.merge(self.c, self.jane, a["trip_id"], b["trip_id"])
        assert merged
        self.assertEqual((merged["id"], merged["auto"], len(merged["segments"]), merged["start_date"], merged["end_date"]),
                         (a["trip_id"], False, 2, "2026-06-01", "2026-09-02"))
        self.assertIsNone(trips.get(self.c, self.jane, b["trip_id"]))
        with self.assertRaisesRegex(trips.Invalid, "another trip"):
            trips.merge(self.c, self.jane, a["trip_id"], a["trip_id"])
        self.assertIsNone(trips.merge(self.c, self.jane, a["trip_id"], 9999))

    def test_merging_keeps_what_the_first_trip_lacks(self):
        empty = trips.create_trip(self.c, Viewer(None, household=True), {"name": "Blank"})
        full = trips.create_trip(self.c, self.jane, {"name": "Full", "destination": "Lisbon", "notes": "Fado"})
        merged = trips.merge(self.c, Viewer(None, household=True), empty["id"], full["id"])
        assert merged
        self.assertEqual((merged["name"], merged["destination"], merged["notes"], merged["booked_by"]),
                         ("Blank", "Lisbon", "Fado", self.jane.person_id))

    def test_splitting_moves_some_segments_to_a_new_trip_both_made_by_hand(self):
        a, b = self.add(self.jane, OUT), self.add(self.jane, BACK)
        new = trips.split(self.c, self.jane, a["trip_id"], [b["id"]])
        assert new
        self.assertEqual((new["name"], new["auto"], [s["id"] for s in new["segments"]], new["start_date"]),
                         (f"{(trips.get(self.c, self.jane, a['trip_id']) or {})['name']} (split)", False, [b["id"]], "2026-06-08"))
        old = trips.get(self.c, self.jane, a["trip_id"])
        assert old
        self.assertEqual(([s["id"] for s in old["segments"]], old["auto"], old["end_date"]), ([a["id"]], False, "2026-06-02"))
        for ids in ([], [9999], [a["id"], b["id"]]):
            with self.subTest(ids=ids), self.assertRaises(trips.Invalid):
                trips.split(self.c, self.jane, a["trip_id"], ids)
        with self.assertRaises(trips.Invalid):   # nothing left to split
            trips.split(self.c, self.jane, new["id"], [b["id"]])

    def test_the_splitter_sees_the_new_trip_because_they_booked_it(self):
        a = self.add(self.jane, OUT, travelers=self.on(self.sam.person_id))   # Jane booked it for Sam, who's travelling
        b = self.add(self.jane, BACK, trip_id=a["trip_id"], travelers=self.on(self.sam.person_id))
        new = trips.split(self.c, self.sam, a["trip_id"], [b["id"]])
        assert new
        self.assertEqual(new["booked_by"], self.sam.person_id)
        self.assertIsNotNone(trips.get(self.c, self.sam, new["id"]))
        self.assertIsNotNone(trips.get(self.c, self.jane, new["id"]))   # (Jane booked the segment inside it)


class GroupingTests(Household):
    def test_a_round_trip_and_its_hotel_are_one_trip(self):
        out, stay, back = self.add(self.jane, OUT), self.add(self.jane, HOTEL), self.add(self.jane, BACK)
        self.assertEqual({out["trip_id"], stay["trip_id"], back["trip_id"]}, {out["trip_id"]})
        trip = trips.get(self.c, self.jane, out["trip_id"])
        assert trip
        self.assertEqual((trip["auto"], trip["name"], trip["destination"]), (True, "Trip to London (Jun 2026)", "London"))

    def test_a_trip_after_getting_home_is_a_new_one(self):
        a, b = self.add(self.jane, OUT), self.add(self.jane, BACK)
        later = self.add(self.jane, {**OUT, "start_local": "2026-06-09T19:00", "end_local": "2026-06-10T07:10"})
        self.assertEqual(a["trip_id"], b["trip_id"])
        self.assertNotEqual(later["trip_id"], a["trip_id"])   # one day after getting back: not the same trip
        far = self.add(self.jane, {**OUT, "start_local": "2026-07-20T19:00", "end_local": "2026-07-21T07:10"})
        self.assertNotIn(far["trip_id"], (a["trip_id"], later["trip_id"]))

    def test_a_leg_within_the_gap_joins_while_the_trip_is_still_out(self):
        a = self.add(self.jane, OUT)
        onward = self.add(self.jane, {**OUT, "origin": "LHR", "destination": "LIS", "start_local": "2026-06-04T09:00",
                                      "end_local": "2026-06-04T12:00"})
        self.assertEqual(onward["trip_id"], a["trip_id"])
        near = self.add(self.jane, {**OUT, "origin": "LIS", "destination": "MAD", "start_local": "2026-06-06T09:00",
                                    "end_local": "2026-06-06T10:00"})
        self.assertEqual(near["trip_id"], a["trip_id"])
        gap = self.add(self.jane, {**OUT, "origin": "CDG", "destination": "FCO", "start_local": "2026-06-20T09:00",
                                   "end_local": "2026-06-20T11:00"})
        self.assertNotEqual(gap["trip_id"], a["trip_id"])

    def test_someone_elses_booking_never_joins_a_solo_trip(self):
        jane = self.add(self.jane, OUT, travelers=self.on(self.jane.person_id))
        sam = self.add(self.sam, HOTEL, travelers=self.on(self.sam.person_id))   # the same days and city
        self.assertNotEqual(jane["trip_id"], sam["trip_id"])
        self.assertEqual(len(trips.listing(self.c, self.sam)), 1)
        self.assertEqual(len(trips.listing(self.c, self.jane)), 1)
        for t in trips.listing(self.c, self.sam):
            self.assertEqual([s["id"] for s in t["segments"]], [sam["id"]])

    def test_a_booking_for_people_already_on_the_trip_joins_it(self):
        family = self.add(self.jane, OUT, travelers=self.on(self.jane.person_id, self.mia, self.sam.person_id))
        hotel = self.add(self.jane, HOTEL, travelers=self.on(self.jane.person_id))
        self.assertEqual(hotel["trip_id"], family["trip_id"])
        newcomer = self.add(self.jane, {**OUT, "start_local": "2026-06-02T08:00", "end_local": "2026-06-02T22:00"},
                            travelers=self.on(self.jane.person_id, self.joan))   # Joan isn't on it yet: a trip of its own
        self.assertNotEqual(newcomer["trip_id"], family["trip_id"])

    def test_only_grouped_trips_you_see_take_a_new_segment(self):
        mine = trips.create_trip(self.c, self.jane, {"name": "Made by hand", "start_date": "2026-06-01", "end_date": "2026-06-08"})
        seg = self.add(self.jane, OUT)
        self.assertNotEqual(seg["trip_id"], mine["id"])   # a trip made by hand is left alone
        theirs = self.add(self.sam, BACK, travelers=self.on(self.sam.person_id))
        self.assertNotEqual(theirs["trip_id"], seg["trip_id"])

    def test_choose_trip(self):
        def facts(start, end, *people):
            return trips.Facts(date.fromisoformat(start), date.fromisoformat(end), frozenset(people))
        round_trip = (("JFK", "LHR"), ("LHR", "JFK"))
        trips_ = [trips.Candidate(1, facts("2026-06-01", "2026-06-08", 1, 2), round_trip),
                  trips.Candidate(2, facts("2026-06-10", "2026-06-12", 1), (("JFK", "LHR"),)),
                  trips.Candidate(3, facts("2026-06-13", "2026-06-15", 1), ())]
        pick = lambda start, end, *people: trips.choose_trip(trips_, facts(start, end, *people))
        self.assertEqual(pick("2026-06-03", "2026-06-04", 1), 1)         # inside one, within its people
        self.assertIsNone(pick("2026-06-03", "2026-06-04", 3))           # someone who isn't on it
        self.assertEqual(pick("2026-06-09", "2026-06-09", 1), 2)         # a day from 2, a day after the others' end: 2 is nearest... 1 has returned
        self.assertEqual(pick("2026-06-12", "2026-06-13", 1), 2)         # two trips touch it: the nearest (an overlap beats a gap), then the earliest
        self.assertEqual(pick("2026-05-30", "2026-05-30", 1), 1)         # up to two days before
        self.assertIsNone(pick("2026-05-20", "2026-05-20", 1))
        self.assertIsNone(pick("2026-06-10", "2026-06-10", 9))
        self.assertIsNone(trips.choose_trip([], facts("2026-06-01", "2026-06-01")))
        self.assertTrue(trips.returned_home(round_trip))
        self.assertFalse(trips.returned_home((("JFK", "LHR"),)))
        self.assertFalse(trips.returned_home((("JFK", "LHR"), ("LHR", "CDG"))))
        self.assertFalse(trips.returned_home(((None, None), (None, None))))


class AirportTests(DbCase):
    def test_lookup_by_code(self):
        found = airports.lookup(self.c, " akl ")
        assert found
        self.assertEqual((found["code"], found["city"], found["country"], found["zone"]), ("AKL", "Auckland", "NZ", "Pacific/Auckland"))
        self.assertIsNone(airports.lookup(self.c, "ZZZ"))
        self.assertEqual(airports.zones(self.c, ["jfk", "LHR", "ZZZ"]), {"JFK": "America/New_York", "LHR": "Europe/London"})

    def test_every_airports_zone_is_a_real_one(self):
        from zoneinfo import ZoneInfo
        for _code, zone in self.c.execute(select(db_airports.code, db_airports.zone)).fetchall():
            ZoneInfo(zone)   # raises for one that isn't


db_airports = __import__("waypoint.storage.models", fromlist=["Airport"]).Airport


class DemoTests(DbCase):
    def test_the_demo_has_trips_each_member_sees_only_their_own(self):
        demo.seed(self.c)
        jane = Viewer(people.person_for_sub(self.c, "demo-jane"))
        sam = Viewer(people.person_for_sub(self.c, "demo-sam"))
        names = {who: [t["name"] for t in trips.listing(self.c, who)] for who in (jane, sam)}
        self.assertEqual(len(names[jane]), 2)
        self.assertEqual(len(names[sam]), 2)
        self.assertEqual(len(set(names[jane]) & set(names[sam])), 1)   # the family trip is both's; each has a solo one
        for t in trips.listing(self.c, Viewer(None, household=True)):
            for s in t["segments"]:
                self.assertTrue(s["start_zone"] and s["end_zone"])


# ------------------------------------------------------------------------------------------------ the routes

class RouteCase(ServerCase):
    """Waypoint with sign-in on and three members with sessions: Ana, Ben and Cy."""
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint",
           "OIDC_ALLOWED_EMAILS": "ana@example.com,ben@example.com,cy@example.com"}

    def setUp(self):
        with db.session() as conn:
            for table in (Trip, AuthSession, User, Person):   # (a trip takes its segments and their travellers)
                conn.execute(delete(table))
        self.who = {n: self.sign_in(f"sub-{n}", f"{n}@example.com", n.title()) for n in ("ana", "ben", "cy")}
        with db.session() as conn:
            self.person = {n: people.person_for_sub(conn, f"sub-{n}") for n in self.who}

    def sign_in(self, sub, email, name) -> dict:
        token = secrets.token_urlsafe(24)
        now = time.time()
        with db.session() as conn:
            conn.execute(insert(AuthSession).values(token_hash=oidc._hash(token), sub=sub, email=email, name=name,
                                                    created=now, expires=now + 86400))
            oidc.remember_user(conn, sub, email, name, None, now)
        return {"Cookie": f"waypoint_session={token}"}

    def call(self, who, method, path, body=None):
        return self.req(method, path, body if method != "GET" else None, self.who[who])

    def ok(self, who, method, path, body=None):
        status, got = self.call(who, method, path, body)
        self.assertEqual(status, 200, got)
        return got

    def book(self, who="ana", fields=OUT, **extra):
        return self.ok(who, "POST", "/api/segments", {**fields, **extra})


class VisibilityRouteTests(RouteCase):
    def test_a_stranger_gets_404_for_the_trip_and_each_segment_on_every_route(self):
        seg = self.book("ana", travelers=[{"person_id": self.person["ana"]}])
        second = self.book("ana", BACK, trip_id=seg["trip_id"])
        mine = self.book("cy", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"})
        trip, segs = seg["trip_id"], [seg["id"], second["id"]]
        calls = [("GET", f"/api/trips/{trip}", None), ("POST", f"/api/trips/{trip}", {"name": "Stolen"}),
                 ("DELETE", f"/api/trips/{trip}", None), ("POST", f"/api/trips/{trip}/merge", {"merge": mine["trip_id"]}),
                 ("POST", f"/api/trips/{mine['trip_id']}/merge", {"merge": trip}),
                 ("POST", f"/api/trips/{trip}/split", {"segment_ids": segs[:1]}),
                 ("POST", "/api/segments", {**HOTEL, "trip_id": trip})]
        for s in segs:
            calls += [("GET", f"/api/segments/{s}", None), ("POST", f"/api/segments/{s}", {"status": "cancelled"}),
                      ("DELETE", f"/api/segments/{s}", None)]
        gone = [(m, p.replace(str(trip), "99999").replace(str(segs[0]), "99998").replace(str(segs[1]), "99997"), b) for m, p, b in calls[:3]]
        for who in ("ben",):
            for method, path, body in calls:
                with self.subTest(who=who, call=f"{method} {path}"):
                    status, got = self.call(who, method, path, body)
                    self.assertEqual((status, got), (404, {"error": got["error"]}))
                    self.assertIn(got["error"], ("No such trip", "No such segment"))
        for method, path, body in gone:   # a trip that isn't there answers exactly the same
            self.assertEqual(self.call("ben", method, path, body)[0], 404)
        self.assertEqual(self.ok("ben", "GET", "/api/trips")["trips"], [])
        # Nothing the stranger tried changed anything for the person it belongs to.
        got = self.ok("ana", "GET", f"/api/trips/{trip}")
        self.assertEqual((got["name"], [s["status"] for s in got["segments"]]), (got["name"], ["confirmed", "confirmed"]))
        self.assertNotEqual(got["name"], "Stolen")
        self.assertEqual(len(got["segments"]), 2)
        self.assertEqual([t["id"] for t in self.ok("cy", "GET", "/api/trips")["trips"]], [mine["trip_id"]])

    def test_every_trip_and_segment_route_with_an_id_is_covered_above(self):
        covered = {("GET", "/api/trips/{id}"), ("POST", "/api/trips/{id}"), ("DELETE", "/api/trips/{id}"),
                   ("POST", "/api/trips/{id}/merge"), ("POST", "/api/trips/{id}/split"), ("POST", "/api/segments"),
                   ("GET", "/api/segments/{id}"), ("POST", "/api/segments/{id}"), ("DELETE", "/api/segments/{id}")}
        found = {(m, p) for m, p, _ in ROUTES if p.startswith(("/api/trips/", "/api/segments"))}
        self.assertEqual(found, covered, "a new route that takes a trip or segment goes in the stranger's 404 test")

    def test_the_booker_of_a_guest_only_trip_sees_it_and_adding_a_traveller_shares_it(self):
        mia = self.ok("ana", "POST", "/api/people", {"display_name": "Mia Doe"})["id"]
        seg = self.book("ana", travelers=[{"person_id": mia}])
        self.assertEqual([t["id"] for t in self.ok("ana", "GET", "/api/trips")["trips"]], [seg["trip_id"]])
        self.assertEqual(self.call("ben", "GET", f"/api/trips/{seg['trip_id']}")[0], 404)
        shared = self.ok("ana", "POST", f"/api/segments/{seg['id']}", {"travelers": [{"person_id": mia}, {"person_id": self.person["ben"]}]})
        self.assertEqual([t["name"] for t in shared["travelers"]], ["Mia Doe", "Ben"])
        self.assertEqual(self.ok("ben", "GET", f"/api/trips/{seg['trip_id']}")["id"], seg["trip_id"])
        self.assertEqual(self.ok("ben", "GET", f"/api/segments/{seg['id']}")["id"], seg["id"])
        self.assertEqual(self.call("cy", "GET", f"/api/segments/{seg['id']}")[0], 404)

    def test_a_signed_in_member_with_no_person_sees_nothing(self):
        with db.session() as conn:
            conn.execute(delete(Person).where(Person.id == self.person["cy"]))
        self.assertEqual(self.ok("cy", "GET", "/api/trips"), {"trips": []})


class TripRouteTests(RouteCase):
    def test_make_rename_merge_split_and_remove_trips(self):
        made = self.ok("ana", "POST", "/api/trips", {"name": "  Cabin weekend ", "destination": "Lake", "notes": "Skates",
                                                     "start_date": "2026-12-04", "end_date": "2026-12-06"})
        self.assertEqual((made["name"], made["auto"], made["booked_by"], made["segments"]), ("Cabin weekend", False, self.person["ana"], []))
        seg = self.book("ana", trip_id=made["id"])
        back = self.book("ana", BACK, trip_id=made["id"])
        renamed = self.ok("ana", "POST", f"/api/trips/{made['id']}", {"name": "Lake and London", "notes": None})
        self.assertEqual((renamed["name"], renamed["notes"], renamed["destination"]), ("Lake and London", None, "Lake"))
        split = self.ok("ana", "POST", f"/api/trips/{made['id']}/split", {"segment_ids": [back["id"]]})
        self.assertEqual([s["id"] for s in split["segments"]], [back["id"]])
        merged = self.ok("ana", "POST", f"/api/trips/{made['id']}/merge", {"merge": split["id"]})
        self.assertEqual(sorted(s["id"] for s in merged["segments"]), sorted([seg["id"], back["id"]]))
        self.assertEqual(self.call("ana", "GET", f"/api/trips/{split['id']}")[0], 404)
        self.assertEqual([t["id"] for t in self.ok("ana", "GET", "/api/trips")["trips"]], [made["id"]])
        self.assertEqual(self.ok("ana", "DELETE", f"/api/trips/{made['id']}"), {"ok": True})
        self.assertEqual(self.call("ana", "GET", f"/api/segments/{seg['id']}")[0], 404)
        self.assertEqual(self.call("ana", "DELETE", f"/api/trips/{made['id']}")[0], 404)

    def test_what_cannot_be_done_says_so(self):
        seg = self.book("ana")
        trip = seg["trip_id"]
        for method, path, body, status, why in [
                ("POST", "/api/trips", {"name": " "}, 400, "Enter the name"),
                ("POST", "/api/trips", {"name": 5}, 400, "as text"),
                ("POST", "/api/trips", {"name": "x" * 101}, 400, "too long"),
                ("POST", "/api/trips", {"name": "x", "start_date": "tomorrow"}, 400, "must be a date"),
                ("POST", "/api/trips", {"name": "x", "start_date": "2026-01-01"}, 400, "both dates"),
                ("POST", f"/api/trips/{trip}", {"start_date": "2026-01-01"}, 400, "come from its segments"),
                ("POST", f"/api/trips/{trip}", {"name": ""}, 400, "Enter the name"),
                ("POST", f"/api/trips/{trip}", {"notes": ["a"]}, 400, "as text"),
                ("POST", f"/api/trips/{trip}/merge", {"merge": trip}, 400, "another trip"),
                ("POST", f"/api/trips/{trip}/merge", {"merge": "abc"}, 400, "Choose the trip"),
                ("POST", f"/api/trips/{trip}/merge", {}, 400, "Choose the trip"),
                ("POST", f"/api/trips/{trip}/split", {"segment_ids": "1"}, 400, "list of segments"),
                ("POST", f"/api/trips/{trip}/split", {"segment_ids": []}, 400, "Choose segments"),
                ("POST", f"/api/trips/{trip}/split", {"segment_ids": ["x"]}, 400, "Choose segments"),
                ("POST", f"/api/trips/{trip}/split", {"segment_ids": [seg["id"]]}, 400, "at least one"),
                ("GET", "/api/trips/abc", None, 404, "No such trip"), ("POST", "/api/trips/abc", {"name": "x"}, 404, "No such trip"),
                ("DELETE", "/api/trips/abc", None, 404, "No such trip"), ("GET", "/api/trips/99999", None, 404, "No such trip"),
                ("POST", f"/api/trips/{trip}/merge", {"merge": 99999}, 404, "No such trip"),
                ("POST", "/api/trips/abc/merge", {"merge": 1}, 404, "No such trip"),
                ("GET", "/api/segments/abc", None, 404, "No such segment"), ("GET", "/api/segments/99999", None, 404, "No such segment"),
                ("POST", "/api/segments/99999", {"status": "changed"}, 404, "No such segment"),
                ("DELETE", "/api/segments/99999", None, 404, "No such segment"),
                ("DELETE", "/api/segments/abc", None, 404, "No such segment")]:
            with self.subTest(call=f"{method} {path}", body=str(body)[:50]):
                got_status, got = self.call("ana", method, path, body)
                self.assertEqual(got_status, status, got)
                self.assertIn(why, got["error"])


class SegmentRouteTests(RouteCase):
    def test_add_read_edit_and_remove_a_segment(self):
        seg = self.book("ana", AUCKLAND_LA, manage_url="https://air.example.com/manage?c=ZQ4PXD", provider=" Example Air ")
        self.assertEqual((seg["start_local"], seg["start_zone"], seg["end_local"], seg["end_zone"], seg["provider"]),
                         ("2026-03-01T22:15", "Pacific/Auckland", "2026-03-01T15:10", "America/Los_Angeles", "Example Air"))
        self.assertEqual((seg["source"], seg["booked_by"], seg["details"]), ("manual", self.person["ana"], {"flight_number": "NZ6", "seat": "34K"}))
        self.assertEqual(self.ok("ana", "GET", f"/api/segments/{seg['id']}"), seg)
        trip = self.ok("ana", "GET", f"/api/trips/{seg['trip_id']}")
        self.assertEqual((trip["segments"], trip["name"], trip["destination"]), ([seg], "Trip to Los Angeles (Mar 2026)", "Los Angeles"))
        edited = self.ok("ana", "POST", f"/api/segments/{seg['id']}", {"status": "changed", "details": {"seat": "35A", "terminal": " 2 "},
                                                                     "provider": None})
        self.assertEqual((edited["status"], edited["details"], edited["provider"], edited["locked_fields"]),
                         ("changed", {"seat": "35A", "terminal": "2"}, None, ["details", "provider", "status"]))
        self.assertEqual(self.ok("ana", "DELETE", f"/api/segments/{seg['id']}"), {"ok": True})
        self.assertEqual(self.ok("ana", "GET", "/api/trips"), {"trips": []})   # the grouped trip went with its last segment

    def test_a_segment_goes_to_the_trip_named_or_is_grouped(self):
        out = self.book("ana")
        into = self.ok("ana", "POST", "/api/trips", {"name": "Mine"})
        named = self.book("ana", HOTEL, trip_id=into["id"])
        grouped = self.book("ana", HOTEL)
        self.assertEqual((named["trip_id"], grouped["trip_id"]), (into["id"], out["trip_id"]))

    def test_what_cannot_be_sent_says_so(self):
        for body, why in [({**OUT, "kind": 5}, "as text"), ({**OUT, "kind": "boat"}, "Choose what"),
                          ({**OUT, "provider": ["x"]}, "as text"), ({**OUT, "provider": "x" * 101}, "too long"),
                          ({**OUT, "confirmation": "x" * 51}, "too long"), ({**OUT, "manage_url": "javascript:alert(1)"}, "must start with https"),
                          ({**OUT, "manage_url": 7}, "as text"), ({**OUT, "manage_url": "https://x.example/" + "a" * 500}, "too long"),
                          ({**OUT, "details": ["seat"]}, "object of texts"), ({**OUT, "details": {"seat": 4}}, "object of texts"),
                          ({**OUT, "details": {"seat": "x" * 201}}, "too long"), ({**OUT, "details": {"mood": "ok"}}, "Details can hold"),
                          ({**OUT, "travelers": "Mia"}, "list of people"), ({**OUT, "travelers": ["Mia"]}, "list of people"),
                          ({**OUT, "travelers": [{"name": "A"}] * 21}, "at most 20"),
                          ({**OUT, "travelers": [{"person_id": "abc"}]}, "Choose travellers"),
                          ({**OUT, "travelers": [{"person_id": 99999}]}, "isn’t in People"),
                          ({**OUT, "travelers": [{"name": 3}]}, "as text"), ({**OUT, "travelers": [{}]}, "Name each"),
                          ({**OUT, "trip_id": "abc"}, "No such trip"), ({**OUT, "trip_id": 99999}, "No such trip"),
                          ({**OUT, "start_local": "soon"}, "local time"), ({"kind": "flight", "origin": "JFK", "destination": "LHR"}, "local time")]:
            with self.subTest(body=str(body)[:70]):
                status, got = self.call("ana", "POST", "/api/segments", body)
                self.assertEqual(status, 404 if "No such trip" in why else 400, got)
                self.assertIn(why, got["error"])
        seg = self.book("ana")
        for body, why in [({"status": "maybe"}, "status must be"), ({"origin": "ZZZ"}, "start time zone"), ({"end_local": "2020-01-01T00:00"}, "ends before"),
                          ({"details": {"mood": "ok"}}, "Details can hold")]:
            with self.subTest(edit=body):
                status, got = self.call("ana", "POST", f"/api/segments/{seg['id']}", body)
                self.assertEqual(status, 400, got)
                self.assertIn(why, got["error"])
        self.assertEqual(self.ok("ana", "GET", f"/api/segments/{seg['id']}")["status"], "confirmed")   # (a refused edit changes nothing)

    def test_a_manage_link_must_be_a_web_address_and_may_be_cleared(self):
        seg = self.book("ana", manage_url="http://air.example.com/m")
        self.assertEqual(self.ok("ana", "POST", f"/api/segments/{seg['id']}", {"manage_url": ""})["manage_url"], None)


class AirportRouteTests(RouteCase):
    def test_an_airport_by_code(self):
        got = self.ok("ana", "GET", "/api/airports/akl")
        self.assertEqual(got, {"code": "AKL", "name": got["name"], "city": "Auckland", "country": "NZ", "zone": "Pacific/Auckland"})
        for code in ("ZZZ", "AK", "AKLX", "12A", "ÅKL"):
            with self.subTest(code=code):
                self.assertEqual(self.call("ana", "GET", f"/api/airports/{urllib.parse.quote(code)}")[0], 404)


class LocalHouseholdTests(ServerCase):
    """Without sign-in, on your own machine, everyone is the one local household and sees every trip."""
    unset = ("OIDC_ISSUER",)

    def test_the_household_books_and_sees(self):
        status, seg = self.req("POST", "/api/segments", AUCKLAND_LA)
        self.assertEqual((status, seg["booked_by"], seg["travelers"]), (200, None, []))
        status, listing = self.req("GET", "/api/trips")
        self.assertEqual(status, 200)
        self.assertIn(seg["trip_id"], [t["id"] for t in listing["trips"]])
        self.assertEqual(self.req("DELETE", f"/api/trips/{seg['trip_id']}"), (200, {"ok": True}))


class ApiFieldTests(unittest.TestCase):
    def test_what_is_left_out_stays_out(self):
        self.assertEqual(api.segment_fields({}), {})
        self.assertEqual(api.segment_fields({"provider": "  ", "details": {"seat": " "}}), {"provider": None, "details": {}})
        self.assertEqual(api.trip_fields({}, creating=False), {})
        with self.assertRaises(ApiError):
            api.trip_fields({}, creating=True)


if __name__ == "__main__":
    unittest.main()
