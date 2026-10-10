import secrets
import urllib.parse
import time
import unittest
from datetime import date
from unittest import mock

from sqlalchemy import delete, func, insert, select

from waypoint import monitoring, oidc
from waypoint.domain import airports, demo, links, people, trips, visibility
from waypoint.domain.visibility import Viewer
from waypoint.server import ROUTES
from waypoint.server.api import trips as api
from waypoint.server.common import ApiError
from waypoint.storage import backup, db
from waypoint.storage.models import AuthSession, Person, Segment, SegmentTraveler, Trip, User
from tests.privacy import no_leaks
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


class LinkTests(Household):
    def test_a_card_carries_its_actions_built_by_the_server(self):
        got = self.add(self.jane, {**HOTEL, "details": {"address": "1 Quay Street, London", "phone": "+44 20 7946 0000"},
                                   "manage_url": "https://example.com/manage"}, None, self.on(self.jane.person_id))
        self.assertEqual(got["links"], {"app": "https://example.com/manage", "directions": "https://maps.apple.com/?q=1%20Quay%20Street%2C%20London",
                                        "call": "tel:+442079460000"})

    def test_a_manage_link_that_isnt_https_is_not_offered(self):
        got = self.add(self.jane, {**OUT, "manage_url": "http://example.com/manage"}, None, self.on(self.jane.person_id))
        self.assertEqual(got["links"], {"app": None, "directions": None, "call": None})


