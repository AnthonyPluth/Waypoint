from datetime import UTC, date, datetime

from collections import Counter
from unittest import mock

from sqlalchemy import MetaData, func, select

from waypoint import tls
from waypoint.domain import demo, people, photos, stats, trips
from waypoint.domain.visibility import Viewer
from waypoint.storage import gate_codes, secretbox, stored_mail
from waypoint.storage.models import Photo, PhotoExclusion, PhotoGrant, PhotoSource, PhotoTripSync, Segment
from tests.shared import DbCase


class DemoTests(DbCase):
    def rows(self) -> int:
        meta = MetaData()
        meta.reflect(self.c.sa)
        return sum(self.c.sa.execute(select(func.count()).select_from(t)).scalar() or 0
                   for t in meta.sorted_tables if t.name != "alembic_version")

    def test_says_how_many_rows_it_added(self):
        before = self.rows()
        added = demo.seed(self.c)
        self.assertEqual(self.rows() - before, added)

    def check_dates(self, today: date) -> None:
        demo.seed(self.c, today)
        found = trips.listing(self.c, Viewer(None, household=True))
        day = today.isoformat()
        self.assertEqual(len([t for t in found if (t["end_date"] or "") < day]), 5)
        self.assertEqual(len([t for t in found if (t["start_date"] or "") <= day <= (t["end_date"] or "")]), 1)
        self.assertEqual(len([t for t in found if (t["start_date"] or "") > day]), 5)
        self.assertTrue(all(t["segments"] for t in found))

    def test_has_a_past_trip_one_in_progress_and_some_to_come(self):
        self.check_dates(date(2026, 10, 5))

    def test_keeps_its_trips_around_today_across_a_year_end(self):
        self.check_dates(date(2026, 12, 30))

    def test_the_family_flights_are_each_on_two_bookings_one_flight(self):
        demo.seed(self.c, date(2026, 10, 5))
        found = [s for t in trips.listing(self.c, Viewer(None, household=True)) for s in t["segments"] if s["details"].get("flight_number") in ("AA 101", "AA 102")]
        self.assertEqual(len(found), 4)
        self.assertEqual({s["confirmation"] for s in found}, {"KQ7M2X", "MW5T9Z"})
        self.assertEqual([len(g) for g in trips.flight_groups(found)], [2, 2])

    def test_stats_has_something_in_every_section_and_more_than_one_year(self):
        demo.seed(self.c, date(2026, 10, 5))
        got = stats.compute(self.c, Viewer(None, household=True), None, None, datetime(2026, 10, 5, 12, tzinfo=UTC))
        assert got is not None
        f = got["flights"]
        self.assertGreaterEqual(len(got["years"]), 3)
        for name in ("airports", "airlines", "countries", "routes", "cabins"):
            self.assertGreater(len(f[name]), 2, name)
        self.assertTrue(f["top_seat"] and f["longest"] and f["shortest"] and f["busiest_month"])
        self.assertTrue(f["seat_positions"]["window"] and f["seat_positions"]["aisle"])
        self.assertTrue(got["stays"]["chains"] and got["stays"]["nights"] and got["cars"]["companies"] and got["cars"]["days"])
        self.assertTrue(got["parking"]["lots"] and got["parking"]["days"] and got["parking"]["bookings"])

    def test_has_parking_on_a_trip_with_flights_and_one_still_to_come(self):
        demo.seed(self.c, date(2026, 10, 5))
        found = trips.listing(self.c, Viewer(None, household=True))
        with_parking = [t for t in found if any(s["kind"] == "parking" for s in t["segments"])]
        self.assertEqual(len(with_parking), 2)
        for t in with_parking:
            self.assertTrue(any(s["kind"] == "flight" for s in t["segments"]))
        lot = next(s for t in with_parking for s in t["segments"] if s["kind"] == "parking" and s["start_local"][:10] > "2026-10-05")
        self.assertEqual((lot["start_zone"], lot["details"]["space_type"]), ("America/New_York", "Covered"))

    def test_the_coming_parking_booking_keeps_a_made_up_gate_code_chosen_from_its_email_and_the_past_one_none(self):
        demo.seed(self.c, date(2026, 10, 5))
        found = trips.listing(self.c, Viewer(None, household=True))
        lots = sorted((s for t in found for s in t["segments"] if s["kind"] == "parking"), key=lambda s: s["start_local"])
        self.assertEqual([s["gate_code"] for s in lots], [None, {"state": "ready", "day": "2026-10-04"}])
        shown = gate_codes.image_for(self.c, lots[1]["id"])
        assert shown
        self.assertEqual(gate_codes.dimensions(shown["data"]), (290, 290))
        self.assertEqual(len(stored_mail.for_segment(self.c, lots[1]["id"])), 1)


