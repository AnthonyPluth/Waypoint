import json
import unittest

from sqlalchemy import delete, insert, select

from tests.privacy import no_leaks
from tests.shared import ServerCase
from tests.test_photos_api import ASSET, KEY, SOHO, URL, grant_row, photo_row, source_row, stored
from tests.test_trips import HOTEL, OUT, RouteCase
from waypoint.server import mcp_access, mcp_http
from waypoint.storage import db
from waypoint.storage.models import PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoTripSync, SegmentRecipient, TripPerson

STATE, COUNTRY = "Canaryshire-7q2x", "Canaryland-3k9v"
EMPTY = {"photos": [], "clusters": [], "counts": {"total": 0, "located": 0, "inferred": 0, "far": 0}, "people": []}
NO_TRIP, NO_PHOTO = {"error": "No such trip"}, {"error": "No such photo"}
PHOTO_ROUTES = (("GET", "/api/trips/{id}/photos"), ("GET", "/api/photos/review"), ("POST", "/api/photos/{id}"), ("GET", "/api/trips/{id}/photo-sharing"),
                ("POST", "/api/trips/{id}/photo-sharing"), ("DELETE", "/api/trips/{id}/photo-sharing"), ("POST", "/api/trips/{id}/photo-exclusions"),
                ("DELETE", "/api/trips/{id}/photo-exclusions/{id}"), ("GET", "/api/photo-grants"), ("POST", "/api/photo-sharing-prefs/{id}"))


class AccessCase(RouteCase):
    def setUp(self):
        super().setUp()
        self.flight = self.book("ana", travelers=[{"person_id": self.person["ana"]}, {"person_id": self.person["ben"]}])
        self.trip = self.flight["trip_id"]
        self.stay = self.book("ana", HOTEL, trip_id=self.trip)
        self.sources = {who: self.keep(source_row(self.person[who], f"sub-{who}")) for who in ("ana", "ben")}

    def keep(self, row):
        with db.session() as conn:
            conn.orm.add(row)
            conn.orm.flush()
            return getattr(row, "id", None)

    def share(self, who, trip=None, scope="trip", revoked=None):
        with db.session() as conn:
            conn.execute(delete(PhotoGrant).where(PhotoGrant.person_id == self.person[who], PhotoGrant.trip_id == (trip or self.trip)))
        self.keep(grant_row(self.person[who], trip or self.trip, scope, revoked, f"sub-{who}"))

    def photo(self, who, trip=None, local="2026-06-02T10:00", placed=True, **fields):
        row = photo_row(self.sources[who], trip or self.trip, local, where=SOHO, segment_id=self.stay["id"] if trip in (None, self.trip) else None, **fields)
        if placed:
            row.state, row.country = STATE, COUNTRY
        return self.keep(row)

    def listing(self, who, trip=None):
        return self.ok(who, "GET", f"/api/trips/{trip or self.trip}/photos")

    def summary(self, who, trip=None):
        return self.ok(who, "GET", f"/api/trips/{trip or self.trip}/summary")

    def sharing(self, who, trip=None):
        return self.ok(who, "GET", f"/api/trips/{trip or self.trip}/photo-sharing")

    def seen_by(self, who, trip=None):
        got = self.listing(who, trip)
        return [p["id"] for p in got["photos"]]

    def assertNoPhotos(self, who, trip=None):
        self.assertEqual(self.listing(who, trip), EMPTY, who)
        got = self.summary(who, trip)
        self.assertEqual(got["photos"], {"total": 0, "inferred": 0}, who)
        self.assertNotIn(COUNTRY, json.dumps(got), who)