class PrefilledLinkTests(Household):
    ENTRY = {"example air": ("www.example.com", "/trip?code={code}&name={name}")}

    def flight(self, who, travelers, provider="Example Air", manage_url=None):
        fields = {**OUT, "provider": provider, "confirmation": "QZXW7413", "manage_url": manage_url}
        return self.add(who, fields, None, travelers)

    def test_the_link_uses_the_signed_in_travellers_last_name(self):
        with mock.patch.dict(links.MANAGE, self.ENTRY):
            got = self.flight(self.jane, self.on(self.joan, self.jane.person_id))
            self.assertEqual(got["links"]["app"], "https://www.example.com/trip?code=QZXW7413&name=Doe")
            got = self.flight(self.sam, [{"person_id": None, "name": "MR AMBROSE LINDQVIST"}, {"person_id": self.sam.person_id, "name": None}])
            self.assertEqual(got["links"]["app"], "https://www.example.com/trip?code=QZXW7413&name=Doe")

    def test_a_viewer_not_on_the_booking_gets_the_first_travellers_last_name(self):
        with mock.patch.dict(links.MANAGE, self.ENTRY):
            got = self.flight(self.jane, [{"person_id": None, "name": "MR AMBROSE LINDQVIST"}, {"person_id": self.mia, "name": None}])
            self.assertEqual(got["links"]["app"], "https://www.example.com/trip?code=QZXW7413&name=LINDQVIST")
            seen = trips.get_segment(self.c, self.jane, got["id"])
            assert seen is not None
            self.assertEqual(seen["links"]["app"], got["links"]["app"])

    def test_no_traveller_name_keeps_the_manage_link_from_the_email(self):
        with mock.patch.dict(links.MANAGE, self.ENTRY):
            got = self.flight(self.jane, [], manage_url="https://mail.example.org/m")
            self.assertEqual(got["links"]["app"], "https://mail.example.org/m")

    def test_an_airline_with_no_entry_keeps_the_manage_link_from_the_email(self):
        with mock.patch.dict(links.MANAGE, self.ENTRY):
            got = self.flight(self.jane, self.on(self.jane.person_id), provider="Nobody Air", manage_url="https://mail.example.org/m")
            self.assertEqual(got["links"]["app"], "https://mail.example.org/m")

    def test_the_code_and_last_name_reach_no_log_line_or_error_page(self):
        with mock.patch.dict(links.MANAGE, {"example air": ("www.example.com", "/trip?code={code}&name={name}")}):
            with no_leaks(self, "QZXW7413", "LINDQVIST", database=None, sent_ok=False):
                got = self.flight(self.jane, [{"person_id": None, "name": "MR AMBROSE LINDQVIST"}])
                self.assertIn("QZXW7413", got["links"]["app"] or "")
                trips.listing(self.c, self.jane)
                monitoring.log(monitoring.scrub(f"opened {got['links']['app']}"))
                try:
                    raise ValueError(f"failed for {got['links']['app']}")
                except ValueError:
                    monitoring.report(values=False)


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
        seg = self.add(self.jane, OUT, travelers=self.on(self.mia))
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
        self.assertEqual(len(trips.listing(self.c, self.sam)), 1)

    def test_adding_a_traveller_shares_the_trip(self):
        seg = self.add(self.jane, OUT, travelers=self.on(self.mia))
        self.assertIsNone(trips.get_segment(self.c, self.sam, seg["id"]))
        trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": self.on(self.mia, self.sam.person_id)})
        self.assertIsNotNone(trips.get_segment(self.c, self.sam, seg["id"]))
        self.assertEqual(len(trips.listing(self.c, self.sam)), 1)
        trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": self.on(self.mia)})
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
        self.assertEqual((trip["start_date"], trip["end_date"]), ("2026-03-01", "2026-03-01"))

    def test_clocks_changing_do_not_move_the_times(self):
        london = {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": "2026-03-29T00:45",
                  "end_local": "2026-03-29T03:30"}
        stay = {**HOTEL, "start_local": "2026-03-07T15:00", "end_local": "2026-03-08T11:00",
                "start_zone": "America/New_York", "end_zone": "America/New_York"}
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
        unlisted = self.add(self.jane, {**OUT, "origin": "ZZZ", "start_zone": "Pacific/Fiji"})
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
        self.assertEqual(same["locked_fields"], [])
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

    def test_an_edited_address_is_locked_against_a_later_email_but_an_empty_one_is_filled(self):
        mail = {**HOTEL, "confirmation": "H77001", "details": {"address": "9 Mill Lane\nLondon N1 1AA"}}
        empty = self.add(self.jane, {**HOTEL, "confirmation": "H77001"})
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, mail), "updated")
        self.assertEqual(trips.get_segment(self.c, self.jane, empty["id"])["details"], {"address": "9 Mill Lane\nLondon N1 1AA"})
        edited = trips.edit_segment(self.c, self.jane, empty["id"], {"details": {"address": "2 Dock Road"}})
        assert edited
        self.assertIn("details", edited["locked_fields"])
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, mail), "unchanged")
        self.assertEqual(trips.get_segment(self.c, self.jane, empty["id"])["details"], {"address": "2 Dock Road"})

    def test_an_address_from_an_email_is_cut_to_the_limit_so_the_booking_can_still_be_edited(self):
        seg = self.add(self.jane, {**HOTEL, "details": {"address": "x" * 400}})
        self.assertEqual(len(seg["details"]["address"]), 300)

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
        with self.assertRaisesRegex(trips.Invalid, "ends before"):
            trips.edit_segment(self.c, self.jane, seg["id"], {"end_local": "2026-05-01T00:00"})

    def test_editing_a_stays_place_keeps_its_zone(self):
        stay = self.add(self.jane, HOTEL)
        renamed = trips.edit_segment(self.c, self.jane, stay["id"], {"origin": "Quay Hotel", "destination": "Elsewhere"})
        assert renamed
        self.assertEqual((renamed["origin"], renamed["start_zone"], renamed["end_zone"]), ("Quay Hotel", "Europe/London", "Europe/London"))

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
        self.assertEqual(trip["end_date"], "2026-06-02")
        trips.edit_segment(self.c, self.jane, a["id"], {"status": "cancelled"})
        trip = trips.get(self.c, self.jane, a["trip_id"])
        assert trip
        self.assertEqual((trip["start_date"], trip["end_date"]), ("2026-06-01", "2026-06-08"))

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


CRUISE = {"kind": "cruise", "origin": "Miami", "destination": "Miami", "provider": "Example Cruise Line",
          "start_local": "2026-03-01T16:30", "start_zone": "America/New_York", "end_local": "2026-03-08T07:00", "end_zone": "America/New_York",
          "details": {"ship": "Example Voyager", "deck": "9"}}
PORTS = [{"name": "Nassau", "zone": "America/Nassau", "arrive_local": "2026-03-02T08:00", "depart_local": "2026-03-02T17:00"},
         {"name": "Cozumel", "zone": "America/Cancun", "arrive_local": "2026-03-05T08:00", "depart_local": "2026-03-05T17:00"}]


