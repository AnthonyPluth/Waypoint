import itertools
import json
import unittest
from datetime import UTC

from tests.privacy import no_leaks
from tests.test_trips import CRUISE, HOTEL, OUT, PORTS, Household, RouteCase
from sqlalchemy import select, update

from waypoint.domain import photos, trips
from waypoint.domain.visibility import Viewer
from waypoint.server import mcp_access, mcp_http
from waypoint.storage import db, secretbox
from waypoint.storage.models import Photo, PhotoSource, Segment

ASSET = "canary-asset-9f3k2x7q"
URL = "https://immich-canary-8h2k.example:2283"
KEY = "canary-immich-key-5m7p2w"
LONDON = "Europe/London"
NEW_YORK = "America/New_York"
SOHO = (51.5136, -0.1365)
HEATHROW = (51.4706, -0.4619)
ROUTES = ("/api/trips/{id}/photos", "/api/photos/review", "/api/photos/{id}")
ROME = (41.9028, 12.4964)
PARIS = "Europe/Paris"
ST_PANCRAS = (51.5312, -0.1262)
GARE_DU_NORD = (48.8809, 2.3553)
DENVER = (39.8561, -104.6737)
PHOENIX = (33.4342, -112.0116)
_assets = itertools.count()


def utc(local, zone):
    return trips.instant(local, zone).astimezone(UTC).isoformat()


def source_row(person_id, owner):
    return PhotoSource(person_id=person_id, owner_sub=owner, url=URL, immich_user_id="immich-user-1", api_key=secretbox.encrypt(KEY) or "",
                       status="ok", created=1.0)


def photo_row(source_id, trip_id, local, zone=LONDON, *, match="place", where=None, segment_id=None, hidden=False, offset=None,
              decided=None, located=None, kind="image", distance=None, taken_utc=None):
    lat, lon = where or (None, None)
    return Photo(source_id=source_id, asset_id=f"{ASSET}-{next(_assets)}", asset_updated="2026-06-02T00:00:00Z", kind=kind, taken_utc=taken_utc or utc(local, zone), taken_local=local,
                 taken_offset=offset, latitude=lat, longitude=lon, location_source=located or ("exif" if where else None), state=None, country=None,
                 trip_id=trip_id, segment_id=segment_id, match=match, distance_km=distance, decided_by=decided, hidden=hidden, seen=1.0)


def stored(photo_id):
    with db.session() as conn:
        row = conn.orm.get(Photo, photo_id)
        assert row is not None
        return {k: getattr(row, k) for k in ("trip_id", "segment_id", "match", "distance_km", "decided_by", "hidden", "latitude", "longitude", "location_source")}