class ScopeTests(AccessCase):
    def test_without_a_grant_nobody_sees_the_photo_not_even_its_person(self):
        self.photo("ben")
        for who in ("ana", "ben"):
            self.assertNoPhotos(who)
        self.assertEqual(self.sharing("ben")["state"], "none")

    def test_only_me_shows_the_photo_to_its_person_alone_and_trip_to_everyone_who_can_see_the_trip(self):
        self.share("ben", scope="only_me")
        mine = self.photo("ben")
        self.assertEqual(self.seen_by("ben"), [mine])
        self.assertEqual(self.listing("ben")["people"], [{"person_id": self.person["ben"], "count": 1}])
        self.assertEqual(self.summary("ben")["photos"], {"total": 1, "inferred": 0})
        self.assertIn(COUNTRY, self.summary("ben")["countries"])
        self.assertNoPhotos("ana")
        self.assertEqual(self.sharing("ben"), {"state": "shared", "scope": "only_me", "count": 1, "removed_count": 0, "removed": []})
        self.assertEqual(self.sharing("ana"), {"state": "none", "scope": None, "count": 0, "removed_count": 0, "removed": []})
        self.share("ben", scope="trip")
        self.assertEqual(self.seen_by("ana"), [mine])
        self.assertEqual(self.listing("ana")["clusters"][0]["count"], 1)
        self.assertIn(COUNTRY, self.summary("ana")["countries"])
        self.assertEqual(self.call("cy", "GET", f"/api/trips/{self.trip}/photos"), (404, NO_TRIP))
        self.assertEqual(self.call("cy", "GET", f"/api/trips/{self.trip}/summary"), (404, NO_TRIP))
        self.assertEqual(self.call("cy", "GET", f"/api/trips/{self.trip}/photo-sharing"), (404, NO_TRIP))

    def test_a_revoked_grant_shows_nothing_and_reads_as_declined_to_its_person_only(self):
        self.share("ben", revoked=5.0)
        self.photo("ben")
        for who in ("ana", "ben"):
            self.assertNoPhotos(who)
        self.assertEqual(self.sharing("ben")["state"], "declined")
        self.assertEqual(self.sharing("ana")["state"], "none")

    def test_the_trips_booker_who_is_not_on_it_has_no_special_access(self):
        booked = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        trip = booked["trip_id"]
        self.share("ben", trip, "only_me")
        mine = self.keep(photo_row(self.sources["ben"], trip, "2026-09-02T09:00", where=SOHO))
        self.assertEqual(self.seen_by("ben", trip), [mine])
        self.assertNoPhotos("ana", trip)
        self.assertEqual(self.sharing("ana", trip)["state"], "none")
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{trip}/photo-sharing", {"scope": "trip"}), (404, NO_TRIP))
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{trip}/photo-sharing", {"scope": "only_me", "person_id": self.person["ben"]}), (404, NO_TRIP))
        self.assertEqual(self.call("ana", "DELETE", f"/api/trips/{trip}/photo-sharing?person_id={self.person['ben']}"), (404, NO_TRIP))
        self.share("ben", trip, "trip")
        self.assertNoPhotos("ana", trip)
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{trip}/photo-exclusions", {"photo_ids": [mine]}), (404, NO_PHOTO))
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": trip}), (404, NO_PHOTO))
        self.assertEqual(self.seen_by("ben", trip), [mine])
        self.assertEqual(self.ok("ana", "GET", "/api/photo-grants")["people"], [{"person_id": self.person["ana"], "prefs": {"default_scope": "only_me", "share_all": False}, "trips": []}])

    def test_trip_scope_reaches_the_trips_people_alone_not_a_confirmation_recipient(self):
        self.share("ben")
        mine = self.photo("ben")
        self.assertEqual(self.seen_by("ana"), [mine])
        with db.session() as conn:
            conn.execute(delete(TripPerson).where(TripPerson.person_id == self.person["ana"]))
            conn.execute(insert(SegmentRecipient).values(segment_id=self.flight["id"], person_id=self.person["ana"]))
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{self.trip}")["id"], self.trip)
        self.assertNoPhotos("ana")
        self.assertEqual(self.seen_by("ben"), [mine])

    def test_a_grant_for_someone_no_longer_on_the_trip_shows_nothing(self):
        self.share("ben")
        self.photo("ben")
        with db.session() as conn:
            conn.execute(delete(TripPerson).where(TripPerson.person_id == self.person["ben"]))
        self.assertNoPhotos("ana")

    def test_a_person_cannot_share_on_a_trip_they_are_not_on(self):
        booked = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{booked['trip_id']}/photo-sharing", {"scope": "only_me"}), (404, NO_TRIP))
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{booked['trip_id']}/photo-sharing", {"declined": True}), (404, NO_TRIP))
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{booked['trip_id']}/photo-sharing", {"scope": "only_me"})[0], 200)

    def test_ambiguous_home_and_unmatched_rows_are_for_nobody_on_a_trip(self):
        self.share("ana")
        for match in ("ambiguous", "home", "none"):
            self.photo("ana", match=match)
        for who in ("ana", "ben"):
            self.assertNoPhotos(who)


