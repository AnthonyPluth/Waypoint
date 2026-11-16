import json
import unittest
from datetime import date

from sqlalchemy import delete, event

from tests.privacy import no_leaks
from tests.shared import freeze_today
from tests.test_photo_access import COUNTRY, STATE, AccessCase
from tests.test_photos_api import ASSET, KEY, ROME, SOHO, TOKYO, URL, grant_row, photo_row, source_row
from tests.test_trips import OUT, Household
from waypoint.domain import photos
from waypoint.domain.visibility import Viewer
from waypoint.storage import db, secretbox
from waypoint.storage.models import Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, Trip, TripPerson

TODAY = date(2026, 12, 1)
NEAR_SOHO = (SOHO[0] + 0.001, SOHO[1] + 0.001)
CANARIES = (ASSET, URL, KEY, STATE, COUNTRY)


def shot(number, local, where=None, kind="image", located="exif"):
    lat, lon = where or (None, None)
    return {"id": number, "person_id": 1, "trip_id": 1, "kind": kind, "taken_local": local, "zone": None, "latitude": lat, "longitude": lon,
            "location_source": located if where else None, "segment_id": None, "match": "place", "distance_km": None, "cluster": None, "removed_at": None}


def best(rows, limit):
    return photos.best_photos(rows, photos.clusters(rows), limit)