class SeatTests(Household):
    def two(self, **extra):
        return self.add(self.jane, {**OUT, **extra}, travelers=[{"person_id": self.jane.person_id, "name": None, "seat": " 31a "},
                                                                {"person_id": self.sam.person_id, "name": None, "seat": "31B"},
                                                                {"person_id": None, "name": "DOE/MIA MISS", "seat": "32A"}])

    def test_each_traveller_has_their_own_seat_as_typed_and_trimmed(self):
        seg = self.two()
        self.assertEqual([(t["name"], t["seat"]) for t in seg["travelers"]], [("Jane Doe", "31a"), ("Sam Doe", "31B"), ("DOE/MIA MISS", "32A")])
        again = trips.get_segment(self.c, self.jane, seg["id"])
        assert again
        self.assertEqual([t["seat"] for t in again["travelers"]], ["31a", "31B", "32A"])
        self.assertEqual([t["seat"] for t in self.add(self.jane, OUT)["travelers"]], [None])
        with self.assertRaisesRegex(trips.Invalid, "at most 10"):
            self.add(self.jane, OUT, travelers=[{"person_id": self.jane.person_id, "name": None, "seat": "x" * 11}])

    def test_changing_a_seat_locks_the_travellers_and_leaving_the_seats_out_keeps_them(self):
        seg = self.two()
        moved = trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": [
            {"person_id": self.jane.person_id, "name": None, "seat": "12C"}, {"person_id": self.sam.person_id, "name": None, "seat": "31B"},
            {"person_id": None, "name": "DOE/MIA MISS", "seat": "32A"}]})
        assert moved
        self.assertEqual(([t["seat"] for t in moved["travelers"]], moved["locked_fields"]), (["12C", "31B", "32A"], ["travelers"]))
        quiet = trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": [
            {"person_id": self.jane.person_id, "name": None}, {"person_id": self.sam.person_id, "name": None}]})
        assert quiet
        self.assertEqual([(t["name"], t["seat"]) for t in quiet["travelers"]], [("Jane Doe", "12C"), ("Sam Doe", "31B")])
        cleared = trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": [{"person_id": self.jane.person_id, "name": None, "seat": ""}]})
        assert cleared
        self.assertEqual([t["seat"] for t in cleared["travelers"]], [None])
        same = trips.edit_segment(self.c, self.jane, seg["id"], {"status": "changed"})
        assert same
        self.assertEqual([t["seat"] for t in same["travelers"]], [None])

    def test_leaving_a_seat_out_keeps_it_for_a_traveller_matched_from_a_printed_name(self):
        seg = self.add(self.jane, OUT, travelers=[{"person_id": None, "name": "DOE/MIA MISS", "seat": "32A"}])
        mia = self.sam.person_id
        assert mia is not None
        self.assertEqual(trips.name_traveler(self.c, self.jane, seg["travelers"][0]["id"], mia), 1)
        quiet = trips.edit_segment(self.c, self.jane, seg["id"], {"travelers": [{"person_id": mia, "name": None}]})
        assert quiet
        self.assertEqual([t["seat"] for t in quiet["travelers"]], ["32A"])

    def test_a_later_email_leaves_the_seats_alone_and_adds_who_it_names(self):
        seg = self.two(confirmation="SEAT01")
        mail = {**OUT, "confirmation": "SEAT01", "travelers": [{"person_id": None, "name": "DOE/MIA MISS"}, {"person_id": None, "name": "NEW/PERSON MR"}]}
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, mail), "updated")
        got = trips.get_segment(self.c, self.jane, seg["id"])
        assert got
        self.assertEqual([(t["name"], t["seat"]) for t in got["travelers"]],
                         [("Jane Doe", "31a"), ("Sam Doe", "31B"), ("DOE/MIA MISS", "32A"), ("NEW/PERSON MR", None)])