class RemovalTests(AccessCase):
    def setUp(self):
        super().setUp()
        self.share("ana")
        self.share("ben")
        self.mine = self.photo("ben")
        self.hers = self.photo("ana", local="2026-06-02T11:00")

    def test_remove_from_this_trip_takes_the_photo_from_everyone_at_once_and_only_its_person_lists_it(self):
        got = self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [self.mine]})
        self.assertEqual((got["state"], got["count"], got["removed_count"], [p["id"] for p in got["removed"]]), ("shared", 0, 1, [self.mine]))
        for who in ("ana", "ben"):
            self.assertEqual(self.seen_by(who), [self.hers], who)
            self.assertEqual(self.summary(who)["photos"], {"total": 1, "inferred": 0})
            self.assertEqual(self.listing(who)["people"], [{"person_id": self.person["ana"], "count": 1}])
        self.assertEqual([p["id"] for p in self.sharing("ben")["removed"]], [self.mine])
        self.assertEqual(self.sharing("ana")["removed"], [])
        self.assertEqual(stored(self.mine)["trip_id"], self.trip)
        self.assertEqual(self.ok("ben", "GET", "/api/photos/review")["photos"], [])
        self.assertEqual(self.call("ben", "POST", f"/api/photos/{self.mine}", {"trip_id": self.trip}), (404, NO_PHOTO))

    def test_put_back_returns_the_photo_on_the_next_request(self):
        self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [self.mine]})
        self.assertEqual(self.call("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{self.mine}"), (404, NO_PHOTO))
        self.assertEqual(self.call("cy", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{self.mine}"), (404, NO_TRIP))
        got = self.ok("ben", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{self.mine}")
        self.assertEqual((got["count"], got["removed_count"], got["removed"]), (1, 0, []))
        for who in ("ana", "ben"):
            self.assertEqual(self.seen_by(who), [self.mine, self.hers], who)
        self.assertEqual(self.call("ben", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{self.mine}"), (404, NO_PHOTO))

    def test_removing_several_is_all_or_none_and_only_the_persons_own(self):
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [self.mine, self.hers]}), (404, NO_PHOTO))
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [self.mine, 99999]}), (404, NO_PHOTO))
        self.assertEqual(self.seen_by("ana"), [self.mine, self.hers])
        with db.session() as conn:
            self.assertEqual(conn.execute(select(PhotoExclusion.asset_id)).fetchall(), [])
        for bad in ([], [0], ["1"], [True], "1", None, [1.5], list(range(1, 502))):
            self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": bad}), (400, {"error": 'Send "photo_ids" as a list of whole numbers'}), bad)
        self.assertEqual(self.call("cy", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [self.mine]}), (404, NO_TRIP))
        other = self.photo("ben", local="2026-06-03T10:00")
        got = self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [self.mine, other, self.mine]})
        self.assertEqual(got["removed_count"], 2)
        self.assertEqual(self.seen_by("ana"), [self.hers])

    def test_stop_sharing_takes_every_photo_back_at_once_and_keeps_removals_for_later(self):
        other = self.photo("ben", local="2026-06-03T10:00")
        self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [other]})
        with db.session() as conn:
            conn.execute(insert(PhotoTripSync).values(source_id=self.sources["ben"], trip_id=self.trip, window_start="a", window_end="b"))
        self.assertEqual(self.call("ana", "DELETE", f"/api/trips/{self.trip}/photo-sharing?person_id={self.person['ben']}"), (404, NO_TRIP))
        got = self.ok("ben", "DELETE", f"/api/trips/{self.trip}/photo-sharing")
        self.assertEqual((got["state"], got["scope"], got["count"], got["removed_count"], got["removed"]), ("declined", None, 0, 0, []))
        for who in ("ana", "ben"):
            self.assertEqual(self.seen_by(who), [self.hers], who)
            self.assertEqual(self.listing(who)["people"], [{"person_id": self.person["ana"], "count": 1}], who)
        self.assertEqual((stored(self.mine), stored(other)), (None, None))
        with db.session() as conn:
            self.assertEqual(conn.execute(select(PhotoTripSync.trip_id)).fetchall(), [])
            kept = conn.execute(select(PhotoExclusion.person_id, PhotoExclusion.trip_id)).fetchall()
        self.assertEqual(kept, [(self.person["ben"], self.trip)])
        self.assertEqual(self.ok("ben", "GET", "/api/photo-grants")["people"][0]["trips"][0]["state"], "declined")
        again = self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip"})
        self.assertEqual((again["state"], again["scope"], again["count"]), ("shared", "trip", 0))
        with db.session() as conn:
            asset = conn.execute(select(PhotoExclusion.asset_id)).scalar()
        back = self.keep(photo_row(self.sources["ben"], self.trip, "2026-06-03T10:00", where=SOHO, asset=asset))
        self.assertEqual(self.seen_by("ana"), [self.hers])
        self.assertEqual([p["id"] for p in self.sharing("ben")["removed"]], [back])

    def test_switching_to_only_me_hides_the_photos_from_others_on_the_next_request_and_back_shows_them(self):
        got = self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "only_me"})
        self.assertEqual((got["state"], got["scope"], got["count"]), ("shared", "only_me", 1))
        self.assertEqual(self.seen_by("ana"), [self.hers])
        self.assertEqual(self.seen_by("ben"), [self.mine, self.hers])
        self.assertEqual(stored(self.mine)["trip_id"], self.trip)
        self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip"})
        self.assertEqual(self.seen_by("ana"), [self.mine, self.hers])
        for bad in ({"scope": "everyone"}, {"scope": 1}, {}, {"declined": "yes"}, {"person_id": "x", "scope": "trip"}, {"person_id": True, "scope": "trip"}):
            self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", bad)[0], 400, bad)
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": self.person["ana"], "scope": "trip"}), (404, NO_TRIP))
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": 99999, "scope": "trip"}), (404, NO_TRIP))

    def test_not_now_records_a_declined_row_the_person_can_share_again(self):
        later = self.book("ben", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        trip = later["trip_id"]
        got = self.ok("ben", "POST", f"/api/trips/{trip}/photo-sharing", {"declined": True})
        self.assertEqual((got["state"], got["scope"]), ("declined", None))
        self.assertEqual(self.ok("ben", "POST", f"/api/trips/{trip}/photo-sharing", {"scope": "trip"})["state"], "shared")


class LookAndCandidateTests(AccessCase):
    def test_needs_a_look_is_for_the_photos_person_with_granted_trips_as_candidates(self):
        self.share("ana")
        far = self.photo("ana", match="far", distance=900.0)
        torn = self.keep(photo_row(self.sources["ana"], None, "2026-06-04T12:00", where=SOHO, match="ambiguous"))
        week = self.ok("ana", "POST", "/api/trips", {"name": "Week", "people": [self.person["ana"]]})["id"]
        self.book("ana", {**HOTEL, "start_local": "2026-06-03T15:00", "end_local": "2026-06-05T10:00"}, trip_id=week)
        got = self.ok("ana", "GET", "/api/photos/review")
        self.assertEqual([(p["id"], [c["id"] for c in p["candidates"]]) for p in got["photos"]], [(far, [self.trip]), (torn, [self.trip])])
        self.share("ana", week)
        got = self.ok("ana", "GET", "/api/photos/review")
        self.assertEqual([c["id"] for c in got["photos"][1]["candidates"]], [self.trip, week])
        self.assertEqual(self.ok("ben", "GET", "/api/photos/review")["photos"], [])
        self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [far]})
        self.assertEqual([p["id"] for p in self.ok("ana", "GET", "/api/photos/review")["photos"]], [torn])
        self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-sharing")
        self.assertEqual(self.ok("ana", "GET", "/api/photos/review")["photos"], [])
        self.assertEqual([(p["id"], p["match"]) for p in self.listing("ana", week)["photos"]], [(torn, "time")])
        self.assertEqual(stored(far), None)

    def test_a_photo_moves_only_to_a_trip_its_person_shared_and_was_not_removed_from(self):
        self.share("ana")
        later = self.book("ana", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])
        mine = self.photo("ana", local="2027-01-02T09:00")
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": later["trip_id"]}), (400, {"error": "Share your photos on that trip first"}))
        self.share("ana", later["trip_id"])
        with db.session() as conn:
            conn.execute(insert(PhotoExclusion).values(person_id=self.person["ana"], asset_id=stored_asset(mine), trip_id=later["trip_id"], created=1.0))
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": later["trip_id"]}), (400, {"error": "Put the photo back on that trip first"}))
        self.ok("ana", "DELETE", f"/api/trips/{later['trip_id']}/photo-exclusions/{mine}")
        self.assertEqual(self.ok("ana", "POST", f"/api/photos/{mine}", {"trip_id": later["trip_id"]})["trip_id"], later["trip_id"])