class BestPhotosTests(unittest.TestCase):
    def test_nothing_in_gives_nothing_out(self):
        self.assertEqual(best([], 7), [])
        self.assertEqual(photos.best_photos([], [], 3), [])

    def test_a_limit_of_zero_chooses_nothing(self):
        self.assertEqual(best([shot(1, "2026-06-01T10:00", SOHO)], 0), [])

    def test_the_cover_of_each_cluster_comes_largest_cluster_first(self):
        rows = [shot(1, "2026-06-01T09:00", TOKYO), shot(2, "2026-06-02T09:00", ROME), shot(3, "2026-06-02T10:00", ROME), shot(4, "2026-06-03T09:00", SOHO),
                shot(5, "2026-06-03T10:00", NEAR_SOHO), shot(6, "2026-06-03T11:00", SOHO)]
        self.assertEqual(best(rows, 3), [4, 2, 1])

    def test_a_limit_below_the_cluster_count_keeps_only_the_largest(self):
        rows = [shot(1, "2026-06-01T09:00", TOKYO), shot(2, "2026-06-02T09:00", ROME), shot(3, "2026-06-02T10:00", ROME)]
        self.assertEqual(best(rows, 1), [2])

    def test_clusters_of_one_size_go_by_which_began_first(self):
        rows = [shot(2, "2026-06-01T09:00", ROME), shot(3, "2026-06-02T09:00", TOKYO), shot(1, "2026-06-03T09:00", SOHO)]
        self.assertEqual(best(rows, 3), [2, 3, 1])

    def test_fewer_clusters_than_the_limit_take_more_photos_one_per_cluster_per_round(self):
        rows = [shot(1, "2026-06-01T09:00", ROME), shot(2, "2026-06-01T10:00", ROME), shot(3, "2026-06-01T11:00", ROME), shot(4, "2026-06-02T09:00", SOHO),
                shot(5, "2026-06-02T10:00", SOHO)]
        self.assertEqual(best(rows, 4), [1, 4, 2, 5])
        self.assertEqual(best(rows, 7), [1, 4, 2, 5, 3])

    def test_photos_in_no_cluster_come_last_oldest_first(self):
        rows = [shot(2, "2026-06-01T09:00"), shot(3, "2026-06-02T09:00", ROME), shot(4, "2026-06-02T10:00"), shot(1, "2026-06-03T09:00")]
        self.assertEqual(best(rows, 7), [3, 2, 4, 1])
        self.assertEqual(best(rows, 2), [3, 2])

    def test_a_trip_with_no_clusters_takes_its_photos_oldest_first(self):
        rows = [shot(1, "2026-06-01T09:00"), shot(2, "2026-06-02T09:00"), shot(3, "2026-06-03T09:00")]
        self.assertEqual(best(rows, 2), [1, 2])

    def test_videos_are_never_chosen(self):
        rows = [shot(1, "2026-06-01T09:00", ROME, "video"), shot(2, "2026-06-01T10:00", ROME), shot(3, "2026-06-02T09:00", SOHO, "video"),
                shot(4, "2026-06-03T09:00", None, "video"), shot(5, "2026-06-04T09:00")]
        self.assertEqual(best(rows, 7), [2, 5])

    def test_a_cluster_led_by_a_video_is_covered_by_its_first_photo(self):
        rows = [shot(1, "2026-06-01T09:00", ROME, "video"), shot(2, "2026-06-01T10:00", ROME), shot(3, "2026-06-01T11:00", ROME)]
        self.assertEqual(photos.clusters(rows)[0]["cover"], 1)
        self.assertEqual(best(rows, 2), [2, 3])

    def test_the_first_few_never_change_with_the_limit(self):
        rows = sorted((shot(n, f"2026-06-0{1 + n % 5}T{9 + n % 7:02d}:00", (ROME, SOHO, TOKYO, None)[n % 4]) for n in range(1, 30)), key=lambda row: (row["taken_local"], row["id"]))
        everything = best(rows, 29)
        self.assertEqual(len(set(everything)), len(everything))
        for limit in range(1, 10):
            self.assertEqual(best(rows, limit), everything[:limit])

    def test_unplaced_photos_follow_the_instant_order_not_the_wall_clock_across_zones(self):
        rows = [shot(1, "2026-06-02T07:00"), shot(2, "2026-06-02T01:00")]
        self.assertGreater(rows[0]["taken_local"], rows[1]["taken_local"])
        self.assertEqual(best(rows, 7), [1, 2])
        self.assertEqual(best(rows, 1), [1])

    def test_clusters_of_one_size_go_by_the_instant_they_began_not_the_wall_clock_across_zones(self):
        rows = [shot(1, "2026-06-02T07:00", TOKYO), shot(2, "2026-06-02T01:00", ROME)]
        self.assertGreater(rows[0]["taken_local"], rows[1]["taken_local"])
        self.assertEqual(best(rows, 2), [1, 2])
        self.assertEqual(best(rows, 1), [1])

    def test_photos_inside_a_cluster_follow_the_instant_order_not_the_wall_clock_across_zones(self):
        rows = [shot(1, "2026-06-02T07:00", ROME), shot(2, "2026-06-02T07:05", ROME), shot(3, "2026-06-02T01:00", ROME)]
        rows[0]["zone"], rows[1]["zone"], rows[2]["zone"] = "+09:00", "+09:00", "+02:00"
        self.assertEqual(best(rows, 3), [1, 2, 3])

    def test_a_photo_naming_a_cluster_that_is_not_there_counts_as_in_none(self):
        rows = [shot(1, "2026-06-01T09:00")]
        rows[0]["cluster"] = 5
        self.assertEqual(photos.best_photos(rows, [], 3), [1])


class CoverCase(AccessCase):
    def setUp(self):
        super().setUp()
        freeze_today(self, TODAY)
        self.share("ana")
        self.share("ben")

    def asset_of(self, photo_id):
        with db.session() as conn:
            row = conn.orm.get(Photo, photo_id)
            assert row is not None
            return row.asset_id

    def covers(self, who):
        return self.ok(who, "GET", "/api/photos/trip-covers")

    def cover(self, who, trip=None):
        found = [t for t in self.covers(who)["trips"] if t["trip_id"] == (trip or self.trip)]
        return found[0] if found else None

    def at(self, who, local, where=SOHO, trip=None, **fields):
        row = photo_row(self.sources[who], trip or self.trip, local, where=where, segment_id=self.stay["id"] if trip in (None, self.trip) else None, **fields)
        row.state, row.country = STATE, COUNTRY
        return self.keep(row)

    def own_past_trip(self, who, month="03"):
        seg = self.book(who, {**OUT, "start_local": f"2026-{month}-01T19:00", "end_local": f"2026-{month}-02T07:10"}, travelers=[{"person_id": self.person[who]}])
        self.share(who, seg["trip_id"])
        return seg["trip_id"]