class StayZoneTests(Household):
    def stay(self, **extra):
        fields = {**HOTEL, "start_zone": None, "end_zone": None, **extra}
        return self.add(self.jane, fields, None, self.on(self.jane.person_id))

    def test_a_stay_has_one_zone_and_the_end_follows_the_start(self):
        seg = self.stay(start_zone="America/Chicago", end_zone="Europe/London")
        self.assertEqual((seg["start_zone"], seg["end_zone"]), ("America/Chicago", "America/Chicago"))

    def test_a_stay_with_no_zone_takes_the_one_its_address_is_in(self):
        seg = self.stay(details={"address": "1 Ocean Ave, Honolulu, HI 96815"})
        self.assertEqual((seg["start_zone"], seg["end_zone"]), ("Pacific/Honolulu", "Pacific/Honolulu"))
        given = self.stay(details={"address": "1 Ocean Ave, Honolulu, HI 96815"}, start_zone="America/Denver")
        self.assertEqual(given["start_zone"], "America/Denver")

    def test_a_stay_whose_address_settles_nothing_is_refused_and_says_what_to_do(self):
        for details in ({}, {"address": "Hotel Foo, 1 Road"}):
            with self.subTest(details=details), self.assertRaisesRegex(trips.Invalid, "time zone of the stay"):
                self.stay(details=details)

    def test_clearing_a_stays_zone_on_an_edit_works_it_out_again_from_the_address(self):
        seg = self.stay(start_zone="America/Chicago", details={"address": "1 Ocean Ave, Honolulu, HI 96815"})
        cleared = trips.edit_segment(self.c, self.jane, seg["id"], {"start_zone": None})
        assert cleared
        self.assertEqual((cleared["start_zone"], cleared["end_zone"]), ("Pacific/Honolulu", "Pacific/Honolulu"))
        with self.assertRaisesRegex(trips.Invalid, "time zone of the stay"):
            trips.edit_segment(self.c, self.jane, self.stay(start_zone="America/Chicago")["id"], {"start_zone": None})

    def test_a_stay_saved_with_two_zones_before_gets_its_start_zone_for_both_on_its_next_edit(self):
        seg = self.stay(start_zone="America/Chicago")
        self.c.orm.get(Segment, seg["id"]).end_zone = "Europe/London"
        self.c.orm.flush()
        renamed = trips.edit_segment(self.c, self.jane, seg["id"], {"origin": "Other Hotel"})
        assert renamed
        self.assertEqual((renamed["start_zone"], renamed["end_zone"]), ("America/Chicago", "America/Chicago"))

    def test_editing_a_stay_keeps_its_zone_in_both_places(self):
        seg = self.stay(start_zone="America/Chicago")
        moved = trips.edit_segment(self.c, self.jane, seg["id"], {"start_zone": "America/Denver"})
        assert moved
        self.assertEqual((moved["start_zone"], moved["end_zone"]), ("America/Denver", "America/Denver"))
        renamed = trips.edit_segment(self.c, self.jane, seg["id"], {"origin": "Other Hotel"})
        assert renamed
        self.assertEqual((renamed["start_zone"], renamed["end_zone"]), ("America/Denver", "America/Denver"))