class StewardTests(AccessCase):
    def setUp(self):
        super().setUp()
        self.kid = self.ok("ana", "POST", "/api/people", {"display_name": "Kid Example"})["id"]
        self.ok("ana", "POST", f"/api/trips/{self.trip}", {"people": [self.person["ana"], self.person["ben"], self.kid], "confirm": True})
        self.sources["kid"] = self.keep(source_row(self.kid, "sub-ana"))
        self.keep(PhotoSharingPrefs(person_id=self.kid, default_scope="only_me", share_all=False, set_by=None, share_all_since=None, steward_sub="sub-ana"))

    def kids(self, trip=None, **fields):
        return self.keep(photo_row(self.sources["kid"], trip or self.trip, "2026-06-02T12:00", where=SOHO, **fields))

    def test_the_steward_acts_for_a_person_without_a_sign_in_and_nobody_else_does(self):
        got = self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": self.kid, "scope": "only_me"})
        self.assertEqual((got["state"], got["scope"]), ("shared", "only_me"))
        theirs = self.kids()
        self.assertEqual(self.seen_by("ana"), [theirs])
        self.assertEqual(self.seen_by("ben"), [])
        self.assertEqual(self.sharing("ana")["state"], "none")
        self.assertEqual([p["person_id"] for p in self.ok("ana", "GET", "/api/photo-grants")["people"]], [self.person["ana"], self.kid])
        self.assertEqual([p["person_id"] for p in self.ok("ben", "GET", "/api/photo-grants")["people"]], [self.person["ben"]])
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": self.kid, "scope": "trip"}), (404, NO_TRIP))
        self.assertEqual(self.call("ben", "POST", f"/api/photo-sharing-prefs/{self.kid}", {"share_all": True}), (404, NO_TRIP))
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [theirs]}), (404, NO_PHOTO))
        got = self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [theirs]})
        self.assertEqual((got["removed_count"], [p["id"] for p in got["removed"]]), (1, [theirs]))
        self.assertEqual(self.sharing("ana")["removed"], [])
        self.assertEqual(self.ok("ana", "GET", "/api/photo-grants")["people"][1]["trips"][0]["removed_count"], 1)
        self.assertEqual(self.seen_by("ana"), [])
        with db.session() as conn:
            self.assertEqual(conn.execute(select(PhotoExclusion.person_id)).scalar(), self.kid)
        got = self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": self.kid, "scope": "trip"})
        self.assertEqual(got["count"], 0)
        self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{theirs}")
        self.assertEqual(self.seen_by("ben"), [theirs])
        self.assertEqual(self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-sharing?person_id={self.kid}")["state"], "declined")
        self.assertEqual(self.seen_by("ben"), [])

    def test_a_steward_reads_the_childs_sharing_state_and_removed_list_and_nobody_else_does(self):
        self.keep(grant_row(self.kid, self.trip, "only_me", by="sub-ana"))
        theirs = self.kids()
        self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [theirs]})
        got = self.ok("ana", "GET", f"/api/trips/{self.trip}/photo-sharing?person_id={self.kid}")
        self.assertEqual((got["state"], got["scope"], [p["id"] for p in got["removed"]]), ("shared", "only_me", [theirs]))
        self.assertEqual(self.sharing("ana")["state"], "none")
        self.assertEqual(self.call("ben", "GET", f"/api/trips/{self.trip}/photo-sharing?person_id={self.kid}"), (404, NO_TRIP))
        self.assertEqual(self.call("ana", "GET", f"/api/trips/{self.trip}/photo-sharing?person_id={self.person['ben']}"), (404, NO_TRIP))
        self.assertEqual(self.call("ana", "GET", f"/api/trips/{self.trip}/photo-sharing?person_id=x")[0], 400)

    def test_a_library_alone_makes_nobody_a_steward(self):
        with db.session() as conn:
            conn.execute(delete(PhotoSharingPrefs).where(PhotoSharingPrefs.person_id == self.kid))
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": self.kid, "scope": "only_me"}), (404, NO_TRIP))
        self.assertEqual([p["person_id"] for p in self.ok("ana", "GET", "/api/photo-grants")["people"]], [self.person["ana"]])
        self.keep(grant_row(self.kid, self.trip, "only_me", by="sub-ana"))
        self.kids()
        self.assertEqual(self.seen_by("ana"), [])

    def test_needs_a_look_shows_a_steward_nothing_whose_only_trips_they_cannot_see(self):
        theirs = self.book("ben", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.kid}])
        self.keep(grant_row(self.kid, theirs["trip_id"], "trip", by="sub-ben"))
        torn = self.keep(photo_row(self.sources["kid"], None, "2027-01-02T09:00", where=SOHO, match="ambiguous"))
        self.assertEqual(self.ok("ana", "GET", "/api/photos/review")["photos"], [])
        self.assertEqual(self.ok("ben", "GET", "/api/photos/review")["photos"], [])
        for body in ({"excluded": True}, {"trip_id": theirs["trip_id"]}, {"trip_id": self.trip}):
            self.assertEqual(self.call("ana", "POST", f"/api/photos/{torn}", body), (404, NO_PHOTO), body)
        self.assertEqual(stored(torn)["trip_id"], None)
        with db.session() as conn:
            self.assertEqual(conn.execute(select(PhotoExclusion.asset_id)).fetchall(), [])
        self.keep(grant_row(self.kid, self.trip, "trip", by="sub-ana"))
        self.book("ana", {**HOTEL, "start_local": "2027-01-02T08:00", "end_local": "2027-01-03T10:00"}, trip_id=self.trip)
        got = self.ok("ana", "GET", "/api/photos/review")
        self.assertEqual([(p["id"], [c["id"] for c in p["candidates"]]) for p in got["photos"]], [(torn, [self.trip])])
        self.ok("ana", "POST", f"/api/photos/{torn}", {"excluded": True})
        with db.session() as conn:
            self.assertEqual(conn.execute(select(PhotoExclusion.trip_id)).fetchall(), [(self.trip,)])

    def test_a_steward_cannot_share_on_a_trip_they_cannot_see(self):
        theirs = self.book("ben", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.kid}])
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{theirs['trip_id']}/photo-sharing", {"person_id": self.kid, "scope": "trip"}), (404, NO_TRIP))
        self.assertEqual(self.call("ana", "GET", f"/api/trips/{theirs['trip_id']}/photo-sharing"), (404, NO_TRIP))
        self.share("ana", scope="only_me")
        self.keep(grant_row(self.kid, theirs["trip_id"], "trip", by="sub-ben"))
        self.assertEqual([t["trip_id"] for t in self.ok("ana", "GET", "/api/photo-grants")["people"][1]["trips"]], [])


