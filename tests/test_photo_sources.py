import contextlib
import io
import json
import os
import time
import unittest
from unittest import mock

from sqlalchemy import delete, select, update

from tests.privacy import no_leaks
from tests.shared import DbCase, ServerCase
from tests.test_trips import OUT, RouteCase, guest
from waypoint import oidc
from waypoint.domain import people, photogrants, photos, photosources, trips
from waypoint.domain.visibility import Viewer
from waypoint.providers import immich
from waypoint.server import ROUTES, jobs, mcp_access, mcp_http
from waypoint.storage import backup, db, photo_sources, secretbox
from waypoint.storage.models import Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, User

URL = "https://immich-canary-8h2k.example:2283"
LAN = "http://immich.local:2283"
KEY = "canary-immich-key-5m7p2w"
NEW_KEY = "canary-immich-key-second-x1"
ACCOUNT = immich.Account(user_id="immich-user-canary-1", name="Ana Example", email="ana@immich.example")
OTHER = immich.Account(user_id="immich-user-canary-2", name="Someone Else", email=None)
PATTERNS = ("/api/photo-sources", "/api/photo-sources/test", "/api/photo-sources/{id}", "/api/photo-sources/{id}/test", "/api/photo-sources/{id}/sync")


def ping(result=ACCOUNT):
    return mock.patch.object(immich, "ping", return_value=result)


def failing(error):
    return mock.patch.object(immich, "ping", side_effect=error)


def photo(source_id, trip_id, number, match="place"):
    return Photo(source_id=source_id, asset_id=f"asset-{number}", asset_updated="2026-06-02T00:00:00Z", kind="image", taken_utc="2026-06-02T09:00:00+00:00",
                 taken_local="2026-06-02T10:00", taken_offset=None, latitude=None, longitude=None, location_source=None, state=None, country=None,
                 trip_id=trip_id, segment_id=None, match=match, distance_km=None, decided_by=None, seen=1.0)