class PhotoRoutes(RouteCase):
    def setUp(self):
        super().setUp()
        self.flight = self.book("ana", travelers=[{"person_id": self.person["ana"]}, {"person_id": self.person["ben"]}])
        self.trip = self.flight["trip_id"]
        self.stay = self.book("ana", HOTEL, trip_id=self.trip)
        self.ana = self.source("ana")
        self.ben = self.source("ben")

    def keep(self, row):
        with db.session() as conn:
            conn.orm.add(row)
            conn.orm.flush()
            return row.id

    def source(self, who):
        return self.keep(source_row(self.person[who], f"sub-{who}"))

    def photo(self, source, trip, local, zone=LONDON, **fields):
        return self.keep(photo_row(source, trip, local, zone, **fields))

    def listing(self, who, trip=None):
        return self.ok(who, "GET", f"/api/trips/{self.trip if trip is None else trip}/photos")

    def own_trip(self, who, name="Later"):
        return self.ok(who, "POST", "/api/trips", {"name": name, "people": [self.person[who]]})["id"]

    def test_members_on_the_trip_get_every_librarys_photos_and_a_stranger_the_missing_trips_404(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO, segment_id=self.stay["id"], distance=1.2)
        theirs = self.photo(self.ben, self.trip, "2026-06-01T20:00", NEW_YORK, offset=-240, segment_id=self.flight["id"], match="time")
        for who in ("ana", "ben"):
            got = self.listing(who)
            self.assertEqual([p["id"] for p in got["photos"]], [theirs, mine], who)
            self.assertEqual(got["counts"], {"total": 2, "located": 1, "inferred": 0, "far": 0, "hidden": 0})
            self.assertEqual(got["people"], [{"person_id": self.person["ana"], "count": 1}, {"person_id": self.person["ben"], "count": 1}])
            self.assertEqual(got["clusters"], [{"latitude": SOHO[0], "longitude": SOHO[1], "count": 1, "first": "2026-06-02T10:00", "last": "2026-06-02T10:00",
                                                "cover": mine, "inferred": False}])
            self.assertEqual([p["cluster"] for p in got["photos"]], [None, 0])
        self.assertEqual(got["photos"][1], {"id": mine, "person_id": self.person["ana"], "trip_id": self.trip, "kind": "image", "taken_local": "2026-06-02T10:00", "zone": LONDON,
                                            "latitude": SOHO[0], "longitude": SOHO[1], "location_source": "exif", "segment_id": self.stay["id"],
                                            "match": "place", "distance_km": 1.2, "cluster": 0, "hidden": False})
        stranger = self.call("cy", "GET", f"/api/trips/{self.trip}/photos")
        self.assertEqual(stranger, (404, {"error": "No such trip"}))
        self.assertEqual(self.call("ana", "GET", "/api/trips/99999/photos"), stranger)
        self.assertEqual(self.call("ana", "GET", "/api/trips/x/photos"), stranger)

    def test_whoever_booked_a_segment_of_the_trip_gets_its_photos_too(self):
        booked = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        only = self.photo(self.ben, booked["trip_id"], "2026-09-02T09:00", segment_id=booked["id"])
        self.assertEqual([p["id"] for p in self.listing("ana", booked["trip_id"])["photos"]], [only])
        self.assertEqual([p["id"] for p in self.listing("ben", booked["trip_id"])["photos"]], [only])
        self.assertEqual(self.call("cy", "GET", f"/api/trips/{booked['trip_id']}/photos")[0], 404)

    def test_a_hidden_photo_is_seen_by_its_librarys_person_alone(self):
        shown = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO)
        hidden = self.photo(self.ana, self.trip, "2026-06-02T11:00", where=SOHO, hidden=True)
        got = self.listing("ana")
        self.assertEqual([(p["id"], p["hidden"]) for p in got["photos"]], [(shown, False), (hidden, True)])
        self.assertEqual((got["counts"]["total"], got["counts"]["hidden"], got["clusters"][0]["count"]), (2, 1, 2))
        got = self.listing("ben")
        self.assertEqual([(p["id"], p["hidden"]) for p in got["photos"]], [(shown, False)])
        self.assertEqual((got["counts"]["total"], got["counts"]["hidden"], got["clusters"][0]["count"]), (1, 0, 1))
        self.assertEqual(got["people"], [{"person_id": self.person["ana"], "count": 1}])

    def test_ambiguous_home_and_unmatched_rows_never_show_on_a_trip(self):
        for match in ("ambiguous", "home", "none"):
            self.photo(self.ana, self.trip, "2026-06-02T10:00", match=match, where=SOHO)
        far = self.photo(self.ana, self.trip, "2026-06-03T10:00", match="far", where=(48.85, 2.35), distance=410.0)
        timed = self.photo(self.ben, self.trip, "2026-06-04T10:00", match="time")
        got = self.listing("ana")
        self.assertEqual([(p["id"], p["match"]) for p in got["photos"]], [(far, "far"), (timed, "time")])
        self.assertEqual(got["counts"], {"total": 2, "located": 1, "inferred": 0, "far": 1, "hidden": 0})

    def test_the_zone_label_comes_with_the_photo_or_else_from_its_booking(self):
        cases = [(self.photo(self.ana, self.trip, "2026-06-02T03:00", offset=-420), "UTC−07:00"),
                 (self.photo(self.ana, self.trip, "2026-06-02T10:00", offset=0), "UTC"),
                 (self.photo(self.ana, self.trip, "2026-06-02T15:30", offset=330), "UTC+05:30"),
                 (self.photo(self.ana, self.trip, "2026-06-01T20:00", NEW_YORK, segment_id=self.flight["id"]), NEW_YORK),
                 (self.photo(self.ana, self.trip, "2026-06-02T07:10", segment_id=self.flight["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-02T09:00", segment_id=self.flight["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-03T09:00", segment_id=self.stay["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-03T09:30"), None)]
        self.ok("ana", "POST", f"/api/segments/{self.stay['id']}", {"status": "cancelled"})
        labels = {p["id"]: p["zone"] for p in self.listing("ana")["photos"]}
        self.assertEqual([labels[i] for i, _ in cases], [z for _, z in cases])

    def test_the_zone_follows_the_place_the_photo_matched_not_the_bookings_clock(self):
        early = self.photo(self.ana, self.trip, "2026-06-02T06:30", where=HEATHROW, segment_id=self.flight["id"])
        unplaced = self.photo(self.ana, self.trip, "2026-06-02T06:35", segment_id=self.flight["id"])
        guessed = self.photo(self.ana, self.trip, "2026-06-02T06:40", where=HEATHROW, located="inferred", segment_id=self.flight["id"])
        still_there = self.photo(self.ana, self.trip, "2026-06-01T23:30", NEW_YORK, where=(40.64, -73.78), segment_id=self.flight["id"])
        labels = {p["id"]: p["zone"] for p in self.listing("ana")["photos"]}
        self.assertEqual([labels[i] for i in (early, unplaced, guessed, still_there)], [LONDON, NEW_YORK, NEW_YORK, NEW_YORK])

    def located(self, segment_id, where):
        with db.session() as conn:
            conn.execute(update(Segment).where(Segment.id == segment_id).values(latitude=where[0], longitude=where[1]))

    def test_a_platform_photo_keeps_the_start_zone_until_the_train_arrives(self):
        train = self.book("ana", {"kind": "train", "origin": "London St Pancras", "destination": "Paris Gare du Nord", "provider": "Example Rail",
                                  "start_local": "2026-06-03T09:00", "end_local": "2026-06-03T12:30", "start_zone": LONDON, "end_zone": PARIS},
                          trip_id=self.trip, travelers=[{"person_id": self.person["ana"]}])
        self.located(train["id"], GARE_DU_NORD)
        cases = [(self.photo(self.ana, self.trip, "2026-06-03T08:45", where=ST_PANCRAS, segment_id=train["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-03T10:00", segment_id=train["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-03T10:30", where=(50.9, 1.8), segment_id=train["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-03T12:45", PARIS, where=GARE_DU_NORD, segment_id=train["id"]), PARIS),
                 (self.photo(self.ana, self.trip, "2026-06-03T13:00", PARIS, segment_id=train["id"]), PARIS)]
        labels = {p["id"]: p["zone"] for p in self.listing("ana")["photos"]}
        self.assertEqual([labels[i] for i, _ in cases], [z for _, z in cases])

    def test_a_one_way_rental_reads_in_the_drop_off_zone_only_once_it_is_there(self):
        car = self.book("ana", {"kind": "car", "origin": "Denver Airport", "destination": "Phoenix Airport", "provider": "Example Cars",
                                "start_local": "2026-06-04T10:00", "end_local": "2026-06-05T10:00", "start_zone": "America/Denver", "end_zone": "America/Phoenix"},
                        trip_id=self.trip)
        self.located(car["id"], DENVER)
        cases = [(self.photo(self.ana, self.trip, "2026-06-04T10:30", "America/Denver", where=DENVER, segment_id=car["id"]), "America/Denver"),
                 (self.photo(self.ana, self.trip, "2026-06-04T18:00", "America/Denver", where=(36.0, -109.0), segment_id=car["id"]), "America/Denver"),
                 (self.photo(self.ana, self.trip, "2026-06-05T09:00", "America/Phoenix", where=PHOENIX, segment_id=car["id"]), "America/Denver"),
                 (self.photo(self.ana, self.trip, "2026-06-05T11:00", "America/Phoenix", where=PHOENIX, segment_id=car["id"]), "America/Phoenix"),
                 (self.photo(self.ana, self.trip, "2026-06-05T11:30", "America/Phoenix", segment_id=car["id"]), "America/Phoenix")]
        labels = {p["id"]: p["zone"] for p in self.listing("ana")["photos"]}
        self.assertEqual([labels[i] for i, _ in cases], [z for _, z in cases])

    def test_a_photo_at_a_port_of_call_takes_the_ports_zone(self):
        voyage = self.own_trip("ana", "Caribbean")
        cruise = self.book("ana", {**CRUISE, "itinerary": PORTS}, trip_id=voyage, travelers=[{"person_id": self.person["ana"]}])
        nassau, cozumel, miami = (25.06, -77.34), (20.42, -86.92), (25.77, -80.19)
        cases = [(self.photo(self.ana, voyage, "2026-03-02T12:00", "America/Nassau", where=nassau, segment_id=cruise["id"]), "America/Nassau"),
                 (self.photo(self.ana, voyage, "2026-03-02T12:30", "America/Nassau", segment_id=cruise["id"]), "America/Nassau"),
                 (self.photo(self.ana, voyage, "2026-03-03T12:00", NEW_YORK, segment_id=cruise["id"]), NEW_YORK),
                 (self.photo(self.ana, voyage, "2026-03-05T12:00", "America/Cancun", where=cozumel, segment_id=cruise["id"]), "America/Cancun"),
                 (self.photo(self.ana, voyage, "2026-03-01T15:00", NEW_YORK, where=miami, segment_id=cruise["id"]), NEW_YORK),
                 (self.photo(self.ana, voyage, "2026-03-08T09:00", NEW_YORK, segment_id=cruise["id"]), NEW_YORK)]
        labels = {p["id"]: p["zone"] for p in self.listing("ana", voyage)["photos"]}
        self.assertEqual([labels[i] for i, _ in cases], [z for _, z in cases])

    def test_photos_are_ordered_by_the_instant_whatever_its_spelling(self):
        spelled = [("2026-06-02T09:00:00Z", "09:00Z"), ("2026-06-02T08:30:00+00:00", "08:30"), ("2026-06-02T08:00:00", "naive 08:00"),
                   ("2026-06-02T12:45:00+05:00", "07:45 as +05:00"), ("2026-06-02T09:00:00+00:00", "09:00 again")]
        ids = [self.photo(self.ana, self.trip, f"2026-06-02T{n:02d}:00", taken_utc=text) for n, (text, _) in enumerate(spelled)]
        self.assertEqual([p["id"] for p in self.listing("ana")["photos"]], [ids[3], ids[2], ids[1], ids[0], ids[4]])

    def test_a_trip_with_no_bookings_shows_its_photos_with_no_zone_and_no_pin_for_the_unplaced(self):
        empty = self.own_trip("ana", "Zoë’s week")
        only = self.photo(self.ana, empty, "2026-07-02T10:00", match="time")
        got = self.listing("ana", empty)
        self.assertEqual([(p["id"], p["zone"], p["segment_id"], p["cluster"]) for p in got["photos"]], [(only, None, None, None)])
        self.assertEqual(got["clusters"], [])

    def test_the_same_asset_in_two_libraries_is_two_photos(self):
        first = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO)
        second = self.photo(self.ben, self.trip, "2026-06-02T10:00", where=SOHO)
        got = self.listing("ben")
        self.assertEqual([p["id"] for p in got["photos"]], [first, second])
        self.assertEqual([p["count"] for p in got["people"]], [1, 1])
        self.assertEqual(got["clusters"][0]["count"], 2)

    def test_decide_refuses_another_persons_photo_and_a_trip_they_are_not_on(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO)
        self.assertEqual(self.call("ben", "POST", f"/api/photos/{mine}", {"hidden": True}), (404, {"error": "No such photo"}))
        self.assertEqual(self.call("ben", "POST", f"/api/photos/{mine}", {"trip_id": self.trip}), (404, {"error": "No such photo"}))
        self.assertEqual(self.call("ana", "POST", "/api/photos/99999", {"hidden": True}), (404, {"error": "No such photo"}))
        self.assertEqual(self.call("ana", "POST", "/api/photos/abc", {"hidden": True}), (404, {"error": "No such photo"}))
        cys = self.book("cy", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"})
        booked_for_ben = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{booked_for_ben['trip_id']}")["people"], [self.person["ben"]])
        for trip in (cys["trip_id"], booked_for_ben["trip_id"], 99999):
            self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": trip}), (400, {"error": "Choose a trip you are on"}), trip)
        for odd in ("abc", True, 1.5, 0, [1]):
            self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": odd})[0], 400, odd)
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": "abc"}), (400, {"error": "The trip must be a whole number"}))
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"hidden": "yes"}), (400, {"error": 'Send "hidden" as true or false'}))
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {})[0], 400)
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": None, "hidden": None})[0], 400)
        self.assertEqual(stored(mine)["trip_id"], self.trip)
        self.assertEqual((stored(mine)["decided_by"], stored(mine)["hidden"]), (None, False))

    def test_the_owner_places_a_photo_and_the_row_remembers_it_was_their_choice(self):
        later = self.book("ana", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])
        unsettled = self.photo(self.ana, None, "2027-01-02T09:00", where=SOHO, match="ambiguous")
        got = self.ok("ana", "POST", f"/api/photos/{unsettled}", {"trip_id": later["trip_id"]})
        self.assertEqual((got["trip_id"], got["match"], got["segment_id"], got["zone"], got["hidden"], got["cluster"]), (later["trip_id"], "place", later["id"], LONDON, False, None))
        self.assertAlmostEqual(got["distance_km"], 23.0, delta=1.5)
        self.assertEqual([p["id"] for p in self.listing("ana", later["trip_id"])["photos"]], [unsettled])
        self.assertEqual(self.listing("ana")["photos"], [])
        row = stored(unsettled)
        self.assertEqual((row["trip_id"], row["decided_by"], row["match"], row["location_source"]), (later["trip_id"], "owner", "place", "exif"))
        self.assertEqual((row["latitude"], row["longitude"]), SOHO)
        hidden = self.ok("ana", "POST", f"/api/photos/{unsettled}", {"hidden": True})
        self.assertEqual((hidden["hidden"], hidden["match"]), (True, "place"))
        self.assertEqual((stored(unsettled)["decided_by"], stored(unsettled)["hidden"]), ("owner", True))
        self.assertEqual([p["hidden"] for p in self.listing("ana", later["trip_id"])["photos"]], [True])
        shown = self.ok("ana", "POST", f"/api/photos/{unsettled}", {"hidden": False})
        self.assertEqual(shown["hidden"], False)

    def test_hiding_alone_leaves_the_match_to_the_sync(self):
        auto = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO, decided="auto")
        got = self.ok("ana", "POST", f"/api/photos/{auto}", {"trip_id": None, "hidden": True})
        self.assertEqual((got["hidden"], got["match"], got["segment_id"]), (True, "place", None))
        self.assertEqual((stored(auto)["decided_by"], stored(auto)["hidden"], stored(auto)["trip_id"]), ("auto", True, self.trip))

    def test_a_far_photo_the_owner_accepts_stays_flagged_but_leaves_needs_a_look(self):
        far = self.photo(self.ana, self.trip, "2026-06-03T10:00", match="far", where=ROME, segment_id=self.stay["id"], distance=1400.0)
        self.assertEqual([p["id"] for p in self.ok("ana", "GET", "/api/photos/review")["photos"]], [far])
        got = self.ok("ana", "POST", f"/api/photos/{far}", {"trip_id": self.trip})
        self.assertEqual((got["match"], got["segment_id"]), ("far", self.flight["id"]))
        self.assertAlmostEqual(got["distance_km"], 1435.0, delta=15.0)
        self.assertEqual(self.ok("ana", "GET", "/api/photos/review")["photos"], [])
        self.assertEqual([(p["id"], p["match"]) for p in self.listing("ben")["photos"]], [(far, "far")])
        self.assertEqual(stored(far)["decided_by"], "owner")

    def test_a_photo_without_gps_is_placed_from_the_itinerary_of_the_trip_it_moves_to(self):
        later = self.book("ana", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])
        guessed = self.photo(self.ana, self.trip, "2027-01-02T12:00", where=SOHO, located="inferred", segment_id=self.stay["id"], match="time")
        got = self.ok("ana", "POST", f"/api/photos/{guessed}", {"trip_id": later["trip_id"]})
        self.assertEqual((got["match"], got["segment_id"], got["location_source"], got["distance_km"], got["zone"]), ("time", later["id"], "inferred", None, LONDON))
        self.assertAlmostEqual(got["latitude"], HEATHROW[0], delta=0.05)
        self.assertAlmostEqual(got["longitude"], HEATHROW[1], delta=0.05)
        self.assertEqual(self.listing("ana", later["trip_id"])["clusters"][0]["inferred"], True)
        empty = self.own_trip("ana")
        got = self.ok("ana", "POST", f"/api/photos/{guessed}", {"trip_id": empty})
        self.assertEqual((got["match"], got["segment_id"], got["latitude"], got["longitude"], got["location_source"], got["zone"]), ("time", None, None, None, None, None))
        self.assertEqual(stored(guessed)["trip_id"], empty)
        blank = self.photo(self.ana, None, "2027-01-02T12:00", match="ambiguous")
        got = self.ok("ana", "POST", f"/api/photos/{blank}", {"trip_id": later["trip_id"]})
        self.assertEqual((got["match"], got["segment_id"], got["location_source"]), ("time", later["id"], "inferred"))

    def test_moving_to_a_trip_whose_bookings_are_all_cancelled_keeps_the_time_match(self):
        later = self.book("ana", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])
        self.ok("ana", "POST", f"/api/segments/{later['id']}", {"status": "cancelled"})
        mine = self.photo(self.ana, self.trip, "2027-01-02T09:00", where=SOHO, segment_id=self.stay["id"], distance=1.0)
        got = self.ok("ana", "POST", f"/api/photos/{mine}", {"trip_id": later["trip_id"]})
        self.assertEqual((got["match"], got["segment_id"], got["distance_km"], got["latitude"], got["location_source"], got["zone"]), ("time", None, None, SOHO[0], "exif", None))

    def test_needs_a_look_lists_the_persons_unsettled_photos_with_the_trips_they_could_join(self):
        week = self.own_trip("ana", "Zoë’s week in Montréal")
        self.book("ana", {**HOTEL, "origin": "Hôtel Été", "start_local": "2026-06-03T15:00", "end_local": "2026-06-05T10:00"}, trip_id=week)
        torn = self.photo(self.ana, None, "2026-06-04T12:00", match="ambiguous", where=SOHO)
        far = self.photo(self.ana, self.trip, "2026-06-02T10:00", match="far", where=(48.85, 2.35), segment_id=self.stay["id"], distance=410.0)
        self.photo(self.ana, self.trip, "2026-06-02T11:00", match="far", where=(48.85, 2.35), decided="owner")
        self.photo(self.ana, self.trip, "2026-06-02T12:00", where=SOHO)
        self.photo(self.ana, None, "2026-06-04T12:30", match="home")
        bens = self.photo(self.ben, None, "2026-06-04T13:00", match="ambiguous")
        got = self.ok("ana", "GET", "/api/photos/review")
        self.assertEqual([(p["id"], p["trip_id"]) for p in got["photos"]], [(far, self.trip), (torn, None)])
        name = self.ok("ana", "GET", f"/api/trips/{self.trip}")["name"]
        self.assertEqual(got["photos"][0]["candidates"], [{"id": self.trip, "name": name}])
        self.assertEqual(got["photos"][1]["candidates"], [{"id": self.trip, "name": name}, {"id": week, "name": "Zoë’s week in Montréal"}])
        self.assertEqual((got["photos"][0]["zone"], got["photos"][1]["zone"], got["photos"][1]["segment_id"]), (LONDON, None, None))
        self.assertEqual(sorted(got["photos"][1]), sorted([*self.listing("ana")["photos"][0], "candidates"]))
        self.assertEqual([p["id"] for p in self.ok("ben", "GET", "/api/photos/review")["photos"]], [bens])
        self.assertEqual([p["candidates"] for p in self.ok("ben", "GET", "/api/photos/review")["photos"]], [[{"id": self.trip, "name": name}]])
        self.assertEqual(self.ok("cy", "GET", "/api/photos/review"), {"photos": []})
        self.ok("ana", "POST", f"/api/photos/{torn}", {"trip_id": week})
        self.assertEqual([p["id"] for p in self.ok("ana", "GET", "/api/photos/review")["photos"]], [far])
        self.assertEqual([p["id"] for p in self.listing("ana", week)["photos"]], [torn])

    def test_the_replies_never_carry_the_asset_id_the_library_address_or_the_key(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO, segment_id=self.stay["id"])
        torn = self.photo(self.ana, None, "2026-06-04T12:00", match="ambiguous")
        with no_leaks(self, ASSET, URL, KEY, "immich-user-1"):
            replies = [self.listing("ana"), self.ok("ana", "GET", "/api/photos/review"), self.ok("ana", "POST", f"/api/photos/{mine}", {"hidden": True}),
                       self.ok("ana", "POST", f"/api/photos/{torn}", {"trip_id": self.trip}), self.call("ben", "POST", f"/api/photos/{mine}", {"hidden": False})[1],
                       self.call("cy", "GET", f"/api/trips/{self.trip}/photos")[1]]
        text = json.dumps(replies)
        for canary in (ASSET, URL, KEY, "immich-user-1", "asset", "api_key", "source_id"):
            self.assertNotIn(canary, text, canary)

    def test_assistants_never_reach_the_photo_routes(self):
        for pattern in ROUTES:
            self.assertTrue(mcp_access.blocked(pattern), pattern)
            for method in ("GET", "POST"):
                self.assertIsNone(mcp_http.needs(method, pattern), f"{method} {pattern}")


