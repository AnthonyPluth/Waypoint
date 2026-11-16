import json
import os
import time
import unittest
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.shared import DbCase, add_database
from tests.test_trip_roads import DENVER, SALT_LAKE
from tests.test_trips import HOTEL, RouteCase
from waypoint.domain import driving_routes
from waypoint.storage import backup, db
from waypoint.storage.models import DrivingRoute, Trip


def drive_of(places):
    first, second = places["stays"][:2]
    return {"start": {"latitude": first["latitude"], "longitude": first["longitude"]},
            "end": {"latitude": second["latitude"], "longitude": second["longitude"]}}


def at(now):
    return mock.patch("waypoint.server.api.driving_routes.time", mock.Mock(time=lambda: now))


def rounded(place):
    return f"{place['latitude']:.4f},{place['longitude']:.4f}"


def line(drive, middle=((40.0, -108.0),)):
    return [[drive["start"]["latitude"], drive["start"]["longitude"]], *[list(p) for p in middle], [drive["end"]["latitude"], drive["end"]["longitude"]]]


SAME = object()


class RouteCacheCase(RouteCase):
    def trip_with_a_drive(self, who="ana"):
        first = self.book(who, DENVER)
        self.book(who, SALT_LAKE, trip_id=first["trip_id"])
        trip = first["trip_id"]
        return trip, drive_of(self.ok(who, "GET", f"/api/trips/{trip}/places"))

    def look_up(self, who, trip, *drives):
        query = "&".join(f"drive={rounded(d['start'])},{rounded(d['end'])}" for d in drives)
        return self.call(who, "GET", f"/api/trips/{trip}/driving-routes?{query}")

    def put(self, who, trip, drive, path=SAME):
        return self.call(who, "PUT", f"/api/trips/{trip}/driving-routes", {**drive, "path": line(drive) if path is SAME else path})

    def rows(self):
        with db.session() as conn:
            return list(conn.orm.scalars(select(DrivingRoute)))