class CoverRouteTests(CoverCase):
    def test_a_member_gets_the_count_and_covers_the_trip_page_would_start_from(self):
        a = [self.at("ben", f"2026-06-02T1{n}:00", SOHO) for n in range(3)]
        b = [self.at("ana", f"2026-06-03T1{n}:00", ROME) for n in range(2)]
        c = [self.at("ana", "2026-06-04T10:00", TOKYO)]
        for who in ("ana", "ben"):
            listed = self.listing(who)
            got = self.cover(who)
            self.assertEqual(got, {"trip_id": self.trip, "count": 6, "covers": [a[0], b[0], c[0]]}, who)
            self.assertEqual(got["count"], listed["counts"]["total"])
            self.assertEqual(listed["best"][:3], got["covers"])
            self.assertEqual(listed["best"], [a[0], b[0], c[0], a[1], b[1], a[2]])
            self.assertLessEqual(set(listed["best"]), {p["id"] for p in listed["photos"]})

    def test_best_holds_at_most_seven_and_covers_three(self):
        made = [self.at("ben", f"2026-06-02T{9 + n:02d}:00", SOHO) for n in range(9)]
        listed = self.listing("ana")
        self.assertEqual(listed["best"], made[:7])
        self.assertEqual(self.cover("ana"), {"trip_id": self.trip, "count": 9, "covers": made[:3]})

    def test_best_and_covers_follow_the_instant_when_the_wall_clock_disagrees_across_zones(self):
        later = self.at("ben", "2026-06-02T01:00", None, taken_utc="2026-06-01T23:00:00+00:00")
        earlier = self.at("ben", "2026-06-02T07:00", None, taken_utc="2026-06-01T22:00:00+00:00")
        self.assertLess(later, earlier)
        self.assertEqual(self.listing("ana")["best"], [earlier, later])
        self.assertEqual(self.cover("ana"), {"trip_id": self.trip, "count": 2, "covers": [earlier, later]})
        placed_later = self.at("ben", "2026-06-03T01:00", SOHO, taken_utc="2026-06-02T23:00:00+00:00")
        placed_earlier = self.at("ben", "2026-06-03T07:00", ROME, taken_utc="2026-06-02T22:00:00+00:00")
        self.assertEqual(self.listing("ana")["best"], [placed_earlier, placed_later, earlier, later])
        self.assertEqual(self.cover("ana")["covers"], [placed_earlier, placed_later, earlier])

    def test_two_people_with_the_same_asset_id_each_keep_their_photo_on_the_trip_and_the_covers(self):
        theirs = self.at("ana", "2026-06-02T10:00", SOHO, asset="canary-asset-shared-4k8m")
        mine = self.at("ben", "2026-06-02T11:00", SOHO, asset="canary-asset-shared-4k8m")
        self.assertNotEqual(self.sources["ana"], self.sources["ben"])
        with no_leaks(self, *CANARIES):
            for who in ("ana", "ben"):
                listed = self.listing(who)
                self.assertEqual(sorted(p["id"] for p in listed["photos"]), sorted([theirs, mine]), who)
                self.assertEqual(listed["counts"]["total"], 2, who)
                self.assertEqual(sorted(p["person_id"] for p in listed["people"]), sorted([self.person["ana"], self.person["ben"]]), who)
                self.assertEqual(self.cover(who), {"trip_id": self.trip, "count": 2, "covers": [theirs, mine]}, who)
                self.assertEqual(listed["best"], [theirs, mine], who)

    def test_a_trip_with_no_visible_photo_says_so_and_invents_nothing(self):
        self.assertEqual(self.cover("ana"), {"trip_id": self.trip, "count": 0, "covers": []})
        self.assertEqual(self.listing("ana")["best"], [])
        self.at("ben", "2026-06-02T10:00")
        with self.subTest("nobody shared"):
            with db.session() as conn:
                conn.execute(delete(PhotoGrant))
            self.assertEqual(self.cover("ana"), {"trip_id": self.trip, "count": 0, "covers": []})
            self.assertEqual(self.listing("ben")["best"], [])

    def test_photos_without_a_place_still_cover_a_trip_oldest_first(self):
        first = self.at("ben", "2026-06-02T09:00", None)
        second = self.at("ben", "2026-06-02T10:00", None)
        self.assertEqual(self.cover("ana"), {"trip_id": self.trip, "count": 2, "covers": [first, second]})

    def test_only_past_trips_the_viewer_can_see_are_listed(self):
        future = self.book("ana", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])["trip_id"]
        undated = self.ok("ana", "POST", "/api/trips", {"name": "Someday", "people": [self.person["ana"]]})["id"]
        ending_today = self.book("ana", {**OUT, "start_local": "2026-11-30T19:00", "end_local": "2026-12-01T07:10"}, travelers=[{"person_id": self.person["ana"]}])["trip_id"]
        ben_alone = self.own_past_trip("ben")
        listed = [t["trip_id"] for t in self.covers("ana")["trips"]]
        self.assertEqual(listed, [self.trip])
        self.assertNotIn(future, listed)
        self.assertNotIn(undated, listed)
        self.assertNotIn(ending_today, listed)
        self.assertEqual([t["trip_id"] for t in self.covers("ben")["trips"]], sorted([self.trip, ben_alone]))
        self.assertEqual(self.covers("cy"), {"trips": []})

    def test_a_trip_the_viewer_cannot_see_is_absent_and_its_routes_keep_answering_404(self):
        stranger_trip = self.own_past_trip("ben")
        self.at("ben", "2026-03-01T10:00", SOHO, trip=stranger_trip)
        self.assertEqual(self.covers("cy"), {"trips": []})
        self.assertNotIn(stranger_trip, [t["trip_id"] for t in self.covers("ana")["trips"]])
        for path in (f"/api/trips/{stranger_trip}/photos", f"/api/trips/{self.trip}/photos"):
            self.assertEqual(self.call("cy", "GET", path), (404, {"error": "No such trip"}))
        self.assertEqual(self.call("ana", "GET", f"/api/trips/{stranger_trip}/photos"), (404, {"error": "No such trip"}))

    def test_someone_elses_unshared_removed_or_foreign_photos_never_reach_a_count_a_cover_or_best(self):
        shared = self.at("ben", "2026-06-02T09:00", SOHO)
        only_me = self.at("ben", "2026-06-02T10:00", ROME)
        removed = self.at("ben", "2026-06-02T11:00", TOKYO)
        elsewhere = self.own_past_trip("ben")
        foreign = self.at("ben", "2026-03-01T10:00", SOHO, trip=elsewhere)
        with db.session() as conn:
            conn.orm.add(PhotoExclusion(person_id=self.person["ben"], asset_id=self.asset_of(removed), trip_id=self.trip, created=1.0))
        self.share("ben", scope="only_me")
        self.share("ana")
        mine = self.at("ana", "2026-06-02T12:00", SOHO)
        for photo_id in (shared, only_me, removed, foreign):
            self.assertIn(ASSET, self.asset_of(photo_id))
        with no_leaks(self, *CANARIES):
            theirs = self.cover("ana")
            listed = self.listing("ana")
            everything = json.dumps([self.covers("ana"), listed, self.covers("cy"), self.listing("ben")])
        self.assertEqual(theirs, {"trip_id": self.trip, "count": 1, "covers": [mine]})
        self.assertEqual((listed["counts"]["total"], listed["best"]), (1, [mine]))
        self.assertNotIn(elsewhere, [t["trip_id"] for t in self.covers("ana")["trips"]])
        for canary in (ASSET, STATE, COUNTRY):
            self.assertNotIn(canary, everything)
        self.assertEqual(self.cover("ben")["count"], 3)
        self.assertEqual(self.cover("ben")["covers"], [shared, only_me, mine])
        self.assertEqual(self.cover("ben", elsewhere), {"trip_id": elsewhere, "count": 1, "covers": [foreign]})

    def test_a_confirmation_recipient_or_booker_who_is_not_on_the_trip_sees_it_with_no_photos(self):
        booked = self.book("ana", {**OUT, "start_local": "2026-04-01T19:00", "end_local": "2026-04-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        self.share("ben", booked["trip_id"])
        only = self.keep(photo_row(self.sources["ben"], booked["trip_id"], "2026-04-02T09:00", where=SOHO, segment_id=booked["id"]))
        self.assertEqual(self.cover("ana", booked["trip_id"]), {"trip_id": booked["trip_id"], "count": 0, "covers": []})
        self.assertEqual(self.cover("ben", booked["trip_id"]), {"trip_id": booked["trip_id"], "count": 1, "covers": [only]})
        self.assertNotIn(booked["trip_id"], [t["trip_id"] for t in self.covers("cy")["trips"]])

    def test_a_revoked_grant_takes_the_photo_back_on_the_next_request(self):
        mine = self.at("ben", "2026-06-02T10:00")
        self.assertEqual(self.cover("ana")["covers"], [mine])
        self.share("ben", revoked=5.0)
        self.assertEqual(self.cover("ana"), {"trip_id": self.trip, "count": 0, "covers": []})
        self.assertEqual(self.cover("ben"), {"trip_id": self.trip, "count": 0, "covers": []})

    def test_the_same_asset_in_two_libraries_of_one_person_counts_once(self):
        twin = self.keep(PhotoSource(person_id=self.person["ben"], owner_sub="sub-ben", url=URL + "1", immich_user_id="immich-user-1", api_key=secretbox.encrypt(KEY) or "",
                                     status="ok", created=1.0))
        first = self.at("ben", "2026-06-02T10:00", asset="canary-asset-twin-7x2q")
        self.keep(photo_row(twin, self.trip, "2026-06-02T10:00", where=SOHO, segment_id=self.stay["id"], asset="canary-asset-twin-7x2q"))
        self.assertEqual(self.cover("ana"), {"trip_id": self.trip, "count": 1, "covers": [first]})
        self.assertEqual(self.listing("ana")["counts"]["total"], 1)

    def test_the_count_always_equals_the_trip_photos_total(self):
        for n in range(4):
            self.at("ben" if n % 2 else "ana", f"2026-06-02T1{n}:00", (SOHO, ROME)[n % 2])
        self.share("ben", scope="only_me")
        for who in ("ana", "ben"):
            self.assertEqual(self.cover(who)["count"], self.listing(who)["counts"]["total"], who)

    def test_a_viewer_without_a_sign_in_or_a_person_sees_nothing(self):
        with db.session() as conn:
            self.at("ben", "2026-06-02T10:00")
            self.assertEqual(photos.trip_covers(conn, Viewer(None), TODAY.isoformat()), {"trips": []})
            self.assertEqual(photos.trip_covers(conn, Viewer(None, household=True), TODAY.isoformat()), {"trips": []})


class CoverStewardTests(CoverCase):
    def setUp(self):
        super().setUp()
        self.kid = self.ok("ana", "POST", "/api/people", {"display_name": "Kid Example"})["id"]
        self.ok("ana", "POST", f"/api/trips/{self.trip}", {"people": [self.person["ana"], self.person["ben"], self.kid], "confirm": True})
        self.sources["kid"] = self.keep(source_row(self.kid, "sub-ana"))
        self.keep(PhotoSharingPrefs(person_id=self.kid, default_scope="only_me", share_all=False, set_by=None, share_all_since=None, steward_sub="sub-ana"))
        self.keep(grant_row(self.kid, self.trip, "only_me", by="sub-ana"))

    def test_a_stewards_covers_hold_the_childs_only_me_photos_and_nobody_elses_do(self):
        theirs = self.keep(photo_row(self.sources["kid"], self.trip, "2026-06-02T12:00", where=SOHO, segment_id=self.stay["id"]))
        self.assertEqual(self.cover("ana"), {"trip_id": self.trip, "count": 1, "covers": [theirs]})
        self.assertEqual(self.cover("ben"), {"trip_id": self.trip, "count": 0, "covers": []})
        self.assertEqual(self.listing("ana")["best"], [theirs])
        self.assertEqual(self.listing("ben")["best"], [])
        with db.session() as conn:
            conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == self.kid))
        self.keep(grant_row(self.kid, self.trip, "trip", by="sub-ana"))
        self.assertEqual(self.cover("ben"), {"trip_id": self.trip, "count": 1, "covers": [theirs]})