class DemoPhotoTests(DbCase):
    TODAY = date(2026, 10, 5)

    def setUp(self):
        super().setUp()
        failed = mock.patch.object(tls, "urlopen", side_effect=AssertionError("seeding the demo opened a connection"))
        failed.start()
        self.addCleanup(failed.stop)
        demo.seed(self.c, self.TODAY)
        self.jane, self.sam = (people.person_for_sub(self.c, sub) for sub in ("demo-jane", "demo-sam"))

    def trip_of(self, origin: str) -> int:
        trip_id = self.c.orm.scalars(select(Segment.trip_id).where(Segment.origin == origin).order_by(Segment.id)).first()
        assert trip_id is not None
        return trip_id

    def count(self, model, *where) -> int:
        return self.c.orm.scalar(select(func.count()).select_from(model).where(*where)) or 0

    def test_each_member_has_a_demo_library_that_is_never_synced(self):
        sources = self.c.orm.scalars(select(PhotoSource).order_by(PhotoSource.person_id)).all()
        self.assertEqual([s.person_id for s in sources], sorted([self.jane, self.sam]))
        for source in sources:
            self.assertEqual((source.url, source.status, source.owner_sub), ("demo", "ok", f"demo-{'jane' if source.person_id == self.jane else 'sam'}"))
            self.assertIsNotNone(source.last_sync)
            self.assertNotIn("demo", source.api_key)
            self.assertEqual(secretbox.decrypt(source.api_key), "demo-not-a-token")
        synced = self.c.orm.scalars(select(PhotoTripSync)).all()
        self.assertEqual(len(synced), 5)
        for row in synced:
            self.assertEqual((row.cursor is None, row.resume_after is None, row.inputs is None, row.fetch_started is None, row.synced is not None), (False, True, False, True, True))

    def test_has_the_rows_the_ui_needs(self):
        self.assertEqual((self.count(PhotoSource), self.count(Photo), self.count(PhotoGrant), self.count(PhotoExclusion), self.count(PhotoTripSync)), (2, 29, 6, 1, 5))
        self.assertEqual(Counter(p.match for p in self.c.orm.scalars(select(Photo))), {"place": 21, "time": 6, "far": 1, "ambiguous": 1})
        self.assertEqual(Counter(p.kind for p in self.c.orm.scalars(select(Photo))), {"image": 29})
        self.assertEqual(len({p.asset_id for p in self.c.orm.scalars(select(Photo))}), 29)

    def test_every_photo_is_inside_its_trips_window_and_not_after_the_clock(self):
        now = datetime(2026, 10, 5, 12, tzinfo=UTC)
        for photo in self.c.orm.scalars(select(Photo)):
            taken = photos.instant(photo.taken_utc)
            self.assertLessEqual(taken, now, photo.asset_id)
            person = self.c.orm.get(PhotoSource, photo.source_id).person_id
            if photo.trip_id is None:
                windows = photos.candidate_windows(self.c, person)
            else:
                found = photos.trip_window(self.c, photo.trip_id)
                assert found is not None
                windows = [found]
            self.assertTrue(any(w.start <= taken <= w.end for w in windows), photo.asset_id)

    def test_grants_share_each_photographed_trip_with_the_trip_and_leave_two_trips_unshared_or_declined(self):
        granted = self.c.orm.scalars(select(PhotoGrant)).all()
        live = [g for g in granted if g.revoked is None]
        self.assertEqual((len(live), {g.scope for g in live}), (5, {"trip"}))
        self.assertEqual({g.trip_id for g in live}, {self.trip_of(o) for o in ("Mile High Inn", "Lakeside Resort", "Harbour Hotel")})
        declined = [g for g in granted if g.revoked is not None]
        self.assertEqual([(g.person_id, g.trip_id) for g in declined], [(self.sam, self.trip_of("Miami"))])
        self.assertEqual(self.count(Photo, Photo.trip_id == self.trip_of("Bayview Inn")), 0)
        self.assertEqual(self.c.orm.get(PhotoGrant, (self.jane, self.trip_of("Bayview Inn"))), None)

    def test_the_road_trip_has_clusters_an_inferred_only_one_a_far_photo_and_a_removed_one(self):
        road = self.trip_of("Mile High Inn")
        got = photos.for_trip(self.c, Viewer(self.jane), road)
        assert got
        self.assertEqual((got["counts"]["total"], got["counts"]["far"]), (13, 1))
        self.assertTrue(any(c["inferred"] for c in got["clusters"]))
        self.assertTrue(any(not c["inferred"] and c["count"] >= 3 for c in got["clusters"]))
        self.assertIsNone(photos.for_trip(self.c, Viewer(self.sam), road))
        sharing = photos.removed(self.c, Viewer(self.jane), road)
        self.assertEqual(len(sharing), 1)
        self.assertEqual(self.count(PhotoExclusion, PhotoExclusion.trip_id == road), 1)

    def test_needs_a_look_has_one_far_and_one_ambiguous_photo(self):
        got = photos.needs_a_look(self.c, Viewer(self.jane))["photos"]
        self.assertEqual(sorted(p["match"] for p in got), ["ambiguous", "far"])
        self.assertTrue(all(p["candidates"] for p in got))
        self.assertEqual(photos.needs_a_look(self.c, Viewer(self.sam))["photos"], [])

    def test_a_trip_nobody_shared_shows_no_photos(self):
        for who in (self.jane, self.sam):
            got = photos.for_trip(self.c, Viewer(who), self.trip_of("Bayview Inn"))
            assert got
            self.assertEqual(got["counts"]["total"], 0)