class SourceRoutes(RouteCase):
    def setUp(self):
        super().setUp()
        self.guest = self.ok("ana", "POST", "/api/people", {"display_name": "Mia Doe"})["id"]
        self.path = os.path.join(os.environ["WAYPOINT_DATA"], "waypoint.db")

    def connect(self, who="ana", url=URL, key=KEY, **extra):
        with ping() as pong:
            got = self.ok(who, "POST", "/api/photo-sources", {"url": url, "key": key, **extra})
        self.pinged = pong
        return got

    def raw(self, source_id):
        with db.session() as conn:
            return tuple(conn.execute(select(PhotoSource.api_key, PhotoSource.status, PhotoSource.last_error, PhotoSource.immich_user_id)
                                      .where(PhotoSource.id == source_id)).fetchone())

    def unlocked(self, source_id):
        with db.session() as conn:
            found = photo_sources.source_for_provider(conn, source_id)
            assert found is not None
            return found.key

    def listing(self, who):
        return self.ok(who, "GET", "/api/photo-sources")

    def test_a_member_connects_their_own_library_and_the_key_is_sealed_at_rest(self):
        got = self.connect(label="Ana’s library")
        self.assertEqual(got, {"id": got["id"], "person_id": self.person["ana"], "url": URL, "label": "Ana’s library", "status": "ok", "mine": True,
                               "last_sync": None, "last_error": None, "photos": 0, "trips": 0})
        self.assertEqual(self.pinged.call_args.args[0], immich.Source(url=URL, key=KEY, allow_http=False))
        stored = self.raw(got["id"])
        self.assertTrue(stored[0].startswith("enc:v1:"))
        self.assertNotIn(KEY, stored[0])
        self.assertEqual((stored[1], stored[3]), ("ok", ACCOUNT.user_id))
        self.assertEqual(self.unlocked(got["id"]), KEY)
        listed = self.listing("ana")
        self.assertEqual(listed, {"sources": [got], "permissions": ["asset.read", "asset.view", "user.read", "map.read", "asset.download"]})

    def test_a_library_on_the_home_network_may_use_http_and_one_elsewhere_may_not(self):
        got = self.connect(url=LAN)
        self.assertEqual(self.pinged.call_args.args[0], immich.Source(url=LAN, key=KEY, allow_http=True))
        self.assertEqual(got["url"], LAN)
        with ping() as pong:
            status, got = self.call("ana", "POST", "/api/photo-sources", {"url": "http://immich-canary.example", "key": KEY})
        self.assertEqual((status, got), (400, {"error": photosources.HTTPS_ONLY}))
        pong.assert_not_called()

    def test_connecting_refuses_a_bad_address_a_bad_key_a_missing_person_and_a_duplicate(self):
        with ping() as pong:
            for body, status, error in (({"url": "ftp://immich.example", "key": KEY}, 400, None), ({"url": "https://immich.example/path", "key": KEY}, 400, None),
                                        ({"url": "https://user:pw@immich.example", "key": KEY}, 400, None), ({"url": "", "key": KEY}, 400, None),
                                        ({"url": URL, "key": ""}, 400, None), ({"url": URL, "key": "has space"}, 400, None), ({"url": URL, "key": 7}, 400, None),
                                        ({"url": URL, "key": KEY, "person_id": 99999}, 404, photosources.NO_PERSON),
                                        ({"url": URL, "key": KEY, "person_id": "x"}, 400, None), ({"url": URL, "key": KEY, "person_id": True}, 400, None),
                                        ({"url": URL, "key": KEY, "label": "x" * 101}, 400, None)):
                with self.subTest(body=body):
                    got = self.call("ana", "POST", "/api/photo-sources", body)
                    self.assertEqual(got[0], status, got)
                    if error:
                        self.assertEqual(got[1], {"error": error})
            pong.assert_not_called()
        self.connect()
        with ping() as pong:
            status, got = self.call("ana", "POST", "/api/photo-sources", {"url": URL + "/", "key": NEW_KEY})
        self.assertEqual((status, got), (409, {"error": photosources.ALREADY}))
        self.assertEqual(pong.call_args.args[0], immich.Source(url=URL, key=NEW_KEY, allow_http=False))
        self.assertEqual(len(self.listing("ana")["sources"]), 1)

    def test_the_same_server_holds_one_library_per_immich_account(self):
        first = self.connect()
        with ping(OTHER):
            second = self.ok("ana", "POST", "/api/photo-sources", {"url": URL, "key": NEW_KEY})
        self.assertEqual([s["id"] for s in self.listing("ana")["sources"]], [first["id"], second["id"]])
        self.assertEqual((self.raw(first["id"])[3], self.raw(second["id"])[3]), (ACCOUNT.user_id, OTHER.user_id))
        with ping(OTHER):
            self.assertEqual(self.call("ana", "POST", "/api/photo-sources", {"url": URL, "key": KEY})[0], 409)

    def test_what_immich_answers_decides_whether_the_library_is_saved(self):
        for error, status in ((immich.Refused(immich.REFUSED), 400), (immich.Unavailable(immich.UNREACHABLE), 502),
                              (immich.Unavailable(immich.UNREADABLE), 502), (immich.RateLimited(immich.RATE_LIMITED, 30.0), 503),
                              (immich.NotConfigured(immich.NOT_CONFIGURED), 400)):
            with self.subTest(error=error), failing(error):
                got = self.call("ana", "POST", "/api/photo-sources", {"url": URL, "key": KEY})
                self.assertEqual(got, (status, {"error": str(error)}))
                self.assertEqual(self.listing("ana")["sources"], [])

    def test_a_member_who_signs_in_connects_only_their_own_libraries(self):
        with ping() as pong:
            status, got = self.call("ana", "POST", "/api/photo-sources", {"url": URL, "key": KEY, "person_id": self.person["ben"]})
        self.assertEqual((status, got), (403, {"error": photosources.NOT_YOURS}))
        pong.assert_not_called()
        self.assertEqual(self.listing("ben")["sources"], [])
        mine = self.connect(person_id=self.person["ana"])
        self.assertEqual((mine["person_id"], mine["mine"]), (self.person["ana"], True))

    def test_a_person_without_a_sign_in_has_one_steward(self):
        first = self.connect(person_id=self.guest)
        self.assertEqual((first["person_id"], first["mine"]), (self.guest, True))
        with ping() as pong:
            status, got = self.call("ben", "POST", "/api/photo-sources", {"url": LAN, "key": KEY, "person_id": self.guest})
        self.assertEqual((status, got), (403, {"error": photosources.OTHER_STEWARD}))
        pong.assert_not_called()
        second = self.connect(url=LAN, person_id=self.guest)
        self.assertEqual([s["id"] for s in self.listing("ana")["sources"]], [first["id"], second["id"]])
        for route, body in (("POST", {"label": "Mia’s"}), ("DELETE", None)):
            self.assertEqual(self.call("ben", route, f"/api/photo-sources/{first['id']}", body), (404, {"error": photosources.NO_SOURCE}))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{first['id']}", {"label": "Mia’s"})["label"], "Mia’s")

    def steward(self, person_id):
        with db.session() as conn:
            row = conn.orm.get(PhotoSharingPrefs, person_id)
            return None if row is None else (row.steward_sub, row.default_scope, row.share_all)

    def test_connecting_a_childs_first_library_records_their_steward(self):
        mine = self.connect()
        self.assertIsNone(self.steward(self.person["ana"]))
        first = self.connect(url=LAN, person_id=self.guest)
        self.assertEqual(self.steward(self.guest), ("sub-ana", "only_me", False))
        self.connect(url="https://second-canary.example", person_id=self.guest)
        self.assertEqual(self.steward(self.guest), ("sub-ana", "only_me", False))
        self.assertIsNone(self.steward(self.person["ana"]))
        with db.session() as conn:
            self.assertEqual(photos.persons_of(conn, Viewer(self.person["ana"])), [self.person["ana"], self.guest])
            self.assertEqual(photos.persons_of(conn, Viewer(self.person["ben"])), [self.person["ben"]])
        self.assertEqual([s["mine"] for s in self.listing("ana")["sources"]], [True, True, True])
        self.assertEqual((mine["person_id"], first["person_id"]), (self.person["ana"], self.guest))

    def test_the_steward_is_kept_after_the_last_library_is_removed(self):
        first = self.connect(person_id=self.guest)
        self.assertEqual(self.ok("ana", "DELETE", f"/api/photo-sources/{first['id']}"), {"ok": True})
        self.assertEqual(self.steward(self.guest), ("sub-ana", "only_me", False))
        with ping() as pong:
            status, got = self.call("ben", "POST", "/api/photo-sources", {"url": LAN, "key": KEY, "person_id": self.guest})
        self.assertEqual((status, got), (403, {"error": photosources.OTHER_STEWARD}))
        pong.assert_not_called()
        self.assertEqual(self.steward(self.guest), ("sub-ana", "only_me", False))
        again = self.connect(url=LAN, person_id=self.guest)
        self.assertEqual((again["person_id"], again["mine"]), (self.guest, True))
        self.assertEqual(self.steward(self.guest), ("sub-ana", "only_me", False))

    def test_counts_and_errors_show_only_to_those_acting_for_the_person(self):
        trip = self.book("ana", travelers=[{"person_id": self.person["ana"]}])["trip_id"]
        mine = self.connect(label="Ana’s")
        theirs = self.connect(who="ben", url=LAN)
        with db.session() as conn:
            conn.orm.add_all([photo(mine["id"], trip, 1), photo(mine["id"], trip, 2, "time"), photo(mine["id"], trip, 3, "far"), photo(mine["id"], None, 4, "ambiguous"),
                              photo(mine["id"], trip, 5, "home"), photo(theirs["id"], trip, 6)])
            conn.orm.flush()
            photo_sources.mark(conn, theirs["id"], "unreachable", immich.UNREACHABLE, 1_700_000_000.0)
        got = {s["id"]: s for s in self.listing("ana")["sources"]}
        self.assertEqual(got[mine["id"]], {**mine, "photos": 3, "trips": 1})
        self.assertEqual(got[theirs["id"]], {"id": theirs["id"], "person_id": self.person["ben"], "url": LAN, "label": None, "status": "unreachable", "mine": False,
                                             "last_sync": None, "last_error": None, "photos": None, "trips": None})
        got = {s["id"]: s for s in self.listing("ben")["sources"]}
        self.assertEqual(got[theirs["id"]], {**theirs, "status": "unreachable", "last_error": immich.UNREACHABLE, "last_sync": "2023-11-14T22:13:20+00:00",
                                             "photos": 1, "trips": 1})
        self.assertEqual((got[mine["id"]]["photos"], got[mine["id"]]["trips"], got[mine["id"]]["last_sync"], got[mine["id"]]["mine"]), (None, None, None, False))

    def test_a_photo_removed_from_its_only_trip_leaves_the_librarys_counts_at_once(self):
        trip = self.book("ana", travelers=[{"person_id": self.person["ana"]}])["trip_id"]
        other = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])["trip_id"]
        mine = self.connect()
        with db.session() as conn:
            conn.orm.add_all([photo(mine["id"], trip, 1), photo(mine["id"], trip, 2), photo(mine["id"], other, 3)])
            conn.orm.flush()
        counts = lambda: next((s["photos"], s["trips"]) for s in self.listing("ana")["sources"] if s["id"] == mine["id"])
        self.assertEqual(counts(), (3, 2))
        with db.session() as conn:
            conn.orm.add(PhotoExclusion(person_id=self.person["ana"], asset_id="asset-3", trip_id=other, created=2.0, was_trip_id=other))
            conn.orm.flush()
        self.assertEqual(counts(), (2, 1))
        with db.session() as conn:
            conn.orm.add(PhotoExclusion(person_id=self.person["ben"], asset_id="asset-1", trip_id=trip, created=2.0, was_trip_id=trip))
            conn.orm.flush()
        self.assertEqual(counts(), (2, 1))
        with db.session() as conn:
            conn.execute(delete(PhotoExclusion).where(PhotoExclusion.person_id == self.person["ana"]))
        self.assertEqual(counts(), (3, 2))

    def test_only_the_owner_edits_tests_removes_and_syncs_a_library(self):
        made = self.connect()
        calls = [("POST", f"/api/photo-sources/{made['id']}", {"label": "Stolen"}), ("DELETE", f"/api/photo-sources/{made['id']}", None),
                 ("POST", f"/api/photo-sources/{made['id']}/test", {}), ("POST", f"/api/photo-sources/{made['id']}/test", {"key": NEW_KEY}),
                 ("POST", f"/api/photo-sources/{made['id']}/sync", None)]
        with ping() as pong:
            for who in ("ben", "cy"):
                for method, path, body in calls:
                    with self.subTest(who=who, call=f"{method} {path}"):
                        self.assertEqual(self.call(who, method, path, body), (404, {"error": photosources.NO_SOURCE}))
            pong.assert_not_called()
            for method, path, body in calls[:1] + calls[2:]:
                with self.subTest(call=f"{method} {path}"):
                    self.assertEqual(self.call("ana", method, path, body)[0], 200)
            for method, path, body in calls:
                self.assertEqual(self.call("ana", method, path.replace(str(made["id"]), "99999"), body), (404, {"error": photosources.NO_SOURCE}))
                self.assertEqual(self.call("ana", method, path.replace(str(made["id"]), "x"), body), (404, {"error": photosources.NO_SOURCE}))
        self.assertEqual(self.ok("ana", "DELETE", f"/api/photo-sources/{made['id']}"), {"ok": True})
        self.assertEqual(self.call("ana", "DELETE", f"/api/photo-sources/{made['id']}"), (404, {"error": photosources.NO_SOURCE}))

    def test_a_new_key_must_belong_to_the_same_immich_account(self):
        made = self.connect()
        with ping(OTHER):
            status, got = self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY})
        self.assertEqual((status, got), (400, {"error": photosources.OTHER_ACCOUNT}))
        self.assertEqual(self.unlocked(made["id"]), KEY)
        with db.session() as conn:
            photo_sources.mark(conn, made["id"], "refused", immich.REFUSED)
        with ping() as pong:
            got = self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY})
        self.assertEqual(pong.call_args.args[0], immich.Source(url=URL, key=NEW_KEY, allow_http=False))
        self.assertEqual((got["status"], got["last_error"]), ("ok", None))
        self.assertEqual(self.unlocked(made["id"]), NEW_KEY)
        self.assertEqual(self.raw(made["id"])[3], ACCOUNT.user_id)
        with failing(immich.Refused(immich.REFUSED)):
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": KEY}), (400, {"error": immich.REFUSED}))
        self.assertEqual(self.unlocked(made["id"]), NEW_KEY)

    def test_pausing_turns_the_library_off_until_it_is_resumed(self):
        made = self.connect()
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {}), (400, {"error": "Send \"key\", \"label\" or \"paused\""}))
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": "yes"})[0], 400)
        off = self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.assertEqual(off["status"], "off")
        with ping():
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})["name"], "Ana Example")
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY})["status"], "off")
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True, "label": "Mine"})["status"], "off")
        back = self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False})
        self.assertEqual((back["status"], back["label"], back["last_error"]), ("ok", "Mine", None))
        self.assertIsNone(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"label": None})["label"])

    def test_testing_with_the_saved_key_records_the_outcome_and_a_typed_key_saves_nothing(self):
        made = self.connect()
        with failing(immich.Refused(immich.REFUSED)):
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {}), (400, {"error": immich.REFUSED}))
        self.assertEqual(self.raw(made["id"])[1:3], ("refused", immich.REFUSED))
        with failing(immich.Unavailable(immich.UNREACHABLE)):
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})[0], 502)
        self.assertEqual(self.raw(made["id"])[1:3], ("unreachable", immich.UNREACHABLE))
        with ping() as pong:
            got = self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})
        self.assertEqual(got, {"name": "Ana Example", "same_account": True})
        self.assertEqual(pong.call_args.args[0], immich.Source(url=URL, key=KEY, allow_http=False, user_id=ACCOUNT.user_id))
        self.assertEqual(self.raw(made["id"])[1:3], ("ok", None))
        with ping(OTHER) as pong:
            got = self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/test", {"key": NEW_KEY})
        self.assertEqual(got, {"name": "Someone Else", "same_account": False})
        self.assertEqual(pong.call_args.args[0], immich.Source(url=URL, key=NEW_KEY, allow_http=False))
        with failing(immich.Refused(immich.REFUSED)):
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {"key": NEW_KEY})[0], 400)
        self.assertEqual(self.raw(made["id"])[1:3], ("ok", None))
        self.assertEqual(self.unlocked(made["id"]), KEY)
        with ping() as pong:
            self.assertEqual(self.ok("ana", "POST", "/api/photo-sources/test", {"url": LAN, "key": NEW_KEY}), {"name": "Ana Example", "same_account": None})
        self.assertEqual(pong.call_args.args[0], immich.Source(url=LAN, key=NEW_KEY, allow_http=True))
        self.assertEqual(len(self.listing("ana")["sources"]), 1)

    def test_testing_a_paused_library_records_the_outcome_without_resuming_it(self):
        made = self.connect()
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})["status"], "off")
        with failing(immich.Refused(immich.REFUSED)):
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})[0], 400)
        self.assertEqual(self.raw(made["id"])[1:3], ("off", immich.REFUSED))
        with ping():
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})["name"], "Ana Example")
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == made["id"]).values(api_key="enc:v1:not-a-token"))
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})[0], 400)
        self.assertEqual(self.raw(made["id"])[1:3], ("off", photosources.KEY_LOST))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False})["status"], "ok")

    def test_a_former_steward_whose_request_is_in_flight_changes_nothing(self):
        made = self.connect(person_id=self.guest)

        def handed_over(_source):
            with db.session() as conn:
                photogrants.claim(conn, self.guest, self.person["ben"], "sub-ben")
            return ACCOUNT
        with mock.patch.object(immich, "ping", side_effect=handed_over):
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY}), (404, {"error": photosources.NO_SOURCE}))
        self.assertEqual(self.unlocked(made["id"]), KEY)
        self.assertEqual(self.raw(made["id"])[1:3], ("ok", None))
        self.assertEqual(self.ok("ben", "POST", f"/api/photo-sources/{made['id']}", {"label": "Mine now"})["label"], "Mine now")

    def meanwhile(self, source_id, status):
        def change(_source):
            with db.session() as conn:
                photo_sources.mark(conn, source_id, status, None)
            return ACCOUNT
        return mock.patch.object(immich, "ping", side_effect=change)

    def test_a_pause_made_while_a_test_waits_on_immich_survives_the_test(self):
        made = self.connect()
        with self.meanwhile(made["id"], "off"):
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})["name"], "Ana Example")
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False})["status"], "ok")
        with self.meanwhile(made["id"], "off"):
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY})["status"], "off")
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        self.assertEqual(self.unlocked(made["id"]), NEW_KEY)

    def test_a_resume_made_while_a_test_waits_on_immich_survives_the_test(self):
        made = self.connect()
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})["status"], "off")

        def resumed_then_refused(_source):
            with db.session() as conn:
                photo_sources.mark(conn, made["id"], "ok", None)
            raise immich.Refused(immich.REFUSED)
        with mock.patch.object(immich, "ping", side_effect=resumed_then_refused):
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})[0], 400)
        self.assertEqual(self.raw(made["id"])[1:3], ("refused", immich.REFUSED))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})["status"], "off")
        with self.meanwhile(made["id"], "ok"):
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})["name"], "Ana Example")
        self.assertEqual(self.raw(made["id"])[1:3], ("ok", None))

    def shared(self, who, scope="trip", revoked=None):
        trip = self.book(who, travelers=[{"person_id": self.person[who]}])["trip_id"]
        with db.session() as conn:
            conn.orm.add(PhotoGrant(person_id=self.person[who], trip_id=trip, scope=scope, revoked=revoked, changed=1.0, granted_by=f"sub-{who}"))
            conn.orm.flush()
        return trip

    def test_a_library_connected_under_an_active_trip_grant_starts_paused(self):
        self.shared("ana")
        self.shared("ben", scope="only_me")
        self.shared("cy", revoked=2.0)
        made = self.connect()
        self.assertEqual((made["status"], self.raw(made["id"])[1:3]), ("off", ("off", None)))
        self.assertEqual(self.connect(who="ben")["status"], "ok")
        self.assertEqual(self.connect(who="cy")["status"], "ok")
        self.assertEqual(self.connect(url=LAN, person_id=self.guest)["status"], "ok")
        with ping():
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})["name"], "Ana Example")
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))

    def test_resuming_under_an_active_trip_grant_waits_for_a_confirmation_that_is_not_here_yet(self):
        made = self.connect()
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})["status"], "off")
        self.shared("ana")
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False}), (409, {"error": photosources.RESUME_ASKS}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True, "label": "Still off"})["status"], "off")
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"label": "Named"})["status"], "off")
        theirs = self.connect(who="ben")
        self.assertEqual(self.ok("ben", "POST", f"/api/photo-sources/{theirs['id']}", {"paused": True})["status"], "off")
        self.assertEqual(self.ok("ben", "POST", f"/api/photo-sources/{theirs['id']}", {"paused": False})["status"], "ok")

    def test_a_key_that_can_no_longer_be_unlocked_asks_to_be_entered_again(self):
        made = self.connect()
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == made["id"]).values(api_key="enc:v1:not-a-token"))
        with ping() as pong:
            self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {}), (400, {"error": photosources.KEY_LOST}))
        pong.assert_not_called()
        self.assertEqual(self.raw(made["id"])[1:3], ("refused", photosources.KEY_LOST))
        with ping():
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY})["status"], "ok")
        self.assertEqual(self.unlocked(made["id"]), NEW_KEY)

    def test_sync_now_answers_whether_a_run_started(self):
        made = self.connect()
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/sync"), {"started": False})
        with mock.patch.object(jobs, "sync_photos_now", return_value=True) as started:
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/sync"), {"started": True})
        started.assert_called_once_with(made["id"])

    def test_removing_a_library_takes_its_photos_with_it(self):
        trip = self.book("ana", travelers=[{"person_id": self.person["ana"]}])["trip_id"]
        made, kept = self.connect(), self.connect(url=LAN)
        with db.session() as conn:
            conn.orm.add_all([photo(made["id"], trip, 1), photo(made["id"], None, 2, "ambiguous"), photo(kept["id"], trip, 3)])
            conn.orm.flush()
        self.assertEqual(self.ok("ana", "DELETE", f"/api/photo-sources/{made['id']}"), {"ok": True})
        with db.session() as conn:
            self.assertEqual(sorted(conn.execute(select(Photo.source_id)).scalars()), [kept["id"]])
        self.assertEqual([s["id"] for s in self.listing("ana")["sources"]], [kept["id"]])

    def test_the_key_never_reaches_a_reply_a_log_line_or_the_database_in_the_clear(self):
        with no_leaks(self, KEY, NEW_KEY, database=self.path):
            made = self.connect()
            replies = [made, self.listing("ana"), self.listing("ben")]
            with failing(immich.Refused(immich.REFUSED)):
                replies.append(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {})[1])
                replies.append(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY})[1])
            with failing(RuntimeError(f"boom {NEW_KEY}")):
                replies.append(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {"key": NEW_KEY})[1])
            with ping():
                replies.append(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY}))
                replies.append(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}/test", {}))
            with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ben@example.com"}):
                jobs.sweep_lapsed()
            self.assertEqual(self.listing("ana")["sources"], [])
        text_ = json.dumps(replies)
        for canary in (KEY, NEW_KEY, "api_key", "immich_user_id", "owner_sub"):
            self.assertNotIn(canary, text_, canary)

    def test_the_sweep_ends_the_libraries_of_a_member_who_can_no_longer_sign_in(self):
        trip = self.book("ana", travelers=[{"person_id": self.person["ana"]}])["trip_id"]
        gone, kept, stewarded = self.connect(who="ben"), self.connect(), self.connect(who="ben", url=LAN, person_id=self.guest)
        with db.session() as conn:
            conn.orm.add_all([photo(gone["id"], trip, 1), photo(kept["id"], trip, 2), photo(stewarded["id"], trip, 3)])
            conn.orm.flush()
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com,cy@example.com"}):
            with db.session() as conn:
                self.assertEqual(photosources.end_lapsed(conn), 2)
            with db.session() as conn:
                self.assertEqual(photosources.end_lapsed(conn), 0)
        with db.session() as conn:
            self.assertEqual([s["id"] for s in photo_sources.list_all(conn)], [kept["id"]])
            self.assertEqual(sorted(conn.execute(select(Photo.source_id)).scalars()), [kept["id"]])

    def test_the_hourly_job_runs_the_sweep_logs_a_count_and_survives_a_failure(self):
        self.connect(who="ben")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com"}), contextlib.redirect_stdout(out):
            jobs.sweep_lapsed()
        self.assertIn("1 Immich library connection(s)", out.getvalue())
        self.assertEqual(self.listing("ana")["sources"], [])
        with mock.patch.object(photosources, "end_lapsed", side_effect=RuntimeError("boom")), contextlib.redirect_stderr(io.StringIO()):
            jobs.sweep_lapsed()

    def test_assistants_never_reach_the_source_routes(self):
        for pattern in PATTERNS:
            self.assertTrue(mcp_access.blocked(pattern), pattern)
            for method in ("GET", "POST", "DELETE"):
                self.assertIsNone(mcp_http.needs(method, pattern), f"{method} {pattern}")
        self.assertEqual({p for _m, p, *_ in ROUTES if p.startswith("/api/photo-sources")}, set(PATTERNS))


