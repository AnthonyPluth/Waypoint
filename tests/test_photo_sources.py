import contextlib
import gc
import io
import json
import os
import time
import unittest
import weakref
from unittest import mock

from sqlalchemy import delete, select, update

from tests.privacy import no_leaks
from tests.shared import DbCase, ServerCase
from tests.test_trips import BACK, OUT, RouteCase, guest
from waypoint import oidc
from waypoint.domain import people, photogrants, photomatch, photos, photosources, trips
from waypoint.domain.visibility import Viewer
from waypoint.providers import immich
from waypoint.server import ROUTES, jobs, mcp_access, mcp_http
from waypoint.storage import backup, db, photo_sources, secretbox
from waypoint.storage.models import Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, Segment, User

URL = "https://immich-canary-8h2k.example:2283"
LAN = "http://immich.local:2283"
KEY = "canary-immich-key-5m7p2w"
NEW_KEY = "canary-immich-key-second-x1"
ACCOUNT = immich.Account(user_id="immich-user-canary-1", name="Ana Example", email="ana@immich.example")
OTHER = immich.Account(user_id="immich-user-canary-2", name="Someone Else", email=None)
PATTERNS = ("/api/photo-sources", "/api/photo-sources/test", "/api/photo-sources/{id}", "/api/photo-sources/{id}/test", "/api/photo-sources/{id}/sync",
            "/api/photo-sources/{id}/resume")
LATER = {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}
CANARY_ASSET = "0a000000-0000-4000-8000-00000000c4a1"


def item(number, taken="2026-06-02T09:00:00.000Z", owner=ACCOUNT.user_id, gps=None, ident=None):
    lat, lon = gps or (None, None)
    return {"id": ident or f"0a000000-0000-4000-8000-{number:012d}", "type": "IMAGE", "ownerId": owner, "localDateTime": taken, "fileCreatedAt": taken,
            "updatedAt": "2026-06-20T00:00:00.000Z", "exifInfo": {"timeZone": None, "latitude": lat, "longitude": lon, "state": None, "country": None}}


