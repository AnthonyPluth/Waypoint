import os
import time
import unittest
from unittest import mock

from sqlalchemy import insert, select, update

from tests.test_photos_api import SOHO, grant_row, photo_row, source_row
from tests.test_trips import HOTEL, OUT, Household
from waypoint.domain import people, photogrants, photos, trippeople, trips, visibility
from waypoint.domain.visibility import Viewer
from waypoint.server import jobs
from waypoint.storage import db
from waypoint.storage.models import Person, Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, PhotoTripSync, Trip, User

ALLOWED = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "u-jane@example.com,u-sam@example.com"}
INSIDE_B = "2026-06-04T12:00"
ONLY_A = "2026-06-07T12:00"


class GrantCase(Household):
    def setUp(self):
        super().setUp()
        self.jid, self.sid = self.jane.person_id, self.sam.person_id
        self.flight = self.add(self.jane, OUT, None, self.on(self.jid, self.sid))
        self.a = self.flight["trip_id"]
        self.add(self.jane, HOTEL, self.a)
        self.b = trips.create_trip(self.c, self.jane, {"name": "Short", "people": [self.jid]})["id"]
        self.add(self.jane, {**HOTEL, "start_local": "2026-06-03T15:00", "end_local": "2026-06-05T10:00"}, self.b)
        self.c.orm.add(source_row(self.jid, "u-jane"))
        self.c.orm.flush()
        self.janes = self.c.orm.scalars(select(PhotoSource.id)).one()

    def share(self, person, trip, scope="trip", revoked=None, by="u-jane"):
        row = self.c.orm.get(PhotoGrant, (person, trip))
        if row is not None:
            self.c.orm.delete(row)
            self.c.orm.flush()
        self.c.orm.add(grant_row(person, trip, scope, revoked, by))
        self.c.orm.flush()

    def photo(self, trip, local=INSIDE_B, source=None, **fields):
        row = photo_row(source or self.janes, trip, local, where=SOHO, **fields)
        self.c.orm.add(row)
        self.c.orm.flush()
        return row

    def row(self, photo_id):
        self.c.orm.expire_all()
        return self.c.orm.get(Photo, photo_id)

    def grant(self, person, trip):
        row = self.c.orm.get(PhotoGrant, (person, trip))
        self.c.orm.expire_all()
        return None if row is None else (row.scope, row.revoked, row.granted_by)

    def steward(self, person, sub):
        self.c.orm.add(PhotoSharingPrefs(person_id=person, default_scope="only_me", share_all=False, set_by=None, share_all_since=None, steward_sub=sub))
        self.c.orm.flush()

    def seen(self, who, trip):
        got = photos.for_trip(self.c, who, trip)
        return [p["id"] for p in got["photos"]] if got else None