class LocalMode(ServerCase):
    unset = ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_ALLOWED_EMAILS")

    def test_photos_are_off_without_sign_in_so_every_source_route_answers_404(self):
        with ping() as pong:
            for method, path, body in (("GET", "/api/photo-sources", None), ("POST", "/api/photo-sources", {"url": URL, "key": KEY}),
                                       ("POST", "/api/photo-sources/test", {"url": URL, "key": KEY}), ("POST", "/api/photo-sources/1", {"label": "x"}),
                                       ("DELETE", "/api/photo-sources/1", None), ("POST", "/api/photo-sources/1/test", {}), ("POST", "/api/photo-sources/1/sync", None)):
                with self.subTest(call=f"{method} {path}"):
                    self.assertEqual(self.req(method, path, body), (404, {"error": "Photos are off without sign-in."}))
            pong.assert_not_called()
        self.assertEqual(self.req("GET", "/api/people")[0], 200)
        with db.session() as conn:
            self.assertEqual(photo_sources.list_all(conn), [])


class Storage(DbCase):
    def setUp(self):
        super().setUp()
        self.person = people.add_guest(self.c, guest("Mia Doe"))["id"]
        self.source = photo_sources.save(self.c, self.person, "sub-ana", URL, ACCOUNT.user_id, KEY, None, 1.0)
        self.c.commit()

    def raw(self):
        return self.c.execute(select(PhotoSource.api_key).where(PhotoSource.id == self.source)).scalar()

    def test_the_key_is_encrypted_at_rest_and_listed_nowhere(self):
        self.assertTrue(self.raw().startswith("enc:v1:"))
        self.assertNotIn(KEY, self.raw())
        for found in (photo_sources.list_all(self.c)[0], photo_sources.get(self.c, self.source), photo_sources.for_person(self.c, self.person)[0]):
            self.assertNotIn("api_key", found or {})
            self.assertNotIn(KEY, json.dumps(found))
        unlocked = photo_sources.source_for_provider(self.c, self.source)
        assert unlocked is not None
        self.assertEqual((unlocked.key, unlocked.url, unlocked.user_id), (KEY, URL, ACCOUNT.user_id))
        self.assertNotIn(KEY, repr(unlocked))
        self.assertIsNone(photo_sources.source_for_provider(self.c, 999))
        self.assertIsNone(photo_sources.get(self.c, 999))

    def test_rotating_the_secret_key_re_encrypts_a_saved_library_key(self):
        old = os.environ["WAYPOINT_SECRET_KEY"]
        new = "a-brand-new-key-abcdefghijklmnopqrstuvwxyz"
        sealed = self.raw()
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": new, "WAYPOINT_SECRET_KEY_OLD": old}):
            self.assertEqual(secretbox.encrypt_stored(self.c), 1)
            self.assertNotEqual(self.raw(), sealed)
            self.assertEqual(secretbox.encrypt_stored(self.c), 0)
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": new}):
            found = photo_sources.source_for_provider(self.c, self.source)
            assert found is not None
            self.assertEqual(found.key, KEY)
            self.assertEqual(backup.unreadable_secrets(self.c), [])
        with self.assertRaises(secretbox.SecretError):
            photo_sources.source_for_provider(self.c, self.source)
        self.assertEqual(backup.unreadable_secrets(self.c), [backup.PHOTO_SOURCES])
        self.assertIn("Immich library keys", backup.unreadable_summary([backup.PHOTO_SOURCES]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(secretbox.encrypt_stored(self.c), 0)
        self.assertIn("Immich library's key can't be decrypted", out.getvalue())
        self.assertNotIn(KEY, out.getvalue())

    def test_a_key_lost_at_start_marks_the_library_until_it_is_entered_again(self):
        paused = photo_sources.save(self.c, self.person, "sub-ana", LAN, ACCOUNT.user_id, NEW_KEY, None, 1.0, "off")
        self.c.commit()
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": "a-brand-new-key-abcdefghijklmnopqrstuvwxyz"}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(secretbox.encrypt_stored(self.c), 0)
        found = {s["id"]: s for s in photo_sources.list_all(self.c)}
        self.assertEqual((found[self.source]["status"], found[self.source]["last_error"]), ("refused", photosources.KEY_LOST))
        self.assertEqual((found[paused]["status"], found[paused]["last_error"]), ("off", photosources.KEY_LOST))
        photo_sources.set_key(self.c, self.source, KEY)
        photo_sources.mark(self.c, self.source, "ok", None)
        self.assertEqual(secretbox.encrypt_stored(self.c), 0)
        self.assertEqual(photo_sources.get(self.c, self.source)["status"], "ok")

    def test_a_plain_key_is_sealed_at_start(self):
        self.c.execute(update(PhotoSource).where(PhotoSource.id == self.source).values(api_key=NEW_KEY))
        self.assertEqual(secretbox.encrypt_stored(self.c), 1)
        self.assertTrue(self.raw().startswith("enc:v1:"))
        found = photo_sources.source_for_provider(self.c, self.source)
        assert found is not None
        self.assertEqual(found.key, NEW_KEY)

    def test_marking_and_removing(self):
        photo_sources.mark(self.c, self.source, "refused", immich.REFUSED)
        found = photo_sources.get(self.c, self.source)
        assert found is not None
        self.assertEqual((found["status"], found["last_error"], found["last_sync"]), ("refused", immich.REFUSED, None))
        photo_sources.mark(self.c, self.source, "ok", None, 5.0)
        found = photo_sources.get(self.c, self.source)
        assert found is not None
        self.assertEqual((found["status"], found["last_error"], found["last_sync"]), ("ok", None, 5.0))
        self.c.execute(update(PhotoSource).where(PhotoSource.id == self.source).values(status="weird"))
        self.assertEqual(photo_sources.list_all(self.c)[0]["status"], "unreachable")
        self.assertTrue(photo_sources.remove(self.c, self.source))
        self.assertFalse(photo_sources.remove(self.c, self.source))
        self.assertEqual(photo_sources.counts(self.c), {})

    def test_the_sweep_does_nothing_without_sign_in(self):
        self.assertEqual(photosources.end_lapsed(self.c), 0)
        self.assertEqual(len(photo_sources.list_all(self.c)), 1)

    def test_unlocking_builds_the_providers_source(self):
        found = photosources.unlock(self.c, self.source)
        self.assertEqual(found, immich.Source(url=URL, key=KEY, allow_http=False, user_id=ACCOUNT.user_id))
        self.assertIsNone(photosources.unlock(self.c, 999))
        self.assertTrue(photosources.allow_http("http://192.168.1.20:2283"))
        self.assertFalse(photosources.allow_http("http://immich-canary.example"))


class Races(DbCase):
    def setUp(self):
        super().setUp()
        oidc.remember_user(self.c, "sub-ana", "ana@example.com", "Ana", None)
        oidc.remember_user(self.c, "sub-ben", "ben@example.com", "Ben", None)
        self.c.commit()
        self.ana = photosources.Actor("sub-ana", people.person_for_sub(self.c, "sub-ana"))
        self.ben = photosources.Actor("sub-ben", people.person_for_sub(self.c, "sub-ben"))
        self.guest = people.add_guest(self.c, guest("Mia Doe"))["id"]
        self.c.commit()

    def elsewhere(self, change):
        def during(_source):
            with db.session(self.path) as conn:
                change(conn)
            return ACCOUNT
        return mock.patch.object(immich, "ping", side_effect=during)

    def test_two_members_connecting_at_once_cannot_both_become_a_persons_steward(self):
        with self.elsewhere(lambda conn: photo_sources.save(conn, self.guest, "sub-ben", LAN, ACCOUNT.user_id, KEY, None, 1.0)):
            with self.assertRaises(photosources.Refused) as refused:
                photosources.connect(self.c, self.ana, self.guest, URL, KEY, None)
        self.assertEqual(str(refused.exception), photosources.OTHER_STEWARD)
        self.c.rollback()
        self.assertEqual([(s["url"], s["owner_sub"]) for s in photo_sources.list_all(self.c)], [(LAN, "sub-ben")])
        self.assertEqual(photo_sources.steward_of(self.c, self.guest), None)

    def test_a_steward_recorded_at_once_by_another_member_wins_over_a_connect_in_flight(self):
        def stewarded(conn):
            photo_sources.set_steward(conn, self.guest, "sub-ben")
        with self.elsewhere(stewarded):
            with self.assertRaises(photosources.Refused) as refused:
                photosources.connect(self.c, self.ana, self.guest, URL, KEY, None)
        self.assertEqual(str(refused.exception), photosources.OTHER_STEWARD)
        self.c.rollback()
        self.assertEqual(photo_sources.list_all(self.c), [])
        self.assertEqual(photo_sources.steward_of(self.c, self.guest), "sub-ben")

    def test_the_same_address_connected_twice_at_once_is_one_library(self):
        with self.elsewhere(lambda conn: photo_sources.save(conn, self.ana.person_id, "sub-ana", URL, ACCOUNT.user_id, KEY, None, 1.0)):
            with self.assertRaises(photosources.Refused) as refused:
                photosources.connect(self.c, self.ana, self.ana.person_id, URL, NEW_KEY, None)
        self.assertEqual(str(refused.exception), photosources.ALREADY)
        self.c.rollback()
        self.assertEqual(len(photo_sources.list_all(self.c)), 1)

    def test_a_library_handed_over_mid_request_is_not_changed_by_its_former_steward(self):
        source = photo_sources.save(self.c, self.guest, "sub-ana", URL, ACCOUNT.user_id, KEY, None, 1.0)
        self.c.commit()

        def moved(conn):
            photogrants.claim(conn, self.guest, self.ben.person_id, "sub-ben")
        with self.elsewhere(moved):
            with self.assertRaises(photosources.NoSuchSource):
                photosources.change_key(self.c, self.ana, source, NEW_KEY)
        self.c.rollback()
        unlocked = photo_sources.source_for_provider(self.c, source)
        assert unlocked is not None
        self.assertEqual(unlocked.key, KEY)
        checked = photosources.owned

        def owned_then_moved(conn, actor, source_id):
            found = checked(conn, actor, source_id)
            with db.session(self.path) as other:
                photogrants.claim(other, self.guest, self.ben.person_id, "sub-ben")
            return found
        for change in (lambda: photosources.edit(self.c, self.ana, source, "Stolen", None, True), lambda: photosources.edit(self.c, self.ana, source, None, True, False),
                       lambda: photosources.remove(self.c, self.ana, source), lambda: photosources.test(self.c, self.ana, source, None)):
            with self.subTest(change=change), mock.patch.object(photosources, "owned", side_effect=owned_then_moved), failing(immich.Refused(immich.REFUSED)):
                with self.assertRaises(photosources.NoSuchSource):
                    change()
                self.c.rollback()
            found = photo_sources.get(self.c, source)
            assert found is not None
            self.assertEqual((found["owner_sub"], found["person_id"], found["label"], found["status"], found["last_error"]), ("sub-ben", self.ben.person_id, None, "ok", None))


    def test_the_sweep_leaves_a_library_handed_to_a_member_who_still_signs_in(self):
        source = photo_sources.save(self.c, self.guest, "sub-ana", URL, ACCOUNT.user_id, KEY, None, 1.0)
        self.c.commit()

        handed = []

        def handed_over(conn, sub, email, now=None):
            if not handed:
                handed.append(sub)
                with db.session(self.path) as other:
                    photogrants.claim(other, self.guest, self.ben.person_id, "sub-ben")
            return "user_removed" if sub == "sub-ana" else None
        with mock.patch.object(oidc, "access_lapsed", side_effect=handed_over):
            self.assertEqual(photosources.end_lapsed(self.c), 0)
        self.c.commit()
        found = photo_sources.get(self.c, source)
        assert found is not None
        self.assertEqual((found["owner_sub"], found["person_id"]), ("sub-ben", self.ben.person_id))
        with mock.patch.object(oidc, "access_lapsed", side_effect=lambda conn, sub, email, now=None: "user_removed" if sub == "sub-ben" else None):
            self.assertEqual(photosources.end_lapsed(self.c), 1)
        self.assertIsNone(photo_sources.get(self.c, source))

    def test_the_sweep_leaves_a_library_whose_owner_signs_in_as_it_runs(self):
        source = photo_sources.save(self.c, self.ana.person_id, "sub-ana", URL, ACCOUNT.user_id, KEY, None, 1.0)
        self.c.execute(update(User).where(User.sub == "sub-ana").values(last_seen=time.time() - 15 * 86400))
        self.c.commit()
        groups = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "", "OIDC_ALLOWED_GROUPS": "household"}
        checked = oidc.access_lapsed

        def signs_in_after_the_check(conn, sub, email, now=None):
            found = checked(conn, sub, email, now)
            if found is not None:
                with db.session(self.path) as other:
                    oidc.remember_user(other, "sub-ana", "ana@example.com", "Ana", None)
            return found
        with mock.patch.dict(os.environ, groups), mock.patch.object(oidc, "access_lapsed", side_effect=signs_in_after_the_check):
            self.assertEqual(photosources.end_lapsed(self.c), 0)
        self.c.commit()
        self.assertIsNotNone(photo_sources.get(self.c, source))
        self.c.execute(update(User).where(User.sub == "sub-ana").values(last_seen=time.time() - 15 * 86400))
        self.c.commit()
        with mock.patch.dict(os.environ, groups):
            self.assertEqual(photosources.end_lapsed(self.c), 1)
        self.assertIsNone(photo_sources.get(self.c, source))

    def test_the_grant_sweep_locks_the_owner_before_its_last_access_check(self):
        trip = trips.add_segment(self.c, Viewer(self.ana.person_id), {**OUT, "travelers": [{"person_id": self.ana.person_id, "name": None}]})
        assert trip is not None
        self.c.orm.add(PhotoGrant(person_id=self.ana.person_id, trip_id=trip["trip_id"], scope="trip", revoked=None, changed=1.0, granted_by="sub-ana"))
        self.c.orm.flush()
        self.c.execute(update(User).where(User.sub == "sub-ana").values(last_seen=time.time() - 15 * 86400))
        self.c.commit()
        groups = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "", "OIDC_ALLOWED_GROUPS": "household"}
        order = []
        checked, locked = oidc.access_lapsed, photo_sources.lock_owner
        with mock.patch.dict(os.environ, groups), \
                mock.patch.object(oidc, "access_lapsed", side_effect=lambda conn, sub, email, now=None: order.append(("check", sub)) or checked(conn, sub, email, now)), \
                mock.patch.object(photo_sources, "lock_owner", side_effect=lambda conn, sub: order.append(("lock", sub)) or locked(conn, sub)):
            self.assertEqual(photogrants.end_lapsed(self.c), 1)
        self.assertIn(("lock", "sub-ana"), order)
        self.assertEqual(order[-1], ("check", "sub-ana"))
        self.assertLess(order.index(("lock", "sub-ana")), len(order) - 1)
        self.assertEqual(self.c.execute(select(PhotoGrant.person_id)).scalars(), [])

    def test_connecting_for_a_guest_who_was_claimed_meanwhile_finds_nobody(self):
        def claimed(conn):
            people.claim_guest(conn, self.ben.person_id, self.guest, "2026-10-05")
        with self.elsewhere(claimed):
            with self.assertRaises(photosources.NoSuchPerson):
                photosources.connect(self.c, self.ana, self.guest, URL, KEY, None)
        self.c.rollback()
        self.assertEqual(photo_sources.list_all(self.c), [])
        self.assertFalse(photo_sources.lock_person(self.c, self.guest))
        self.assertTrue(photo_sources.lock_person(self.c, self.ben.person_id))


