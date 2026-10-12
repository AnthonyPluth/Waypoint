import json
import os
import unittest
from datetime import UTC, date, datetime
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.shared import DbCase, add_database
from tests.test_trips import HOTEL, OUT, RouteCase
from waypoint.domain import home, reminders
from waypoint.storage import backup, db, geocode
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import Setting

CITY = "Springfield"
ZIP = "62701-1234"
DRIVE = {**HOTEL, "origin": "Capitol Inn", "destination": "Boulder", "start_local": "2026-06-02T15:00", "end_local": "2026-06-04T10:00",
         "start_zone": "America/Denver", "end_zone": "America/Denver"}
SECOND = {**DRIVE, "origin": "Flatiron Inn", "destination": "Denver", "start_local": "2026-06-04T15:00", "end_local": "2026-06-08T10:00"}
SPRINGFIELD = {"city": CITY, "state": "IL", "zip": ZIP, "country": "US"}


class PlacingTests(unittest.TestCase):
    def test_a_zip_is_placed_at_the_zip(self):
        found = geocode.locate_home("Springfield", "IL", "62701", "US")
        self.assertEqual(found.precision, "zip")
        self.assertAlmostEqual(found.latitude, 39.8, delta=0.1)
        self.assertAlmostEqual(found.longitude, -89.65, delta=0.1)

    def test_a_city_and_state_is_placed_at_the_city(self):
        found = geocode.locate_home("Springfield", "IL", "", "US")
        self.assertEqual(found.precision, "city")
        self.assertAlmostEqual(found.latitude, 39.8, delta=0.1)
        self.assertEqual(geocode.locate_home("Denver", "Colorado", "", "US").precision, "city")

    def test_a_postal_code_outside_the_us_is_placed(self):
        self.assertEqual(geocode.locate_home("Toronto", "ON", "M5V 2T6", "CA").precision, "zip")
        self.assertEqual(geocode.locate_home("Leeds", "", "LS1 4AP", "GB").precision, "zip")

    def test_a_city_the_reference_data_lacks_is_not_placed(self):
        self.assertIsNone(geocode.locate_home("Nowhereville", "ZZ", "", "US"))
        self.assertIsNone(geocode.locate_home("Zzyzx Qwerty", "", "", "US"))


