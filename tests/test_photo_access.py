import json
import threading
import time
import unittest
from datetime import datetime
from unittest import mock

from sqlalchemy import delete, insert, select, update

from tests.privacy import no_leaks
from tests.shared import ServerCase
from tests.test_photos_api import ASSET, KEY, SOHO, URL, grant_row, photo_row, source_row, stored
from tests.test_trips import HOTEL, OUT, RouteCase
from waypoint.domain import demo, photocount, photosources, trips
from waypoint.domain.visibility import Viewer
from waypoint import tls
from waypoint.providers import immich
from waypoint.server import mcp_access, mcp_http
from waypoint.storage import db
from waypoint.storage.models import PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, PhotoTripSync, SegmentRecipient, TripPerson

STATE, COUNTRY = "Canaryshire-7q2x", "Canaryland-3k9v"
EMPTY = {"photos": [], "clusters": [], "counts": {"total": 0, "located": 0, "inferred": 0, "far": 0}, "people": []}
NO_TRIP, NO_PHOTO = {"error": "No such trip"}, {"error": "No such photo"}
PHOTO_ROUTES = (("GET", "/api/trips/{id}/photos"), ("GET", "/api/photos/review"), ("POST", "/api/photos/{id}"), ("GET", "/api/trips/{id}/photo-sharing"),
                ("POST", "/api/trips/{id}/photo-sharing"), ("DELETE", "/api/trips/{id}/photo-sharing"), ("POST", "/api/trips/{id}/photo-exclusions"),
                ("DELETE", "/api/trips/{id}/photo-exclusions/{id}"), ("GET", "/api/photo-grants"), ("POST", "/api/photo-sharing-prefs/{id}"),
                ("GET", "/api/photos/{id}/thumbnail"), ("GET", "/api/photos/{id}/preview"), ("GET", "/api/photos/{id}/original"))