class StoringAndReadingTests(RouteCacheCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(DrivingRoute.__table__.delete())

    def test_a_computed_path_is_stored_once_and_comes_back_for_the_same_drive(self):
        trip, drive = self.trip_with_a_drive()
        self.assertEqual(self.look_up("ana", trip, drive), (200, {"routes": []}))
        status, got = self.put("ana", trip, drive)
        self.assertEqual((status, got), (200, {"stored": True}))
        status, got = self.look_up("ana", trip, drive)
        self.assertEqual(status, 200)
        self.assertEqual(got["routes"], [{**drive, "path": line(drive)}])

    def test_a_second_member_of_the_trip_gets_the_stored_path(self):
        trip, drive = self.trip_with_a_drive()
        self.ok("ana", "POST", f"/api/trips/{trip}", {"people": [self.person["ben"]], "confirm": True})
        self.assertEqual(self.put("ana", trip, drive)[0], 200)
        status, got = self.look_up("ben", trip, drive)
        self.assertEqual((status, len(got["routes"])), (200, 1))

    def test_another_trip_over_the_same_drive_keeps_its_own_path(self):
        trip, drive = self.trip_with_a_drive()
        self.put("ana", trip, drive)
        again = self.book("ana", {**DENVER, "start_local": "2027-06-02T15:00", "end_local": "2027-06-04T10:00"})
        self.book("ana", {**SALT_LAKE, "start_local": "2027-06-04T15:00", "end_local": "2027-06-08T10:00"}, trip_id=again["trip_id"])
        other = again["trip_id"]
        self.assertNotEqual(other, trip)
        self.assertEqual(self.look_up("ana", other, drive), (200, {"routes": []}))
        self.assertEqual(self.put("ana", other, drive, line(drive, ((41.0, -109.0),)))[1], {"stored": True})
        self.assertEqual(self.look_up("ana", trip, drive)[1]["routes"][0]["path"], line(drive))
        self.assertEqual(self.look_up("ana", other, drive)[1]["routes"][0]["path"], line(drive, ((41.0, -109.0),)))
        self.assertEqual(sorted(r.trip_id for r in self.rows()), sorted([trip, other]))

    def test_removing_a_trip_removes_its_paths_and_only_its_paths(self):
        trip, drive = self.trip_with_a_drive()
        self.put("ana", trip, drive)
        again = self.book("ana", {**DENVER, "start_local": "2027-06-02T15:00", "end_local": "2027-06-04T10:00"})
        self.book("ana", {**SALT_LAKE, "start_local": "2027-06-04T15:00", "end_local": "2027-06-08T10:00"}, trip_id=again["trip_id"])
        self.put("ana", again["trip_id"], drive)
        self.assertEqual(len(self.rows()), 2)
        self.ok("ana", "DELETE", f"/api/trips/{trip}")
        self.assertEqual([r.trip_id for r in self.rows()], [again["trip_id"]])
        self.ok("ana", "DELETE", f"/api/trips/{again['trip_id']}")
        self.assertEqual(self.rows(), [])

    def test_a_stored_path_is_kept_until_it_is_old_enough_to_be_asked_for_again_and_replaced(self):
        trip, drive = self.trip_with_a_drive()
        now = time.time()
        with at(now):
            self.assertEqual(self.put("ana", trip, drive, line(drive, ((40.0, -108.0),)))[1], {"stored": True})
        with at(now + driving_routes.REPLACE_AFTER_SECONDS - 1):
            self.assertEqual(self.put("ana", trip, drive, line(drive, ((41.0, -109.0),)))[1], {"stored": False})
        with at(now + driving_routes.REPLACE_AFTER_SECONDS - 1):
            self.assertEqual(self.look_up("ana", trip, drive)[1]["routes"][0]["path"], line(drive, ((40.0, -108.0),)))
        with at(now + driving_routes.REPLACE_AFTER_SECONDS):
            self.assertEqual(self.look_up("ana", trip, drive)[1]["routes"], [])
            self.assertEqual(self.put("ana", trip, drive, line(drive, ((41.0, -109.0),)))[1], {"stored": True})
        with at(now + driving_routes.REPLACE_AFTER_SECONDS):
            self.assertEqual(self.look_up("ana", trip, drive)[1]["routes"][0]["path"], line(drive, ((41.0, -109.0),)))
        self.assertEqual(len(self.rows()), 1)

    def test_a_lookup_takes_several_drives_and_returns_only_the_ones_stored(self):
        trip, drive = self.trip_with_a_drive()
        other = {"start": drive["end"], "end": drive["start"]}
        self.put("ana", trip, drive)
        got = self.look_up("ana", trip, drive, other)[1]["routes"]
        self.assertEqual([(r["start"], r["end"]) for r in got], [(drive["start"], drive["end"])])

    def test_a_row_holds_the_rounded_drive_and_the_path_and_nothing_of_the_trip(self):
        trip, drive = self.trip_with_a_drive()
        self.put("ana", trip, drive)
        (row,) = self.rows()
        self.assertEqual(row.trip_id, trip)
        self.assertEqual([c.name for c in DrivingRoute.__table__.columns], ["trip_id", "from_lat", "from_lon", "to_lat", "to_lon", "path", "stored"])
        self.assertEqual((row.from_lat, row.from_lon), (round(drive["start"]["latitude"] * 10000), round(drive["start"]["longitude"] * 10000)))
        self.assertEqual(json.loads(row.path), line(drive))


class VisibilityTests(RouteCacheCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(DrivingRoute.__table__.delete())

    def test_a_stranger_gets_404_for_both_routes_and_nothing_is_stored(self):
        trip, drive = self.trip_with_a_drive()
        self.assertEqual(self.look_up("ben", trip, drive)[0], 404)
        self.assertEqual(self.put("ben", trip, drive)[0], 404)
        self.assertEqual(self.rows(), [])
        self.put("ana", trip, drive)
        self.assertEqual(self.look_up("ben", trip, drive)[0], 404)
        self.assertEqual(self.put("ben", trip, drive, line(drive, ((41.0, -109.0),)))[0], 404)
        self.assertEqual(json.loads(self.rows()[0].path), line(drive))

    def test_a_missing_trip_answers_the_same_404(self):
        _, drive = self.trip_with_a_drive()
        self.assertEqual(self.look_up("ana", 999999, drive)[0], 404)
        self.assertEqual(self.put("ana", 999999, drive)[0], 404)
        self.assertEqual(self.call("ana", "GET", "/api/trips/x/driving-routes?drive=1,2,3,4")[0], 404)

    def test_a_member_cannot_read_a_path_through_a_trip_that_does_not_drive_it(self):
        trip, drive = self.trip_with_a_drive()
        self.put("ana", trip, drive)
        mine = self.book("ben", {**HOTEL, "destination": "Chicago"})
        self.assertEqual(self.look_up("ben", mine["trip_id"], drive), (200, {"routes": []}))
        status, got = self.put("ben", mine["trip_id"], drive, line(drive, ((41.0, -109.0),)))
        self.assertEqual((status, got["error"]), (400, "That isn't a drive of this trip"))
        self.assertEqual(json.loads(self.rows()[0].path), line(drive))

    def test_a_members_own_trip_over_the_same_places_never_reads_or_learns_of_a_path_stored_through_a_trip_they_cannot_see(self):
        trip, drive = self.trip_with_a_drive("ana")
        self.assertEqual(self.put("ana", trip, drive)[1], {"stored": True})
        first = self.book("ben", DENVER)
        self.book("ben", SALT_LAKE, trip_id=first["trip_id"])
        mine = first["trip_id"]
        self.assertNotEqual(mine, trip)
        self.assertEqual(self.look_up("ben", mine, drive), (200, {"routes": []}))
        self.assertEqual(self.put("ben", mine, drive, line(drive, ((41.0, -109.0),)))[1], {"stored": True})
        self.assertEqual(self.look_up("ana", trip, drive)[1]["routes"][0]["path"], line(drive))
        self.assertEqual(self.look_up("ben", mine, drive)[1]["routes"][0]["path"], line(drive, ((41.0, -109.0),)))
        self.assertEqual(self.put("ana", trip, drive, line(drive, ((42.0, -110.0),)))[1], {"stored": False})

    def test_the_routes_run_inside_no_leaks_and_keep_the_trips_details_out_of_the_cache(self):
        name, code = "Quentin Marlowe-Zzyx", "ZQXW7413"
        with no_leaks(self, name, code):
            first = self.book("ana", {**DENVER, "confirmation": code, "travelers": [{"person_id": None, "name": name}]})
            self.book("ana", {**SALT_LAKE, "confirmation": code, "travelers": [{"person_id": None, "name": name}]}, trip_id=first["trip_id"])
            trip = first["trip_id"]
            drive = drive_of(self.ok("ana", "GET", f"/api/trips/{trip}/places"))
            self.assertEqual(self.put("ana", trip, drive)[0], 200)
            got = self.look_up("ana", trip, drive)[1]
            self.assertNotIn(name, repr(got))
            self.assertNotIn(code, repr(got))
        self.assertEqual(sorted(got), ["routes"])
        self.assertEqual(sorted(got["routes"][0]), ["end", "path", "start"])
        self.assertEqual(len(self.rows()), 1)


class RefusalTests(RouteCacheCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(DrivingRoute.__table__.delete())
        self.trip, self.drive = self.trip_with_a_drive()

    def refused(self, path, message=None):
        status, got = self.put("ana", self.trip, self.drive, path)
        self.assertEqual(status, 400, got)
        if message:
            self.assertEqual(got["error"], message)
        self.assertEqual(self.rows(), [])

    def test_a_path_must_be_two_or_more_points(self):
        for bad in (None, "line", {}, [], [[39.7, -104.9]], [[39.7]], [[39.7, -104.9, 5], [40.7, -111.8]], [["a", "b"], ["c", "d"]], [[True, False], [True, False]]):
            with self.subTest(path=bad):
                self.refused(bad)

    def test_points_must_be_finite_and_inside_the_world(self):
        for middle in ((float("nan"), -108.0), (float("inf"), -108.0), (91.0, -108.0), (40.0, 181.0), (-91.0, 0.0)):
            with self.subTest(point=middle):
                self.refused(line(self.drive, (middle,)))

    def test_a_path_over_the_point_limit_is_refused(self):
        self.refused(line(self.drive, [(40.0, -108.0)] * driving_routes.MAX_POINTS))
        self.assertEqual(self.put("ana", self.trip, self.drive, line(self.drive, [(40.0, -108.0)] * (driving_routes.MAX_POINTS - 2)))[0], 200)

    def test_a_path_over_the_size_limit_is_refused(self):
        with mock.patch.object(driving_routes, "MAX_PATH_BYTES", 40):
            self.refused(line(self.drive, ((40.123456, -108.123456),) * 5), "That route is too large")

    def test_a_path_must_start_and_end_at_the_drive(self):
        start, end = self.drive["start"], self.drive["end"]
        self.refused([[start["latitude"] + 0.5, start["longitude"]], [end["latitude"], end["longitude"]]], "The route doesn't start and end at the drive's places")
        self.refused([[start["latitude"], start["longitude"]], [end["latitude"], end["longitude"] + 0.5]], "The route doesn't start and end at the drive's places")

    def test_the_drive_must_be_two_different_valid_places_of_the_trip(self):
        start = self.drive["start"]
        for body in ({"start": start, "end": start, "path": line(self.drive)}, {"start": start, "path": line(self.drive)},
                     {"start": start, "end": {"latitude": "x", "longitude": 1}, "path": line(self.drive)},
                     {"start": start, "end": {"latitude": 95, "longitude": 1}, "path": line(self.drive)},
                     {"start": start, "end": {"latitude": 40.0, "longitude": -100.0}, "path": line(self.drive)},
                     {"start": "here", "end": start, "path": []}):
            with self.subTest(body=body):
                status, _ = self.call("ana", "PUT", f"/api/trips/{self.trip}/driving-routes", body)
                self.assertEqual(status, 400)
        self.assertEqual(self.rows(), [])

    def test_a_lookup_needs_between_one_and_the_limit_of_well_formed_drives(self):
        base = f"/api/trips/{self.trip}/driving-routes"
        self.assertEqual(self.call("ana", "GET", base)[0], 400)
        for query in ("drive=1,2,3", "drive=a,b,c,d", "drive=1,2,3,nan", "drive=91,2,3,4", "drive=1,2,1,2", "drive=1,2,3,4,5"):
            with self.subTest(query=query):
                self.assertEqual(self.call("ana", "GET", f"{base}?{query}")[0], 400)
        too_many = "&".join(["drive=1,2,3,4"] * (driving_routes.MAX_DRIVES + 1))
        self.assertEqual(self.call("ana", "GET", f"{base}?{too_many}")[0], 400)
        self.assertEqual(self.call("ana", "GET", f"{base}?" + "&".join(["drive=1,2,3,4"] * driving_routes.MAX_DRIVES)), (200, {"routes": []}))


class BackupTests(DbCase):
    def test_the_stored_paths_travel_in_a_backup_and_come_back_on_restore(self):
        self.c.execute(Trip.__table__.insert().values(id=5, name="Trip", auto=True))
        self.c.execute(DrivingRoute.__table__.insert().values(trip_id=5, from_lat=397392, from_lon=-1049903, to_lat=407608, to_lon=-1118910,
                                                              path="[[39.7392,-104.9903],[40.0,-108.0],[40.7608,-111.891]]", stored=1700000000.5))
        self.c.commit()
        data = backup.load(backup.dump(self.c))
        self.assertEqual(data["tables"]["driving_routes"]["rows"], [[5, 397392, -1049903, 407608, -1118910, "[[39.7392,-104.9903],[40.0,-108.0],[40.7608,-111.891]]", 1700000000.5]])
        other = db.connect(add_database(self, os.path.join(os.path.dirname(self.path), "restored.db")))
        self.addCleanup(other.close)
        other.execute(Trip.__table__.insert().values(id=9, name="Old", auto=True))
        other.execute(DrivingRoute.__table__.insert().values(trip_id=9, from_lat=1, from_lon=2, to_lat=3, to_lon=4, path="[]", stored=0.0))
        self.assertEqual(backup.restore(other, data)["driving_routes"], 1)
        other.commit()
        (row,) = list(other.execute(select(DrivingRoute.trip_id, DrivingRoute.from_lat, DrivingRoute.path, DrivingRoute.stored)))
        self.assertEqual(tuple(row), (5, 397392, "[[39.7392,-104.9903],[40.0,-108.0],[40.7608,-111.891]]", 1700000000.5))


if __name__ == "__main__":
    unittest.main()