class GrantTests(GrantCase):
    def test_a_grant_needs_the_person_on_the_trip_and_records_who_made_it(self):
        booked = self.add(self.jane, {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, None, self.on(self.sid))["trip_id"]
        self.assertIsNone(photogrants.grant(self.c, self.jane, self.jid, booked, "trip"))
        self.assertIsNone(photogrants.grant(self.c, self.jane, self.jid, 99999, "trip"))
        self.assertIsNone(photogrants.grant(self.c, self.jane, self.sid, self.a, "trip"))
        self.assertIsNone(photogrants.grant(self.c, self.jane, self.jid, self.a, "everyone"))
        self.assertIsNone(photogrants.grant(self.c, Viewer(None, household=True), self.jid, self.a, "trip"))
        self.assertIsNone(photogrants.grant(self.c, Viewer(None), self.jid, self.a, "trip"))
        got = photogrants.grant(self.c, self.jane, self.jid, self.a, "only_me", 10.0)
        self.assertEqual((got["state"], got["scope"]), ("shared", "only_me"))
        self.assertEqual(self.grant(self.jid, self.a), ("only_me", None, "u-jane"))
        photogrants.stop(self.c, self.jane, self.jid, self.a, 11.0)
        self.assertEqual(self.grant(self.jid, self.a), ("only_me", 11.0, "u-jane"))
        self.assertEqual(photogrants.grant(self.c, self.jane, self.jid, self.a, "trip", 12.0)["scope"], "trip")
        self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))
        self.assertEqual(photogrants.state_of(self.c, self.jane, self.jid, self.a)["state"], "shared")
        self.assertIsNone(photogrants.state_of(self.c, self.sam, self.jid, self.a))
        self.assertIsNone(photogrants.state_of(self.c, self.jane, self.jid, self.b + 1000))

    def test_two_requests_that_both_find_no_row_write_one_grant(self):
        self.share(self.jid, self.a, "only_me", revoked=3.0, by="u-sam")
        with mock.patch.object(photogrants, "lock", return_value={}):
            self.assertEqual(photogrants.grant(self.c, self.jane, self.jid, self.a, "trip", 10.0)["scope"], "trip")
            self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))
            photogrants.stop(self.c, self.jane, self.jid, self.a, 11.0)
            self.assertEqual(self.grant(self.jid, self.a), ("trip", 11.0, "u-jane"))
        self.assertEqual(self.c.execute(select(PhotoGrant.trip_id)).fetchall(), [(self.a,)])

    def test_a_first_share_that_races_with_leaving_the_trip_writes_nothing(self):
        real, removed = photogrants._lock_trip, []

        def leave_first(conn, trip_id):
            if not removed:
                removed.append(True)
                trippeople.remove(self.c, self.a, [self.jid])
                photogrants.trips_changed(self.c, [self.a])
            return real(conn, trip_id)
        with mock.patch.object(photogrants, "_lock_trip", side_effect=leave_first):
            self.assertIsNone(photogrants.grant(self.c, self.jane, self.jid, self.a, "trip", 12.0))
        self.assertIsNone(self.grant(self.jid, self.a))
        self.assertEqual(self.c.execute(select(PhotoGrant.trip_id)).fetchall(), [])

    def test_not_now_needs_the_person_on_the_trip_but_stopping_an_old_grant_does_not(self):
        booked = self.add(self.jane, {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, None, self.on(self.sid))["trip_id"]
        self.assertIsNone(photogrants.stop(self.c, self.jane, self.jid, booked, 5.0))
        self.share(self.jid, booked)
        self.assertEqual(photogrants.stop(self.c, self.jane, self.jid, booked, 5.0)["state"], "declined")

    def test_stopping_re_places_the_rows_on_another_shared_trip_and_deletes_the_rest(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        only_a = self.photo(self.a, ONLY_A)
        torn = self.photo(None, match="ambiguous")
        self.c.execute(insert(PhotoTripSync).values(source_id=self.janes, trip_id=self.b, window_start="s", window_end="e"))
        self.c.execute(insert(PhotoExclusion).values(person_id=self.jid, asset_id=only_a.asset_id, trip_id=self.b, created=1.0))
        self.assertEqual(self.seen(self.jane, self.b), [both.id])
        got = photogrants.stop(self.c, self.jane, self.jid, self.b, 20.0)
        self.assertEqual((got["state"], got["count"]), ("declined", 0))
        moved = self.row(both.id)
        self.assertEqual((moved.trip_id, moved.match, moved.decided_by), (self.a, "place", "auto"))
        self.assertEqual((self.row(torn.id).trip_id, self.row(torn.id).match), (self.a, "place"))
        self.assertEqual(self.seen(self.jane, self.a), [both.id, torn.id, only_a.id])
        self.assertEqual(self.c.execute(select(PhotoTripSync.trip_id)).fetchall(), [])
        self.assertEqual(self.c.execute(select(PhotoExclusion.trip_id)).fetchall(), [(self.b,)])
        photogrants.stop(self.c, self.jane, self.jid, self.a, 21.0)
        for gone in (both, only_a, torn):
            self.assertIsNone(self.row(gone.id), gone.id)

    def test_removing_from_one_of_two_overlapping_trips_moves_the_photo_to_the_other(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        only_a = self.photo(self.a, ONLY_A)
        self.assertIsNone(photogrants.exclude(self.c, self.jane, self.b, [both.id, only_a.id]))
        self.assertIsNone(photogrants.exclude(self.c, self.sam, self.b, [both.id]))
        self.assertIsNone(photogrants.exclude(self.c, self.jane, self.b, []))
        got = photogrants.exclude(self.c, self.jane, self.b, [both.id], 30.0)
        self.assertEqual((got["count"], got["removed_count"], [p["id"] for p in got["removed"]]), (0, 1, [both.id]))
        self.assertEqual((self.row(both.id).trip_id, self.row(both.id).decided_by), (self.a, "auto"))
        self.assertEqual(self.seen(self.jane, self.a), [both.id, only_a.id])
        self.assertEqual([p.id for p, _ in photos.removed(self.c, self.jane, self.b)], [both.id])
        photogrants.exclude(self.c, self.jane, self.a, [only_a.id], 31.0)
        self.assertEqual((self.row(only_a.id).trip_id, self.row(only_a.id).match), (self.a, "place"))
        self.assertEqual(self.seen(self.jane, self.a), [both.id])
        self.assertEqual([p.id for p, _ in photos.removed(self.c, self.jane, self.a)], [only_a.id])
        self.assertEqual(self.c.execute(select(PhotoExclusion.created).order_by(PhotoExclusion.created)).scalars(), [30.0, 31.0])

    def test_removing_sees_a_hand_placement_made_meanwhile_and_writes_nothing(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        real, moved = photos.lock_grants, []

        def move_first(conn, person, trip_ids):
            if not moved:
                moved.append(True)
                photos.decide(self.c, self.jane, both.id, self.a, None)
            return real(conn, person, trip_ids)
        with mock.patch.object(photos, "lock_grants", side_effect=move_first):
            self.assertIsNone(photogrants.exclude(self.c, self.jane, self.b, [both.id], 40.0))
        self.assertEqual((self.row(both.id).trip_id, self.row(both.id).decided_by), (self.a, "owner"))
        self.assertEqual(self.c.execute(select(PhotoExclusion.asset_id)).fetchall(), [])

    def test_put_back_returns_the_photo_unless_its_person_placed_it_elsewhere_by_hand(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        photogrants.exclude(self.c, self.jane, self.b, [both.id])
        self.assertEqual(self.row(both.id).trip_id, self.a)
        self.assertIsNone(photogrants.put_back(self.c, self.sam, self.b, both.id))
        self.assertIsNone(photogrants.put_back(self.c, self.jane, self.a, both.id))
        got = photogrants.put_back(self.c, self.jane, self.b, both.id)
        self.assertEqual((got["count"], got["removed_count"]), (1, 0))
        self.assertEqual(self.row(both.id).trip_id, self.b)
        self.assertEqual(self.c.execute(select(PhotoExclusion.asset_id)).fetchall(), [])
        photogrants.exclude(self.c, self.jane, self.b, [both.id])
        self.c.execute(update(Photo).where(Photo.id == both.id).values(decided_by="owner", trip_id=self.a))
        photogrants.put_back(self.c, self.jane, self.b, both.id)
        self.assertEqual((self.row(both.id).trip_id, self.row(both.id).decided_by), (self.a, "owner"))
        self.assertEqual(self.c.execute(select(PhotoExclusion.asset_id)).fetchall(), [])

    def test_a_photo_removed_from_its_only_trip_stays_as_a_removed_row_and_one_removed_everywhere_is_deleted_on_stop(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        only_a = self.photo(self.a, ONLY_A)
        photogrants.exclude(self.c, self.jane, self.a, [only_a.id])
        self.assertEqual(self.row(only_a.id).trip_id, self.a)
        photogrants.stop(self.c, self.jane, self.jid, self.b)
        self.assertEqual(self.row(only_a.id).trip_id, self.a)
        photogrants.stop(self.c, self.jane, self.jid, self.a)
        self.assertIsNone(self.row(only_a.id))


class StandingSettingTests(GrantCase):
    def test_share_on_all_my_trips_grants_every_eligible_trip_once_and_later_stops_stay_stopped(self):
        theirs = self.add(self.sam, {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, None, self.on(self.sid))["trip_id"]
        self.share(self.jid, self.b, revoked=5.0)
        self.assertEqual(photogrants.prefs_of(self.c, self.jid), {"default_scope": "only_me", "share_all": False})
        self.assertIsNone(photogrants.set_prefs(self.c, self.sam, self.jid, None, True))
        self.assertIsNone(photogrants.set_prefs(self.c, self.jane, self.jid, "all", None))
        self.assertIsNone(photogrants.set_prefs(self.c, Viewer(None, household=True), self.jid, None, True))
        got = photogrants.set_prefs(self.c, self.jane, self.jid, "trip", True, 40.0)
        self.assertEqual(got, {"default_scope": "trip", "share_all": True})
        self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))
        self.assertEqual(self.grant(self.jid, self.b), ("trip", None, "u-jane"))
        self.assertIsNone(self.grant(self.jid, theirs))
        self.assertEqual(self.c.orm.get(PhotoSharingPrefs, self.jid).set_by, "u-jane")
        photogrants.stop(self.c, self.jane, self.jid, self.b, 41.0)
        photogrants.set_prefs(self.c, self.jane, self.jid, None, True, 42.0)
        self.assertEqual(self.grant(self.jid, self.b), ("trip", 41.0, "u-jane"))
        photogrants.set_prefs(self.c, self.jane, self.jid, "only_me", False, 43.0)
        self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))
        self.assertEqual(self.grant(self.jid, self.b), ("trip", 41.0, "u-jane"))
        self.assertEqual(photogrants.prefs_of(self.c, self.jid), {"default_scope": "only_me", "share_all": False})
        photogrants.set_prefs(self.c, self.jane, self.jid, None, True, 44.0)
        self.assertEqual(self.grant(self.jid, self.b), ("only_me", None, "u-jane"))

    def test_the_first_preferences_row_survives_a_request_that_wrote_it_first(self):
        real = db.insert_ignore

        def other_request_first(conn, entity, values, key=None):
            if entity is PhotoSharingPrefs:
                real(conn, entity, {**values, "default_scope": "trip"}, key)
            return real(conn, entity, values, key)
        with mock.patch.object(photogrants.db, "insert_ignore", side_effect=other_request_first):
            self.assertEqual(photogrants.set_prefs(self.c, self.jane, self.jid, None, True, 97.0), {"default_scope": "trip", "share_all": True})
        self.assertEqual(self.c.execute(select(PhotoSharingPrefs.person_id)).fetchall(), [(self.jid,)])

    def test_a_person_who_joins_a_trip_is_shared_by_the_setting_when_its_setter_can_see_the_trip(self):
        later = self.add(self.jane, {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, None, self.on(self.jid))["trip_id"]
        self.assertFalse(photogrants.joined(self.c, self.jid, later))
        photogrants.set_prefs(self.c, self.jane, self.jid, "trip", True, 50.0)
        self.assertFalse(photogrants.joined(self.c, self.jid, later))
        newer = self.add(self.sam, {**OUT, "start_local": "2027-03-01T19:00", "end_local": "2027-03-02T07:10"}, None, self.on(self.sid))["trip_id"]
        self.assertIsNone(self.grant(self.jid, newer))
        trips.edit_trip(self.c, self.sam, newer, {"people": [self.sid, self.jid]}, confirmed=True)
        self.assertEqual(self.grant(self.jid, newer), ("trip", None, "u-jane"))
        self.assertFalse(photogrants.joined(self.c, self.jid, newer, 52.0))
        trips.edit_trip(self.c, self.sam, newer, {"people": [self.sid]}, confirmed=True)
        self.assertIsNone(self.grant(self.jid, newer))
        trips.edit_trip(self.c, self.sam, newer, {"people": [self.sid, self.jid]}, confirmed=True)
        self.assertEqual(self.grant(self.jid, newer), ("trip", None, "u-jane"))
        self.c.orm.add(source_row(self.mia, "u-jane"))
        self.c.orm.flush()
        self.steward(self.mia, "u-jane")
        photogrants.set_prefs(self.c, self.jane, self.mia, "only_me", True, 53.0)
        hidden = self.add(self.sam, {**OUT, "start_local": "2027-05-01T19:00", "end_local": "2027-05-02T07:10"}, None, self.on(self.sid, self.mia))["trip_id"]
        self.assertFalse(photogrants.joined(self.c, self.mia, hidden, 54.0))
        self.assertIsNone(self.grant(self.mia, hidden))
        self.assertEqual(photogrants.reconcile(self.c, hidden, 55.0), 0)
        trips.edit_trip(self.c, self.sam, hidden, {"people": [self.sid, self.mia, self.jid]}, confirmed=True)
        self.assertEqual(self.grant(self.mia, hidden), ("only_me", None, "u-jane"))
        self.assertEqual(self.grant(self.jid, hidden), ("trip", None, "u-jane"))
        self.assertEqual(photogrants.reconcile(self.c, hidden, 57.0), 0)

    def test_reconcile_re_shares_a_decline_older_than_the_setting_and_ends_a_grant_its_setter_lost_sight_of(self):
        self.share(self.jid, self.a, revoked=5.0)
        photogrants.set_prefs(self.c, self.jane, self.jid, "trip", True, 60.0)
        self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))
        photogrants.stop(self.c, self.jane, self.jid, self.a, 61.0)
        self.assertEqual(photogrants.reconcile(self.c, self.a, 62.0), 0)
        self.assertEqual(self.grant(self.jid, self.a), ("trip", 61.0, "u-jane"))
        self.c.execute(update(PhotoGrant).where(PhotoGrant.person_id == self.jid, PhotoGrant.trip_id == self.a).values(revoked=59.0))
        self.assertEqual(photogrants.reconcile(self.c, self.a, 63.0), 1)
        self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))
        self.c.orm.add(source_row(self.mia, "u-sam"))
        self.c.orm.flush()
        self.steward(self.mia, "u-sam")
        apart = self.add(self.jane, {**OUT, "start_local": "2027-05-01T19:00", "end_local": "2027-05-02T07:10"}, None, self.on(self.jid, self.mia))["trip_id"]
        self.share(self.mia, apart, by="u-sam")
        lost = self.photo(apart, "2027-05-02T09:00", source=self.c.orm.scalars(select(PhotoSource.id).where(PhotoSource.person_id == self.mia)).one())
        self.c.execute(insert(PhotoTripSync).values(source_id=lost.source_id, trip_id=apart, window_start="s", window_end="e"))
        self.assertEqual(self.grant(self.jid, apart), ("trip", None, "u-jane"))
        self.assertEqual(photogrants.reconcile(self.c, apart, 64.0), 1)
        self.assertIsNone(self.grant(self.mia, apart))
        self.assertIsNone(self.row(lost.id))
        self.assertEqual(self.c.execute(select(PhotoTripSync.trip_id)).fetchall(), [])
        self.assertEqual(photogrants.reconcile(self.c, apart, 65.0), 0)