class AccessCase(RouteCase):
    def setUp(self):
        super().setUp()
        self.flight = self.book("ana", travelers=[{"person_id": self.person["ana"]}, {"person_id": self.person["ben"]}])
        self.trip = self.flight["trip_id"]
        self.stay = self.book("ana", HOTEL, trip_id=self.trip)
        self.sources = {who: self.keep(source_row(self.person[who], f"sub-{who}")) for who in ("ana", "ben")}
        self.in_immich: list[dict] = []
        photocount.forget_counts()
        searching = mock.patch.object(immich, "search", side_effect=self.search)
        searching.start()
        self.addCleanup(searching.stop)
        offline = mock.patch.object(tls, "urlopen", side_effect=AssertionError("a photo access test reached the network"))
        offline.start()
        self.addCleanup(offline.stop)

    def search(self, source, taken_after, taken_before, *, updated_after=None, page=1, seconds=None):
        found = [a for a in self.in_immich if taken_after <= datetime.fromisoformat(a["fileCreatedAt"]) <= taken_before]
        return immich.parse_page({"assets": {"items": found, "nextPage": None}}, page, source.user_id)

    def in_library(self, number, taken="2026-06-03T09:00:00.000Z"):
        self.in_immich.append({"id": f"0a000000-0000-4000-8000-{number:012d}", "type": "IMAGE", "ownerId": "immich-user-1", "localDateTime": taken,
                               "fileCreatedAt": taken, "updatedAt": "2026-06-20T00:00:00.000Z",
                               "exifInfo": {"timeZone": None, "latitude": SOHO[0], "longitude": SOHO[1], "state": None, "country": None}})

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

    def confirm(self, who, trip=None, person=None, scope="trip"):
        trip = self.trip if trip is None else trip
        query = f"?person_id={person}" if person is not None else ""
        seen = self.ok(who, "GET", f"/api/trips/{trip}/photo-sharing{query}")
        body = {"scope": scope, "window": seen["window"], "audience": seen["audience"], "sources": seen["sources"]}
        if person is not None:
            body["person_id"] = person
        if seen["changed"] is not None:
            body["expected_changed"] = seen["changed"]
        return self.ok(who, "POST", f"/api/trips/{trip}/photo-sharing", body)

    def setting_snapshots(self, who, trip_ids):
        seen = {str(t): self.ok(who, "GET", f"/api/trips/{t}/photo-sharing") for t in trip_ids}
        sources = next(iter(seen.values()))["sources"] if seen else []
        return {"windows": {t: s["window"] for t, s in seen.items() if s["window"] is not None}, "audiences": {t: s["audience"] for t, s in seen.items()}, "sources": sources}

    def core(self, state):
        return {k: v for k, v in state.items() if k not in ("window", "changed", "audience", "sources", "count_token")}

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
        self.assertEqual(self.core(self.sharing("ben")), {"state": "shared", "scope": "only_me", "count": 1, "removed_count": 0, "removed": []})
        self.assertEqual(self.core(self.sharing("ana")), {"state": "none", "scope": None, "count": 0, "removed_count": 0, "removed": []})
        self.assertEqual((self.sharing("ben")["changed"], self.sharing("ana")["changed"]), (1.0, None))
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
        self.assertEqual([{k: v for k, v in p.items() if k != "count_token"} for p in self.ok("ana", "GET", "/api/photo-grants")["people"]],
                         [{"person_id": self.person["ana"], "prefs": {"default_scope": "only_me", "share_all": False}, "trips": []}])

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
        self.in_library(1)
        got = self.ok("ben", "DELETE", f"/api/trips/{self.trip}/photo-sharing")
        self.assertEqual((got["state"], got["scope"], got["count"], got["removed_count"], got["removed"]), ("declined", None, None, 0, []))
        self.assertEqual(self.sharing("ben")["count"], 1)
        for who in ("ana", "ben"):
            self.assertEqual(self.seen_by(who), [self.hers], who)
            self.assertEqual(self.listing(who)["people"], [{"person_id": self.person["ana"], "count": 1}], who)
        self.assertEqual((stored(self.mine), stored(other)), (None, None))
        with db.session() as conn:
            self.assertEqual(conn.execute(select(PhotoTripSync.trip_id)).fetchall(), [])
            kept = conn.execute(select(PhotoExclusion.person_id, PhotoExclusion.trip_id)).fetchall()
        self.assertEqual(kept, [(self.person["ben"], self.trip)])
        listed = self.ok("ben", "GET", "/api/photo-grants")["people"][0]["trips"]
        self.assertEqual([(t["trip_id"], t["state"], t["count"]) for t in listed], [(self.trip, "declined", 1)])
        again = self.confirm("ben")
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
        self.confirm("ben")
        self.assertEqual(self.seen_by("ana"), [self.mine, self.hers])
        for bad in ({"scope": "everyone"}, {"scope": 1}, {}, {"declined": "yes"}, {"person_id": "x", "scope": "trip"}, {"person_id": True, "scope": "trip"}):
            self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", bad)[0], 400, bad)
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": self.person["ana"], "scope": "trip"}), (404, NO_TRIP))
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"person_id": 99999, "scope": "trip"}), (404, NO_TRIP))

    def test_a_share_can_be_bound_to_the_count_token_the_count_came_with(self):
        state = self.sharing("ben")
        self.assertRegex(state["count_token"], r"^[0-9a-f]{32}$")
        self.assertEqual(self.sharing("ben")["count_token"], state["count_token"])
        shown = {"scope": "trip", "window": state["window"], "audience": state["audience"], "sources": state["sources"]}
        if state["changed"] is not None:
            shown["expected_changed"] = state["changed"]
        with db.session() as conn:
            conn.execute(insert(PhotoExclusion).values(person_id=self.person["ben"], asset_id="asset-x", trip_id=self.trip, created=3.0))
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {**shown, "count_token": state["count_token"]}),
                         (409, {"error": "Your photos or trips changed since they were counted. Review the count before sharing."}))
        self.assertEqual(self.sharing("ben")["scope"], state["scope"])
        for bad in (1, "", "x" * 65, True, ["a"], "é", "é" * 32, "A" * 32, "0" * 31):
            self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {**shown, "count_token": bad})[0], 400, bad)
        fresh = self.sharing("ben")["count_token"]
        self.assertNotEqual(fresh, state["count_token"])
        self.assertEqual(self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {**shown, "count_token": fresh})["scope"], "trip")

    def test_share_on_all_can_be_bound_to_the_count_token_of_the_grants_reply(self):
        mine = self.ok("ana", "GET", "/api/photo-grants")["people"][0]
        self.assertRegex(mine["count_token"], r"^[0-9a-f]{32}$")
        with db.session() as conn:
            conn.execute(insert(PhotoExclusion).values(person_id=self.person["ana"], asset_id="asset-x", trip_id=self.trip, created=3.0))
        body = {"default_scope": "trip", "share_all": True, **self.setting_snapshots("ana", [self.trip])}
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {**body, "count_token": mine["count_token"]})[0], 409)
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {**body, "count_token": 5})[0], 400)
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {**body, "count_token": "é"})[0], 400)
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {**body, "count_token": "0" * 32})[0], 409)
        fresh = self.ok("ana", "GET", "/api/photo-grants")["people"][0]["count_token"]
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {**body, "count_token": fresh}), {"default_scope": "trip", "share_all": True})

    def test_a_widening_and_a_put_back_can_be_bound_to_what_the_person_saw(self):
        self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "only_me"})
        state = self.sharing("ben")
        self.assertEqual(sorted(state["window"]), ["end", "start"])
        shown = {"scope": "trip", "audience": state["audience"], "sources": state["sources"], "expected_changed": state["changed"]}
        stale = {**shown, "window": {"start": state["window"]["start"], "end": "2030-01-01T00:00:00+00:00"}}
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", stale), (409, {"error": "The trip changed. Review who sees your photos under Your photos on this trip."}))
        self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {**shown, "window": state["window"], "expected_changed": state["changed"] + 1})[0], 409)
        self.assertEqual(self.seen_by("ana"), [self.hers])
        got = self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", {**shown, "window": state["window"]})
        self.assertEqual(got["scope"], "trip")
        for bad in ({"scope": "trip", "window": "x"}, {"scope": "trip", "window": {"start": 1}}, {"scope": "trip", "expected_changed": "x"}, {"scope": "trip", "expected_changed": True}):
            self.assertEqual(self.call("ben", "POST", f"/api/trips/{self.trip}/photo-sharing", bad)[0], 400, bad)
        self.ok("ben", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [self.mine]})
        with db.session() as conn:
            stamp = conn.execute(select(PhotoExclusion.created)).scalar()
        self.assertEqual(self.call("ben", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{self.mine}?created={stamp + 1}"),
                         (409, {"error": "The trip changed since that photo was removed. Open the removed list again."}))
        self.assertEqual(self.call("ben", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{self.mine}?created=x")[0], 400)
        self.assertEqual(self.ok("ben", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{self.mine}?created={stamp}")["removed_count"], 0)
        prefs = self.ok("ben", "POST", f"/api/photo-sharing-prefs/{self.person['ben']}", {"share_all": False})
        self.assertEqual(prefs["share_all"], False)
        self.assertEqual(self.call("ben", "POST", f"/api/photo-sharing-prefs/{self.person['ben']}", {"share_all": True, "windows": "x"})[0], 400)

    def test_not_now_records_a_declined_row_the_person_can_share_again(self):
        later = self.book("ben", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        trip = later["trip_id"]
        got = self.ok("ben", "POST", f"/api/trips/{trip}/photo-sharing", {"declined": True})
        self.assertEqual((got["state"], got["scope"]), ("declined", None))
        self.assertEqual(self.confirm("ben", trip)["state"], "shared")


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

    def test_one_cap_covers_every_person_settings_counts_for(self):
        for m in range(1, 6):
            self.book("ana", {**OUT, "start_local": f"2027-0{m}-01T19:00", "end_local": f"2027-0{m}-02T07:10"},
                      travelers=[{"person_id": self.person["ana"]}, {"person_id": self.kid}])

        started, lock = [], threading.Lock()

        def slow(source, taken_after, taken_before, *, updated_after=None, page=1, seconds=None):
            with lock:
                started.append(taken_after)
            time.sleep(0.7)
            return self.search(source, taken_after, taken_before, page=page)
        immich.search.side_effect = slow
        with mock.patch.object(photocount, "COUNT_SECONDS", 0.3), mock.patch.object(photocount, "COUNT_TOTAL", 0.6):
            got = self.ok("ana", "GET", "/api/photo-grants")["people"]
        self.assertEqual([p["person_id"] for p in got], [self.person["ana"], self.kid])
        self.assertTrue(all(t["count"] is None for p in got for t in p["trips"]))
        self.assertEqual(len(started), photocount.COUNT_AT_ONCE)

    def test_a_steward_whose_trips_always_time_out_does_not_starve_the_child(self):
        for m in range(1, 6):
            self.book("ana", {**OUT, "start_local": f"2027-0{m}-01T19:00", "end_local": f"2027-0{m}-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])
        child = self.book("ana", {**OUT, "start_local": "2028-01-01T19:00", "end_local": "2028-01-02T07:10"}, travelers=[{"person_id": self.kid}])["trip_id"]
        self.in_library(1, "2028-01-02T03:00:00.000Z")

        def search(source, taken_after, taken_before, *, updated_after=None, page=1, seconds=None):
            if taken_after.isoformat().startswith("2027-0"):
                time.sleep(seconds or 0)
                raise immich.Unavailable(immich.TOO_SLOW)
            return self.search(source, taken_after, taken_before, page=page)
        immich.search.side_effect = search
        with mock.patch.object(photocount, "COUNT_SECONDS", 0.8), mock.patch.object(photocount, "COUNT_TOTAL", 1.2):
            for _ in range(2):
                photocount.forget_counts()
                got = self.ok("ana", "GET", "/api/photo-grants")["people"]
                kid = next(p for p in got if p["person_id"] == self.kid)
                self.assertEqual([t["count"] for t in kid["trips"] if t["trip_id"] == child], [1])
                steward = next(p for p in got if p["person_id"] == self.person["ana"])
                self.assertTrue(all(t["count"] is None for t in steward["trips"] if t["trip_id"] != self.trip))

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
        got = self.confirm("ana", person=self.kid)
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
        cys = self.book("cy", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.kid}])
        self.keep(grant_row(self.kid, theirs["trip_id"], "trip", by="sub-ben"))
        self.keep(grant_row(self.kid, cys["trip_id"], "trip", by="sub-cy"))
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
        got = self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}",
                      {"default_scope": "trip", "share_all": True, **self.setting_snapshots("ana", [self.trip, later["trip_id"]])})
        self.assertEqual(got, {"default_scope": "trip", "share_all": True})
        mine = self.ok("ana", "GET", "/api/photo-grants")["people"][0]
        self.assertEqual(mine["prefs"], got)
        self.assertEqual([(t["trip_id"], t["state"], t["scope"]) for t in mine["trips"]], [(self.trip, "shared", "trip"), (later["trip_id"], "shared", "trip")])
        self.assertEqual(self.sharing("ana", booked["trip_id"])["state"], "none")
        with db.session() as conn:
            self.assertEqual(set(conn.execute(select(PhotoGrant.granted_by)).scalars()), {"sub-ana"})
        self.ok("ana", "DELETE", f"/api/trips/{later['trip_id']}/photo-sharing")
        self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {"share_all": True, **self.setting_snapshots("ana", [self.trip, later["trip_id"]])})
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


class UnsharedCountTests(AccessCase):
    def setUp(self):
        super().setUp()
        self.share("ben", revoked=5.0)

    def count(self, who="ben", trip=None):
        with db.session() as conn:
            return photocount.unshared_counts(conn, self.person[who], [trip or self.trip])[trip or self.trip]

    def test_a_declined_trip_counts_what_the_sync_would_put_on_it_once_per_asset(self):
        self.keep(PhotoSource(person_id=self.person["ben"], owner_sub="sub-ben", url="https://second-canary.example", immich_user_id="immich-user-1",
                              api_key=source_row(self.person["ben"], "sub-ben").api_key, status="ok", created=1.0))
        self.keep(PhotoSource(person_id=self.person["ben"], owner_sub="sub-ben", url="https://paused-canary.example", immich_user_id="immich-user-1",
                              api_key=source_row(self.person["ben"], "sub-ben").api_key, status="off", created=1.0))
        for n in range(1, 4):
            self.in_library(n)
        self.in_library(4, "2026-07-20T09:00:00.000Z")
        self.in_immich.append({**self.in_immich[0], "id": "0a000000-0000-4000-8000-000000000099", "ownerId": "someone-else"})
        self.keep(PhotoExclusion(person_id=self.person["ben"], asset_id="0a000000-0000-4000-8000-000000000003", trip_id=self.trip, created=1.0))
        self.assertEqual(self.count(), 2)
        got = self.sharing("ben")
        self.assertEqual((got["state"], got["count"]), ("declined", 2))
        self.assertEqual(immich.search.call_count, 2)

    def test_a_library_that_cannot_be_checked_fails_the_whole_count(self):
        self.in_library(1)
        for status in ("refused", "unreachable"):
            with self.subTest(status=status):
                with db.session() as conn:
                    conn.execute(update(PhotoSource).where(PhotoSource.id == self.sources["ben"]).values(status=status))
                photocount.forget_counts()
                self.assertIsNone(self.count())
                self.assertIsNone(self.sharing("ben")["count"])
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.sources["ben"]).values(status="ok", api_key="enc:v1:not-a-token"))
        self.assertIsNone(self.count())
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.sources["ben"]).values(api_key=source_row(1, "x").api_key))
        immich.search.side_effect = immich.Unavailable(immich.UNREACHABLE)
        self.assertIsNone(self.count())
        with db.session() as conn:
            with self.assertRaises(photocount.Unchecked):
                photocount.unshared_count(conn, self.person["ben"], self.trip)
        immich.search.side_effect = self.search
        with db.session() as conn:
            self.assertEqual(photocount.unshared_count(conn, self.person["ben"], self.trip), 1)

    def test_a_dense_instant_fails_the_count_and_a_partners_one_is_stepped_through(self):
        def dense(source, taken_after, taken_before, *, updated_after=None, page=1, seconds=None):
            items = [{**self.in_immich[0], "id": f"0a000000-0000-4000-8000-{n:012d}", "ownerId": owner} for n in range(3)]
            return immich.parse_page({"assets": {"items": items, "nextPage": "2"}}, page, source.user_id)
        self.in_library(1)
        for owner in ("immich-user-1", "someone-else"):
            with self.subTest(owner=owner):
                photocount.forget_counts()
                immich.search.side_effect = dense
                with mock.patch.object(photocount, "COUNT_SECONDS", 0.5):
                    self.assertIsNone(self.count())

    def test_a_demo_library_counts_its_fixed_inventory_and_nothing_else_asks_immich(self):
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.sources["ben"]).values(status="off"))
        self.in_library(1)
        self.assertEqual(self.count(), 0)
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.sources["ben"]).values(status="ok", url="demo"))
        self.assertEqual(self.count(), demo.unshared_inventory(self.person["ben"], self.trip))
        self.assertGreater(self.count(), 0)
        with db.session() as conn:
            dateless = trips.create_trip(conn, Viewer(self.person["ben"]), {"name": "Someday", "people": [self.person["ben"]]})["id"]
            self.assertEqual(photocount.unshared_counts(conn, self.person["ben"], [dateless]), {dateless: 0})
        immich.search.assert_not_called()

    def test_a_count_is_kept_ten_minutes_for_the_same_window_libraries_and_removals(self):
        self.in_library(1)
        clock = [1000.0]
        with mock.patch.object(photocount.time, "monotonic", side_effect=lambda: clock[0]):
            self.assertEqual(self.count(), 1)
            self.in_library(2)
            self.assertEqual(self.count(), 1)
            self.assertEqual(self.sharing("ben")["count"], 1)
            self.assertIsNone(self.ok("ben", "DELETE", f"/api/trips/{self.trip}/photo-sharing")["count"])
            self.keep(PhotoExclusion(person_id=self.person["ben"], asset_id="unrelated-asset", trip_id=self.trip, created=1.0))
            self.assertEqual(self.count(), 2)
            self.in_library(3)
            clock[0] += photocount.COUNT_KEPT - 1
            self.assertEqual(self.count(), 2)
            clock[0] += 1
            self.assertEqual(self.count(), 3)
        self.assertEqual(immich.search.call_count, 3)

    def test_a_photo_the_owner_placed_on_a_shared_trip_is_not_counted_for_another_trip(self):
        with db.session() as conn:
            day = trips.create_trip(conn, Viewer(self.person["ben"]), {"name": "Day out", "people": [self.person["ben"]],
                                                                      "start_date": "2026-07-03", "end_date": "2026-07-03"})["id"]
        self.in_library(1, "2026-06-03T09:00:00.000Z")
        self.share("ben", day, scope="only_me")
        self.assertEqual(self.count(), 1)
        self.keep(photo_row(self.sources["ben"], day, "2026-06-03T09:00", where=SOHO, decided="owner", asset="0a000000-0000-4000-8000-000000000001"))
        self.assertEqual(self.count(), 0)
        self.keep(PhotoExclusion(person_id=self.person["ben"], asset_id="0a000000-0000-4000-8000-000000000001", trip_id=day, created=1.0))
        self.assertEqual(self.count(), 1)

    def test_the_count_opens_a_library_as_the_source_rules_do(self):
        for url in ("https://immich-canary.example", "http://192.168.1.20:2283", "http://immich-canary.example"):
            self.assertEqual(photocount.provider_source(url, "k", "u"), photosources.provider_source(url, "k", "u"))

    def test_a_trip_granted_meanwhile_that_takes_the_photos_is_counted_afresh(self):
        self.in_library(1, "2026-06-04T09:00:00.000Z")
        self.assertEqual(self.count(), 1)
        with db.session() as conn:
            inside = trips.create_trip(conn, Viewer(self.person["ben"]), {"name": "Day out", "people": [self.person["ben"]],
                                                                          "start_date": "2026-06-04", "end_date": "2026-06-04"})["id"]
        self.share("ben", inside, scope="only_me")
        self.assertEqual(self.count(), 0)
        self.assertEqual(immich.search.call_count, 2)

    def test_settings_lists_a_trip_not_shared_only_when_it_has_photos_and_says_when_it_could_not_check(self):
        later = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])["trip_id"]
        quiet = self.book("ana", {**OUT, "start_local": "2027-02-01T19:00", "end_local": "2027-02-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])["trip_id"]
        shared = self.book("ana", {**OUT, "start_local": "2027-05-01T19:00", "end_local": "2027-05-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])["trip_id"]
        self.book("ana", {**OUT, "start_local": "2027-08-01T19:00", "end_local": "2027-08-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])
        self.share("ben", shared, scope="only_me")
        self.in_library(1)
        self.in_library(2, "2026-09-02T09:00:00.000Z")
        self.in_library(3, "2026-09-02T10:00:00.000Z")
        listed = lambda: [(t["trip_id"], t["state"], t["scope"], t["count"]) for t in self.ok("ben", "GET", "/api/photo-grants")["people"][0]["trips"]]
        self.assertEqual(listed(), [(self.trip, "declined", None, 1), (later, "none", None, 2), (shared, "shared", "only_me", 0)])
        self.assertNotIn(quiet, [t[0] for t in listed()])
        photocount.forget_counts()
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.sources["ben"]).values(status="unreachable"))
        self.assertEqual(listed(), [(self.trip, "declined", None, None), (later, "none", None, None), (quiet, "none", None, None),
                                    (shared, "shared", "only_me", 0)])

    def test_at_most_four_trips_are_counted_at_once(self):
        trips_of_ben = [self.book("ana", {**OUT, "start_local": f"2027-0{m}-01T19:00", "end_local": f"2027-0{m}-02T07:10"},
                                  travelers=[{"person_id": self.person["ben"]}])["trip_id"] for m in range(1, 8)]
        lock, now, peak = threading.Lock(), [0], [0]

        def slow(source, taken_after, taken_before, *, updated_after=None, page=1, seconds=None):
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            time.sleep(0.05)
            with lock:
                now[0] -= 1
            return immich.parse_page({"assets": {"items": [], "nextPage": None}}, page, source.user_id)
        immich.search.side_effect = slow
        with db.session() as conn:
            got = photocount.unshared_counts(conn, self.person["ben"], trips_of_ben)
        self.assertEqual(got, {t: 0 for t in trips_of_ben})
        self.assertEqual(peak[0], photocount.COUNT_AT_ONCE)

    def slow_trips(self, count):
        made = [self.book("ana", {**OUT, "start_local": f"2027-0{m}-01T19:00", "end_local": f"2027-0{m}-02T07:10"},
                          travelers=[{"person_id": self.person["ben"]}])["trip_id"] for m in range(1, count + 1)]
        self.in_library(1, f"2027-0{count}-02T09:00:00.000Z")
        fast = f"2027-0{count}"

        def search(source, taken_after, taken_before, *, updated_after=None, page=1, seconds=None):
            if not taken_after.isoformat().startswith(fast):
                time.sleep(1.0)
            return self.search(source, taken_after, taken_before, page=page)
        immich.search.side_effect = search
        return made

    def test_slow_trips_counted_first_do_not_use_up_the_budget_of_the_trips_after_them(self):
        made = self.slow_trips(5)
        with mock.patch.object(photocount, "COUNT_SECONDS", 0.8), db.session() as conn:
            got = photocount.unshared_counts(conn, self.person["ben"], made)
        self.assertEqual(got, {**{t: None for t in made[:4]}, made[4]: 1})

    def test_trips_left_unchecked_at_the_overall_cap_go_first_the_next_time(self):
        made = self.slow_trips(5)
        with mock.patch.object(photocount, "COUNT_SECONDS", 0.8), mock.patch.object(photocount, "COUNT_TOTAL", 0.9):
            with db.session() as conn:
                self.assertEqual(photocount.unshared_counts(conn, self.person["ben"], made), {t: None for t in made})
            with db.session() as conn:
                self.assertEqual(photocount.unshared_counts(conn, self.person["ben"], made)[made[4]], 1)

    def test_a_library_connected_in_place_of_another_is_counted_afresh(self):
        self.in_library(1)
        self.assertEqual(self.count(), 1)
        with db.session() as conn:
            old = conn.orm.get(PhotoSource, self.sources["ben"])
            conn.orm.delete(old)
            conn.orm.flush()
            conn.orm.add(PhotoSource(id=self.sources["ben"], person_id=self.person["ben"], owner_sub="sub-ben", url="https://replacement-canary.example",
                                     immich_user_id="immich-user-1", api_key=source_row(1, "x").api_key, status="ok", created=2.0))
        self.in_library(2)
        self.assertEqual(self.count(), 2)

    def test_nothing_private_is_logged_when_a_count_fails(self):
        immich.search.side_effect = immich.Refused(immich.REFUSED)
        with no_leaks(self, URL, KEY, ASSET):
            replies = [self.sharing("ben"), self.ok("ben", "GET", "/api/photo-grants")]
        self.assertIsNone(replies[0]["count"])
        for canary in (URL, KEY):
            self.assertNotIn(canary, json.dumps(replies))


class LocalModeTests(ServerCase):
    unset = ("OIDC_ISSUER",)

    def test_every_photo_route_answers_404_without_sign_in(self):
        status, seg = self.req("POST", "/api/segments", OUT)
        self.assertEqual(status, 200)
        trip = seg["trip_id"]
        calls = [("GET", f"/api/trips/{trip}/photos", None), ("GET", "/api/photos/review", None), ("POST", "/api/photos/1", {"trip_id": trip}),
                 ("GET", f"/api/trips/{trip}/photo-sharing", None), ("POST", f"/api/trips/{trip}/photo-sharing", {"scope": "trip"}),
                 ("DELETE", f"/api/trips/{trip}/photo-sharing", None), ("POST", f"/api/trips/{trip}/photo-exclusions", {"photo_ids": [1]}),
                 ("DELETE", f"/api/trips/{trip}/photo-exclusions/1", None), ("GET", "/api/photo-grants", None), ("POST", "/api/photo-sharing-prefs/1", {"share_all": True}),
                 ("GET", "/api/photos/1/thumbnail", None), ("GET", "/api/photos/1/preview", None), ("GET", "/api/photos/1/original", None)]
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