class CruiseTests(Household):
    def test_a_cruise_keeps_its_ports_in_order_with_their_own_zones(self):
        seg = self.add(self.jane, {**CRUISE, "itinerary": PORTS})
        self.assertEqual(seg["itinerary"], PORTS)
        self.assertEqual(trips.get_segment(self.c, self.jane, seg["id"])["itinerary"], PORTS)
        self.assertEqual(self.add(self.jane, {**CRUISE, "confirmation": "NOPORTS"})["itinerary"], [])

    def test_a_cruise_lists_every_day_with_embark_first_disembark_last_and_sea_days_between(self):
        seg = self.add(self.jane, {**CRUISE, "itinerary": PORTS})
        days = seg["days"]
        self.assertEqual([d["day"] for d in days], list(range(1, 9)))
        self.assertEqual([d["date"] for d in days][::7], ["2026-03-01", "2026-03-08"])
        self.assertEqual([d["sea"] for d in days], [False, False, True, True, False, True, True, False])
        self.assertEqual(days[0]["stops"], [{"name": "Miami", "zone": "America/New_York", "arrive_local": None, "depart_local": "2026-03-01T16:30", "recorded": True}])
        self.assertEqual(days[1]["stops"], [{**PORTS[0], "recorded": True}])
        self.assertEqual(days[7]["stops"], [{"name": "Miami", "zone": "America/New_York", "arrive_local": "2026-03-08T07:00", "depart_local": None, "recorded": True}])
        self.assertEqual(days[2]["stops"], [])

    def test_an_overnight_in_port_is_not_a_sea_day_and_a_port_with_no_times_keeps_its_row(self):
        overnight = [{"name": "Reykjavik", "zone": "Atlantic/Reykjavik", "arrive_local": "2026-03-02T08:00", "depart_local": "2026-03-03T17:00"},
                     {"name": "Akureyri", "zone": "Atlantic/Reykjavik", "arrive_local": None, "depart_local": None}]
        days = self.add(self.jane, {**CRUISE, "itinerary": overnight})["days"]
        self.assertEqual([(d["day"], d["sea"], [s["name"] for s in d["stops"]]) for d in days[1:4]],
                         [(2, False, ["Reykjavik"]), (3, False, ["Reykjavik", "Akureyri"]), (4, True, [])])
        self.assertEqual([(s["arrive_local"], s["depart_local"], s["recorded"]) for s in days[2]["stops"]],
                         [(None, "2026-03-03T17:00", True), (None, None, False)])

    def test_a_hotel_carries_its_brand_from_its_name_and_nothing_else_does(self):
        branded = self.add(self.jane, {**HOTEL, "origin": "Hyatt Place Example Beach Convention Center", "confirmation": "BRAND1"})
        self.assertEqual(branded["hotel_brand"], "Hyatt Place")
        self.assertEqual(branded["origin"], "Hyatt Place Example Beach Convention Center")
        self.assertIsNone(self.add(self.jane, HOTEL)["hotel_brand"])
        self.assertIsNone(self.add(self.jane, {**OUT, "origin": "JFK", "confirmation": "NOHOTEL"})["hotel_brand"])

    def test_a_cruise_with_no_ports_and_other_kinds_have_no_days(self):
        self.assertEqual(self.add(self.jane, {**CRUISE, "confirmation": "NOPORTS"})["days"], [])
        self.assertEqual(self.add(self.jane, OUT)["days"], [])

    def test_a_cruise_with_a_bad_itinerary_is_refused_and_says_why(self):
        for ports, why in (([{**PORTS[0], "name": " "}], "Name port 1"), ([{**PORTS[0], "zone": "Nowhere/Land"}], "port 1"),
                           ([{**PORTS[0], "arrive_local": "soon"}], "arrival"),
                           ([{**PORTS[0], "depart_local": "2026-03-02T07:00"}], "before it arrives"),
                           ([PORTS[1], PORTS[0]], "in the order"),
                           ([{**PORTS[0], "arrive_local": "2026-02-28T08:00", "depart_local": None}], "in the order"),
                           ([{**PORTS[0], "arrive_local": "2026-03-09T08:00", "depart_local": None}], "after the cruise ends"),
                           ([PORTS[0]] * 41, "at most 40")):
            with self.subTest(why=why), self.assertRaisesRegex(trips.Invalid, why):
                self.add(self.jane, {**CRUISE, "itinerary": ports})
        with self.assertRaisesRegex(trips.Invalid, "Only a cruise"):
            self.add(self.jane, {**HOTEL, "itinerary": PORTS})

    def test_editing_the_ports_locks_them_and_a_later_email_leaves_them_alone_but_fills_an_empty_list(self):
        mail = {**CRUISE, "confirmation": "CR1234", "itinerary": [PORTS[0]]}
        empty = self.add(self.jane, {**CRUISE, "confirmation": "CR1234"})
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, mail), "updated")
        self.assertEqual(trips.get_segment(self.c, self.jane, empty["id"])["itinerary"], [PORTS[0]])
        edited = trips.edit_segment(self.c, self.jane, empty["id"], {"itinerary": PORTS})
        assert edited
        self.assertEqual((edited["itinerary"], edited["locked_fields"]), (PORTS, ["itinerary"]))
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, {**mail, "itinerary": [PORTS[1]]}), "unchanged")
        self.assertEqual(trips.get_segment(self.c, self.jane, empty["id"])["itinerary"], PORTS)
        same = trips.edit_segment(self.c, self.jane, empty["id"], {"itinerary": PORTS})
        assert same
        cleared = trips.edit_segment(self.c, self.jane, empty["id"], {"itinerary": []})
        assert cleared
        self.assertEqual(cleared["itinerary"], [])

    def test_an_edit_that_leaves_the_ports_alone_keeps_them_and_removing_the_cruise_removes_them(self):
        seg = self.add(self.jane, {**CRUISE, "itinerary": PORTS})
        edited = trips.edit_segment(self.c, self.jane, seg["id"], {"provider": "Another Line"})
        assert edited
        self.assertEqual((edited["itinerary"], edited["locked_fields"]), (PORTS, ["provider"]))
        self.assertTrue(trips.delete_segment(self.c, self.jane, seg["id"]))
        self.assertEqual(trips.ports_of(self.c, [seg["id"]]), {})

    def test_a_cruise_that_changes_kind_loses_its_ports_instead_of_refusing_the_edit(self):
        seg = self.add(self.jane, {**CRUISE, "itinerary": PORTS})
        edited = trips.edit_segment(self.c, self.jane, seg["id"], {"kind": "hotel"})
        assert edited
        self.assertEqual((edited["kind"], edited["itinerary"], edited["locked_fields"]), ("hotel", [], ["itinerary", "kind"]))
        self.assertEqual(trips.ports_of(self.c, [seg["id"]]), {})
        with self.assertRaisesRegex(trips.Invalid, "Only a cruise"):
            trips.edit_segment(self.c, self.jane, seg["id"], {"itinerary": PORTS})

    def test_a_bad_list_of_ports_in_an_email_is_left_out_without_spoiling_the_merge(self):
        empty = self.add(self.jane, {**CRUISE, "confirmation": "CR5555"})
        bad = [{**PORTS[0], "arrive_local": "2030-01-01T08:00", "depart_local": None}]
        mail = {**CRUISE, "confirmation": "CR5555", "details": {"ship": "Example Voyager II"}, "itinerary": bad}
        self.assertEqual(trips.merge_email_segment(self.c, self.jane, mail), "updated")
        got = trips.get_segment(self.c, self.jane, empty["id"])
        assert got
        self.assertEqual((got["details"], got["itinerary"]), ({"ship": "Example Voyager II", "deck": "9"}, []))

    def test_the_ports_are_only_the_viewers_to_see(self):
        seg = self.add(self.jane, {**CRUISE, "itinerary": PORTS}, travelers=self.on(self.jane.person_id))
        self.assertIsNone(trips.get_segment(self.c, self.sam, seg["id"]))
        self.assertEqual([s["itinerary"] for t in trips.listing(self.c, self.sam) for s in t["segments"]], [])