class CoverQueryTests(CoverCase):
    def trips_of(self, count):
        with db.session() as conn:
            for number in range(count):
                trip = Trip(name=f"Trip {number}", start_date=f"2025-{1 + number % 12:02d}-01", end_date=f"2025-{1 + number % 12:02d}-05", auto=False, booked_by=self.person["ana"])
                conn.orm.add(trip)
                conn.orm.flush()
                conn.orm.add_all([TripPerson(trip_id=trip.id, person_id=self.person["ana"]), TripPerson(trip_id=trip.id, person_id=self.person["ben"]),
                                  grant_row(self.person["ben"], trip.id, "trip", by="sub-ben")])
                conn.orm.flush()
                for n in range(4):
                    conn.orm.add(photo_row(self.sources["ben"], trip.id, f"2025-01-0{1 + n}T10:00", where=(SOHO, ROME)[n % 2]))

    widest = 0

    def statements(self, who):
        seen: list[str] = []
        engine = db.engine()

        def count(conn, cursor, statement, parameters, *rest):
            seen.append(statement)
            self.widest = max(self.widest, len(parameters))

        event.listen(engine, "before_cursor_execute", count)
        try:
            with db.session() as conn:
                got = photos.trip_covers(conn, Viewer(self.person[who]), TODAY.isoformat())
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return got, len(seen)

    def test_the_list_costs_the_same_number_of_statements_for_three_trips_as_for_thirty(self):
        self.trips_of(3)
        small, few = self.statements("ana")
        with db.session() as conn:
            conn.execute(delete(PhotoExclusion))
        self.trips_of(27)
        large, many = self.statements("ana")
        self.assertEqual(len([t for t in small["trips"] if t["count"]]), 3)
        self.assertEqual(len([t for t in large["trips"] if t["count"]]), 30)
        self.assertTrue(all(len(t["covers"]) == 3 and t["count"] == 4 for t in large["trips"] if t["count"]))
        self.assertEqual(few, many)

    def test_no_statement_binds_a_parameter_for_each_photo_or_asset(self):
        self.trips_of(30)
        self.statements("ana")
        self.assertLess(self.widest, 100)