class PreferenceTests(AccessCase):
    def test_share_on_all_my_trips_grants_every_trip_the_person_is_on_and_later_stops_stay_stopped(self):
        later = self.book("ana", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])
        booked = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        self.share("ana", later["trip_id"], revoked=5.0)
        got = self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {"default_scope": "trip", "share_all": True})
        self.assertEqual(got, {"default_scope": "trip", "share_all": True})
        mine = self.ok("ana", "GET", "/api/photo-grants")["people"][0]
        self.assertEqual(mine["prefs"], got)
        self.assertEqual([(t["trip_id"], t["state"], t["scope"]) for t in mine["trips"]], [(self.trip, "shared", "trip"), (later["trip_id"], "shared", "trip")])
        self.assertEqual(self.sharing("ana", booked["trip_id"])["state"], "none")
        with db.session() as conn:
            self.assertEqual(set(conn.execute(select(PhotoGrant.granted_by)).scalars()), {"sub-ana"})
        self.ok("ana", "DELETE", f"/api/trips/{later['trip_id']}/photo-sharing")
        self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {"share_all": True})
        self.assertEqual(self.sharing("ana", later["trip_id"])["state"], "declined")
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {"share_all": False}), {"default_scope": "trip", "share_all": False})
        self.assertEqual(self.sharing("ana")["state"], "shared")
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {"default_scope": "only_me"}), {"default_scope": "only_me", "share_all": False})
        self.assertEqual(self.sharing("ana")["scope"], "trip")
        for bad in ({}, {"default_scope": "all"}, {"share_all": "yes"}, {"default_scope": 1}):
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", bad)[0], 400, bad)
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ben']}", {"share_all": True}), (404, NO_TRIP))
        self.assertEqual(self.call("ana", "POST", "/api/photo-sharing-prefs/x", {"share_all": True}), (404, NO_TRIP))
        self.assertEqual(self.ok("ben", "GET", "/api/photo-grants")["people"][0]["trips"], [])


