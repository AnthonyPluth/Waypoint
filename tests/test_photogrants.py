import os
import time
import unittest
from unittest import mock

from sqlalchemy import insert, select, update

from tests.test_photos_api import SOHO, grant_row, photo_row, source_row
from tests.test_trips import HOTEL, OUT, Household
from waypoint.domain import people, photogrants, photos, trips
from waypoint.domain.visibility import Viewer
from waypoint.server import jobs
from waypoint.storage.models import Person, Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, PhotoTripSync, TripPerson, User

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
        self.c.orm.add(source_row(self.mia, "u-jane"))
        self.c.orm.flush()
        photogrants.set_prefs(self.c, self.jane, self.mia, "only_me", True, 53.0)
        hidden = self.add(self.sam, {**OUT, "start_local": "2027-05-01T19:00", "end_local": "2027-05-02T07:10"}, None, self.on(self.sid, self.mia))["trip_id"]
        self.assertFalse(photogrants.joined(self.c, self.mia, hidden, 54.0))
        self.assertIsNone(self.grant(self.mia, hidden))
        self.assertEqual(photogrants.reconcile(self.c, hidden, 55.0), 0)
        self.c.execute(insert(TripPerson).values(trip_id=hidden, person_id=self.jid))
        self.assertEqual(photogrants.reconcile(self.c, hidden, 56.0), 2)
        self.assertEqual(self.grant(self.mia, hidden), ("only_me", None, "u-jane"))
        self.assertEqual(self.grant(self.jid, hidden), ("trip", None, "u-jane"))
        self.assertEqual(photogrants.reconcile(self.c, hidden, 57.0), 0)


class TripChangeTests(GrantCase):
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
        self.c.orm.add(PhotoSharingPrefs(person_id=self.jid, default_scope="trip", share_all=True, set_by="u-sam"))
        self.c.orm.flush()
        groups = {**ALLOWED, "OIDC_ALLOWED_GROUPS": "household"}
        with mock.patch.dict(os.environ, groups):
            self.assertEqual(photogrants.end_lapsed(self.c, time.time()), 0)
            self.lapse("u-sam")
            self.assertEqual(photogrants.end_lapsed(self.c, time.time()), 3)
        self.assertEqual(self.grant(self.jid, self.a), ("trip", None, "u-jane"))
        self.assertIsNotNone(self.grant(self.jid, self.b)[1])
        self.assertIsNotNone(self.grant(self.sid, self.a)[1])
        self.assertEqual(photogrants.prefs_of(self.c, self.jid), {"default_scope": "trip", "share_all": False})
        self.assertEqual(self.row(both.id).trip_id, self.a)
        with mock.patch.dict(os.environ, groups):
            self.assertEqual(photogrants.end_lapsed(self.c, time.time()), 0)

    def test_the_hourly_sweep_ends_them_too(self):
        self.share(self.jid, self.a, by="u-sam")
        self.c.commit()
        with mock.patch.dict(os.environ, {**ALLOWED, "OIDC_ALLOWED_EMAILS": "u-jane@example.com"}):
            jobs.sweep_lapsed()
        self.assertIsNotNone(self.grant(self.jid, self.a)[1])


class ClaimTests(GrantCase):
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
                            PhotoSharingPrefs(person_id=self.mia, default_scope="trip", share_all=True, set_by="u-sam")])
        self.c.orm.flush()
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertEqual(self.grant(self.jid, self.a), ("only_me", None, "u-jane"))
        self.assertEqual(self.grant(self.jid, self.b), ("trip", None, "u-jane"))
        self.assertEqual(self.c.execute(select(PhotoGrant.person_id).distinct()).fetchall(), [(self.jid,)])
        self.assertEqual(sorted(self.c.execute(select(PhotoExclusion.person_id, PhotoExclusion.asset_id, PhotoExclusion.trip_id, PhotoExclusion.created)).fetchall()),
                         [(self.jid, "x", self.b, 1.0), (self.jid, "y", self.a, 3.0)])
        prefs = self.c.orm.get(PhotoSharingPrefs, self.jid)
        self.assertEqual((prefs.default_scope, prefs.share_all, prefs.set_by), ("trip", True, "u-jane"))
        self.assertEqual(sorted(self.c.execute(select(PhotoSource.person_id, PhotoSource.url, PhotoSource.owner_sub)).fetchall()),
                         sorted([(self.jid, "https://immich-canary-8h2k.example:2283", "u-jane"), (self.jid, "https://other.example", "u-jane")]))
        self.assertIsNone(self.c.orm.get(Person, self.mia))

    def test_a_member_with_preferences_keeps_them(self):
        self.c.orm.add_all([PhotoSharingPrefs(person_id=self.jid, default_scope="only_me", share_all=False, set_by=None),
                            PhotoSharingPrefs(person_id=self.mia, default_scope="trip", share_all=True, set_by="u-sam")])
        self.c.orm.flush()
        people.claim_guest(self.c, self.jid, self.mia, "2026-10-05")
        self.assertEqual(photogrants.prefs_of(self.c, self.jid), {"default_scope": "only_me", "share_all": False})
        self.assertEqual(self.c.execute(select(PhotoSharingPrefs.person_id)).fetchall(), [(self.jid,)])


if __name__ == "__main__":
    unittest.main()