class TripTests(Household):
    def test_a_trip_made_by_hand(self):
        made = trips.create_trip(self.c, self.jane, {"name": "Cabin weekend", "destination": "Lake", "notes": "Bring skates",
                                                     "start_date": "2026-12-04", "end_date": "2026-12-06"})
        self.assertEqual((made["auto"], made["booked_by"], made["start_date"], made["segments"]),
                         (False, self.jane.person_id, "2026-12-04", []))
        self.assertEqual(len(trips.listing(self.c, self.jane)), 1)
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

    def test_merging_trips_with_different_people_is_refused(self):
        a = self.add(self.jane, OUT, travelers=self.on(self.jane.person_id, self.sam.person_id))
        b = self.add(self.jane, {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"},
                     travelers=self.on(self.jane.person_id))
        with self.assertRaisesRegex(trips.Invalid, "different people"):
            trips.merge(self.c, self.jane, a["trip_id"], b["trip_id"])
        with self.assertRaisesRegex(trips.Invalid, "different people"):
            trips.merge(self.c, self.jane, b["trip_id"], a["trip_id"])
        self.assertEqual(trips.listing(self.c, self.sam)[0]["id"], a["trip_id"])
        self.assertEqual(len(trips.listing(self.c, self.sam)), 1)
        self.assertEqual(len(trips.listing(self.c, self.jane)), 2)

    def test_adding_without_a_person_is_refused(self):
        for make in (lambda: trips.create_trip(self.c, Viewer(None), {"name": "x"}), lambda: trips.add_segment(self.c, Viewer(None), OUT)):
            with self.assertRaisesRegex(trips.Invalid, "no person"):
                make()

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
        with self.assertRaises(trips.Invalid):
            trips.split(self.c, self.jane, new["id"], [b["id"]])

    def test_the_splitter_sees_the_new_trip_because_they_booked_it(self):
        a = self.add(self.jane, OUT, travelers=self.on(self.sam.person_id))
        b = self.add(self.jane, BACK, trip_id=a["trip_id"], travelers=self.on(self.sam.person_id))
        new = trips.split(self.c, self.sam, a["trip_id"], [b["id"]])
        assert new
        self.assertEqual(new["booked_by"], self.sam.person_id)
        self.assertIsNotNone(trips.get(self.c, self.sam, new["id"]))
        self.assertIsNotNone(trips.get(self.c, self.jane, new["id"]))


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
        self.assertNotEqual(later["trip_id"], a["trip_id"])
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
        sam = self.add(self.sam, HOTEL, travelers=self.on(self.sam.person_id))
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
                            travelers=self.on(self.jane.person_id, self.joan))
        self.assertNotEqual(newcomer["trip_id"], family["trip_id"])

    def test_only_grouped_trips_you_see_take_a_new_segment(self):
        mine = trips.create_trip(self.c, self.jane, {"name": "Made by hand", "start_date": "2026-06-01", "end_date": "2026-06-08"})
        seg = self.add(self.jane, OUT)
        self.assertNotEqual(seg["trip_id"], mine["id"])
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
        self.assertEqual(pick("2026-06-03", "2026-06-04", 1), 1)
        self.assertIsNone(pick("2026-06-03", "2026-06-04", 3))
        self.assertEqual(pick("2026-06-09", "2026-06-09", 1), 2)
        self.assertEqual(pick("2026-06-12", "2026-06-13", 1), 2)
        self.assertEqual(pick("2026-05-30", "2026-05-30", 1), 1)
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
            ZoneInfo(zone)