class Claiming(DbCase):
    def setUp(self):
        super().setUp()
        oidc.remember_user(self.c, "u1", "jane@example.com", "Jane Doe", "Jane")
        self.member = people.person_for_sub(self.c, "u1")
        self.guest = people.add_guest(self.c, guest("J. Doe"))["id"]

    def test_claiming_a_guest_hands_their_libraries_to_the_member_one_per_immich_account(self):
        moved = photo_sources.save(self.c, self.guest, "sub-steward", URL, ACCOUNT.user_id, KEY, "Mia’s", 1.0)
        other_user = photo_sources.save(self.c, self.guest, "sub-steward", LAN, ACCOUNT.user_id, NEW_KEY, None, 1.0)
        merged = photo_sources.save(self.c, self.guest, "sub-steward", "https://third-canary.example", ACCOUNT.user_id, NEW_KEY, None, 1.0)
        mine = photo_sources.save(self.c, self.member, "u1", LAN, OTHER.user_id, KEY, None, 1.0)
        twin = photo_sources.save(self.c, self.member, "u1", "https://third-canary.example", ACCOUNT.user_id, KEY, None, 1.0)
        assert moved and other_user and merged and mine and twin
        self.c.orm.add(photo(merged, None, 1, "ambiguous"))
        self.c.orm.flush()
        photo_sources.set_steward(self.c, self.guest, "sub-steward")
        people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertIsNone(self.c.orm.get(PhotoSharingPrefs, self.guest))
        prefs = self.c.orm.get(PhotoSharingPrefs, self.member)
        assert prefs is not None
        self.assertIsNone(prefs.steward_sub)
        found = {s["id"]: s for s in photo_sources.list_all(self.c)}
        self.assertEqual(sorted(found), [moved, other_user, mine, twin])
        self.assertEqual({(s["person_id"], s["owner_sub"]) for s in found.values()}, {(self.member, "u1")})
        self.assertEqual((found[moved]["label"], found[other_user]["immich_user_id"], found[mine]["immich_user_id"]), ("Mia’s", ACCOUNT.user_id, OTHER.user_id))
        self.assertEqual(self.c.execute(select(Photo.source_id)).scalars(), [twin])
        for source, key in ((moved, KEY), (other_user, NEW_KEY), (twin, KEY)):
            unlocked = photo_sources.source_for_provider(self.c, source)
            assert unlocked is not None
            self.assertEqual(unlocked.key, key)

    def test_claiming_locks_the_guest_before_moving_their_libraries(self):
        order = []
        lock, move = photo_sources.lock_person, photogrants.claim
        with mock.patch.object(photo_sources, "lock_person", side_effect=lambda conn, person: order.append(("lock", person)) or lock(conn, person)), \
                mock.patch.object(photogrants, "claim", side_effect=lambda conn, *rest: order.append(("move", rest[0])) or move(conn, *rest)):
            people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertEqual(order, [("lock", self.guest), ("move", self.guest)])

    def test_claiming_writes_no_key_anywhere(self):
        photo_sources.save(self.c, self.guest, "sub-steward", URL, ACCOUNT.user_id, KEY, None, 1.0)
        self.c.commit()
        with no_leaks(self, KEY, database=self.path):
            people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
            self.c.commit()


if __name__ == "__main__":
    unittest.main()