def library(*pages):
    asked = []

    def search(source, taken_after, taken_before, *, updated_after=None, page=1):
        asked.append((source, taken_after, taken_before, page))
        index = min(len(asked), len(pages)) - 1
        items = pages[index]
        return immich.parse_page({"assets": {"items": items, "nextPage": str(page + 1) if index < len(pages) - 1 else None}}, page, source.user_id)
    patched = mock.patch.object(immich, "search", side_effect=search)
    patched.asked = asked
    return patched


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

    def test_an_address_with_its_default_port_is_the_same_library(self):
        first = self.connect(url="https://immich-canary.example")
        self.assertEqual(first["url"], "https://immich-canary.example")
        with ping():
            self.assertEqual(self.call("ana", "POST", "/api/photo-sources", {"url": "https://immich-canary.example:443", "key": NEW_KEY}),
                             (409, {"error": photosources.ALREADY}))
        lan = self.connect(url="http://immich.local:80/")
        self.assertEqual(lan["url"], "http://immich.local")
        with ping():
            self.assertEqual(self.call("ana", "POST", "/api/photo-sources", {"url": "http://immich.local", "key": NEW_KEY})[0], 409)
        self.assertEqual(len(self.listing("ana")["sources"]), 2)

    def test_a_library_saved_with_its_default_port_before_is_still_found_as_a_duplicate(self):
        with db.session() as conn:
            photo_sources.save(conn, self.person["ana"], "sub-ana", "https://immich-canary.example:443", ACCOUNT.user_id, KEY, None, 1.0)
        with ping():
            self.assertEqual(self.call("ana", "POST", "/api/photo-sources", {"url": "https://immich-canary.example", "key": NEW_KEY}),
                             (409, {"error": photosources.ALREADY}))
        self.assertEqual(len(self.listing("ana")["sources"]), 1)

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
        theirs = self.connect(who="ben", url=LAN, label="Ben’s private name")
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
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False}), (400, {"error": photosources.KEY_LOST}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", photosources.KEY_LOST))
        with ping():
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY})["status"], "off")
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False})["status"], "ok")

    def test_a_new_key_and_a_resume_in_one_request_take_the_person_before_writing_the_library(self):
        made = self.connect()
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})["status"], "off")
        order = []
        person, keyed, marked = photo_sources.lock_person, photo_sources.set_key, photo_sources.mark
        with mock.patch.object(photo_sources, "lock_person", side_effect=lambda conn, person_id: order.append("person") or person(conn, person_id)), \
                mock.patch.object(photo_sources, "set_key", side_effect=lambda *a, **k: order.append("write") or keyed(*a, **k)), \
                mock.patch.object(photo_sources, "mark", side_effect=lambda *a, **k: order.append("write") or marked(*a, **k)), ping():
            self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY, "paused": False})["status"], "ok")
        self.assertEqual(order[0], "person")
        self.assertIn("write", order)
        self.assertEqual(self.unlocked(made["id"]), NEW_KEY)

    def test_a_library_whose_key_was_lost_stays_off_through_a_pause_until_the_key_is_entered_again(self):
        made = self.connect()
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == made["id"]).values(api_key="enc:v1:not-a-token"))
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}/test", {}), (400, {"error": photosources.KEY_LOST}))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})["last_error"], photosources.KEY_LOST)
        self.assertEqual(self.raw(made["id"])[1:3], ("off", photosources.KEY_LOST))
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False, "label": "Back"}), (400, {"error": photosources.KEY_LOST}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", photosources.KEY_LOST))
        self.assertIsNone(self.listing("ana")["sources"][0]["label"])
        with ping():
            self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"key": NEW_KEY})
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False})["status"], "ok")
        self.assertEqual(self.raw(made["id"])[1:3], ("ok", None))
        self.assertEqual(self.unlocked(made["id"]), NEW_KEY)

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

    def shared(self, who, scope="trip", revoked=None, segment=None):
        trip = self.book(who, segment or OUT, travelers=[{"person_id": self.person[who]}])["trip_id"]
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

    def resume(self, source_id, seen, who="ana"):
        return self.call(who, "POST", f"/api/photo-sources/{source_id}", {"paused": False, "snapshot": seen["snapshot"]})

    def check(self, source_id, *pages, who="ana"):
        patched = library(*pages)
        with patched:
            got = self.call(who, "GET", f"/api/photo-sources/{source_id}/resume")
        self.asked = patched.asked
        return got

    def test_resuming_under_an_active_trip_grant_shows_the_count_and_needs_the_snapshot(self):
        made = self.connect()
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})["status"], "off")
        trip = self.shared("ana")
        quiet = self.shared("ana", scope="only_me", segment=LATER)
        with db.session() as conn:
            conn.orm.add(PhotoExclusion(person_id=self.person["ana"], asset_id=item(3)["id"], trip_id=trip, created=2.0, was_trip_id=None))
            conn.orm.flush()
            window = photos.window_out(photos.trip_window(conn, trip))
        status, seen = self.check(made["id"], [item(1), item(2), item(2), item(3), item(4, owner="partner-canary"), item(5, taken="2026-03-01T09:00:00.000Z")])
        self.assertEqual(status, 200, seen)
        self.assertEqual(seen, {"asks": True, "count": 2, "grants": [{"trip_id": trip, "changed": 1.0, "window": window}],
                                "snapshot": seen["snapshot"]})
        self.assertRegex(seen["snapshot"], r"\A[0-9a-f]{64}\Z")
        self.assertNotIn(quiet, [g["trip_id"] for g in seen["grants"]])
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.asked[0][0], immich.Source(url=URL, key=KEY, allow_http=False, user_id=ACCOUNT.user_id))
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False}), (400, {"error": photosources.NEEDS_RESUME_SNAPSHOT}))
        for bad in ({"snapshot": 7}, {"snapshot": ["x"]}, {"snapshot": "x" * 65}):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False, **bad})[0], 400)
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True, "label": "Still off"})["status"], "off")
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"label": "Named"})["status"], "off")
        status, got = self.resume(made["id"], seen)
        self.assertEqual((status, got["status"], got["label"]), (200, "ok", "Named"))
        status, after = self.check(made["id"])
        self.assertEqual((status, after["asks"], after["count"], after["grants"]), (200, False, 0, seen["grants"]))
        self.assertNotEqual(after["snapshot"], seen["snapshot"])
        self.assertEqual(self.asked, [])
        theirs = self.connect(who="ben")
        self.assertEqual(self.ok("ben", "POST", f"/api/photo-sources/{theirs['id']}", {"paused": True})["status"], "off")
        status, got = self.check(theirs["id"], who="ben")
        self.assertEqual((status, got["asks"], got["count"], got["grants"]), (200, False, 0, []))
        self.assertEqual(self.ok("ben", "POST", f"/api/photo-sources/{theirs['id']}", {"paused": False})["status"], "ok")

    def paused_with_stored(self, *stored):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        trip = self.shared("ana")
        quiet = self.shared("ana", scope="only_me", segment=LATER)
        with db.session() as conn:
            conn.orm.add_all([photo(made["id"], {"trip": trip, "quiet": quiet, None: None}[where], number, match) for where, number, match in stored])
        return made, trip

    def test_a_library_that_synced_before_it_was_paused_counts_only_the_photos_a_resume_would_add(self):
        made, trip = self.paused_with_stored(("trip", 1, "place"), ("trip", 2, "time"), ("trip", 3, "far"), ("quiet", 4, "place"), (None, 5, "ambiguous"), (None, 6, "home"))
        status, seen = self.check(made["id"], [item(n, ident=f"asset-{n}") for n in range(1, 9)])
        self.assertEqual((status, seen["asks"], seen["count"], [g["trip_id"] for g in seen["grants"]]), (200, True, 5, [trip]))
        self.assertEqual(self.resume(made["id"], seen)[1]["status"], "ok")

    def test_a_library_with_every_matching_photo_already_stored_counts_none_and_still_asks(self):
        made, _ = self.paused_with_stored(("trip", 1, "place"), ("trip", 2, "place"))
        status, seen = self.check(made["id"], [item(1, ident="asset-1"), item(2, ident="asset-2")])
        self.assertEqual((status, seen["asks"], seen["count"]), (200, True, 0))

    def test_a_library_with_nothing_stored_counts_every_matching_photo(self):
        made, _ = self.paused_with_stored()
        status, seen = self.check(made["id"], [item(n, ident=f"asset-{n}") for n in range(1, 4)])
        self.assertEqual((status, seen["count"]), (200, 3))

    def test_a_photo_stored_on_one_shared_trip_that_now_matches_another_is_counted(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        first = self.shared("ana")
        second = self.shared("ana", segment=LATER)
        with db.session() as conn:
            conn.orm.add_all([photo(made["id"], first, 1), photo(made["id"], second, 2)])
        status, seen = self.check(made["id"], [item(1, ident="asset-1"), item(2, ident="asset-2")])
        self.assertEqual((status, seen["count"]), (200, 1))

    def test_a_photo_the_owner_pinned_to_one_shared_trip_is_not_counted_for_another(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        first = self.shared("ana")
        second = self.shared("ana", segment=LATER)
        with db.session() as conn:
            pinned = photo(made["id"], second, 2)
            pinned.decided_by = "owner"
            conn.orm.add_all([photo(made["id"], first, 1), pinned, photo(made["id"], second, 3)])
        status, seen = self.check(made["id"], [item(n, ident=f"asset-{n}") for n in (1, 2, 3, 4)])
        self.assertEqual((status, seen["count"]), (200, 2))

    def test_a_photo_stored_for_another_library_does_not_lower_this_librarys_count(self):
        made, trip = self.paused_with_stored(("trip", 1, "place"))
        theirs = self.connect(who="ben")
        with db.session() as conn:
            conn.orm.add(photo(theirs["id"], trip, 2))
        status, seen = self.check(made["id"], [item(1, ident="asset-1"), item(2, ident="asset-2")])
        self.assertEqual((status, seen["count"]), (200, 1))

    def test_the_stored_photos_a_count_leaves_out_are_those_shown_on_the_trips_it_counts(self):
        made, trip = self.paused_with_stored(("trip", 1, "place"), ("trip", 2, "time"), ("trip", 3, "far"), ("trip", 4, "place"), ("quiet", 5, "place"),
                                             (None, 6, "ambiguous"), (None, 7, "home"), ("trip", 8, "none"))
        with db.session() as conn:
            conn.orm.add(PhotoExclusion(person_id=self.person["ana"], asset_id="asset-4", trip_id=trip, created=2.0, was_trip_id=None))
            conn.orm.flush()
            self.assertEqual(photo_sources.shown_assets(conn, made["id"], {trip}), {"asset-1": (trip, False), "asset-2": (trip, False), "asset-3": (trip, False)})
            self.assertEqual(photo_sources.shown_assets(conn, made["id"], set()), {})
            self.assertEqual(photo_sources.shown_assets(conn, made["id"] + 1000, {trip}), {})

    def test_a_connection_under_a_trip_grant_asks_even_when_it_would_add_no_photos(self):
        trip = self.shared("ana")
        made = self.connect()
        self.assertEqual(made["status"], "off")
        status, seen = self.check(made["id"], [])
        self.assertEqual((status, seen["asks"], seen["count"], [g["trip_id"] for g in seen["grants"]]), (200, True, 0, [trip]))
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False}), (400, {"error": photosources.NEEDS_RESUME_SNAPSHOT}))
        self.assertEqual(self.resume(made["id"], seen)[1]["status"], "ok")

    def test_a_count_is_walked_page_by_page_and_a_page_on_one_instant_fails_it(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.shared("ana")
        status, seen = self.check(made["id"], [item(1, "2026-06-02T08:00:00.000Z"), item(2, "2026-06-02T09:00:00.000Z")],
                                  [item(2, "2026-06-02T09:00:00.000Z"), item(3, "2026-06-02T10:00:00.000Z")])
        self.assertEqual((status, seen["count"]), (200, 3))
        self.assertEqual([(a[1].isoformat(), a[3]) for a in self.asked][1], ("2026-06-02T09:00:00+00:00", 1))
        status, got = self.check(made["id"], [item(1), item(2)], [item(3)])
        self.assertEqual((status, got), (502, {"error": photosources.TOO_DENSE}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", photosources.TOO_DENSE))
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": False}), (400, {"error": photosources.NEEDS_RESUME_SNAPSHOT}))

    def test_a_count_immich_refuses_or_runs_out_of_time_shows_no_number(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.shared("ana")
        with mock.patch.object(immich, "search", side_effect=immich.Refused(immich.REFUSED)):
            self.assertEqual(self.call("ana", "GET", f"/api/photo-sources/{made['id']}/resume"), (400, {"error": immich.REFUSED}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", immich.REFUSED))
        with mock.patch.object(photosources, "COUNT_SECONDS", 0.0), library([item(1)]) as searched:
            self.assertEqual(self.call("ana", "GET", f"/api/photo-sources/{made['id']}/resume"), (502, {"error": immich.TOO_SLOW}))
        searched.assert_not_called()
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == made["id"]).values(api_key="enc:v1:not-a-token"))
        self.assertEqual(self.check(made["id"], [item(1)]), (400, {"error": photosources.KEY_LOST}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", photosources.KEY_LOST))

    def test_a_snapshot_taken_before_the_trip_grants_or_libraries_changed_is_refused(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        trip = self.shared("ana")
        fresh = lambda: self.check(made["id"], [item(1)])[1]
        seen = fresh()
        other = self.shared("ana", segment=LATER)
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        with db.session() as conn:
            conn.execute(delete(PhotoGrant).where(PhotoGrant.trip_id == other))
        self.assertEqual(self.resume(made["id"], {"snapshot": "0" * 64}), (409, {"error": photosources.STALE_GRANTS}))
        with db.session() as conn:
            conn.execute(update(PhotoGrant).where(PhotoGrant.trip_id == trip).values(changed=5.0))
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        seen = fresh()
        self.book("ana", BACK, trip_id=trip, travelers=[{"person_id": self.person["ana"]}])
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        seen = fresh()
        with ping(OTHER):
            self.ok("ana", "POST", "/api/photo-sources", {"url": LAN, "key": NEW_KEY})
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        seen = fresh()
        with db.session() as conn:
            conn.orm.add(PhotoExclusion(person_id=self.person["ana"], asset_id=item(1)["id"], trip_id=trip, created=2.0, was_trip_id=None))
            conn.orm.flush()
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        self.assertEqual(self.resume(made["id"], fresh())[1]["status"], "ok")

    def test_the_snapshot_carries_the_home_the_count_used_even_when_home_moves_meanwhile(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.shared("ana")
        real, calls = photos.home_in, []

        def moving(conn):
            calls.append(1)
            return photomatch.HomeIn(40.7128, -74.006, "address") if len(calls) == 1 else real(conn)
        with mock.patch.object(photos, "home_in", side_effect=moving):
            status, seen = self.check(made["id"], [item(1, gps=(40.7128, -74.006))])
        self.assertEqual((status, seen["count"]), (200, 0))
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        seen = self.check(made["id"], [item(1, gps=(40.7128, -74.006))])[1]
        self.assertEqual((seen["count"], self.resume(made["id"], seen)[1]["status"]), (1, "ok"))

    def test_a_point_only_change_to_a_booking_makes_the_snapshot_stale(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        trip = self.shared("ana")
        with db.session() as conn:
            flight = conn.execute(select(Segment.id).where(Segment.trip_id == trip)).scalar()
        seen = self.check(made["id"], [item(1)])[1]
        self.ok("ana", "POST", f"/api/segments/{flight}", {"origin": "EWR"})
        after = self.check(made["id"], [item(1)])[1]
        self.assertEqual(after["grants"], seen["grants"])
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        self.assertEqual(self.resume(made["id"], after)[1]["status"], "ok")

    def test_a_snapshot_counted_for_one_library_cannot_resume_another(self):
        first = self.connect()
        with ping(OTHER):
            second = self.ok("ana", "POST", "/api/photo-sources", {"url": LAN, "key": NEW_KEY})
        self.ok("ana", "POST", f"/api/photo-sources/{first['id']}", {"paused": True})
        self.ok("ana", "POST", f"/api/photo-sources/{second['id']}", {"paused": True})
        self.shared("ana")
        seen = self.check(first["id"], [])[1]
        self.assertEqual(seen["count"], 0)
        self.assertEqual(self.resume(second["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        self.assertEqual(self.raw(second["id"])[1:3], ("off", None))
        self.assertEqual(self.resume(second["id"], self.check(second["id"], [item(1)])[1])[1]["status"], "ok")
        self.assertEqual(self.resume(first["id"], seen), (409, {"error": photosources.STALE_GRANTS}))

    def test_the_count_keeps_only_asset_ids_across_pages(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.shared("ana")
        live, peaks = weakref.WeakSet(), []
        pages = [[item(n, f"2026-06-02T{8 + n:02d}:00:00.000Z"), item(n + 10, f"2026-06-02T{8 + n:02d}:30:00.000Z")] for n in range(4)]
        asked = []

        def search(source, taken_after, taken_before, *, updated_after=None, page=1):
            gc.collect()
            peaks.append(len(live))
            index = len(asked)
            asked.append(index)
            got = immich.parse_page({"assets": {"items": pages[index], "nextPage": "2" if index < len(pages) - 1 else None}}, page, source.user_id)
            live.update(got.assets)
            return got
        with mock.patch.object(immich, "search", side_effect=search):
            status, seen = self.call("ana", "GET", f"/api/photo-sources/{made['id']}/resume")
        self.assertEqual((status, seen["count"], len(asked)), (200, 8, 4))
        self.assertLessEqual(max(peaks), 2)

    def test_a_count_shown_before_home_moved_or_was_cleared_is_refused(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.shared("ana")
        fresh = lambda: self.check(made["id"], [item(1, gps=(40.7128, -74.006))])[1]
        seen = fresh()
        self.ok("ana", "POST", "/api/home", {"city": "Springfield", "state": "IL", "zip": "62701", "country": "US"})
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        seen = fresh()
        self.ok("ana", "POST", "/api/home", {"city": "Portland", "state": "OR", "zip": "97201", "country": "US"})
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        seen = fresh()
        self.ok("ana", "DELETE", "/api/home")
        self.assertEqual(self.resume(made["id"], seen), (409, {"error": photosources.STALE_GRANTS}))
        self.assertEqual(self.raw(made["id"])[1:3], ("off", None))
        seen = fresh()
        self.ok("ana", "POST", "/api/home", {"city": "Portland", "state": "OR", "zip": "97201", "country": "US"})
        seen = fresh()
        self.ok("ana", "POST", "/api/home", {"city": "Portland", "state": "OR", "zip": "97201", "country": "US"})
        self.assertEqual(self.resume(made["id"], seen)[1]["status"], "ok")

    def test_a_page_with_an_asset_immich_described_unusably_fails_the_count(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.shared("ana")
        broken = {**item(2, "2026-06-02T09:00:00.000Z"), "updatedAt": "not a time"}
        for pages in (([item(1, "2026-06-02T08:00:00.000Z"), broken, item(3, "2026-06-02T10:00:00.000Z")], [item(4, "2026-06-02T11:00:00.000Z")]),
                      ([item(1, "2026-06-02T08:00:00.000Z"), broken],)):
            with self.subTest(pages=len(pages)):
                self.assertEqual(self.check(made["id"], *pages), (502, {"error": photosources.TOO_DENSE}))
                self.assertEqual(len(self.asked), 1)
                self.assertEqual(self.raw(made["id"])[1:3], ("off", photosources.TOO_DENSE))

    def test_only_the_libraries_owner_asks_for_its_count(self):
        made = self.connect(person_id=self.guest)
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        for who in ("ben", "cy"):
            with self.subTest(who=who):
                self.assertEqual(self.check(made["id"], [item(1)], who=who), (404, {"error": photosources.NO_SOURCE}))
                self.assertEqual(self.asked, [])
        self.assertEqual(self.check(99999, [item(1)]), (404, {"error": photosources.NO_SOURCE}))
        self.assertEqual(self.check(made["id"], [item(1)])[0], 200)

    def test_a_demo_library_is_counted_without_asking_immich(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.shared("ana")
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == made["id"]).values(url=photosources.photoqueue.DEMO))
        status, seen = self.check(made["id"], [item(1)])
        self.assertEqual((status, seen["asks"], seen["count"], self.asked), (200, True, 0, []))
        self.assertEqual(self.resume(made["id"], seen)[1]["status"], "ok")

    def test_the_count_says_nothing_of_the_key_or_the_photos(self):
        made = self.connect()
        self.ok("ana", "POST", f"/api/photo-sources/{made['id']}", {"paused": True})
        self.shared("ana")
        with no_leaks(self, KEY, CANARY_ASSET, database=self.path):
            status, seen = self.check(made["id"], [item(1, ident=CANARY_ASSET)])
            self.assertEqual((status, seen["count"]), (200, 1))
            with mock.patch.object(immich, "search", side_effect=immich.Unavailable(immich.UNREACHABLE)):
                self.assertEqual(self.call("ana", "GET", f"/api/photo-sources/{made['id']}/resume")[0], 502)
            self.assertEqual(self.resume(made["id"], seen)[1]["status"], "ok")
        self.assertNotIn(CANARY_ASSET, json.dumps(seen))

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


class SnapshotRoutes(RouteCase):
    def setUp(self):
        super().setUp()
        self.trip = self.book("ana", travelers=[{"person_id": self.person["ana"]}])["trip_id"]
        with ping():
            self.library = self.ok("ana", "POST", "/api/photo-sources", {"url": URL, "key": KEY})

    def sharing(self, trip=None):
        return self.ok("ana", "GET", f"/api/trips/{self.trip if trip is None else trip}/photo-sharing")

    def snapshot(self, seen):
        return {"window": seen["window"], "audience": seen["audience"], "sources": seen["sources"]}

    def test_a_first_sharing_confirmed_before_someone_joined_is_refused_by_the_route(self):
        seen = self.sharing()
        self.assertEqual((seen["audience"], seen["sources"]), ([self.person["ana"]], [{"id": self.library["id"], "status": "ok"}]))
        stale = self.snapshot(seen)
        self.book("ana", BACK, trip_id=self.trip, travelers=[{"person_id": self.person["ben"]}])
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip", **stale}), (409, {"error": photogrants.STALE_SHARE}))
        self.assertEqual(self.sharing()["state"], "none")
        fresh = self.sharing()
        got = self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip", **self.snapshot(fresh)})
        self.assertEqual((got["state"], got["audience"], got["sources"]), ("shared", sorted([self.person["ana"], self.person["ben"]]), fresh["sources"]))

    def test_a_library_connected_or_resumed_after_the_snapshot_is_refused_by_the_route(self):
        stale = self.snapshot(self.sharing())
        with ping(OTHER):
            second = self.ok("ana", "POST", "/api/photo-sources", {"url": LAN, "key": NEW_KEY})
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip", **stale}), (409, {"error": photogrants.STALE_SOURCES}))
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{second['id']}", {"paused": True})["status"], "off")
        stale = self.snapshot(self.sharing())
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{second['id']}", {"paused": False})["status"], "ok")
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip", **stale}), (409, {"error": photogrants.STALE_SOURCES}))
        self.assertEqual(self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip", **self.snapshot(self.sharing())})["state"], "shared")
        self.assertEqual(self.ok("ana", "POST", f"/api/photo-sources/{second['id']}", {"paused": True})["status"], "off")
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sources/{second['id']}", {"paused": False}), (400, {"error": photosources.NEEDS_RESUME_SNAPSHOT}))

    def test_share_on_all_confirmed_before_someone_joined_a_pending_trip_is_refused_by_the_route(self):
        seen = self.sharing()
        stale = {"share_all": True, "windows": {str(self.trip): seen["window"]}, "audiences": {str(self.trip): seen["audience"]}, "sources": seen["sources"]}
        self.book("ana", BACK, trip_id=self.trip, travelers=[{"person_id": self.person["ben"]}])
        self.assertEqual(self.call("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", stale), (409, {"error": photogrants.STALE_SETTING}))
        self.assertFalse(self.ok("ana", "GET", "/api/photo-grants")["people"][0]["prefs"]["share_all"])
        fresh = self.sharing()
        got = self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}",
                      {"share_all": True, "windows": {str(self.trip): fresh["window"]}, "audiences": {str(self.trip): fresh["audience"]}, "sources": fresh["sources"]})
        self.assertTrue(got["share_all"])
        self.assertEqual(self.sharing()["state"], "shared")


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

    def test_the_grant_sweep_takes_owners_before_people_as_sign_in_does(self):
        trip = trips.add_segment(self.c, Viewer(self.ana.person_id), {**OUT, "travelers": [{"person_id": self.ana.person_id, "name": None}]})
        assert trip is not None
        self.c.orm.add(PhotoGrant(person_id=self.ana.person_id, trip_id=trip["trip_id"], scope="trip", revoked=None, changed=1.0, granted_by="sub-ana"))
        self.c.orm.flush()
        self.c.execute(update(User).where(User.sub == "sub-ana").values(last_seen=time.time() - 15 * 86400))
        self.c.commit()
        groups = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "", "OIDC_ALLOWED_GROUPS": "household"}
        order = []
        owner, person = photo_sources.lock_owner, people.lock
        with mock.patch.dict(os.environ, groups), \
                mock.patch.object(photo_sources, "lock_owner", side_effect=lambda conn, sub: order.append("owner") or owner(conn, sub)), \
                mock.patch.object(people, "lock", side_effect=lambda conn, person_id: order.append("person") or person(conn, person_id)):
            self.assertEqual(photogrants.end_lapsed(self.c), 1)
        self.assertIn("owner", order)
        self.assertIn("person", order)
        self.assertLess(max(i for i, kind in enumerate(order) if kind == "owner"), min(i for i, kind in enumerate(order) if kind == "person"))

    def paused(self):
        source = photo_sources.save(self.c, self.ana.person_id, "sub-ana", URL, ACCOUNT.user_id, KEY, None, 1.0, "off")
        trip = trips.add_segment(self.c, Viewer(self.ana.person_id), {**OUT, "travelers": [{"person_id": self.ana.person_id, "name": None}]})
        assert source is not None and trip is not None
        self.c.commit()
        return source, trip["trip_id"]

    def test_a_trip_grant_made_while_a_resume_waits_for_the_person_keeps_the_library_paused(self):
        source, trip = self.paused()
        order = []
        real, home = photo_sources.lock_person, photogrants.lock_home

        def granted_first(conn):
            with db.session(self.path) as other:
                other.orm.add(PhotoGrant(person_id=self.ana.person_id, trip_id=trip, scope="trip", revoked=None, changed=1.0, granted_by="sub-ana"))
                other.orm.flush()
            return home(conn)
        shared = photo_sources.trip_shared
        with mock.patch.object(photogrants, "lock_home", side_effect=granted_first), \
                mock.patch.object(photo_sources, "lock_person", side_effect=lambda conn, person_id: order.append("person") or real(conn, person_id)), \
                mock.patch.object(photo_sources, "trip_shared", side_effect=lambda conn, person_id: order.append("shared") or shared(conn, person_id)):
            with self.assertRaises(photosources.Refused) as refused:
                photosources.edit(self.c, self.ana, source, None, False, False)
        self.assertEqual(str(refused.exception), photosources.NEEDS_RESUME_SNAPSHOT)
        self.assertEqual(order, ["person", "shared"])
        self.c.rollback()
        found = photo_sources.get(self.c, source)
        assert found is not None
        self.assertEqual(found["status"], "off")

    def test_a_resume_takes_the_person_before_the_library(self):
        source, _ = self.paused()
        order = []
        person, row = photo_sources.lock_person, photo_sources.lock
        with mock.patch.object(photo_sources, "lock_person", side_effect=lambda conn, person_id: order.append("person") or person(conn, person_id)), \
                mock.patch.object(photo_sources, "lock", side_effect=lambda conn, source_id: order.append("source") or row(conn, source_id)):
            self.assertEqual(photosources.edit(self.c, self.ana, source, "Back", False, True)["status"], "ok")
        self.assertEqual(order, ["person", "source"])

    def test_a_new_key_sent_with_a_resume_takes_the_person_before_writing_the_library(self):
        source, _ = self.paused()
        order = []
        person, row, keyed, marked = photo_sources.lock_person, photo_sources.lock, photo_sources.set_key, photo_sources.mark
        with mock.patch.object(photo_sources, "lock_person", side_effect=lambda conn, person_id: order.append("person") or person(conn, person_id)), \
                mock.patch.object(photo_sources, "lock", side_effect=lambda conn, source_id: order.append("source") or row(conn, source_id)), \
                mock.patch.object(photo_sources, "set_key", side_effect=lambda *a, **k: order.append("write") or keyed(*a, **k)), \
                mock.patch.object(photo_sources, "mark", side_effect=lambda *a, **k: order.append("write") or marked(*a, **k)), ping():
            photosources.change_key(self.c, self.ana, source, NEW_KEY, resuming=True)
            self.assertEqual(photosources.edit(self.c, self.ana, source, None, False, False)["status"], "ok")
        self.assertEqual(order[:2], ["person", "source"])
        self.assertIn("write", order)

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

    def test_claiming_merges_a_library_saved_with_its_default_port_into_the_members(self):
        theirs = photo_sources.save(self.c, self.guest, "sub-steward", "https://third-canary.example:443", ACCOUNT.user_id, NEW_KEY, None, 1.0)
        mine = photo_sources.save(self.c, self.member, "u1", "https://third-canary.example", ACCOUNT.user_id, KEY, None, 1.0)
        assert theirs and mine
        self.c.orm.add(photo(theirs, None, 1, "ambiguous"))
        self.c.orm.flush()
        people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertEqual([s["id"] for s in photo_sources.list_all(self.c)], [mine])
        self.assertEqual(self.c.execute(select(Photo.source_id)).scalars(), [mine])

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