db_airports = __import__("waypoint.storage.models", fromlist=["Airport"]).Airport


class DemoTests(DbCase):
    def test_the_demo_has_trips_each_member_sees_only_their_own(self):
        demo.seed(self.c)
        jane = Viewer(people.person_for_sub(self.c, "demo-jane"))
        sam = Viewer(people.person_for_sub(self.c, "demo-sam"))
        names = {who: [t["name"] for t in trips.listing(self.c, who)] for who in (jane, sam)}
        self.assertEqual(len(names[jane]), 9)
        self.assertEqual(len(names[sam]), 7)
        self.assertEqual(len(set(names[jane]) & set(names[sam])), 6)
        for t in trips.listing(self.c, Viewer(None, household=True)):
            for s in t["segments"]:
                self.assertTrue(s["start_zone"] and s["end_zone"])


class RouteCase(ServerCase):
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint",
           "OIDC_ALLOWED_EMAILS": "ana@example.com,ben@example.com,cy@example.com"}

    def setUp(self):
        with db.session() as conn:
            for table in (Trip, AuthSession, User, Person):
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
            calls += [("GET", f"/api/segments/{s}", None), ("GET", f"/api/segments/{s}/logo", None), ("GET", f"/api/segments/{s}/emails", None),
                      ("GET", f"/api/segments/{s}/emails/1/images", None),
                      ("POST", f"/api/segments/{s}", {"status": "cancelled"}),
                      ("DELETE", f"/api/segments/{s}", None)]
        gone = [(m, p.replace(str(trip), "99999").replace(str(segs[0]), "99998").replace(str(segs[1]), "99997"), b) for m, p, b in calls[:3]]
        for who in ("ben",):
            for method, path, body in calls:
                with self.subTest(who=who, call=f"{method} {path}"):
                    status, got = self.call(who, method, path, body)
                    self.assertEqual((status, got), (404, {"error": got["error"]}))
                    self.assertIn(got["error"], ("No such trip", "No such segment"))
        for method, path, body in gone:
            self.assertEqual(self.call("ben", method, path, body)[0], 404)
        self.assertEqual(self.ok("ben", "GET", "/api/trips")["trips"], [])
        got = self.ok("ana", "GET", f"/api/trips/{trip}")
        self.assertEqual((got["name"], [s["status"] for s in got["segments"]]), (got["name"], ["confirmed", "confirmed"]))
        self.assertNotEqual(got["name"], "Stolen")
        self.assertEqual(len(got["segments"]), 2)
        self.assertEqual([t["id"] for t in self.ok("cy", "GET", "/api/trips")["trips"]], [mine["trip_id"]])

    def test_every_trip_and_segment_route_with_an_id_is_covered_above(self):
        covered = {("GET", "/api/trips/{id}"), ("POST", "/api/trips/{id}"), ("DELETE", "/api/trips/{id}"),
                   ("POST", "/api/trips/{id}/merge"), ("POST", "/api/trips/{id}/split"), ("POST", "/api/segments"),
                   ("GET", "/api/segments/{id}"), ("POST", "/api/segments/{id}"), ("DELETE", "/api/segments/{id}"),
                   ("GET", "/api/segments/{id}/logo"), ("GET", "/api/segments/{id}/emails"), ("GET", "/api/segments/{id}/emails/{id}/images")}
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
        self.assertEqual(self.ok("ana", "GET", "/api/trips"), {"trips": []})

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
        self.assertEqual(self.ok("ana", "GET", f"/api/segments/{seg['id']}")["status"], "confirmed")

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
    unset = ("OIDC_ISSUER",)

    def test_the_household_books_and_sees(self):
        status, seg = self.req("POST", "/api/segments", AUCKLAND_LA)
        self.assertEqual((status, seg["booked_by"], seg["travelers"]), (200, None, []))
        status, listing = self.req("GET", "/api/trips")
        self.assertEqual(status, 200)
        self.assertIn(seg["trip_id"], [t["id"] for t in listing["trips"]])
        self.assertEqual(self.req("DELETE", f"/api/trips/{seg['trip_id']}"), (200, {"ok": True}))