class LeakTests(AccessCase):
    def test_no_reply_log_or_request_carries_an_asset_id_a_place_only_others_photos_have_or_the_library(self):
        self.share("ben", scope="only_me")
        self.share("ana")
        self.photo("ben")
        hers = self.photo("ana", local="2026-06-02T11:00", placed=False)
        with no_leaks(self, ASSET, URL, KEY, STATE, COUNTRY):
            replies = [self.listing("ana"), self.summary("ana"), self.sharing("ana"), self.ok("ana", "GET", "/api/photos/review"), self.ok("ana", "GET", "/api/photo-grants"),
                       self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [hers]}), self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{hers}"),
                       self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "only_me"}), self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-sharing"),
                       self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {"share_all": True}),
                       self.call("cy", "GET", f"/api/trips/{self.trip}/photo-sharing")[1], self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": self.person["ben"], "scope": "trip"})[1]]
        text = json.dumps(replies)
        for canary in (ASSET, URL, KEY, "immich-user-1", "asset", "api_key", "source_id", "granted_by", "sub-"):
            self.assertNotIn(canary, text, canary)
        self.assertNotIn(COUNTRY, json.dumps(replies[:2]))
        self.assertIn(COUNTRY, self.summary("ben")["countries"])

    def test_assistants_never_reach_a_photo_route(self):
        for method, pattern in PHOTO_ROUTES:
            self.assertTrue(mcp_access.blocked(pattern), pattern)
            self.assertIsNone(mcp_http.needs(method, pattern), f"{method} {pattern}")