class TripChangeTests(GrantCase):
    def only_flight(self, *people):
        flight = self.add(self.jane, {**OUT, "start_local": "2027-06-01T19:00", "end_local": "2027-06-02T07:10"}, None, self.on(*people))
        self.share(self.jid, flight["trip_id"])
        return flight

    def test_a_trip_that_grows_drops_trip_grants_to_only_me_and_asks_again(self):
        flight = self.only_flight(self.jid, self.sid)
        trip = flight["trip_id"]
        mine = self.photo(trip, "2027-06-02T09:00")
        self.assertEqual(self.seen(self.sam, trip), [mine.id])
        hotel = self.add(self.jane, {**HOTEL, "start_local": "2027-06-02T15:00", "end_local": "2027-06-08T10:00"}, trip)
        self.assertEqual(self.grant(self.jid, trip), ("only_me", None, "u-jane"))
        self.assertTrue(self.c.orm.get(PhotoGrant, (self.jid, trip)).ask_again)
        self.assertEqual(photogrants.state_of(self.c, self.jane, self.jid, trip)["state"], "ask")
        self.assertEqual(self.seen(self.sam, trip), [])
        self.assertEqual(self.seen(self.jane, trip), [mine.id])
        got = photogrants.decline(self.c, self.jane, self.jid, trip, 90.0)
        self.assertEqual((got["state"], got["scope"]), ("shared", "only_me"))
        self.assertEqual(self.grant(self.jid, trip), ("only_me", None, "u-jane"))
        self.assertEqual(self.seen(self.jane, trip), [mine.id])
        self.assertEqual(photogrants.grant(self.c, self.jane, self.jid, trip, "trip", 91.0)["state"], "shared")
        self.assertFalse(self.c.orm.get(PhotoGrant, (self.jid, trip)).ask_again)
        trips.edit_segment(self.c, self.jane, hotel["id"], {"end_local": "2027-06-09T10:00"})
        self.assertEqual(photogrants.state_of(self.c, self.jane, self.jid, trip)["state"], "ask")
        self.assertEqual(photogrants.decline(self.c, self.jane, self.jid, trip, 92.0)["state"], "shared")
        self.assertEqual(photogrants.stop(self.c, self.jane, self.jid, trip, 93.0)["state"], "declined")
        self.assertEqual(photogrants.decline(self.c, self.jane, self.jid, trip, 94.0)["state"], "declined")

    def test_a_trip_that_shrinks_re_places_the_rows_outside_its_window(self):
        flight = self.only_flight(self.jid)
        trip = flight["trip_id"]
        hotel = self.add(self.jane, {**HOTEL, "start_local": "2027-06-02T15:00", "end_local": "2027-06-08T10:00"}, trip)
        inside = self.photo(trip, "2027-06-02T09:00")
        late = self.photo(trip, "2027-06-06T12:00", decided="owner")
        trips.edit_segment(self.c, self.jane, hotel["id"], {"status": "cancelled"})
        self.assertEqual(self.row(inside.id).trip_id, trip)
        self.assertIsNone(self.row(late.id))

    def test_someone_taken_off_a_trip_loses_their_grant_there(self):
        flight = self.only_flight(self.jid, self.sid)
        trip = flight["trip_id"]
        self.share(self.sid, trip, by="u-sam")
        self.c.orm.add(source_row(self.sid, "u-sam"))
        self.c.orm.flush()
        theirs = self.photo(trip, "2027-06-02T09:00", source=self.c.orm.scalars(select(PhotoSource.id).where(PhotoSource.person_id == self.sid)).one())
        trips.edit_segment(self.c, self.jane, flight["id"], {"travelers": [{"person_id": self.jid, "name": None}]})
        self.assertEqual(self.grant(self.sid, trip), ("trip", None, "u-sam"))
        trips.edit_trip(self.c, self.jane, trip, {"people": [self.jid]}, confirmed=True)
        self.assertIsNone(self.grant(self.sid, trip))
        self.assertIsNone(self.row(theirs.id))
        self.assertEqual(self.grant(self.jid, trip), ("trip", None, "u-jane"))

    def lone(self):
        trip = trips.create_trip(self.c, self.jane, {"name": "Lone", "people": [self.jid]})["id"]
        self.c.execute(update(Trip).where(Trip.id == trip).values(auto=True))
        booking = self.add(self.jane, {**HOTEL, "start_local": "2026-06-03T15:00", "end_local": "2026-06-05T10:00"}, trip)
        self.share(self.jid, trip)
        return trip, booking

    def test_deleting_the_last_booking_of_an_automatic_trip_re_places_its_photos(self):
        self.share(self.jid, self.a)
        trip, lone = self.lone()
        both = self.photo(trip)
        self.assertTrue(trips.delete_segment(self.c, self.jane, lone["id"]))
        self.assertIsNone(self.c.orm.get(Trip, trip))
        self.assertEqual((self.row(both.id).trip_id, self.row(both.id).decided_by), (self.a, "auto"))

    def test_moving_the_only_booking_out_of_a_trip_re_places_its_photos(self):
        self.share(self.jid, self.a)
        trip, lone = self.lone()
        both = self.photo(trip)
        trips.move_segment(self.c, self.jane, lone["id"], self.a, confirmed=True)
        self.assertIsNone(self.c.orm.get(Trip, trip))
        self.assertEqual(self.row(both.id).trip_id, self.a)
        self.assertEqual(self.c.execute(select(PhotoGrant.trip_id).where(PhotoGrant.trip_id == trip)).fetchall(), [])

    def test_merging_carries_the_other_trips_exclusions_and_re_places_its_photos(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        self.c.execute(insert(PhotoExclusion).values(person_id=self.jid, asset_id="kept", trip_id=self.b, created=4.0))
        trips.merge(self.c, self.jane, self.a, self.b, confirmed=True)
        self.assertEqual(self.c.execute(select(PhotoExclusion.trip_id, PhotoExclusion.asset_id)).fetchall(), [(self.a, "kept")])
        self.assertEqual(self.row(both.id).trip_id, self.a)
        self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))

    def test_stopping_sharing_deletes_tripless_home_rows_outside_every_remaining_window(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        in_b = self.photo(None, INSIDE_B, match="home")
        only_a = self.photo(None, ONLY_A, match="home")
        photogrants.stop(self.c, self.jane, self.jid, self.a, 95.0)
        self.assertIsNotNone(self.row(in_b.id))
        self.assertIsNone(self.row(only_a.id))
        photogrants.stop(self.c, self.jane, self.jid, self.b, 96.0)
        self.assertIsNone(self.row(in_b.id))

    def test_leaving_a_trip_deletes_the_grant_and_re_places_the_rows(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        self.c.execute(insert(PhotoTripSync).values(source_id=self.janes, trip_id=self.b, window_start="s", window_end="e"))
        self.c.execute(insert(PhotoExclusion).values(person_id=self.jid, asset_id="kept", trip_id=self.b, created=1.0))
        photogrants.left(self.c, self.jid, self.b)
        self.assertIsNone(self.grant(self.jid, self.b))
        self.assertEqual(self.row(both.id).trip_id, self.a)
        self.assertEqual(self.c.execute(select(PhotoTripSync.trip_id)).fetchall(), [])
        self.assertEqual(self.c.execute(select(PhotoExclusion.asset_id)).scalar(), "kept")

    def test_deleting_a_trip_re_places_its_photos_before_the_rows_go(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        by_hand = self.photo(self.b, "2026-06-04T13:00", decided="owner")
        gone = self.photo(self.a, ONLY_A)
        torn = self.photo(None, match="ambiguous")
        self.assertTrue(trips.delete_trip(self.c, self.jane, self.b))
        self.assertEqual([(self.row(p.id).trip_id, self.row(p.id).decided_by) for p in (both, by_hand)], [(self.a, "auto"), (self.a, "auto")])
        self.assertEqual(self.row(torn.id).trip_id, self.a)
        self.assertIsNone(self.grant(self.jid, self.b))
        self.assertTrue(trips.delete_trip(self.c, self.jane, self.a))
        for p in (both, by_hand, gone, torn):
            self.assertIsNone(self.row(p.id), p.id)
        self.assertEqual(self.c.execute(select(PhotoGrant.trip_id)).fetchall(), [])

    def test_lock_takes_the_grant_rows_in_trip_order(self):
        self.share(self.jid, self.b)
        self.share(self.jid, self.a)
        self.assertEqual(list(photogrants.lock(self.c, self.jid, [self.b, self.a, 99999])), [self.a, self.b])
        self.assertEqual(photogrants.lock(self.c, self.sid, [self.a]), {})


class LapsedAccessTests(GrantCase):
    def lapse(self, sub):
        self.c.execute(update(User).where(User.sub == sub).values(last_seen=time.time() - 365 * 86400))

    def test_a_grant_and_the_standing_setting_end_when_their_member_can_no_longer_sign_in(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b, by="u-sam")
        self.share(self.sid, self.a, by="u-sam")
        both = self.photo(self.b)
        self.c.orm.add(PhotoSharingPrefs(person_id=self.jid, default_scope="trip", share_all=True, set_by="u-sam", share_all_since=5.0, steward_sub=None))
        self.c.orm.flush()
        self.steward(self.mia, "u-sam")
        groups = {**ALLOWED, "OIDC_ALLOWED_GROUPS": "household"}
        with mock.patch.dict(os.environ, groups):
            self.assertEqual(photogrants.end_lapsed(self.c, time.time()), 0)
            self.lapse("u-sam")
            self.assertEqual(photogrants.end_lapsed(self.c, time.time()), 4)
        self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))
        self.assertIsNone(self.grant(self.jid, self.b))
        self.assertIsNone(self.grant(self.sid, self.a))
        self.assertEqual(photogrants.prefs_of(self.c, self.jid), {"default_scope": "trip", "share_all": False})
        self.c.orm.expire_all()
        self.assertEqual((self.c.orm.get(PhotoSharingPrefs, self.jid).share_all_since, self.c.orm.get(PhotoSharingPrefs, self.mia).steward_sub), (None, None))
        self.assertEqual(self.row(both.id).trip_id, self.a)
        with mock.patch.dict(os.environ, groups):
            self.assertEqual(photogrants.end_lapsed(self.c, time.time()), 0)

    def test_the_hourly_sweep_ends_them_too(self):
        self.share(self.jid, self.a, by="u-sam")
        self.c.commit()
        with mock.patch.dict(os.environ, {**ALLOWED, "OIDC_ALLOWED_EMAILS": "u-jane@example.com"}):
            jobs.sweep_lapsed()
        self.assertIsNone(self.grant(self.jid, self.a))


class DecisionTests(GrantCase):
    def stopping_first(self, trip_id, stamp):
        real, stopped = photos.lock_grants, []

        def lock(conn, person, trip_ids):
            if not stopped:
                stopped.append(True)
                photogrants.stop(self.c, self.jane, self.jid, trip_id, stamp)
            return real(conn, person, trip_ids)
        return mock.patch.object(photos, "lock_grants", side_effect=lock)

    def test_a_decision_that_races_with_stop_sharing_sees_the_stop(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        with self.stopping_first(self.a, 70.0), self.assertRaises(trips.Invalid) as refused:
            photos.decide(self.c, self.jane, both.id, self.a, None)
        self.assertEqual(str(refused.exception), photos.SHARE_FIRST)
        self.assertEqual((self.row(both.id).trip_id, self.row(both.id).decided_by), (self.b, None))
        self.share(self.jid, self.a)
        with self.stopping_first(self.b, 71.0):
            self.assertEqual(photos.decide(self.c, self.jane, both.id, self.a, None)["trip_id"], self.a)
        self.assertEqual((self.row(both.id).trip_id, self.row(both.id).decided_by), (self.a, "owner"))
        photogrants.stop(self.c, self.jane, self.jid, self.b, 72.0)
        with self.stopping_first(self.a, 73.0):
            self.assertIsNone(photos.decide(self.c, self.jane, both.id, self.a, None))
        self.assertIsNone(self.row(both.id))

    def test_a_decision_locks_the_trip_a_concurrent_stop_moved_the_photo_to_before_deciding(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        c = trips.create_trip(self.c, self.jane, {"name": "Shortest", "people": [self.jid]})["id"]
        self.add(self.jane, {**HOTEL, "start_local": "2026-06-03T15:00", "end_local": "2026-06-04T10:00"}, c)
        self.share(self.jid, c)
        row = photo_row(self.janes, self.b, INSIDE_B)
        self.c.orm.add(row)
        self.c.orm.flush()
        with self.stopping_first(self.b, 74.0), mock.patch.object(photos, "lock_grants", wraps=photos.lock_grants) as lock:
            got = photos.decide(self.c, self.jane, row.id, self.a, None)
        self.assertEqual((got["trip_id"], self.row(row.id).decided_by), (self.a, "owner"))
        self.assertEqual([call.args[1:] for call in lock.call_args_list], [(self.jid, [self.a, self.b]), (self.jid, [self.b]), (self.jid, [self.a, self.b, c])])

    def test_a_hand_placement_is_written_to_every_row_of_the_same_asset(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        self.c.orm.add(PhotoSource(person_id=self.jid, owner_sub="u-jane", url="https://second.example", immich_user_id="u", api_key="enc:v1:x", status="ok", created=1.0))
        self.c.orm.flush()
        second = self.c.orm.scalars(select(PhotoSource.id).where(PhotoSource.url == "https://second.example")).one()
        first = self.photo(self.b, asset="twice-5h2k")
        twin = self.photo(self.b, source=second, asset="twice-5h2k", match="time")
        got = photos.decide(self.c, self.jane, first.id, self.a, None)
        self.assertEqual(got["trip_id"], self.a)
        for p in (first, twin):
            row = self.row(p.id)
            self.assertEqual((row.trip_id, row.decided_by, row.match, row.segment_id), (self.a, "owner", got["match"], got["segment_id"]), p.id)
        self.c.execute(update(PhotoSource).where(PhotoSource.id == self.janes).values(status="refused"))
        self.assertEqual(self.seen(self.jane, self.a), [twin.id])

    def test_a_decision_locks_the_grants_of_both_trips_in_order(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        both = self.photo(self.b)
        with mock.patch.object(photos, "lock_grants", wraps=photos.lock_grants) as lock:
            self.assertEqual(photos.decide(self.c, self.jane, both.id, self.a, None)["trip_id"], self.a)
        self.assertEqual(lock.call_args_list[0].args[1:], (self.jid, [self.a, self.b]))


class ClaimTests(GrantCase):
    def test_overlapping_grants_keep_the_more_restrictive_decision(self):
        self.c.orm.add(source_row(self.mia, "u-sam"))
        self.c.orm.flush()
        c = trips.create_trip(self.c, self.jane, {"name": "Third", "people": [self.jid, self.mia]}, confirmed=True)["id"]
        d = trips.create_trip(self.c, self.jane, {"name": "Fourth", "people": [self.jid, self.mia]}, confirmed=True)["id"]
        trips.edit_trip(self.c, self.jane, self.a, {"people": [self.jid, self.sid, self.mia]}, confirmed=True)
        trips.edit_trip(self.c, self.jane, self.b, {"people": [self.jid, self.mia]}, confirmed=True)
        self.share(self.jid, self.a, "trip")
        self.share(self.mia, self.a, "only_me", by="u-sam")
        self.share(self.jid, self.b, "trip")
        self.share(self.mia, self.b, "trip", revoked=9.0, by="u-sam")
        self.share(self.jid, c, "only_me")
        self.share(self.mia, c, "trip", by="u-sam")
        self.share(self.jid, d, "trip", revoked=8.0)
        self.share(self.mia, d, "trip", by="u-sam")
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertEqual(self.grant(self.jid, self.a), ("only_me", None, "u-jane"))
        self.assertEqual(self.grant(self.jid, self.b), ("trip", 9.0, "u-jane"))
        self.assertEqual(self.grant(self.jid, c), ("only_me", None, "u-jane"))
        self.assertEqual(self.grant(self.jid, d), ("trip", 8.0, "u-jane"))
        self.assertEqual(self.c.execute(select(PhotoGrant.person_id).distinct()).fetchall(), [(self.jid,)])

    def test_two_revocations_keep_the_later_one_so_the_standing_setting_cannot_reopen_it(self):
        trips.edit_trip(self.c, self.jane, self.b, {"people": [self.jid, self.mia]}, confirmed=True)
        self.share(self.jid, self.b, "trip", revoked=5.0)
        self.share(self.mia, self.b, "trip", revoked=20.0, by="u-sam")
        self.c.orm.add(PhotoSharingPrefs(person_id=self.jid, default_scope="trip", share_all=True, set_by="u-jane", share_all_since=10.0, steward_sub=None))
        self.c.orm.flush()
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertEqual(self.grant(self.jid, self.b), ("trip", 20.0, "u-jane"))
        self.assertEqual(photogrants.reconcile(self.c, self.b, 98.0), 0)
        self.assertEqual(self.grant(self.jid, self.b), ("trip", 20.0, "u-jane"))

    def test_a_guest_library_of_the_same_immich_user_merges_into_the_members_and_keeps_hand_placements(self):
        self.share(self.jid, self.a)
        self.share(self.jid, self.b)
        trips.edit_trip(self.c, self.jane, self.b, {"people": [self.jid, self.mia]}, confirmed=True)
        self.share(self.mia, self.b, by="u-sam")
        self.c.orm.add_all([source_row(self.mia, "u-sam"), PhotoSource(person_id=self.mia, owner_sub="u-sam", url="https://immich-canary-8h2k.example:2283", immich_user_id="other-user",
                                                                      api_key="enc:v1:x", status="ok", created=1.0)])
        self.c.orm.flush()
        same, other = [s.id for s in self.c.orm.scalars(select(PhotoSource).where(PhotoSource.person_id == self.mia).order_by(PhotoSource.id)).all()]
        mine_a = self.photo(self.b, asset="shared-asset", match="time")
        mine_b = self.photo(self.b, asset="only-mine")
        theirs_a = self.photo(self.b, source=same, asset="shared-asset", decided="owner")
        theirs_c = self.photo(self.b, source=same, asset="only-theirs")
        elsewhere = self.photo(self.b, source=other, asset="other-user-asset")
        self.c.execute(insert(PhotoTripSync), [{"source_id": s, "trip_id": self.b, "window_start": "s", "window_end": "e"} for s in (self.janes, same)])
        self.c.execute(insert(PhotoTripSync).values(source_id=same, trip_id=self.a, window_start="s", window_end="e"))
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertIsNone(self.c.orm.get(PhotoSource, same))
        self.assertEqual((self.c.orm.get(PhotoSource, other).person_id, self.c.orm.get(PhotoSource, other).owner_sub), (self.jid, "u-jane"))
        self.assertIsNone(self.row(theirs_a.id))
        kept = self.row(mine_a.id)
        self.assertEqual((kept.source_id, kept.decided_by, kept.match), (self.janes, "owner", theirs_a.match))
        self.assertEqual((self.row(mine_b.id).source_id, self.row(theirs_c.id).source_id, self.row(elsewhere.id).source_id), (self.janes, self.janes, other))
        self.assertEqual(sorted(self.c.execute(select(PhotoTripSync.source_id, PhotoTripSync.trip_id)).fetchall()), [(self.janes, self.a), (self.janes, self.b)])

    def test_claiming_reconciles_trips_the_member_can_now_see_as_booker_or_recipient(self):
        self.c.orm.add(PhotoSharingPrefs(person_id=self.joan, default_scope="trip", share_all=True, set_by="u-jane", share_all_since=5.0, steward_sub="u-jane"))
        self.c.orm.flush()
        theirs = self.add(Viewer(self.mia), {**OUT, "start_local": "2027-03-01T19:00", "end_local": "2027-03-02T07:10"}, None, self.on(self.joan))["trip_id"]
        self.assertIsNone(self.grant(self.joan, theirs))
        self.assertIsNone(visibility.visible_trip(self.c, self.jane, theirs))
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertIsNotNone(visibility.visible_trip(self.c, self.jane, theirs))
        self.assertEqual(self.grant(self.joan, theirs), ("trip", None, "u-jane"))

    def test_claiming_reconciles_the_trips_the_member_is_now_on(self):
        photogrants.set_prefs(self.c, self.jane, self.jid, "trip", True, 80.0)
        theirs = self.add(self.sam, {**OUT, "start_local": "2027-03-01T19:00", "end_local": "2027-03-02T07:10"}, None, self.on(self.sid, self.mia))["trip_id"]
        self.assertIsNone(self.grant(self.jid, theirs))
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertEqual(self.grant(self.jid, theirs), ("trip", None, "u-jane"))

    def test_a_claimed_guests_sharing_and_libraries_pass_to_the_member(self):
        trips.edit_trip(self.c, self.jane, self.b, {"people": [self.jid, self.mia]}, confirmed=True)
        self.c.orm.add_all([source_row(self.mia, "u-sam"), PhotoSource(person_id=self.mia, owner_sub="u-sam", url="https://other.example", immich_user_id="u2",
                                                                      api_key="enc:v1:x", status="ok", created=1.0),
                            PhotoSource(person_id=self.jid, owner_sub="u-jane", url="https://other.example", immich_user_id="u3", api_key="enc:v1:y", status="ok", created=1.0)])
        self.c.orm.flush()
        self.share(self.jid, self.a, "only_me")
        self.share(self.mia, self.a, "trip", by="u-sam")
        self.share(self.mia, self.b, "trip", by="u-sam")
        self.c.orm.add_all([PhotoExclusion(person_id=self.mia, asset_id="x", trip_id=self.b, created=2.0), PhotoExclusion(person_id=self.jid, asset_id="x", trip_id=self.b, created=1.0),
                            PhotoExclusion(person_id=self.mia, asset_id="y", trip_id=self.a, created=3.0),
                            PhotoSharingPrefs(person_id=self.mia, default_scope="trip", share_all=True, set_by="u-sam", share_all_since=4.0, steward_sub="u-sam")])
        self.c.orm.flush()
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertEqual(self.grant(self.jid, self.a), ("only_me", None, "u-jane"))
        self.assertEqual(self.grant(self.jid, self.b), ("trip", None, "u-jane"))
        self.assertEqual(self.c.execute(select(PhotoGrant.person_id).distinct()).fetchall(), [(self.jid,)])
        self.assertEqual(sorted(self.c.execute(select(PhotoExclusion.person_id, PhotoExclusion.asset_id, PhotoExclusion.trip_id, PhotoExclusion.created)).fetchall()),
                         [(self.jid, "x", self.b, 1.0), (self.jid, "y", self.a, 3.0)])
        prefs = self.c.orm.get(PhotoSharingPrefs, self.jid)
        self.assertEqual((prefs.default_scope, prefs.share_all, prefs.set_by, prefs.share_all_since, prefs.steward_sub), ("trip", True, "u-jane", 4.0, None))
        self.assertEqual(sorted(self.c.execute(select(PhotoSource.person_id, PhotoSource.url, PhotoSource.immich_user_id, PhotoSource.owner_sub)).fetchall()),
                         sorted([(self.jid, "https://immich-canary-8h2k.example:2283", "immich-user-1", "u-jane"), (self.jid, "https://other.example", "u2", "u-jane"),
                                 (self.jid, "https://other.example", "u3", "u-jane")]))
        self.assertIsNone(self.c.orm.get(Person, self.mia))

    def test_a_member_with_preferences_keeps_them(self):
        self.c.orm.add_all([PhotoSharingPrefs(person_id=self.jid, default_scope="only_me", share_all=False, set_by=None, share_all_since=None, steward_sub=None),
                            PhotoSharingPrefs(person_id=self.mia, default_scope="trip", share_all=True, set_by="u-sam", share_all_since=4.0, steward_sub="u-sam")])
        self.c.orm.flush()
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertEqual(photogrants.prefs_of(self.c, self.jid), {"default_scope": "only_me", "share_all": False})
        self.assertEqual(self.c.execute(select(PhotoSharingPrefs.person_id)).fetchall(), [(self.jid,)])


if __name__ == "__main__":
    unittest.main()