class SavingTests(DbCase):
    def test_nothing_is_saved_by_default_and_the_country_is_the_households_most_common(self):
        got = home.read(self.c)
        self.assertEqual((got["city"], got["saved"], got["placed"], got["country"]), ("", False, False, "US"))
        self.assertIsNone(home.point(self.c))

    def test_it_saves_city_state_and_zip_and_places_them(self):
        got = home.save(self.c, {"city": "  Springfield ", "state": "IL", "zip": "62701", "country": "us"})
        self.assertEqual(got, {"city": "Springfield", "state": "IL", "zip": "62701", "country": "US", "saved": True, "placed": True})
        self.assertEqual(home.read(self.c), got)
        point = home.point(self.c)
        self.assertEqual(point["city"], "Springfield")
        self.assertAlmostEqual(point["latitude"], 39.8, delta=0.1)

    def test_a_city_alone_is_enough_and_the_country_follows_the_household(self):
        got = home.save(self.c, {"city": "Boulder"})
        self.assertEqual((got["state"], got["zip"], got["country"], got["placed"]), ("", "", "US", True))

    def test_the_household_s_country_comes_from_its_flights(self):
        from waypoint.domain import trips
        from waypoint.domain.visibility import Viewer
        viewer = Viewer(person_id=None, household=True)
        for origin, destination, start, end in (("LHR", "MAN", "2026-06-01T10:00", "2026-06-01T11:00"), ("MAN", "LHR", "2026-06-05T10:00", "2026-06-05T11:00"),
                                                ("JFK", "LHR", "2026-06-10T19:00", "2026-06-11T07:00")):
            trips.add_segment(self.c, viewer, {"kind": "flight", "origin": origin, "destination": destination, "start_local": start, "end_local": end})
        self.assertEqual(home.read(self.c)["country"], "GB")

    def test_a_city_that_cannot_be_placed_is_kept_and_says_so(self):
        got = home.save(self.c, {"city": "Nowhereville", "state": "ZZ"})
        self.assertEqual((got["saved"], got["placed"]), (True, False))
        self.assertIsNone(home.point(self.c))

    def test_it_rejects_junk(self):
        for body in ({}, {"city": ""}, {"city": "   "}, {"city": "12 Main Street"}, {"city": "Spring<script>"}, {"city": "Springfield", "state": "I1"},
                     {"city": "Springfield", "zip": "!!!"}, {"city": "Springfield", "zip": "1"}, {"city": "Springfield", "country": "USA"},
                     {"city": "Springfield", "country": "1"}, {"city": 5}, {"city": ["Springfield"]}, {"city": "Springfield", "zip": 62701}):
            with self.subTest(body=body):
                with self.assertRaises(home.Invalid):
                    home.save(self.c, body)
        self.assertFalse(home.read(self.c)["saved"])

    def test_it_rejects_anything_over_a_short_limit(self):
        for body in ({"city": "A" * 81}, {"city": "Springfield", "state": "A" * 41}, {"city": "Springfield", "zip": "1" * 11}):
            with self.subTest(body=body):
                with self.assertRaises(home.Invalid):
                    home.save(self.c, body)
        self.assertTrue(home.save(self.c, {"city": "A" * 80})["saved"])

    def test_no_street_address_is_accepted_or_kept(self):
        for body in ({**SPRINGFIELD, "street": "742 Evergreen Terrace"}, {**SPRINGFIELD, "address": "742 Evergreen Terrace"},
                     {"city": "742 Evergreen Terrace"}, {"city": "Springfield", "state": "742 Evergreen Terrace"}):
            with self.subTest(body=body):
                with self.assertRaises(home.Invalid):
                    home.save(self.c, body)
        home.save(self.c, SPRINGFIELD)
        stored = json.loads(db.get_setting(self.c, sk.HOME))
        self.assertEqual(sorted(stored), ["city", "country", "state", "zip"])

    def test_a_refused_save_keeps_what_was_there(self):
        home.save(self.c, SPRINGFIELD)
        with self.assertRaises(home.Invalid):
            home.save(self.c, {"city": "12 Main"})
        self.assertEqual(home.read(self.c)["city"], CITY)

    def test_clearing_empties_it(self):
        home.save(self.c, SPRINGFIELD)
        got = home.clear(self.c)
        self.assertEqual((got["city"], got["saved"], got["placed"]), ("", False, False))
        self.assertIsNone(home.point(self.c))
        self.assertIsNone(db.get_setting(self.c, sk.HOME))

    def test_a_damaged_setting_reads_as_empty(self):
        for raw in ("not json", "[]", json.dumps({"city": "Springfield"}), json.dumps({"city": "", "state": "", "zip": "", "country": "US"}),
                    json.dumps({"city": 1, "state": "", "zip": "", "country": "US"})):
            with self.subTest(raw=raw):
                db.set_setting(self.c, sk.HOME, raw)
                self.assertFalse(home.read(self.c)["saved"])
                self.assertIsNone(home.point(self.c))

    def test_a_backup_round_trip_keeps_it(self):
        home.save(self.c, SPRINGFIELD)
        self.c.commit()
        other = add_database(self, os.path.join(os.path.dirname(self.path), "restored.db"))
        dst = db.connect(other)
        self.addCleanup(dst.close)
        backup.restore(dst, backup.load(backup.dump(self.c)))
        dst.commit()
        self.assertEqual(home.read(dst), home.read(self.c))
        self.assertEqual(home.read(dst)["zip"], ZIP)