class PhotoViewers(Household):
    def setUp(self):
        super().setUp()
        self.jid, self.sid = self.jane.person_id, self.sam.person_id
        self.flight = self.add(self.jane, OUT, None, self.on(self.jid))
        self.trip = self.flight["trip_id"]
        self.sams = self.add(self.sam, {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, None, self.on(self.sid))
        self.household = Viewer(None, household=True)
        self.c.orm.add_all([source_row(self.jid, "u-jane"), source_row(self.sid, "u-sam")])
        self.c.orm.flush()
        self.janes, self.sams_source = [s.id for s in self.c.orm.scalars(select(PhotoSource).order_by(PhotoSource.id)).all()]

    def photo(self, source, trip, local, zone=LONDON, **fields):
        row = photo_row(source, trip, local, zone, **fields)
        self.c.orm.add(row)
        self.c.orm.flush()
        return row.id

    def test_a_viewer_without_a_person_sees_and_decides_nothing(self):
        mine = self.photo(self.janes, self.trip, "2026-06-02T10:00", where=SOHO)
        nobody = Viewer(None)
        self.assertIsNone(photos.for_trip(self.c, nobody, self.trip))
        self.assertEqual(photos.needs_a_look(self.c, nobody), {"photos": []})
        self.assertIsNone(photos.decide(self.c, nobody, mine, None, True))
        self.assertFalse(stored_hidden(self.c, mine))

    def test_without_sign_in_the_household_stands_for_every_library(self):
        hidden = self.photo(self.janes, self.trip, "2026-06-02T10:00", where=SOHO, hidden=True)
        torn = self.photo(self.sams_source, None, "2026-09-02T12:00", match="ambiguous")
        self.assertEqual([(p["id"], p["hidden"]) for p in photos.for_trip(self.c, self.household, self.trip)["photos"]], [(hidden, True)])
        self.assertEqual([p["id"] for p in photos.needs_a_look(self.c, self.household)["photos"]], [torn])
        self.assertEqual(photos.needs_a_look(self.c, self.household)["photos"][0]["candidates"], [{"id": self.sams["trip_id"], "name": trips.get(self.c, self.sam, self.sams["trip_id"])["name"]}])
        with self.assertRaises(trips.Invalid) as refused:
            photos.decide(self.c, self.household, torn, self.trip, None)
        self.assertEqual(str(refused.exception), photos.NOT_ON_TRIP)
        placed = photos.decide(self.c, self.household, torn, self.sams["trip_id"], None)
        self.assertEqual((placed["match"], placed["segment_id"]), ("time", self.sams["id"]))
        self.assertEqual(photos.needs_a_look(self.c, self.household), {"photos": []})

    def test_a_person_decides_only_their_own_librarys_photos(self):
        hers = self.photo(self.janes, self.trip, "2026-06-02T10:00", where=SOHO)
        self.assertIsNone(photos.decide(self.c, self.sam, hers, None, True))
        self.assertEqual(photos.needs_a_look(self.c, self.sam), {"photos": []})
        self.assertIsNone(photos.for_trip(self.c, self.sam, self.trip))
        got = photos.decide(self.c, self.jane, hers, None, True)
        self.assertEqual((got["id"], got["hidden"]), (hers, True))

    def test_a_cruise_without_its_own_point_takes_its_first_ports_zone_at_embarkation(self):
        cruise = self.add(self.jane, {**CRUISE, "itinerary": PORTS}, None, self.on(self.jid))
        self.c.execute(update(Segment).where(Segment.id == cruise["id"]).values(latitude=None, longitude=None))
        self.c.orm.expire_all()
        nassau = (25.06, -77.34)
        during = self.photo(self.janes, cruise["trip_id"], "2026-03-02T12:00", "America/Nassau", where=nassau, segment_id=cruise["id"])
        before = self.photo(self.janes, cruise["trip_id"], "2026-03-01T20:00", NEW_YORK, where=nassau, segment_id=cruise["id"])
        at_sea = self.photo(self.janes, cruise["trip_id"], "2026-03-03T12:00", NEW_YORK, segment_id=cruise["id"])
        ashore = self.photo(self.janes, cruise["trip_id"], "2026-03-08T09:00", NEW_YORK, segment_id=cruise["id"])
        labels = {p["id"]: p["zone"] for p in photos.for_trip(self.c, self.jane, cruise["trip_id"])["photos"]}
        self.assertEqual([labels[i] for i in (before, during, at_sea, ashore)], ["America/Nassau", "America/Nassau", "America/Nassau", NEW_YORK])
        (main, *calls) = photos.segment_points(self.c, [self.c.orm.get(Segment, cruise["id"])])[cruise["id"]]
        self.assertEqual((main.origin, main.zone, main.to_zone), (calls[0].origin, "America/Nassau", NEW_YORK))

    def test_the_offset_label_reads_as_utc_plus_or_minus(self):
        self.assertEqual([photos.offset_label(m) for m in (0, 60, -60, 330, -570, 765, -720)],
                         ["UTC", "UTC+01:00", "UTC−01:00", "UTC+05:30", "UTC−09:30", "UTC+12:45", "UTC−12:00"])

    def test_an_instant_is_read_in_utc_whatever_its_spelling(self):
        for text in ("2026-06-02T09:00:00+00:00", "2026-06-02T09:00:00Z", "2026-06-02T09:00:00", "2026-06-02T10:00:00+01:00"):
            self.assertEqual(photos.instant(text).isoformat(), "2026-06-02T09:00:00+00:00", text)


def stored_hidden(conn, photo_id):
    row = conn.orm.get(Photo, photo_id)
    assert row is not None
    return row.hidden


if __name__ == "__main__":
    unittest.main()