class CoverHouseholdTests(Household):
    def setUp(self):
        super().setUp()
        self.janes = self.add(self.jane, {**OUT, "start_local": "2026-06-01T19:00", "end_local": "2026-06-02T07:10"}, None, self.on(self.jane.person_id))["trip_id"]
        self.sams = self.add(self.sam, {**OUT, "start_local": "2026-05-01T19:00", "end_local": "2026-05-02T07:10"}, None, self.on(self.sam.person_id))["trip_id"]
        self.c.orm.add_all([source_row(self.jane.person_id, "u-jane"), source_row(self.sam.person_id, "u-sam"), grant_row(self.jane.person_id, self.janes, by="u-jane"),
                            grant_row(self.sam.person_id, self.sams, by="u-sam")])
        self.c.orm.flush()
        self.c.orm.add_all([photo_row(1, self.janes, "2026-06-02T10:00", where=SOHO), photo_row(2, self.sams, "2026-05-02T10:00", where=SOHO)])
        self.c.orm.flush()

    def test_each_member_gets_their_own_trips_and_the_household_viewer_none(self):
        self.assertEqual([(t["trip_id"], t["count"]) for t in photos.trip_covers(self.c, self.jane, "2026-12-01")["trips"]], [(self.janes, 1)])
        self.assertEqual([(t["trip_id"], t["count"]) for t in photos.trip_covers(self.c, self.sam, "2026-12-01")["trips"]], [(self.sams, 1)])
        self.assertEqual(photos.trip_covers(self.c, Viewer(None, household=True), "2026-12-01"), {"trips": []})
        self.assertEqual(photos.trip_covers(self.c, Viewer(None), "2026-12-01"), {"trips": []})


if __name__ == "__main__":
    unittest.main()
