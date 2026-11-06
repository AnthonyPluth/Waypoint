import json
import os
import threading
from datetime import UTC, datetime, timedelta
from unittest import mock

from sqlalchemy import select, update

from tests.privacy import no_leaks
from tests.test_immich_provider import JSON_HEADERS, serve
from tests.test_photos_api import SOHO
from tests.test_trips import HOTEL, OUT, Household
from waypoint import monitoring
from waypoint.domain import home, people, photogrants, photoqueue, photos, photosync, trips
from waypoint.providers import immich
from waypoint.server import jobs
from waypoint.storage import db, photo_sources
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import Photo, PhotoExclusion, PhotoGrant, PhotoSharingPrefs, PhotoSource, PhotoTripSync

OIDC = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "u-jane@example.com,u-sam@example.com"}
OWNER = "0c000000-0000-4000-8000-0000000000aa"
PARTNER = "0c000000-0000-4000-8000-0000000000bb"
KEY = "canary-sync-key-7t4m2q9z"
TRIP_NAME = "Canary Trip Name 4k8w"
PLACE = "Canarystate Region 3j6v"
FIRST = "canary-asset-sync-0001"
NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
PER_PAGE = 2
LATER_HOTEL = {**HOTEL, "origin": "Second Hotel", "start_local": "2026-06-08T10:00", "end_local": "2026-06-12T10:00"}


def asset(number, taken, *, gps=None, owner=OWNER, updated="2026-06-20T00:00:00.000Z", zone=None, state=None, ident=None):
    lat, lon = gps or (None, None)
    return {"id": ident or f"0a000000-0000-4000-8000-{number:012d}", "type": "IMAGE", "ownerId": owner,
            "localDateTime": taken.replace("Z", ".000Z"), "fileCreatedAt": taken, "updatedAt": updated,
            "exifInfo": {"dateTimeOriginal": taken, "timeZone": zone, "latitude": lat, "longitude": lon, "state": state, "country": None}}


def at(text):
    return datetime.fromisoformat(text)


class Library:
    def __init__(self, case):
        self.fake = serve(case)
        self.items: list[dict] = []
        self.failing: tuple[int, dict] | None = None
        self.on_search = None
        self.fake.routes[immich.SEARCH] = (200, JSON_HEADERS, self.answer)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.fake.server_port}"

    def asked(self):
        return [json.loads(c["body"]) for c in self.fake.calls if c["path"] == immich.SEARCH]

    def answer(self):
        asked = json.loads(self.fake.calls[-1]["body"])
        if self.on_search is not None:
            self.on_search(asked)
        after, before = at(asked["takenAfter"]), at(asked["takenBefore"])
        since = at(asked["updatedAfter"]) if "updatedAfter" in asked else None
        found = sorted((a for a in self.items if after <= at(a["fileCreatedAt"]) <= before and (since is None or at(a["updatedAt"]) > since)),
                       key=lambda a: (a["fileCreatedAt"], a["id"]))
        page = asked["page"]
        items = found[(page - 1) * PER_PAGE:page * PER_PAGE]
        more = len(found) > page * PER_PAGE
        return json.dumps({"assets": {"items": items, "nextPage": str(page + 1) if more else None, "total": len(found), "count": len(items)}}).encode()

    def fail(self, code, headers=None):
        self.fake.routes[immich.SEARCH] = (code, {**JSON_HEADERS, **(headers or {})}, b'{"message":"no"}')

    def heal(self):
        self.fake.routes[immich.SEARCH] = (200, JSON_HEADERS, self.answer)


class SyncCase(Household):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, OIDC)
        env.start()
        self.addCleanup(env.stop)
        self.lib = Library(self)
        self.jid, self.sid = self.jane.person_id, self.sam.person_id
        self.a = self.add(self.jane, OUT, None, self.on(self.jid))["trip_id"]
        self.add(self.jane, HOTEL, self.a)
        self.c.execute(update(trips.Trip).where(trips.Trip.id == self.a).values(name=TRIP_NAME))
        self.b = trips.create_trip(self.c, self.jane, {"name": "Short", "people": [self.jid]})["id"]
        self.add(self.jane, {**HOTEL, "start_local": "2026-06-03T15:00", "end_local": "2026-06-05T10:00"}, self.b)
        self.other = self.add(self.jane, {**OUT, "start_local": "2026-08-01T19:00", "end_local": "2026-08-02T07:10"}, None, self.on(self.jid))["trip_id"]
        self.source = photo_sources.save(self.c, self.jid, "u-jane", self.lib.url, OWNER, KEY, None, 1.0)
        self.share(self.a)
        self.share(self.b)
        self.c.commit()

    def share(self, trip, person=None, scope="trip", revoked=None):
        person = person or self.jid
        row = self.c.orm.get(PhotoGrant, (person, trip))
        if row is not None:
            self.c.orm.delete(row)
            self.c.orm.flush()
        self.c.orm.add(PhotoGrant(person_id=person, trip_id=trip, scope=scope, revoked=revoked, changed=1.0, granted_by="u-jane"))
        self.c.orm.flush()

    def sync(self, now=NOW, **kw):
        return photosync.run(self.c, self.source, immich, now, **kw)

    def rows(self):
        self.c.orm.expire_all()
        return {p.asset_id: p for p in self.c.orm.scalars(select(Photo).order_by(Photo.id)).all()}

    def syncs(self):
        self.c.orm.expire_all()
        return {s.trip_id: s for s in self.c.orm.scalars(select(PhotoTripSync)).all()}

    def stored(self):
        return photo_sources.get(self.c, self.source)