class HomeRouteTests(RouteCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            home.clear(conn)

    def test_it_answers_only_signed_in_members(self):
        for method, body in (("GET", None), ("POST", SPRINGFIELD), ("DELETE", None)):
            with self.subTest(method=method):
                self.assertEqual(self.req(method, "/api/home", body)[0], 401)
        self.assertEqual(self.ok("ana", "POST", "/api/home", SPRINGFIELD)["city"], CITY)
        self.assertEqual(self.ok("ben", "GET", "/api/home")["city"], CITY)

    def test_it_saves_reads_and_clears(self):
        empty = self.ok("ana", "GET", "/api/home")
        self.assertEqual((empty["saved"], empty["placed"]), (False, False))
        saved = self.ok("ana", "POST", "/api/home", SPRINGFIELD)
        self.assertEqual(saved, {**SPRINGFIELD, "saved": True, "placed": True})
        self.assertEqual(self.ok("ben", "GET", "/api/home"), saved)
        cleared = self.ok("ana", "DELETE", "/api/home")
        self.assertEqual((cleared["city"], cleared["saved"]), ("", False))
        self.assertEqual(self.ok("ana", "GET", "/api/home")["saved"], False)

    def test_junk_and_a_street_address_are_refused_with_a_message(self):
        for body, message in (({"city": "12 Main Street"}, "The city doesn’t look right"), ({"city": ""}, "Enter the city"),
                              ({"city": "A" * 81}, "too long"), ({**SPRINGFIELD, "street": "742 Evergreen Terrace"}, "nothing else")):
            with self.subTest(body=body):
                status, got = self.call("ana", "POST", "/api/home", body)
                self.assertEqual(status, 400)
                self.assertIn(message, got["error"])
                self.assertNotIn("742", got["error"])
        self.assertEqual(self.ok("ana", "GET", "/api/home")["saved"], False)

    def test_an_unplaceable_city_is_saved_and_reported(self):
        got = self.ok("ana", "POST", "/api/home", {"city": "Nowhereville", "state": "ZZ"})
        self.assertEqual((got["saved"], got["placed"]), (True, False))
        trip = self.book("ana", DRIVE)["trip_id"]
        self.assertIsNone(self.ok("ana", "GET", f"/api/trips/{trip}/places")["home"])

    def test_a_trip_s_places_carry_home_only_for_those_who_can_see_the_trip(self):
        self.ok("ana", "POST", "/api/home", SPRINGFIELD)
        trip = self.book("ana", DRIVE)["trip_id"]
        got = self.ok("ana", "GET", f"/api/trips/{trip}/places")["home"]
        self.assertEqual(got["city"], CITY)
        self.assertEqual(sorted(got), ["city", "latitude", "longitude"])
        self.assertEqual(self.call("ben", "GET", f"/api/trips/{trip}/places"), (404, {"error": "No such trip"}))
        self.ok("ana", "DELETE", "/api/home")
        self.assertIsNone(self.ok("ana", "GET", f"/api/trips/{trip}/places")["home"])

    def test_the_zip_and_street_do_not_come_back_in_the_places_reply(self):
        self.ok("ana", "POST", "/api/home", SPRINGFIELD)
        trip = self.book("ana", DRIVE)["trip_id"]
        self.assertNotIn(ZIP, json.dumps(self.ok("ana", "GET", f"/api/trips/{trip}/places")))

    def test_the_replay_choice_defaults_on_and_persists(self):
        trip = self.book("ana", DRIVE)["trip_id"]
        self.assertIs(self.ok("ana", "GET", f"/api/trips/{trip}")["replay_from_home"], True)
        off = self.ok("ana", "POST", f"/api/trips/{trip}", {"replay_from_home": False})
        self.assertIs(off["replay_from_home"], False)
        self.assertIs(self.ok("ana", "GET", f"/api/trips/{trip}")["replay_from_home"], False)
        self.assertIs(self.ok("ana", "POST", f"/api/trips/{trip}", {"name": "Renamed"})["replay_from_home"], False)
        self.assertIs(self.ok("ana", "POST", f"/api/trips/{trip}", {"replay_from_home": True})["replay_from_home"], True)

    def test_the_replay_choice_must_be_true_or_false_and_belongs_to_those_who_see_the_trip(self):
        trip = self.book("ana", DRIVE)["trip_id"]
        for junk in ("yes", 1, None, "false"):
            with self.subTest(junk=junk):
                self.assertEqual(self.call("ana", "POST", f"/api/trips/{trip}", {"replay_from_home": junk})[0], 400)
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{trip}", {"replay_from_home": False}), (404, {"error": "No such trip"}))
        self.assertIs(self.ok("ana", "GET", f"/api/trips/{trip}")["replay_from_home"], True)

    def test_home_is_not_in_the_calendar_feed_or_reminders(self):
        self.ok("ana", "POST", "/api/home", SPRINGFIELD)
        self.book("ana", DRIVE)
        self.book("ana", OUT)
        sent: list = []
        with db.session() as conn:
            text = reminders.feed_text(conn, "sub-ana", datetime(2026, 6, 1, 12, tzinfo=UTC))
            reminders.run_due(conn, datetime(2026, 6, 2, 12, tzinfo=UTC), date(2026, 6, 2), 12, lambda device, message: sent.append(message))
        self.assertIn("BEGIN:VEVENT", text)
        for private in (CITY, ZIP, "62701"):
            self.assertNotIn(private, text)
            self.assertNotIn(private, json.dumps(sent))

    def test_nothing_about_home_is_logged_printed_or_sent_anywhere(self):
        with no_leaks(self, CITY, ZIP, "Quillwortburg", "62701-1234"):
            self.ok("ana", "POST", "/api/home", SPRINGFIELD)
            self.call("ana", "POST", "/api/home", {"city": "Quillwortburg 4", "zip": ZIP})
            self.call("ana", "POST", "/api/home", {**SPRINGFIELD, "street": "Quillwortburg"})
            trip = self.book("ana", DRIVE)["trip_id"]
            self.book("ana", SECOND, trip_id=trip)
            self.ok("ana", "GET", f"/api/trips/{trip}/places")
            self.ok("ana", "GET", "/api/home")
            self.ok("ana", "POST", f"/api/trips/{trip}", {"replay_from_home": False})
            self.ok("ana", "DELETE", "/api/home")

    def test_home_is_kept_with_the_other_settings_and_nowhere_else(self):
        self.ok("ana", "POST", "/api/home", SPRINGFIELD)
        with db.session() as conn:
            rows = dict(conn.execute(select(Setting.key, Setting.value)).fetchall())
        self.assertEqual(json.loads(rows[sk.HOME]), SPRINGFIELD)
        self.assertEqual([k for k, v in rows.items() if v and CITY in v], [sk.HOME])


class WithoutPlacesTests(unittest.TestCase):
    def test_the_location_helper_is_not_reaching_for_an_outside_service(self):
        from waypoint import tls
        with mock.patch.object(tls, "urlopen", side_effect=AssertionError("outside lookup")):
            self.assertIsNotNone(geocode.locate_home("Springfield", "IL", "62701", "US"))


if __name__ == "__main__":
    unittest.main()