class CruiseRouteTests(RouteCase):
    def test_a_cruise_round_trips_through_the_routes_and_a_bad_port_is_a_400(self):
        body = {**CRUISE, "itinerary": PORTS}
        seg = self.ok("ana", "POST", "/api/segments", body)
        self.assertEqual((seg["kind"], seg["itinerary"], seg["details"]), ("cruise", PORTS, {"ship": "Example Voyager", "deck": "9"}))
        self.assertEqual(self.ok("ana", "GET", f"/api/segments/{seg['id']}")["itinerary"], PORTS)
        edited = self.ok("ana", "POST", f"/api/segments/{seg['id']}", {"itinerary": [{**PORTS[0], "name": " Nassau "}]})
        self.assertEqual((edited["itinerary"], edited["locked_fields"]), ([PORTS[0]], ["itinerary"]))
        for bad, why in (("ports", "list of ports"), ([5], "list of ports"), ([{"zone": "Europe/London"}], "name"),
                         ([{**PORTS[0], "name": "x" * 101}], "too long"), ([{**PORTS[0], "zone": 4}], "as text")):
            with self.subTest(bad=str(bad)[:30]):
                status, got = self.call("ana", "POST", f"/api/segments/{seg['id']}", {"itinerary": bad})
                self.assertEqual(status, 400, got)
                self.assertIn(why, got["error"])
        self.assertEqual(self.call("ben", "GET", f"/api/segments/{seg['id']}")[0], 404)


class ApiFieldTests(unittest.TestCase):
    def test_a_travellers_seat_is_trimmed_at_most_10_characters_and_left_out_when_not_sent(self):
        got = api.segment_fields({"travelers": [{"person_id": 1, "seat": " 31A "}, {"person_id": 2}, {"name": "DOE/MIA MISS", "seat": ""}]})["travelers"]
        self.assertEqual([t.get("seat", "left out") for t in got], ["31A", "left out", None])
        with self.assertRaisesRegex(ApiError, "seat is too long"):
            api.segment_fields({"travelers": [{"person_id": 1, "seat": "x" * 11}]})
        with self.assertRaisesRegex(ApiError, 'Send "seat" as text'):
            api.segment_fields({"travelers": [{"person_id": 1, "seat": 31}]})

    def test_an_address_is_trimmed_keeps_its_lines_and_is_at_most_300_characters(self):
        got = api.segment_fields({"details": {"address": "  1 Quay Street\r\nLondon E1 0AA \n", "room": " 4B "}})
        self.assertEqual(got["details"], {"address": "1 Quay Street\nLondon E1 0AA", "room": "4B"})
        self.assertEqual(api.segment_fields({"details": {"address": "x" * 300}})["details"], {"address": "x" * 300})
        with self.assertRaisesRegex(ApiError, "300"):
            api.segment_fields({"details": {"address": "x" * 301}})
        with self.assertRaisesRegex(ApiError, "200"):
            api.segment_fields({"details": {"room": "x" * 201}})

    def test_what_is_left_out_stays_out(self):
        self.assertEqual(api.segment_fields({}), {})
        self.assertEqual(api.segment_fields({"provider": "  ", "details": {"seat": " "}}), {"provider": None, "details": {}})
        self.assertEqual(api.trip_fields({}, creating=False), {})
        with self.assertRaises(ApiError):
            api.trip_fields({}, creating=True)


if __name__ == "__main__":
    unittest.main()