class FirstRunTests(SyncCase):
    def test_a_first_run_writes_rows_only_inside_granted_windows(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO, zone="Europe/London", state="England", ident=FIRST),
                          asset(2, "2026-06-04T12:00:00Z", gps=SOHO),
                          asset(3, "2026-06-02T08:00:00Z"),
                          asset(4, "2026-06-02T13:00:00Z", gps=SOHO, owner=PARTNER),
                          asset(5, "2026-06-20T12:00:00Z", gps=SOHO),
                          asset(6, "2026-08-01T22:00:00Z", gps=SOHO)]
        got = self.sync()
        rows = self.rows()
        self.assertEqual(sorted(rows), sorted([FIRST, self.lib.items[1]["id"], self.lib.items[2]["id"]]))
        first = rows[FIRST]
        self.assertEqual((first.trip_id, first.match, first.location_source, first.decided_by, first.taken_offset, first.state),
                         (self.a, "place", "exif", "auto", 60, "England"))
        self.assertEqual((first.taken_utc, first.taken_local, first.asset_updated), ("2026-06-02T12:00:00.000Z", "2026-06-02T12:00", "2026-06-20T00:00:00.000Z"))
        self.assertEqual(rows[self.lib.items[1]["id"]].trip_id, self.b)
        inferred = rows[self.lib.items[2]["id"]]
        self.assertEqual((inferred.trip_id, inferred.match, inferred.location_source), (self.a, "time", "inferred"))
        windows = {q["takenBefore"] for q in self.lib.asked()}
        self.assertEqual(len(windows), 2)
        self.assertTrue(all("updatedAfter" not in q for q in self.lib.asked()))
        self.assertEqual(set(self.syncs()), {self.a, self.b})
        self.assertTrue(all(s.cursor == NOW.isoformat() and s.resume_after is None and s.fetch_started is None for s in self.syncs().values()))
        self.assertEqual((got.sources, got.new, got.inferred, got.failed, got.budget_hit), (1, 3, 1, 0, 0))
        self.assertEqual(self.stored()["status"], "ok")
        self.assertEqual(self.stored()["last_sync"], NOW.timestamp())
        self.assertIn("3 new", got.line())

    def test_a_second_run_with_no_changes_asks_only_for_what_changed_and_writes_nothing(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO), asset(2, "2026-06-04T12:00:00Z", gps=SOHO)]
        self.sync()
        before = {k: (p.trip_id, p.match, p.seen) for k, p in self.rows().items()}
        calls = len(self.lib.asked())
        later = NOW + timedelta(hours=6)
        got = self.sync(later)
        again = self.lib.asked()[calls:]
        self.assertTrue(again and all(q["updatedAfter"] == "2026-07-01T11:50:00.000Z" for q in again))
        self.assertEqual({k: (p.trip_id, p.match, p.seen) for k, p in self.rows().items()}, before)
        self.assertEqual((got.new, got.seen), (0, 0))
        self.assertTrue(all(s.cursor == later.isoformat() for s in self.syncs().values()))

    def test_a_trip_whose_dates_moved_is_fetched_again_in_full(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO), asset(2, "2026-06-11T12:00:00Z", gps=SOHO)]
        self.sync()
        self.assertEqual(len(self.rows()), 1)
        self.add(self.jane, LATER_HOTEL, self.a)
        self.c.commit()
        calls = len(self.lib.asked())
        self.sync(NOW + timedelta(hours=6))
        for_a = [q for q in self.lib.asked()[calls:] if q["takenBefore"] > "2026-06-10"]
        self.assertTrue(for_a and all("updatedAfter" not in q for q in for_a))
        self.assertEqual(self.rows()[self.lib.items[1]["id"]].trip_id, self.a)

    def test_gps_added_in_immich_rematches_the_photo_by_place(self):
        self.lib.items = [asset(1, "2026-06-02T08:00:00Z")]
        self.sync()
        row = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual((row.match, row.location_source), ("time", "inferred"))
        self.lib.items = [asset(1, "2026-06-02T08:00:00Z", gps=SOHO, updated="2026-07-01T13:00:00.000Z")]
        self.sync(NOW + timedelta(hours=6))
        row = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual((row.match, row.location_source, (row.latitude, row.longitude)), ("place", "exif", SOHO))
        self.lib.items = [asset(1, "2026-06-02T08:00:00Z", updated="2026-07-02T13:00:00.000Z")]
        self.sync(NOW + timedelta(days=1))
        self.assertEqual(self.rows()[self.lib.items[0]["id"]].location_source, "inferred")

    def test_only_the_libraries_own_assets_are_kept(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO, owner=PARTNER)]
        self.sync()
        self.assertEqual(self.rows(), {})

    def test_an_ungranted_or_declined_trip_is_never_searched(self):
        self.share(self.b, revoked=5.0)
        self.c.commit()
        self.lib.items = [asset(1, "2026-06-04T12:00:00Z", gps=SOHO)]
        self.sync()
        self.assertEqual(set(self.syncs()), {self.a})
        self.assertEqual(len({q["takenBefore"] for q in self.lib.asked()}), 1)
        self.assertEqual(self.rows()[self.lib.items[0]["id"]].trip_id, self.a)

    def test_home_photos_inside_a_window_are_kept_but_on_no_trip(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        with mock.patch.object(home, "located", return_value=home.geocode.Point(SOHO[0], SOHO[1], "zip")):
            self.sync()
        row = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual((row.match, row.trip_id), ("home", None))
        with mock.patch.object(home, "located", return_value=home.geocode.Point(SOHO[0], SOHO[1], "zip")):
            self.add(self.jane, LATER_HOTEL, self.a)
            self.c.commit()
            self.sync(NOW + timedelta(hours=6))
        self.assertEqual(self.rows()[self.lib.items[0]["id"]].match, "home")

    def test_nothing_runs_without_sign_in_or_for_a_paused_refused_or_demo_library(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        with mock.patch.dict(os.environ, {"OIDC_ISSUER": ""}):
            self.assertEqual(self.sync().sources, 0)
            self.assertEqual(photosync.sync_all(NOW).sources, 0)
            self.assertFalse(photosync.start(self.source))
        for status in ("off", "refused"):
            photo_sources.mark(self.c, self.source, status)
            self.c.commit()
            self.assertEqual(self.sync().sources, 0)
        self.c.execute(update(PhotoSource).values(url="demo", status="ok"))
        self.c.commit()
        self.assertEqual(self.sync().sources, 0)
        self.assertEqual(self.lib.asked(), [])
        self.assertEqual(photosync.run(self.c, 99999, immich, NOW).sources, 0)


class DecisionTests(SyncCase):
    def test_an_owner_decided_row_keeps_its_trip_and_a_removed_one_stays_removed(self):
        self.lib.items = [asset(1, "2026-06-04T12:00:00Z", gps=SOHO), asset(2, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync()
        rows = self.rows()
        picked, gone = rows[self.lib.items[0]["id"]], rows[self.lib.items[1]["id"]]
        self.assertEqual(picked.trip_id, self.b)
        photos.decide(self.c, self.jane, picked.id, self.a, None)
        photogrants.exclude(self.c, self.jane, self.a, [gone.id], 2.0)
        self.c.commit()
        self.lib.items = [{**a, "updatedAt": "2026-07-01T13:00:00.000Z"} for a in self.lib.items]
        self.sync(NOW + timedelta(hours=6))
        self.sync(NOW + timedelta(days=8), full=True)
        rows = self.rows()
        self.assertEqual((rows[picked.asset_id].trip_id, rows[picked.asset_id].decided_by), (self.a, "owner"))
        self.assertEqual(rows[gone.asset_id].trip_id, self.a)
        self.assertNotIn(gone.id, [p.id for p, _ in photos.visible_rows(self.c, self.jane, self.a)])
        self.assertEqual([p.id for p, _ in photos.removed(self.c, self.jane, self.a)], [gone.id])

    def test_a_photo_removed_from_its_only_trip_comes_back_as_a_removed_row_after_a_re_list_deleted_it(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync()
        row = self.rows()[self.lib.items[0]["id"]]
        photogrants.exclude(self.c, self.jane, self.a, [row.id], 2.0)
        self.c.orm.delete(self.c.orm.get(Photo, row.id))
        self.c.commit()
        self.sync(NOW + timedelta(days=8), full=True)
        back = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual(back.trip_id, self.a)
        self.assertEqual([p.id for p, _ in photos.removed(self.c, self.jane, self.a)], [back.id])
        photogrants.put_back(self.c, self.jane, self.a, back.id)
        self.assertEqual([p.id for p, _ in photos.visible_rows(self.c, self.jane, self.a)], [back.id])

    def test_a_grant_revoked_while_a_page_was_fetched_writes_nothing(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]

        def stop_sharing(asked):
            with db.session() as other:
                other.execute(update(PhotoGrant).where(PhotoGrant.trip_id == self.a).values(revoked=9.0))
                other.execute(update(PhotoGrant).where(PhotoGrant.trip_id == self.b).values(revoked=9.0))
        self.lib.on_search = stop_sharing
        self.sync()
        self.assertEqual(self.rows(), {})

    def test_a_trip_that_left_the_windows_re_places_its_rows(self):
        self.lib.items = [asset(1, "2026-06-04T12:00:00Z", gps=SOHO), asset(2, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync()
        both = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual(both.trip_id, self.b)
        self.c.execute(update(PhotoGrant).where(PhotoGrant.trip_id == self.b).values(revoked=9.0))
        self.c.commit()
        self.sync(NOW + timedelta(hours=6))
        self.assertEqual(self.rows()[both.asset_id].trip_id, self.a)
        self.assertEqual(set(self.syncs()), {self.a})
        self.c.execute(update(PhotoGrant).values(revoked=9.0))
        self.c.commit()
        got = self.sync(NOW + timedelta(hours=12))
        self.assertEqual((self.rows(), self.syncs(), got.deleted), ({}, {}, 2))


class RelistTests(SyncCase):
    def test_a_weekly_re_list_deletes_rows_immich_no_longer_returns(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO), asset(2, "2026-06-04T12:00:00Z", gps=SOHO)]
        self.sync()
        self.lib.items = self.lib.items[:1]
        self.sync(NOW + timedelta(days=1))
        self.assertEqual(len(self.rows()), 2)
        got = self.sync(NOW + timedelta(days=8))
        self.assertEqual(list(self.rows()), [self.lib.items[0]["id"]])
        self.assertEqual(got.deleted, 1)
        self.assertEqual(db.get_setting(self.c, f"{sk.PHOTOS_LAST_RELIST}:{self.source}"), repr((NOW + timedelta(days=8)).timestamp()))
        self.assertIsNone(db.get_setting(self.c, f"{sk.PHOTOS_RELIST_STARTED}:{self.source}"))

    def test_an_interrupted_re_list_deletes_nothing_and_finishes_later(self):
        self.lib.items = [asset(n, f"2026-06-02T1{n}:00:00Z", gps=SOHO) for n in range(5)]
        self.sync()
        self.lib.items = self.lib.items[1:]
        with mock.patch.object(photosync, "TIME_BUDGET", 0.0):
            got = self.sync(NOW + timedelta(days=8), full=True)
            self.assertEqual((got.budget_hit, len(self.rows())), (1, 5))
            self.assertIsNotNone(db.get_setting(self.c, f"{sk.PHOTOS_RELIST_STARTED}:{self.source}"))
            self.sync(NOW + timedelta(days=8, hours=1))
            self.assertEqual(len(self.rows()), 5)
        self.sync(NOW + timedelta(days=8, hours=2))
        self.assertEqual(len(self.rows()), 4)
        self.assertIsNone(db.get_setting(self.c, f"{sk.PHOTOS_RELIST_STARTED}:{self.source}"))

    def test_a_row_outside_every_window_is_not_deleted_by_the_re_list(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync()
        row = self.rows()[self.lib.items[0]["id"]]
        photos.decide(self.c, self.jane, row.id, self.a, None)
        self.c.execute(update(Photo).where(Photo.id == row.id).values(taken_utc="2026-06-30T12:00:00.000Z"))
        self.c.commit()
        self.lib.items = []
        self.sync(NOW + timedelta(days=8))
        self.assertIn(row.asset_id, self.rows())


class BudgetTests(SyncCase):
    def test_the_budget_stops_after_a_page_and_the_next_run_resumes_from_its_cursor(self):
        self.lib.items = [asset(n, f"2026-06-02T1{n}:00:00Z", gps=SOHO) for n in range(5)]
        with mock.patch.object(photosync, "TIME_BUDGET", 0.0):
            got = self.sync()
            self.assertEqual((got.budget_hit, got.pages, len(self.rows())), (1, 1, 2))
            row = self.syncs()[self.a]
            self.assertEqual((row.resume_after, row.cursor, row.fetch_started), ("2026-06-02T11:00:00.000Z", None, NOW.isoformat()))
            self.assertIsNone(self.stored()["last_sync"])
            self.sync(NOW + timedelta(minutes=20))
            self.assertEqual((self.lib.asked()[-1]["page"], self.lib.asked()[-1]["takenAfter"]), (1, "2026-06-02T11:00:00.000Z"))
            self.assertEqual(self.syncs()[self.a].resume_after, "2026-06-02T12:00:00.000Z")
            self.sync(NOW + timedelta(minutes=40))
            self.sync(NOW + timedelta(minutes=60))
        self.assertEqual(len(self.rows()), 5)
        row = self.syncs()[self.a]
        self.assertEqual((row.cursor, row.resume_after, row.fetch_started), (NOW.isoformat(), None, None))
        self.assertTrue(all("updatedAfter" not in q and q["page"] == 1 for q in self.lib.asked()))


class FailureTests(SyncCase):
    def test_a_refused_key_marks_the_library_and_the_next_scheduled_run_skips_it(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.lib.fail(401)
        got = self.sync()
        self.assertEqual((self.stored()["status"], self.stored()["last_error"], got.failed), ("refused", immich.REFUSED, 1))
        calls = len(self.lib.fake.calls)
        self.lib.heal()
        self.assertEqual(photosync.sync_all(NOW).sources, 0)
        self.assertEqual(len(self.lib.fake.calls), calls)

    def test_an_unreachable_library_keeps_its_last_good_sync_and_its_first_warning(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync()
        self.lib.fail(500)
        self.sync(NOW + timedelta(hours=6))
        self.assertEqual((self.stored()["status"], self.stored()["last_error"], self.stored()["last_sync"]), ("unreachable", immich.UNAVAILABLE, NOW.timestamp()))
        self.lib.fake.server_close()
        self.lib.fake.shutdown()
        self.sync(NOW + timedelta(hours=12))
        self.assertEqual((self.stored()["status"], self.stored()["last_error"], self.stored()["last_sync"]), ("unreachable", immich.UNAVAILABLE, NOW.timestamp()))
        self.assertEqual(len(self.rows()), 1)

    def test_a_rate_limit_backs_off_and_keeps_the_cursor(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync()
        cursors = {t: s.cursor for t, s in self.syncs().items()}
        self.lib.fail(429, {"Retry-After": "30"})
        got = self.sync(NOW + timedelta(hours=6))
        self.assertEqual((got.failed, self.stored()["status"], self.stored()["last_error"], self.stored()["last_sync"]),
                         (1, "ok", immich.RATE_LIMITED, NOW.timestamp()))
        self.assertEqual({t: s.cursor for t, s in self.syncs().items()}, cursors)
        self.lib.heal()
        self.sync(NOW + timedelta(hours=12))
        self.assertEqual((self.stored()["status"], self.stored()["last_error"]), ("ok", None))

    def test_a_key_that_cannot_be_unlocked_marks_the_library_refused(self):
        self.c.execute(update(PhotoSource).values(api_key="enc:v1:broken"))
        self.c.commit()
        got = self.sync()
        self.assertEqual((got.failed, self.stored()["status"], self.stored()["last_error"]), (1, "refused", photosync.photosources.KEY_LOST))

    def test_nothing_private_is_logged_or_raised(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO, state=PLACE, ident=FIRST), asset(2, "2026-06-04T12:00:00Z", gps=SOHO, state=PLACE)]
        with no_leaks(self, FIRST, TRIP_NAME, PLACE, "51.51360"):
            self.assertEqual(photosync.sync_all(NOW).sources, 1)
            self.lib.fail(500)
            photosync.sync_all(NOW + timedelta(hours=6))
            self.lib.fail(401)
            photosync.sync_all(NOW + timedelta(hours=12))
            with mock.patch.object(photosync, "run", side_effect=RuntimeError(f"{FIRST} {TRIP_NAME} {PLACE}")):
                photo_sources.mark(self.c, self.source, "ok")
                self.c.commit()
                self.assertEqual(photosync.sync_all(NOW).failed, 1)
        self.assertEqual(self.stored()["status"], "ok")


class BackgroundTests(SyncCase):
    def setUp(self):
        super().setUp()
        photoqueue.enable(photosync.start)
        self.addCleanup(photoqueue.disable)

    def test_a_grant_queues_a_sync_of_that_trip_only_after_commit(self):
        with mock.patch.object(photoqueue, "starter") as started:
            photogrants.grant(self.c, self.jane, self.jid, self.other, "only_me", 3.0)
            self.c.rollback()
            started.assert_not_called()
            photogrants.grant(self.c, self.jane, self.jid, self.other, "only_me", 3.0)
            started.assert_not_called()
            self.c.commit()
        started.assert_called_once_with(self.source, {self.other})

    def test_a_put_back_queues_a_sync_too(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync()
        row = self.rows()[self.lib.items[0]["id"]]
        photogrants.exclude(self.c, self.jane, self.a, [row.id], 2.0)
        self.c.commit()
        with mock.patch.object(photoqueue, "starter") as started:
            photogrants.put_back(self.c, self.jane, self.a, row.id)
            self.c.commit()
        started.assert_called_once_with(self.source, {self.a})

    def test_without_the_background_jobs_nothing_is_queued(self):
        photoqueue.disable()
        with mock.patch.object(photoqueue, "starter") as started:
            photoqueue.queue(self.jid, self.a)
        started.assert_not_called()
        self.assertFalse(jobs.sync_photos_now(self.source))

    def test_one_run_per_library_and_a_waiting_whole_run_replaces_the_queued_trip(self):
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        seen = []

        def slow(conn, source_id, provider, now, *, full=False, trips=None):
            seen.append(trips)
            if len(seen) == 1:
                entered.set()
                release.wait(5)
            else:
                done.set()
            return photosync.Summary(sources=1)
        with mock.patch.object(photosync, "run", side_effect=slow):
            self.assertTrue(jobs.sync_photos_now(self.source))
            self.assertTrue(entered.wait(5))
            self.assertTrue(photosync.running(self.source))
            self.assertFalse(jobs.sync_photos_now(self.source))
            self.assertFalse(photosync.start(self.source, {self.a}))
            self.assertEqual(photosync.sync_all(NOW).sources, 0)
            release.set()
            self.assertTrue(done.wait(5))
        for _ in range(100):
            if not photosync.running(self.source):
                break
            threading.Event().wait(0.05)
        self.assertEqual(seen, [None, None])
        self.assertFalse(photosync.running(self.source))

    def test_a_failed_run_still_frees_the_library(self):
        with mock.patch.object(photosync, "run", side_effect=RuntimeError("boom")), mock.patch.object(monitoring, "report") as reported:
            self.assertEqual(photosync.sync_all(NOW).failed, 1)
        reported.assert_called_once()
        self.assertFalse(photosync.running(self.source))

    def test_queue_starts_each_syncing_library_of_the_person(self):
        second = photo_sources.save(self.c, self.jid, "u-jane", "https://second.example", OWNER, KEY, None, 1.0)
        third = photo_sources.save(self.c, self.jid, "u-jane", "https://third.example", OWNER, KEY, None, 1.0)
        photo_sources.mark(self.c, third, "off")
        self.c.commit()
        with mock.patch.object(photoqueue, "starter") as started:
            photoqueue.queue(self.jid, self.a)
        self.assertEqual([c.args for c in started.call_args_list], [(self.source, {self.a}), (second, {self.a})])
        with mock.patch.object(db, "session", side_effect=RuntimeError("down")), mock.patch.object(monitoring, "report") as reported:
            photoqueue.queue(self.jid, self.a)
        reported.assert_called_once()


class JobTests(SyncCase):
    def test_the_schedule_and_its_constants(self):
        self.assertEqual((jobs.PHOTO_SYNC_EVERY, jobs.PHOTO_SYNC_FIRST, photosync.TIME_BUDGET, photosync.FULL_RELIST_DAYS), (6 * 3600, 600, 600.0, 7))
        stop = threading.Event()
        stop.set()
        with mock.patch.object(jobs, "warm_map_data"), mock.patch.object(jobs.flightstatus, "forget_key_pause"):
            started = jobs.start(stop)
        self.addCleanup(photoqueue.disable)
        self.assertIn("photo-sync", [t.name for t in started])
        self.assertTrue(photoqueue.background.is_set())
        self.assertIs(photoqueue.starter, photosync.start)

    def test_the_scheduled_sync_runs_every_library_and_survives_a_failure(self):
        with mock.patch.object(photosync, "sync_all") as ran:
            jobs.sync_photos()
        ran.assert_called_once()
        with mock.patch.object(photosync, "sync_all", side_effect=RuntimeError("x")), mock.patch.object(monitoring, "report") as reported:
            jobs.sync_photos()
        reported.assert_called_once()

    def test_sync_all_logs_counts_only(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        with mock.patch.object(monitoring, "log") as logged:
            photosync.sync_all(NOW)
        line = logged.call_args.args[0]
        self.assertTrue(line.startswith("Photo sync: 1 library(ies)"), line)
        self.assertIn("1 place", line)


class TripChangeTests(SyncCase):
    def test_leaving_a_trip_ends_the_grant_and_re_places_the_rows(self):
        self.share(self.a, self.sid)
        sams = photo_sources.save(self.c, self.sid, "u-sam", "https://sam.example", OWNER, KEY, None, 1.0)
        trips.edit_trip(self.c, self.jane, self.a, {"people": [self.jid, self.sid]}, confirmed=True)
        self.c.orm.add(Photo(source_id=sams, asset_id="sam-asset-1", asset_updated="x", kind="image", taken_utc="2026-06-02T12:00:00.000Z",
                             taken_local="2026-06-02T13:00", latitude=SOHO[0], longitude=SOHO[1], location_source="exif", trip_id=self.a,
                             match="place", decided_by="auto", seen=1.0))
        self.c.orm.add(PhotoTripSync(source_id=sams, trip_id=self.a, window_start="s", window_end="e"))
        self.c.orm.flush()
        trips.edit_trip(self.c, self.jane, self.a, {"people": [self.jid]}, confirmed=True)
        self.assertIsNone(self.c.orm.get(PhotoGrant, (self.sid, self.a)))
        self.assertEqual(self.c.execute(select(PhotoTripSync.trip_id).where(PhotoTripSync.source_id == sams)).fetchall(), [])
        self.assertNotIn("sam-asset-1", self.rows())
        self.assertIsNotNone(self.c.orm.get(PhotoGrant, (self.jid, self.a)))

    def test_joining_a_trip_with_share_all_on_grants_it_and_queues_a_sync(self):
        self.c.orm.add(PhotoSharingPrefs(person_id=self.sid, default_scope="trip", share_all=True, set_by="u-sam"))
        self.c.orm.flush()
        photoqueue.enable(photosync.start)
        self.addCleanup(photoqueue.disable)
        sams = photo_sources.save(self.c, self.sid, "u-sam", "https://sam.example", OWNER, KEY, None, 1.0)
        with mock.patch.object(photoqueue, "starter") as started:
            trips.edit_trip(self.c, self.jane, self.b, {"people": [self.jid, self.sid]}, confirmed=True)
            self.c.commit()
        row = self.c.orm.get(PhotoGrant, (self.sid, self.b))
        self.assertEqual((row.scope, row.revoked, row.granted_by), ("trip", None, "u-sam"))
        started.assert_called_once_with(sams, {self.b})

    def test_a_grant_whose_maker_can_no_longer_see_the_trip_ends(self):
        mia_source = photo_sources.save(self.c, self.mia, "u-sam", "https://mia.example", OWNER, KEY, None, 1.0)
        self.assertTrue(mia_source)
        trips.edit_trip(self.c, self.jane, self.b, {"people": [self.jid, self.mia]}, confirmed=True)
        self.c.orm.add(PhotoGrant(person_id=self.mia, trip_id=self.b, scope="trip", revoked=None, changed=1.0, granted_by="u-sam"))
        self.c.orm.flush()
        photogrants.reconcile(self.c, self.b)
        self.assertIsNone(self.c.orm.get(PhotoGrant, (self.mia, self.b)))
        self.c.orm.add(PhotoGrant(person_id=self.mia, trip_id=self.b, scope="trip", revoked=None, changed=1.0, granted_by="u-unknown"))
        self.c.orm.flush()
        self.assertEqual(photogrants.reconcile_all(self.c), 1)
        self.assertIsNone(self.c.orm.get(PhotoGrant, (self.mia, self.b)))

    def test_merging_carries_exclusions_and_re_places_the_rows(self):
        self.lib.items = [asset(1, "2026-06-04T12:00:00Z", gps=SOHO), asset(2, "2026-06-03T12:00:00Z", gps=SOHO)]
        self.sync()
        rows = self.rows()
        kept, removed = rows[self.lib.items[0]["id"]], rows[self.lib.items[1]["id"]]
        self.assertEqual((kept.trip_id, removed.trip_id), (self.b, self.b))
        photogrants.exclude(self.c, self.jane, self.b, [removed.id], 2.0)
        trips.merge(self.c, self.jane, self.a, self.b, confirmed=True)
        rows = self.rows()
        self.assertEqual(rows[kept.asset_id].trip_id, self.a)
        self.assertEqual(self.c.execute(select(PhotoExclusion.trip_id).where(PhotoExclusion.asset_id == removed.asset_id)).scalars(), [self.a])
        self.assertNotIn(removed.id, [p.id for p, _ in photos.visible_rows(self.c, self.jane, self.a)])

    def test_deleting_the_last_booking_of_an_auto_trip_re_places_its_photos_first(self):
        self.share(self.other)
        self.lib.items = [asset(1, "2026-08-01T22:00:00Z", gps=SOHO)]
        self.sync()
        self.assertEqual(self.rows()[self.lib.items[0]["id"]].trip_id, self.other)
        seg = trips.visibility.visible_segments(self.c, self.jane, [self.other])[0]
        trips.delete_segment(self.c, self.jane, seg.id)
        self.assertEqual(self.rows(), {})

    def test_moving_a_booking_out_of_a_trip_settles_both_trips(self):
        self.share(self.other)
        seg = trips.visibility.visible_segments(self.c, self.jane, [self.other])[0]
        self.c.orm.add(Photo(source_id=self.source, asset_id="moved-1", asset_updated="x", kind="image", taken_utc="2026-08-01T22:00:00.000Z",
                             taken_local="2026-08-01T23:00", latitude=SOHO[0], longitude=SOHO[1], location_source="exif", trip_id=self.other,
                             match="place", decided_by="auto", seen=1.0))
        self.c.orm.flush()
        trips.move_segment(self.c, self.jane, seg.id, self.a, confirmed=True)
        self.assertIsNone(self.c.orm.get(PhotoGrant, (self.jid, self.other)))
        self.assertEqual(self.rows()["moved-1"].trip_id, self.a)


class KeyTests(SyncCase):
    def test_the_key_never_reaches_the_database_in_the_clear(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        with no_leaks(self, KEY, database=self.path, sent_ok=True):
            self.sync()
        self.assertTrue(self.c.execute(select(PhotoSource.api_key)).scalar().startswith("enc:"))


HOME_POINT = home.geocode.Point(SOHO[0], SOHO[1], "zip")


class ReviewFixTests(SyncCase):
    def home_row(self, taken):
        row = Photo(source_id=self.source, asset_id=f"home-{taken}", asset_updated="x", kind="image", taken_utc=taken, taken_local=taken[:16],
                    latitude=SOHO[0], longitude=SOHO[1], location_source="exif", trip_id=None, match="home", decided_by="auto", seen=1.0)
        self.c.orm.add(row)
        self.c.orm.flush()
        return row.asset_id

    def test_stopping_sharing_drops_home_rows_no_shared_window_still_covers(self):
        only_a, in_b = self.home_row("2026-06-02T12:00:00.000Z"), self.home_row("2026-06-04T12:00:00.000Z")
        with mock.patch.object(home, "located", return_value=HOME_POINT):
            photogrants.stop(self.c, self.jane, self.jid, self.a, 5.0)
        rows = self.rows()
        self.assertNotIn(only_a, rows)
        self.assertEqual((rows[in_b].match, rows[in_b].trip_id), ("home", None))
        with mock.patch.object(home, "located", return_value=HOME_POINT):
            photogrants.left(self.c, self.jid, self.b)
        self.assertNotIn(in_b, self.rows())

    def test_deleting_a_trip_drops_home_rows_it_alone_covered(self):
        only_a = self.home_row("2026-06-02T12:00:00.000Z")
        with mock.patch.object(home, "located", return_value=HOME_POINT):
            photogrants.trip_deleted(self.c, self.a)
        self.assertNotIn(only_a, self.rows())

    def test_the_sync_drops_home_rows_when_their_window_goes(self):
        with mock.patch.object(home, "located", return_value=HOME_POINT):
            self.sync()
            only_a, in_b = self.home_row("2026-06-02T12:00:00.000Z"), self.home_row("2026-06-04T12:00:00.000Z")
            self.c.execute(update(PhotoGrant).where(PhotoGrant.trip_id == self.a).values(revoked=9.0))
            self.c.commit()
            self.sync(NOW + timedelta(hours=6))
        rows = self.rows()
        self.assertNotIn(only_a, rows)
        self.assertEqual(rows[in_b].match, "home")

    def test_the_prep_reads_the_windows_under_the_grant_locks(self):
        self.lib.items = [asset(1, "2026-06-04T12:00:00Z", gps=SOHO)]
        real = photogrants.lock
        waited = []

        def stopped_while_waiting(conn, person, trip_ids):
            if not waited:
                waited.append(1)
                with db.session() as other:
                    other.execute(update(PhotoGrant).where(PhotoGrant.trip_id == self.b).values(revoked=9.0))
            return real(conn, person, trip_ids)
        with mock.patch.object(photogrants, "lock", side_effect=stopped_while_waiting):
            self.sync()
        self.assertEqual(set(self.syncs()), {self.a})
        self.assertEqual(self.rows()[self.lib.items[0]["id"]].trip_id, self.a)
        self.assertEqual(len({q["takenBefore"] for q in self.lib.asked()}), 1)

    def test_a_starter_that_fails_after_commit_is_logged_as_a_count_and_the_rest_still_start(self):
        second = photo_sources.save(self.c, self.jid, "u-jane", "https://second.example", OWNER, KEY, None, 1.0)
        self.c.commit()
        photoqueue.enable(photosync.start)
        self.addCleanup(photoqueue.disable)
        tried = []

        def boom(source_id, trips):
            tried.append(source_id)
            if source_id == self.source:
                raise RuntimeError(f"can't start thread {TRIP_NAME}")
            return True
        with mock.patch.object(photoqueue, "starter", side_effect=boom), mock.patch.object(monitoring, "log") as logged:
            photogrants.grant(self.c, self.jane, self.jid, self.other, "only_me", 3.0)
            self.c.commit()
        self.assertEqual(tried, [self.source, second])
        line = logged.call_args.args[0]
        self.assertIn("1", line)
        self.assertNotIn(TRIP_NAME, line)

    def test_a_claimed_guests_trips_are_shared_by_the_members_standing_setting(self):
        trips.edit_trip(self.c, self.jane, self.b, {"people": [self.jid, self.mia]}, confirmed=True)
        self.c.orm.add(PhotoSharingPrefs(person_id=self.sid, default_scope="trip", share_all=True, set_by="u-sam"))
        sams = photo_sources.save(self.c, self.sid, "u-sam", "https://sam.example", OWNER, KEY, None, 1.0)
        self.c.commit()
        photoqueue.enable(photosync.start)
        self.addCleanup(photoqueue.disable)
        with mock.patch.object(photoqueue, "starter") as started:
            people.claim_guest(self.c, self.sid, self.mia, "2026-07-01")
            started.assert_not_called()
            self.c.commit()
        row = self.c.orm.get(PhotoGrant, (self.sid, self.b))
        self.assertEqual((row.scope, row.revoked, row.granted_by), ("trip", None, "u-sam"))
        self.assertIn(((sams, {self.b}),), [c.args and (c.args,) for c in started.call_args_list])


class SecondReviewTests(SyncCase):
    def test_a_relist_whose_preparation_fails_leaves_no_marker_behind(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO), asset(2, "2026-06-04T12:00:00Z", gps=SOHO)]
        self.sync()
        with mock.patch.object(photos, "candidate_windows", side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                self.sync(NOW + timedelta(days=8))
        self.c.rollback()
        self.assertIsNone(db.get_setting(self.c, f"{sk.PHOTOS_RELIST_STARTED}:{self.source}"))
        self.lib.items = self.lib.items[:1]
        self.sync(NOW + timedelta(days=8, hours=1))
        self.assertEqual(list(self.rows()), [self.lib.items[0]["id"]])

    def test_a_pause_made_during_a_run_survives_its_end(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]

        def pause(asked):
            with db.session() as other:
                photo_sources.mark(other, self.source, "off")
        self.lib.on_search = pause
        self.sync()
        self.assertEqual(self.stored()["status"], "off")
        photo_sources.mark(self.c, self.source, "ok")
        self.c.commit()
        self.lib.fail(500)
        self.lib.on_search = None
        real = photo_sources.mark

        def paused_first(conn, source_id, status, error=None, synced=None, **kw):
            with db.session() as other:
                other.execute(update(PhotoSource).values(status="off"))
            return real(conn, source_id, status, error, synced, **kw)
        with mock.patch.object(photo_sources, "mark", side_effect=paused_first):
            self.sync(NOW + timedelta(hours=6))
        self.assertEqual(self.stored()["status"], "off")

    def test_a_change_to_what_the_matcher_reads_re_places_rows_without_a_new_fetch(self):
        self.lib.items = [asset(1, "2026-06-04T12:00:00Z", gps=(51.5, -0.12))]
        self.sync()
        row = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual((row.trip_id, row.match), (self.b, "time"))
        stay = trips.visibility.visible_segments(self.c, self.jane, [self.b])[0]
        self.c.execute(update(trips.Segment).where(trips.Segment.id == stay.id).values(latitude=51.5, longitude=-0.12))
        self.c.commit()
        self.sync(NOW + timedelta(hours=6))
        row = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual((row.trip_id, row.match, row.segment_id), (self.b, "place", stay.id))
        with mock.patch.object(home, "located", return_value=home.geocode.Point(51.5, -0.12, "zip")):
            self.sync(NOW + timedelta(hours=12))
        self.assertEqual(self.rows()[self.lib.items[0]["id"]].match, "home")

    def test_keyset_paging_does_not_skip_assets_when_earlier_ones_are_deleted_mid_traversal(self):
        self.lib.items = [asset(n, f"2026-06-02T1{n}:00:00Z", gps=SOHO) for n in range(6)]
        first = []

        def delete_early(asked):
            if not first:
                first.append(1)
                return
            if len(first) == 1:
                first.append(1)
                del self.lib.items[0:2]
        self.lib.on_search = delete_early
        self.sync()
        self.assertEqual(sorted(self.rows()), sorted(f"0a000000-0000-4000-8000-{n:012d}" for n in range(6)))

    def test_a_window_too_dense_to_step_past_never_completes(self):
        self.lib.items = [asset(n, "2026-06-02T12:00:00Z", gps=SOHO) for n in range(3)] + [asset(9, "2026-06-03T12:00:00Z", gps=SOHO)]
        got = self.sync()
        row = self.syncs()[self.a]
        self.assertIsNone(row.cursor)
        self.assertEqual(row.resume_after, "2026-06-02T12:00:00.000Z")
        self.assertEqual((self.stored()["status"], self.stored()["last_error"], self.stored()["last_sync"]), ("ok", photosync.TOO_DENSE, None))
        self.assertEqual(got.failed, 1)
        self.sync(NOW + timedelta(days=8))
        self.assertIsNone(db.get_setting(self.c, f"{sk.PHOTOS_LAST_RELIST}:{self.source}"))

    def test_a_sync_now_whose_thread_cannot_start_frees_the_library(self):
        photoqueue.enable(photosync.start)
        self.addCleanup(photoqueue.disable)
        with mock.patch.object(photosync.threading.Thread, "start", side_effect=RuntimeError("can't start new thread")), \
                mock.patch.object(monitoring, "log") as logged:
            self.assertFalse(jobs.sync_photos_now(self.source))
        self.assertFalse(photosync.running(self.source))
        self.assertIn("could not start", logged.call_args.args[0])

    def test_a_split_copies_every_exclusion_of_the_original_before_sharing_the_new_trip(self):
        self.c.orm.add(PhotoSharingPrefs(person_id=self.jid, default_scope="trip", share_all=True, set_by="u-jane"))
        self.c.orm.add_all([PhotoExclusion(person_id=self.jid, asset_id="removed-anywhere", trip_id=self.a, created=1.0)])
        self.c.orm.flush()
        hotel = next(s for s in trips.visibility.visible_segments(self.c, self.jane, [self.a]) if s.kind == "hotel")
        new = trips.split(self.c, self.jane, self.a, [hotel.id])["id"]
        self.assertEqual(self.c.execute(select(PhotoExclusion.asset_id).where(PhotoExclusion.trip_id == new)).scalars(), ["removed-anywhere"])
        self.assertIsNotNone(self.c.orm.get(PhotoGrant, (self.jid, new)))


class ThirdReviewTests(SyncCase):
    def test_a_page_fetched_under_a_window_that_moved_meanwhile_writes_nothing(self):
        self.lib.items = [asset(1, "2026-06-04T12:00:00Z", gps=SOHO)]
        moved = []

        def move_b(asked):
            if moved:
                return
            moved.append(1)
            with db.session() as other:
                other.execute(update(trips.Segment).where(trips.Segment.trip_id == self.b).values(start_local="2026-07-03T15:00", end_local="2026-07-05T10:00"))
        self.lib.on_search = move_b
        got = self.sync()
        self.assertEqual(self.rows()[self.lib.items[0]["id"]].trip_id, self.a)
        self.assertIsNone(self.stored()["last_sync"])
        self.assertIsNone(self.syncs()[self.b].cursor)
        self.assertEqual(got.budget_hit, 0)
        self.sync(NOW + timedelta(hours=6))
        self.assertEqual(self.rows()[self.lib.items[0]["id"]].trip_id, self.a)
        self.assertEqual(self.stored()["last_sync"], (NOW + timedelta(hours=6)).timestamp())

    def test_a_refusal_for_a_key_that_was_replaced_meanwhile_leaves_the_new_key_healthy(self):
        def replaced():
            with db.session() as other:
                photo_sources.set_key(other, self.source, "canary-new-key-8c2v")
                photo_sources.mark(other, self.source, "ok", None)
            return b'{"message":"no"}'
        self.lib.fake.routes[immich.SEARCH] = (401, JSON_HEADERS, replaced)
        got = self.sync()
        self.assertEqual(got.failed, 1)
        self.assertEqual((self.stored()["status"], self.stored()["last_error"]), ("ok", None))
        self.lib.fail(401)
        self.sync(NOW + timedelta(hours=6))
        self.assertEqual(self.stored()["status"], "refused")

    def test_a_run_that_reads_nothing_from_immich_changes_no_status(self):
        photo_sources.mark(self.c, self.source, "unreachable", immich.UNREACHABLE, 5.0)
        self.c.execute(update(PhotoGrant).values(revoked=9.0))
        self.c.commit()
        self.sync()
        self.assertEqual((self.stored()["status"], self.stored()["last_error"], self.stored()["last_sync"]), ("unreachable", immich.UNREACHABLE, 5.0))
        self.assertEqual(self.lib.asked(), [])


class FourthReviewTests(SyncCase):
    def test_a_relist_due_while_nothing_is_shared_leaves_no_pending_generation(self):
        self.c.execute(update(PhotoGrant).values(revoked=9.0))
        self.c.commit()
        self.sync(NOW + timedelta(days=8))
        self.assertIsNone(db.get_setting(self.c, f"{sk.PHOTOS_RELIST_STARTED}:{self.source}"))

    def test_a_window_not_read_in_full_under_a_pending_relist_is_read_in_full(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO), asset(2, "2026-06-04T12:00:00Z", gps=SOHO)]
        self.sync()
        db.set_setting(self.c, f"{sk.PHOTOS_RELIST_STARTED}:{self.source}", repr((NOW + timedelta(days=7)).timestamp()))
        self.c.commit()
        self.lib.items = self.lib.items[:1]
        calls = len(self.lib.asked())
        self.sync(NOW + timedelta(days=8))
        self.assertTrue(all("updatedAfter" not in q for q in self.lib.asked()[calls:]))
        self.assertEqual(list(self.rows()), [self.lib.items[0]["id"]])

    def test_a_scheduled_run_that_finds_the_library_busy_runs_next_and_wins_over_queued_trips(self):
        photoqueue.enable(photosync.start)
        self.addCleanup(photoqueue.disable)
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        seen = []

        def slow(conn, source_id, provider, now, *, full=False, trips=None):
            seen.append((trips, full))
            if len(seen) == 1:
                entered.set()
                release.wait(5)
            else:
                done.set()
            return photosync.Summary(sources=1)
        with mock.patch.object(photosync, "run", side_effect=slow):
            self.assertTrue(photosync.start(self.source, {self.a}))
            self.assertTrue(entered.wait(5))
            self.assertFalse(photosync.start(self.source, {self.b}))
            photosync.sync_all(NOW, full=True)
            release.set()
            self.assertTrue(done.wait(5))
            for _ in range(100):
                if not photosync.running(self.source):
                    break
                threading.Event().wait(0.05)
        self.assertEqual(seen, [({self.a}, False), (None, True)])

    def test_a_dense_window_on_a_library_that_was_unreachable_marks_it_reachable_with_the_warning(self):
        photo_sources.mark(self.c, self.source, "unreachable", immich.UNREACHABLE, 5.0)
        self.c.commit()
        self.lib.items = [asset(n, "2026-06-02T12:00:00Z", gps=SOHO) for n in range(3)]
        self.sync()
        self.assertEqual((self.stored()["status"], self.stored()["last_error"], self.stored()["last_sync"]), ("ok", photosync.TOO_DENSE, 5.0))


class HomeDuringFetchTests(SyncCase):
    def test_home_saved_while_a_page_is_fetched_discards_the_page_and_the_next_run_places_it_as_home(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        located = mock.patch.object(home, "located", return_value=None)
        stub = located.start()
        self.addCleanup(located.stop)

        def home_saved(asked):
            stub.return_value = HOME_POINT
        self.lib.on_search = home_saved
        got = self.sync()
        self.assertEqual(self.rows(), {})
        self.assertIsNone(self.stored()["last_sync"])
        self.assertEqual(got.budget_hit, 0)
        self.lib.on_search = None
        self.sync(NOW + timedelta(hours=6))
        row = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual((row.match, row.trip_id), ("home", None))


class FifthReviewTests(SyncCase):
    def test_a_lost_key_replaced_before_the_refusal_is_written_keeps_the_new_key_healthy(self):
        self.c.execute(update(PhotoSource).values(api_key="enc:v1:broken"))
        self.c.commit()
        real = photosync.photosources.unlock

        def replaced_then_unlock(conn, source_id):
            try:
                return real(conn, source_id)
            finally:
                with db.session() as other:
                    photo_sources.set_key(other, source_id, "canary-fresh-key-3n7d")
                    photo_sources.mark(other, source_id, "ok", None)
        with mock.patch.object(photosync.photosources, "unlock", side_effect=replaced_then_unlock):
            got = self.sync()
        self.assertEqual(got.failed, 1)
        self.assertEqual((self.stored()["status"], self.stored()["last_error"]), ("ok", None))

    def test_a_completed_trip_sync_clears_a_stale_unreachable_status_and_keeps_last_sync(self):
        photo_sources.mark(self.c, self.source, "unreachable", immich.UNREACHABLE, 5.0)
        self.c.commit()
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync(trips={self.a})
        self.assertEqual((self.stored()["status"], self.stored()["last_error"], self.stored()["last_sync"]), ("ok", None, 5.0))
        photo_sources.mark(self.c, self.source, "ok", photosync.TOO_DENSE, 5.0)
        self.c.commit()
        self.sync(NOW + timedelta(hours=1), trips={self.a})
        self.assertEqual((self.stored()["status"], self.stored()["last_error"]), ("ok", photosync.TOO_DENSE))


class SixthReviewTests(SyncCase):
    def test_a_rate_limit_does_not_restore_a_status_a_concurrent_test_changed(self):
        def tested_meanwhile():
            with db.session() as other:
                photo_sources.mark(other, self.source, "unreachable", immich.UNREACHABLE)
            return b'{"message":"slow down"}'
        self.lib.fake.routes[immich.SEARCH] = (429, {**JSON_HEADERS, "Retry-After": "30"}, tested_meanwhile)
        got = self.sync()
        self.assertEqual(got.failed, 1)
        self.assertEqual((self.stored()["status"], self.stored()["last_error"]), ("unreachable", immich.UNREACHABLE))

    def test_a_pause_mid_run_stops_the_next_request_and_records_nothing(self):
        self.lib.items = [asset(n, f"2026-06-02T1{n}:00:00Z", gps=SOHO) for n in range(5)] + [asset(9, "2026-06-04T12:00:00Z", gps=SOHO)]
        self.sync()
        self.lib.items = self.lib.items[1:]
        calls = len(self.lib.asked())

        def pause(asked):
            with db.session() as other:
                photo_sources.mark(other, self.source, "off")
        self.lib.on_search = pause
        got = self.sync(NOW + timedelta(days=8), full=True)
        self.assertEqual(len(self.lib.asked()) - calls, 1)
        self.assertEqual((self.stored()["status"], self.stored()["last_sync"]), ("off", NOW.timestamp()))
        self.assertEqual(len(self.rows()), 6)
        self.assertEqual(got.budget_hit, 0)


class SeventhReviewTests(SyncCase):
    def test_a_library_removed_mid_run_stops_after_one_request(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO), asset(2, "2026-06-02T13:00:00Z", gps=SOHO),
                          asset(3, "2026-06-02T14:00:00Z", gps=SOHO), asset(4, "2026-06-04T12:00:00Z", gps=SOHO)]

        def removed(asked):
            with db.session() as other:
                photo_sources.remove(other, self.source)
        self.lib.on_search = removed
        got = self.sync()
        self.assertEqual(len(self.lib.asked()), 1)
        self.assertEqual(got.budget_hit, 0)
        self.assertIsNone(photo_sources.get(self.c, self.source))

    def test_a_library_the_sweep_ended_mid_run_stops_before_its_next_request(self):
        self.lib.items = [asset(n, f"2026-06-02T1{n}:00:00Z", gps=SOHO) for n in range(5)]
        gone = []
        self.lib.on_search = lambda asked: gone.append(1)
        real = photo_sources.status
        with mock.patch.object(photo_sources, "status", side_effect=lambda conn, source_id: None if gone else real(conn, source_id)):
            got = self.sync()
        self.assertEqual(len(self.lib.asked()), 1)
        self.assertEqual((got.budget_hit, self.stored()["status"], self.stored()["last_sync"]), (0, "ok", None))

    def test_turning_on_share_all_queues_a_sync_of_each_new_trip_after_commit_only(self):
        photoqueue.enable(photosync.start)
        self.addCleanup(photoqueue.disable)
        with mock.patch.object(photoqueue, "starter") as started:
            photogrants.set_prefs(self.c, self.jane, self.jid, "trip", True, 40.0)
            self.c.rollback()
            started.assert_not_called()
            photogrants.set_prefs(self.c, self.jane, self.jid, "trip", True, 41.0)
            started.assert_not_called()
            self.c.commit()
        self.assertIn((self.source, {self.other}), [c.args for c in started.call_args_list])


class EighthReviewTests(SyncCase):
    def test_a_test_that_succeeds_mid_run_survives_a_later_network_error(self):
        photo_sources.mark(self.c, self.source, "unreachable", immich.UNREACHABLE, 5.0)
        self.c.commit()

        def tested_ok():
            with db.session() as other:
                photo_sources.mark(other, self.source, "ok", None)
            return b'{"message":"broken"}'
        self.lib.fake.routes[immich.SEARCH] = (500, JSON_HEADERS, tested_ok)
        got = self.sync()
        self.assertEqual(got.failed, 1)
        self.assertEqual((self.stored()["status"], self.stored()["last_error"]), ("ok", None))

    def test_a_guest_claimed_mid_fetch_stops_the_run_and_deletes_nothing(self):
        trips.edit_trip(self.c, self.jane, self.a, {"people": [self.jid, self.mia]}, confirmed=True)
        mias = photo_sources.save(self.c, self.mia, "u-jane", self.lib.url, OWNER, KEY, None, 1.0)
        self.share(self.a, self.mia)
        self.c.commit()
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO), asset(2, "2026-06-02T13:00:00Z", gps=SOHO)]
        photosync.run(self.c, mias, immich, NOW)
        before = {p.asset_id for p in self.c.orm.scalars(select(Photo).where(Photo.source_id == mias)).all()}
        self.assertEqual(len(before), 2)
        last = photo_sources.get(self.c, mias)["last_sync"]
        relisted = db.get_setting(self.c, f"{sk.PHOTOS_LAST_RELIST}:{mias}")
        self.lib.items = self.lib.items[:1]

        def claimed(asked):
            if self.lib.on_search is None:
                return
            self.lib.on_search = None
            with db.session() as other:
                people.claim_guest(other, self.sid, self.mia, "2026-07-01")
        self.lib.on_search = claimed
        photosync.run(self.c, mias, immich, NOW + timedelta(days=8), full=True)
        self.c.orm.expire_all()
        after = {p.asset_id for p in self.c.orm.scalars(select(Photo).where(Photo.source_id == mias)).all()}
        self.assertEqual(after, before)
        self.assertEqual(photo_sources.get(self.c, mias)["last_sync"], last)
        self.assertEqual(db.get_setting(self.c, f"{sk.PHOTOS_LAST_RELIST}:{mias}"), relisted)


class NinthReviewTests(SyncCase):
    def test_a_pause_during_the_last_page_of_a_relist_deletes_nothing_and_keeps_the_generation(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO), asset(2, "2026-06-04T12:00:00Z", gps=SOHO)]
        self.sync()
        relisted = db.get_setting(self.c, f"{sk.PHOTOS_LAST_RELIST}:{self.source}")
        self.lib.items = self.lib.items[:1]
        calls = []

        def pause_on_last(asked):
            calls.append(1)
            if len(calls) == 2:
                with db.session() as other:
                    photo_sources.mark(other, self.source, "off")
        self.lib.on_search = pause_on_last
        self.sync(NOW + timedelta(days=8), full=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(db.get_setting(self.c, f"{sk.PHOTOS_LAST_RELIST}:{self.source}"), relisted)
        self.assertEqual((self.stored()["status"], self.stored()["last_sync"]), ("off", NOW.timestamp()))

    def test_an_edit_stamped_just_before_the_cursor_by_a_slower_immich_clock_is_still_fetched(self):
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=SOHO)]
        self.sync()
        edited = (NOW - timedelta(minutes=photosync.CLOCK_SKEW.total_seconds() / 120)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self.lib.items = [asset(1, "2026-06-02T12:00:00Z", gps=(51.5, -0.12), updated=edited)]
        self.sync(NOW + timedelta(hours=6))
        row = self.rows()[self.lib.items[0]["id"]]
        self.assertEqual((row.latitude, row.longitude), (51.5, -0.12))
        got = self.sync(NOW + timedelta(hours=12))
        self.assertEqual(got.new, 0)