class LocalModeTests(ServerCase):
    unset = ("OIDC_ISSUER",)

    def test_every_photo_route_answers_404_without_sign_in(self):
        status, seg = self.req("POST", "/api/segments", OUT)
        self.assertEqual(status, 200)
        trip = seg["trip_id"]
        calls = [("GET", f"/api/trips/{trip}/photos", None), ("GET", "/api/photos/review", None), ("POST", "/api/photos/1", {"trip_id": trip}),
                 ("GET", f"/api/trips/{trip}/photo-sharing", None), ("POST", f"/api/trips/{trip}/photo-sharing", {"scope": "trip"}),
                 ("DELETE", f"/api/trips/{trip}/photo-sharing", None), ("POST", f"/api/trips/{trip}/photo-exclusions", {"photo_ids": [1]}),
                 ("DELETE", f"/api/trips/{trip}/photo-exclusions/1", None), ("GET", "/api/photo-grants", None), ("POST", "/api/photo-sharing-prefs/1", {"share_all": True})]
        self.assertEqual(len(calls), len(PHOTO_ROUTES))
        for method, path, body in calls:
            with self.subTest(call=f"{method} {path}"):
                self.assertEqual(self.req(method, path, body), (404, {"error": "Photos need sign-in"}))


def stored_asset(photo_id):
    from waypoint.storage.models import Photo
    with db.session() as conn:
        row = conn.orm.get(Photo, photo_id)
        assert row is not None
        return row.asset_id


if __name__ == "__main__":
    unittest.main()
