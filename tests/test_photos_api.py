import itertools
import json
import unittest
from datetime import UTC

from tests.privacy import no_leaks
from tests.shared import empty_immich
from tests.test_trips import CRUISE, HOTEL, OUT, Household, RouteCase
from sqlalchemy import select, update

from waypoint.domain import photos, trips
from waypoint.domain.visibility import Viewer
from waypoint.server import mcp_access, mcp_http
from waypoint.storage import db, secretbox
from waypoint.storage.models import Photo, PhotoGrant, PhotoSource, Segment

ASSET = "canary-asset-9f3k2x7q"
URL = "https://immich-canary-8h2k.example:2283"
KEY = "canary-immich-key-5m7p2w"
LONDON = "Europe/London"
NEW_YORK = "America/New_York"
SOHO = (51.5136, -0.1365)
HEATHROW = (51.4706, -0.4619)
ROUTES = ("/api/trips/{id}/photos", "/api/photos/review", "/api/photos/{id}", "/api/trips/{id}/photo-sharing", "/api/trips/{id}/photo-exclusions",
          "/api/trips/{id}/photo-exclusions/{id}", "/api/photo-grants", "/api/photo-sharing-prefs/{id}")
ROME = (41.9028, 12.4964)
PARIS = "Europe/Paris"
CHICAGO, CANCUN, PUERTO_RICO = "America/Chicago", "America/Cancun", "America/Puerto_Rico"
ST_PANCRAS = (51.5312, -0.1262)
GARE_DU_NORD = (48.8809, 2.3553)
DENVER = (39.8561, -104.6737)
PHOENIX = (33.4342, -112.0116)
REYKJAVIK = (64.1466, -21.9426)
TOKYO = (35.6895, 139.6917)
GALVESTON = (29.3013, -94.7977)
COZUMEL = (20.5004, -86.9427)
SAN_JUAN = (18.4663, -66.1057)
AT_SEA = (24.5, -88.0)
CALLS = [{"name": "Cozumel", "zone": CANCUN, "arrive_local": "2026-03-03T08:00", "depart_local": "2026-03-03T17:00"},
         {"name": "San Juan", "zone": PUERTO_RICO, "arrive_local": "2026-03-05T08:00", "depart_local": "2026-03-05T17:00"}]
_assets = itertools.count()


def utc(local, zone):
    return trips.instant(local, zone).astimezone(UTC).isoformat()


def source_row(person_id, owner):
    return PhotoSource(person_id=person_id, owner_sub=owner, url=URL, immich_user_id="immich-user-1", api_key=secretbox.encrypt(KEY) or "",
                       status="ok", created=1.0)


def photo_row(source_id, trip_id, local, zone=LONDON, *, match="place", where=None, segment_id=None, offset=None,
              decided=None, located=None, kind="image", distance=None, taken_utc=None, asset=None):
    lat, lon = where or (None, None)
    return Photo(source_id=source_id, asset_id=asset or f"{ASSET}-{next(_assets)}", asset_updated="2026-06-02T00:00:00Z", kind=kind, taken_utc=taken_utc or utc(local, zone), taken_local=local,
                 taken_offset=offset, latitude=lat, longitude=lon, location_source=located or ("exif" if where else None), state=None, country=None,
                 trip_id=trip_id, segment_id=segment_id, match=match, distance_km=distance, decided_by=decided, seen=1.0)


def grant_row(person_id, trip_id, scope="trip", revoked=None, by="sub-x"):
    return PhotoGrant(person_id=person_id, trip_id=trip_id, scope=scope, revoked=revoked, changed=1.0, granted_by=by)


def stored(photo_id):
    with db.session() as conn:
        row = conn.orm.get(Photo, photo_id)
        if row is None:
            return None
        return {k: getattr(row, k) for k in ("trip_id", "segment_id", "match", "distance_km", "decided_by", "latitude", "longitude", "location_source")}


class PhotoRoutes(RouteCase):
    def setUp(self):
        super().setUp()
        empty_immich(self)
        self.flight = self.book("ana", travelers=[{"person_id": self.person["ana"]}, {"person_id": self.person["ben"]}])
        self.trip = self.flight["trip_id"]
        self.stay = self.book("ana", HOTEL, trip_id=self.trip)
        self.ana = self.source("ana")
        self.ben = self.source("ben")
        self.share("ana", self.trip)
        self.share("ben", self.trip)

    def keep(self, row):
        with db.session() as conn:
            conn.orm.add(row)
            conn.orm.flush()
            return getattr(row, "id", None)

    def source(self, who):
        return self.keep(source_row(self.person[who], f"sub-{who}"))

    def share(self, who, trip, scope="trip", revoked=None):
        self.keep(grant_row(self.person[who], trip, scope, revoked, f"sub-{who}"))

    def confirm(self, who, trip, scope="trip"):
        seen = self.ok(who, "GET", f"/api/trips/{trip}/photo-sharing")
        body = {"scope": scope, "window": seen["window"], "audience": seen["audience"], "sources": seen["sources"]}
        if seen["changed"] is not None:
            body["expected_changed"] = seen["changed"]
        return self.ok(who, "POST", f"/api/trips/{trip}/photo-sharing", body)

    def photo(self, source, trip, local, zone=LONDON, **fields):
        return self.keep(photo_row(source, trip, local, zone, **fields))

    def listing(self, who, trip=None):
        return self.ok(who, "GET", f"/api/trips/{self.trip if trip is None else trip}/photos")

    def own_trip(self, who, name="Later", shared=True):
        trip = self.ok(who, "POST", "/api/trips", {"name": name, "people": [self.person[who]]})["id"]
        if shared:
            self.share(who, trip)
        return trip

    def later(self, who="ana", **fields):
        seg = self.book(who, {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10", **fields}, travelers=[{"person_id": self.person[who]}])
        self.share(who, seg["trip_id"])
        return seg

    def test_members_on_the_trip_get_every_librarys_photos_and_a_stranger_the_missing_trips_404(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO, segment_id=self.stay["id"], distance=1.2)
        theirs = self.photo(self.ben, self.trip, "2026-06-01T20:00", NEW_YORK, offset=-240, segment_id=self.flight["id"], match="time")
        for who in ("ana", "ben"):
            got = self.listing(who)
            self.assertEqual([p["id"] for p in got["photos"]], [theirs, mine], who)
            self.assertEqual(got["counts"], {"total": 2, "located": 1, "inferred": 0, "far": 0})
            self.assertEqual(got["people"], [{"person_id": self.person["ana"], "count": 1}, {"person_id": self.person["ben"], "count": 1}])
            self.assertEqual(got["clusters"], [{"latitude": SOHO[0], "longitude": SOHO[1], "count": 1, "first": "2026-06-02T10:00", "last": "2026-06-02T10:00",
                                                "cover": mine, "inferred": False}])
            self.assertEqual([p["cluster"] for p in got["photos"]], [None, 0])
        self.assertEqual(got["photos"][1], {"id": mine, "person_id": self.person["ana"], "trip_id": self.trip, "kind": "image", "taken_local": "2026-06-02T10:00", "zone": LONDON,
                                            "latitude": SOHO[0], "longitude": SOHO[1], "location_source": "exif", "segment_id": self.stay["id"],
                                            "match": "place", "distance_km": 1.2, "cluster": 0, "removed_at": None})
        stranger = self.call("cy", "GET", f"/api/trips/{self.trip}/photos")
        self.assertEqual(stranger, (404, {"error": "No such trip"}))
        self.assertEqual(self.call("ana", "GET", "/api/trips/99999/photos"), stranger)
        self.assertEqual(self.call("ana", "GET", "/api/trips/x/photos"), stranger)

    def test_whoever_booked_a_segment_of_the_trip_without_being_on_it_sees_the_trip_but_not_its_photos(self):
        booked = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        self.share("ben", booked["trip_id"])
        only = self.photo(self.ben, booked["trip_id"], "2026-09-02T09:00", segment_id=booked["id"])
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{booked['trip_id']}")["id"], booked["trip_id"])
        self.assertEqual(self.listing("ana", booked["trip_id"])["photos"], [])
        self.assertEqual([p["id"] for p in self.listing("ben", booked["trip_id"])["photos"]], [only])
        self.assertEqual(self.call("cy", "GET", f"/api/trips/{booked['trip_id']}/photos")[0], 404)
        self.ok("ben", "POST", f"/api/segments/{booked['id']}", {"travelers": [{"person_id": self.person["ben"]}, {"person_id": self.person["ana"]}]})
        self.assertEqual(self.listing("ana", booked["trip_id"])["photos"], [])
        self.assertEqual(self.ok("ben", "GET", f"/api/trips/{booked['trip_id']}/photo-sharing")["state"], "ask")
        self.confirm("ben", booked["trip_id"])
        self.assertEqual([p["id"] for p in self.listing("ana", booked["trip_id"])["photos"]], [only])

    def test_the_canonical_row_is_chosen_before_needs_a_look_filters_so_an_asset_shows_once(self):
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.ana).values(status="refused"))
        second = self.keep(PhotoSource(person_id=self.person["ana"], owner_sub="sub-ana", url=URL + "1", immich_user_id="immich-user-1",
                                       api_key=secretbox.encrypt(KEY) or "", status="ok", created=1.0))
        placed = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO, asset="twice-3p8q")
        torn = self.photo(second, None, "2026-06-02T10:00", where=SOHO, match="ambiguous", asset="twice-3p8q")
        self.assertEqual(self.listing("ana")["photos"], [])
        self.assertEqual([p["id"] for p in self.ok("ana", "GET", "/api/photos/review")["photos"]], [torn])
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{placed}", {"trip_id": self.trip}), (404, {"error": "No such photo"}))
        with db.session() as conn:
            conn.execute(update(PhotoSource).where(PhotoSource.id == self.ana).values(status="ok"))
        self.assertEqual([p["id"] for p in self.listing("ana")["photos"]], [placed])
        self.assertEqual(self.ok("ana", "GET", "/api/photos/review")["photos"], [])
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{torn}", {"excluded": True}), (404, {"error": "No such photo"}))

    def test_the_canonical_lookup_reads_only_the_assets_asked_about(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO, asset="asked-1x")
        self.photo(self.ana, self.trip, "2026-06-02T11:00", where=SOHO, asset="not-asked-2y")
        with db.session() as conn:
            self.assertEqual(photos.canonical_ids(conn, {(self.person["ana"], "asked-1x")}), {mine})
            self.assertEqual(photos.canonical_ids(conn, {(self.person["ben"], "asked-1x")}), set())
            self.assertEqual(photos.canonical_ids(conn, set()), set())

    def test_the_same_asset_through_two_libraries_of_one_person_is_one_photo(self):
        second = self.keep(PhotoSource(person_id=self.person["ana"], owner_sub="sub-ana", url=URL + "1", immich_user_id="immich-user-1",
                                       api_key=secretbox.encrypt(KEY) or "", status="ok", created=1.0))
        first = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO, asset="twice-9k2m")
        twin = self.photo(second, self.trip, "2026-06-02T10:00", where=SOHO, asset="twice-9k2m")
        for who in ("ana", "ben"):
            got = self.listing(who)
            self.assertEqual(([p["id"] for p in got["photos"]], got["counts"]["total"], got["people"], got["clusters"][0]["count"]),
                             ([first], 1, [{"person_id": self.person["ana"], "count": 1}], 1), who)
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{self.trip}/summary")["photos"], {"total": 1, "inferred": 0})
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{twin}", {"trip_id": self.trip}), (404, {"error": "No such photo"}))
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [twin]}), (404, {"error": "No such photo"}))
        got = self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [first]})
        self.assertEqual((got["removed_count"], [p["id"] for p in got["removed"]]), (1, [first]))
        self.assertEqual(self.listing("ana")["photos"], [])
        self.assertEqual(self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{first}")["count"], 1)
        self.assertEqual([p["id"] for p in self.listing("ben")["photos"]], [first])

    def test_ambiguous_home_and_unmatched_rows_never_show_on_a_trip(self):
        for match in ("ambiguous", "home", "none"):
            self.photo(self.ana, self.trip, "2026-06-02T10:00", match=match, where=SOHO)
        far = self.photo(self.ana, self.trip, "2026-06-03T10:00", match="far", where=(48.85, 2.35), distance=410.0)
        timed = self.photo(self.ben, self.trip, "2026-06-04T10:00", match="time")
        got = self.listing("ana")
        self.assertEqual([(p["id"], p["match"]) for p in got["photos"]], [(far, "far"), (timed, "time")])
        self.assertEqual(got["counts"], {"total": 2, "located": 1, "inferred": 0, "far": 1})

    def test_the_zone_label_comes_with_the_photo_or_else_from_its_booking(self):
        self.ok("ana", "POST", f"/api/segments/{self.stay['id']}", {"status": "cancelled"})
        cases = [(self.photo(self.ana, self.trip, "2026-06-02T03:00", offset=-420), "UTC−07:00"),
                 (self.photo(self.ana, self.trip, "2026-06-02T10:00", offset=0), "UTC"),
                 (self.photo(self.ana, self.trip, "2026-06-02T15:30", offset=330), "UTC+05:30"),
                 (self.photo(self.ana, self.trip, "2026-06-01T20:00", NEW_YORK, segment_id=self.flight["id"]), NEW_YORK),
                 (self.photo(self.ana, self.trip, "2026-06-02T07:10", segment_id=self.flight["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-02T09:00", segment_id=self.flight["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-03T09:00", segment_id=self.stay["id"]), LONDON),
                 (self.photo(self.ana, self.trip, "2026-06-03T09:30"), None)]
        labels = {p["id"]: p["zone"] for p in self.listing("ana")["photos"]}
        self.assertEqual([labels[i] for i, _ in cases], [z for _, z in cases])

    def located(self, segment_id, where):
        with db.session() as conn:
            conn.execute(update(Segment).where(Segment.id == segment_id).values(latitude=where[0], longitude=where[1]))

    def labels(self, trip, cases):
        ids = [self.photo(self.ana, trip, local, zone, where=where, segment_id=segment, located="exif" if where else None) for local, zone, where, segment, _ in cases]
        found = {p["id"]: p["zone"] for p in self.listing("ana", trip)["photos"]}
        self.assertEqual([found[i] for i in ids], [expected for *_, expected in cases])

    def test_a_flight_reads_at_the_airport_the_photo_is_near_else_by_its_clock(self):
        f, jfk = self.flight["id"], (40.6413, -73.7781)
        self.labels(self.trip, [("2026-06-01T17:00", NEW_YORK, jfk, f, NEW_YORK), ("2026-06-01T20:00", NEW_YORK, jfk, f, NEW_YORK), ("2026-06-02T09:00", LONDON, jfk, f, NEW_YORK),
                                ("2026-06-01T17:00", NEW_YORK, HEATHROW, f, LONDON), ("2026-06-02T06:30", LONDON, HEATHROW, f, LONDON), ("2026-06-02T09:00", LONDON, HEATHROW, f, LONDON),
                                ("2026-06-01T17:00", NEW_YORK, REYKJAVIK, f, NEW_YORK), ("2026-06-02T02:00", LONDON, REYKJAVIK, f, NEW_YORK), ("2026-06-02T07:10", LONDON, REYKJAVIK, f, LONDON),
                                ("2026-06-01T17:00", NEW_YORK, None, f, NEW_YORK), ("2026-06-02T02:00", LONDON, None, f, NEW_YORK), ("2026-06-02T09:00", LONDON, None, f, LONDON)])

    def test_a_stay_and_a_parking_booking_read_in_their_one_zone_wherever_the_photo_is(self):
        self.located(self.stay["id"], SOHO)
        lot = self.book("ana", {"kind": "parking", "origin": "Pike Lot", "start_local": "2026-06-04T06:00", "end_local": "2026-06-05T22:00",
                                "start_zone": "America/Denver", "end_zone": "America/Denver"}, trip_id=self.trip)
        self.located(lot["id"], DENVER)
        cases = []
        for where in (SOHO, GARE_DU_NORD, None):
            cases += [(local, LONDON, where, self.stay["id"], LONDON) for local in ("2026-06-02T12:00", "2026-06-05T12:00", "2026-06-08T12:00")]
            cases += [(local, "America/Denver", DENVER if where is SOHO else where, lot["id"], "America/Denver") for local in ("2026-06-04T05:00", "2026-06-04T18:00", "2026-06-05T23:00")]
        self.labels(self.trip, cases)

    def test_a_one_way_rental_reads_at_the_pickup_point_when_near_it_else_by_its_clock(self):
        car = self.book("ana", {"kind": "car", "origin": "Denver Airport", "destination": "Phoenix Airport", "provider": "Example Cars",
                                "start_local": "2026-06-04T10:00", "end_local": "2026-06-05T10:00", "start_zone": "America/Denver", "end_zone": "America/Phoenix"},
                        trip_id=self.trip)
        self.located(car["id"], DENVER)
        c, denver, phoenix = car["id"], "America/Denver", "America/Phoenix"
        self.labels(self.trip, [("2026-06-04T09:00", denver, DENVER, c, denver), ("2026-06-04T18:00", denver, DENVER, c, denver), ("2026-06-05T11:00", phoenix, DENVER, c, denver),
                                ("2026-06-04T09:00", denver, PHOENIX, c, denver), ("2026-06-05T09:00", phoenix, PHOENIX, c, denver), ("2026-06-05T11:00", phoenix, PHOENIX, c, phoenix),
                                ("2026-06-04T09:00", denver, None, c, denver), ("2026-06-04T18:00", denver, None, c, denver), ("2026-06-05T11:00", phoenix, None, c, phoenix)])

    def test_a_train_reads_at_its_arrival_station_when_near_it_else_by_its_clock(self):
        train = self.book("ana", {"kind": "train", "origin": "London St Pancras", "destination": "Paris Gare du Nord", "provider": "Example Rail",
                                  "start_local": "2026-06-03T09:00", "end_local": "2026-06-03T12:30", "start_zone": LONDON, "end_zone": PARIS},
                          trip_id=self.trip, travelers=[{"person_id": self.person["ana"]}])
        self.located(train["id"], GARE_DU_NORD)
        t = train["id"]
        self.labels(self.trip, [("2026-06-03T08:00", LONDON, GARE_DU_NORD, t, PARIS), ("2026-06-03T10:00", LONDON, GARE_DU_NORD, t, PARIS), ("2026-06-03T13:00", PARIS, GARE_DU_NORD, t, PARIS),
                                ("2026-06-03T08:45", LONDON, ST_PANCRAS, t, LONDON), ("2026-06-03T10:00", LONDON, ST_PANCRAS, t, LONDON), ("2026-06-03T13:00", PARIS, ST_PANCRAS, t, PARIS),
                                ("2026-06-03T08:45", LONDON, None, t, LONDON), ("2026-06-03T10:00", LONDON, None, t, LONDON), ("2026-06-03T12:30", PARIS, None, t, PARIS)])

    def test_a_visit_reads_in_its_countrys_zone_wherever_the_photo_is(self):
        japan = self.own_trip("ana", "Japan")
        visit = self.book("ana", {"kind": "visit", "destination": "JP", "start_local": "2026-06-20T00:00", "end_local": "2026-06-22T00:00"}, trip_id=japan)
        self.located(visit["id"], TOKYO)
        v, tokyo = visit["id"], "Asia/Tokyo"
        self.labels(japan, [(local, tokyo, where, v, tokyo) for where in (TOKYO, SOHO, None) for local in ("2026-06-19T12:00", "2026-06-21T12:00", "2026-06-23T12:00")])

    def cruise(self, trip, with_point=True):
        voyage = self.book("ana", {**CRUISE, "origin": "Galveston", "destination": "Galveston", "start_zone": CHICAGO, "end_zone": CHICAGO, "itinerary": CALLS},
                           trip_id=trip, travelers=[{"person_id": self.person["ana"]}])
        self.located(voyage["id"], GALVESTON if with_point else (None, None))
        return voyage["id"]

    def test_a_cruise_reads_at_the_port_the_photo_is_near_else_by_the_ships_clock_and_its_calls(self):
        voyage = self.own_trip("ana", "Gulf cruise")
        c = self.cruise(voyage)
        self.labels(voyage, [("2026-03-01T15:00", CHICAGO, GALVESTON, c, CHICAGO), ("2026-03-04T12:00", CHICAGO, GALVESTON, c, CHICAGO), ("2026-03-08T09:00", CHICAGO, GALVESTON, c, CHICAGO),
                             ("2026-03-03T12:00", CANCUN, COZUMEL, c, CANCUN), ("2026-03-03T06:00", CANCUN, COZUMEL, c, CANCUN), ("2026-03-05T12:00", PUERTO_RICO, SAN_JUAN, c, PUERTO_RICO),
                             ("2026-03-01T15:00", CHICAGO, AT_SEA, c, CHICAGO), ("2026-03-04T12:00", CHICAGO, AT_SEA, c, CHICAGO), ("2026-03-03T12:00", CANCUN, AT_SEA, c, CANCUN),
                             ("2026-03-08T09:00", CHICAGO, AT_SEA, c, CHICAGO),
                             ("2026-03-01T15:00", CHICAGO, None, c, CHICAGO), ("2026-03-04T12:00", CHICAGO, None, c, CHICAGO), ("2026-03-03T12:00", CANCUN, None, c, CANCUN),
                             ("2026-03-05T12:00", PUERTO_RICO, None, c, PUERTO_RICO), ("2026-03-08T09:00", CHICAGO, None, c, CHICAGO)])

    def test_a_cruise_without_its_own_point_keeps_the_ships_clock_away_from_its_calls(self):
        voyage = self.own_trip("ana", "Gulf cruise")
        c = self.cruise(voyage, with_point=False)
        self.labels(voyage, [("2026-03-02T12:00", CHICAGO, COZUMEL, c, CANCUN), ("2026-03-03T12:00", CANCUN, COZUMEL, c, CANCUN), ("2026-03-06T12:00", CHICAGO, COZUMEL, c, CANCUN),
                             ("2026-03-01T15:00", CHICAGO, GALVESTON, c, CHICAGO), ("2026-03-04T12:00", CHICAGO, GALVESTON, c, CHICAGO), ("2026-03-08T09:00", CHICAGO, GALVESTON, c, CHICAGO),
                             ("2026-03-01T15:00", CHICAGO, None, c, CHICAGO), ("2026-03-02T12:00", CHICAGO, None, c, CHICAGO), ("2026-03-03T12:00", CANCUN, None, c, CANCUN),
                             ("2026-03-04T12:00", CHICAGO, None, c, CHICAGO), ("2026-03-08T09:00", CHICAGO, None, c, CHICAGO)])
        with db.session() as conn:
            (main, *calls) = photos.segment_points(conn, [conn.orm.get(Segment, c)])[c]
        self.assertEqual((main.origin, main.zone, main.to_zone, main.borrowed), (calls[0].origin, CHICAGO, CHICAGO, True))
        self.assertEqual([(p.zone, p.borrowed) for p in calls], [(CANCUN, False), (PUERTO_RICO, False)])

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

    def test_decide_refuses_another_persons_photo_and_a_trip_they_are_not_on_or_have_not_shared(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T10:00", where=SOHO)
        self.assertEqual(self.call("ben", "POST", f"/api/photos/{mine}", {"excluded": True}), (404, {"error": "No such photo"}))
        self.assertEqual(self.call("ben", "POST", f"/api/photos/{mine}", {"trip_id": self.trip}), (404, {"error": "No such photo"}))
        self.assertEqual(self.call("ana", "POST", "/api/photos/99999", {"trip_id": self.trip}), (404, {"error": "No such photo"}))
        self.assertEqual(self.call("ana", "POST", "/api/photos/abc", {"trip_id": self.trip}), (404, {"error": "No such photo"}))
        cys = self.book("cy", {**OUT, "start_local": "2027-01-01T19:00", "end_local": "2027-01-02T07:10"})
        booked_for_ben = self.book("ana", {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, travelers=[{"person_id": self.person["ben"]}])
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{booked_for_ben['trip_id']}")["people"], [self.person["ben"]])
        for trip in (cys["trip_id"], booked_for_ben["trip_id"], 99999):
            self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": trip}), (400, {"error": "Choose a trip you are on"}), trip)
        unshared = self.own_trip("ana", "Unshared", shared=False)
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": unshared}), (400, {"error": "Share your photos on that trip first"}))
        self.share("ana", unshared, revoked=5.0)
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": unshared}), (400, {"error": "Share your photos on that trip first"}))
        for odd in ("abc", True, 1.5, 0, [1]):
            self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": odd})[0], 400, odd)
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": "abc"}), (400, {"error": "The trip must be a whole number"}))
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"excluded": "yes"}), (400, {"error": 'Send "excluded" as true or false'}))
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"excluded": True}), (400, {"error": "Only a photo waiting under Needs a look can be left off"}))
        for body in ({}, {"trip_id": None, "excluded": None}, {"trip_id": None, "excluded": False}, {"hidden": True}, {"trip_id": self.trip, "hidden": False}):
            self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", body), (400, {"error": 'Send "trip_id" to put the photo on a trip, or "excluded" to leave it off'}), body)
        self.assertEqual((stored(mine)["trip_id"], stored(mine)["decided_by"]), (self.trip, None))

    def test_the_owner_places_a_photo_and_the_row_remembers_it_was_their_choice(self):
        later = self.later()
        unsettled = self.photo(self.ana, None, "2027-01-02T09:00", where=SOHO, match="ambiguous")
        got = self.ok("ana", "POST", f"/api/photos/{unsettled}", {"trip_id": later["trip_id"]})
        self.assertEqual((got["trip_id"], got["match"], got["segment_id"], got["zone"], got["cluster"]), (later["trip_id"], "place", later["id"], LONDON, None))
        self.assertAlmostEqual(got["distance_km"], 23.0, delta=1.5)
        self.assertEqual([p["id"] for p in self.listing("ana", later["trip_id"])["photos"]], [unsettled])
        self.assertEqual(self.listing("ana")["photos"], [])
        row = stored(unsettled)
        self.assertEqual((row["trip_id"], row["decided_by"], row["match"], row["location_source"]), (later["trip_id"], "owner", "place", "exif"))
        self.assertEqual((row["latitude"], row["longitude"]), SOHO)

    def test_an_unsettled_photo_can_be_left_off_every_trip_it_could_join(self):
        week = self.own_trip("ana", "Week")
        self.book("ana", {**HOTEL, "start_local": "2026-06-03T15:00", "end_local": "2026-06-05T10:00"}, trip_id=week)
        torn = self.photo(self.ana, None, "2026-06-04T12:00", match="ambiguous", where=SOHO)
        self.assertEqual([c["id"] for c in self.ok("ana", "GET", "/api/photos/review")["photos"][0]["candidates"]], [self.trip, week])
        got = self.ok("ana", "POST", f"/api/photos/{torn}", {"excluded": True})
        self.assertEqual((got["trip_id"], got["match"]), (None, "ambiguous"))
        self.assertEqual(self.ok("ana", "GET", "/api/photos/review")["photos"], [])
        for trip in (self.trip, week):
            self.assertEqual([p["id"] for p in self.ok("ana", "GET", f"/api/trips/{trip}/photo-sharing")["removed"]], [torn], trip)
            self.assertEqual(self.listing("ana", trip)["photos"], [])
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{torn}", {"excluded": True}), (404, {"error": "No such photo"}))
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{torn}", {"trip_id": week}), (404, {"error": "No such photo"}))
        self.ok("ana", "DELETE", f"/api/trips/{week}/photo-exclusions/{torn}")
        self.assertEqual([p["id"] for p in self.listing("ana", week)["photos"]], [torn])
        self.assertEqual(stored(torn)["decided_by"], "auto")

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
        later = self.later()
        guessed = self.photo(self.ana, self.trip, "2027-01-02T12:00", where=SOHO, located="inferred", segment_id=self.stay["id"], match="time")
        got = self.ok("ana", "POST", f"/api/photos/{guessed}", {"trip_id": later["trip_id"]})
        self.assertEqual((got["match"], got["segment_id"], got["location_source"], got["distance_km"], got["zone"]), ("time", later["id"], "inferred", None, LONDON))
        self.assertAlmostEqual(got["latitude"], HEATHROW[0], delta=0.05)
        self.assertAlmostEqual(got["longitude"], HEATHROW[1], delta=0.05)
        self.assertEqual(self.listing("ana", later["trip_id"])["clusters"][0]["inferred"], True)
        empty = self.own_trip("ana")
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{guessed}", {"trip_id": empty}), (409, {"error": "That trip’s dates don’t cover this photo"}))
        self.assertEqual(stored(guessed)["trip_id"], later["trip_id"])
        blank = self.photo(self.ana, None, "2027-01-02T12:00", match="ambiguous")
        got = self.ok("ana", "POST", f"/api/photos/{blank}", {"trip_id": later["trip_id"]})
        self.assertEqual((got["match"], got["segment_id"], got["location_source"]), ("time", later["id"], "inferred"))

    def test_a_confirmation_carries_the_audience_and_the_libraries_it_saw_and_a_stale_one_answers_409(self):
        seen = self.ok("ana", "GET", f"/api/trips/{self.trip}/photo-sharing")
        self.assertIn(self.person["ana"], seen["audience"])
        self.assertEqual(seen["audience"], sorted(seen["audience"]))
        self.assertEqual([s["status"] for s in seen["sources"]], ["ok"])
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip", "audience": "everyone"})[0], 400)
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {"scope": "trip", "sources": [{"id": "x"}]})[0], 400)
        shown = {"scope": "trip", "window": seen["window"], "audience": seen["audience"], "sources": seen["sources"], "expected_changed": seen["changed"]}
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {**shown, "audience": [*seen["audience"], 9999]}),
                         (409, {"error": "The trip changed. Review who sees your photos under Your photos on this trip."}))
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", {**shown, "sources": [{"id": seen["sources"][0]["id"], "status": "off"}]}),
                         (409, {"error": "Your libraries changed. Review them before sharing."}))
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{self.trip}/photo-sharing")["changed"], seen["changed"])
        got = self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-sharing", shown)
        self.assertEqual((got["scope"], got["audience"], got["sources"]), ("trip", seen["audience"], seen["sources"]))
        later = self.later()
        self.assertEqual(self.ok("ana", "DELETE", f"/api/trips/{later['trip_id']}/photo-sharing")["state"], "declined")
        pending = self.ok("ana", "GET", f"/api/trips/{later['trip_id']}/photo-sharing")
        prefs = f"/api/photo-sharing-prefs/{self.person['ana']}"
        self.assertEqual(self.call("ana", "POST", prefs, {"share_all": True, "audiences": [1]})[0], 400)
        self.assertEqual(self.call("ana", "POST", prefs, {"share_all": True, "audiences": {str(later["trip_id"]): [*pending["audience"], 9999]}}),
                         (409, {"error": "Your trips changed. Review them before sharing on all."}))
        self.assertEqual(self.call("ana", "POST", prefs, {"share_all": True, "sources": []}), (409, {"error": "Your libraries changed. Review them before sharing."}))
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{later['trip_id']}/photo-sharing")["state"], "declined")
        self.assertEqual(self.ok("ana", "POST", prefs, {"share_all": True, "audiences": {str(later["trip_id"]): pending["audience"]}, "sources": seen["sources"]})["share_all"], True)
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{later['trip_id']}/photo-sharing")["state"], "shared")

    def test_a_trip_scope_confirmation_and_share_on_all_need_the_snapshots_the_confirmation_showed(self):
        route, seen = f"/api/trips/{self.trip}/photo-sharing", self.ok("ana", "GET", f"/api/trips/{self.trip}/photo-sharing")
        self.assertEqual(self.ok("ana", "POST", route, {"scope": "only_me"})["scope"], "only_me")
        needs = 'Send the "window", "audience" and "sources" the confirmation showed'
        self.assertEqual(self.call("ana", "POST", route, {"scope": "trip"}), (400, {"error": needs}))
        self.assertEqual(self.call("ana", "POST", route, {"scope": "trip", "window": seen["window"], "audience": seen["audience"]}), (400, {"error": needs}))
        full = {"scope": "trip", "window": seen["window"], "audience": seen["audience"], "sources": seen["sources"]}
        self.assertEqual(self.call("ana", "POST", route, full), (400, {"error": 'Send the "expected_changed" the confirmation showed'}))
        self.assertEqual(self.ok("ana", "GET", route)["scope"], "only_me")
        self.assertEqual(self.ok("ana", "POST", route, {**full, "expected_changed": self.ok("ana", "GET", route)["changed"]})["scope"], "trip")
        fresh = self.book("ana", {**OUT, "start_local": "2027-02-01T19:00", "end_local": "2027-02-02T07:10"}, travelers=[{"person_id": self.person["ana"]}])
        first = self.ok("ana", "GET", f"/api/trips/{fresh['trip_id']}/photo-sharing")
        self.assertIsNone(first["changed"])
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{fresh['trip_id']}/photo-sharing", {"scope": "trip"}), (400, {"error": needs}))
        self.assertEqual(self.confirm("ana", fresh["trip_id"])["scope"], "trip")
        self.assertEqual(self.ok("ana", "DELETE", f"/api/trips/{fresh['trip_id']}/photo-sharing")["state"], "declined")
        prefs, setting = f"/api/photo-sharing-prefs/{self.person['ana']}", 'Send the "windows", "audiences" and "sources" the confirmation showed'
        self.assertEqual(self.ok("ana", "POST", prefs, {"default_scope": "trip"})["share_all"], False)
        self.assertEqual(self.call("ana", "POST", prefs, {"share_all": True}), (400, {"error": setting}))
        self.assertEqual(self.call("ana", "POST", prefs, {"share_all": True, "windows": {}, "audiences": {}}), (400, {"error": setting}))
        pending = self.ok("ana", "GET", f"/api/trips/{fresh['trip_id']}/photo-sharing")
        snapshots = {"windows": {str(fresh["trip_id"]): pending["window"]}, "audiences": {str(fresh["trip_id"]): pending["audience"]}, "sources": pending["sources"]}
        self.assertEqual(self.ok("ana", "POST", prefs, {"share_all": True, **snapshots}), {"default_scope": "trip", "share_all": True})
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{fresh['trip_id']}/photo-sharing")["state"], "shared")
        self.assertEqual(self.ok("ana", "POST", prefs, {"share_all": False})["share_all"], False)
        self.assertEqual(self.ok("ana", "POST", prefs, {"share_all": True, "default_scope": "only_me"}), {"default_scope": "only_me", "share_all": True})

    def test_a_removed_photo_carries_the_removals_stamp_for_undo(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T12:00", where=SOHO)
        got = self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [mine]})
        stamp = got["removed"][0]["removed_at"]
        self.assertIsInstance(stamp, float)
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{self.trip}/photo-sharing")["removed"][0]["removed_at"], stamp)
        self.assertIsNone(self.ok("ana", "GET", f"/api/trips/{self.trip}/photos")["photos"][0]["removed_at"]) if self.ok("ana", "GET", f"/api/trips/{self.trip}/photos")["photos"] else None
        self.assertEqual(self.call("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{mine}?created={stamp + 1}")[0], 409)
        self.assertEqual(self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{mine}?created={stamp}")["removed_count"], 0)

    def test_a_put_back_stamp_that_is_not_a_finite_number_is_a_400(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T12:00", where=SOHO)
        self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [mine]})
        for bad in ("nan", "inf", "-inf", "abc", "1e999", "1e400"):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{mine}?created={bad}"),
                                 (400, {"error": 'Send "created" as a number'}))

    def test_a_blank_put_back_stamp_is_a_400_not_no_stamp(self):
        mine = self.photo(self.ana, self.trip, "2026-06-02T12:00", where=SOHO)
        self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [mine]})
        self.assertEqual(self.call("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{mine}?created="),
                         (400, {"error": 'Send "created" as a number'}))
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{self.trip}/photo-sharing")["removed"][0]["removed_at"] is not None, True)

    def test_a_blank_query_value_on_another_route_is_still_dropped(self):
        self.assertEqual(self.ok("ana", "GET", "/api/stats?person=&year=")["person"], None)

    def test_moving_to_a_trip_whose_bookings_are_all_cancelled_is_refused_because_its_sharing_ended(self):
        later = self.later()
        self.ok("ana", "POST", f"/api/segments/{later['id']}", {"status": "cancelled"})
        self.assertEqual(self.ok("ana", "GET", f"/api/trips/{later['trip_id']}/photo-sharing")["state"], "none")
        mine = self.photo(self.ana, self.trip, "2027-01-02T09:00", where=SOHO, segment_id=self.stay["id"], distance=1.0)
        self.assertEqual(self.call("ana", "POST", f"/api/photos/{mine}", {"trip_id": later["trip_id"]}), (400, {"error": "Share your photos on that trip first"}))
        self.assertEqual((stored(mine)["trip_id"], stored(mine)["decided_by"]), (self.trip, None))
        self.assertEqual(self.call("ana", "POST", f"/api/trips/{later['trip_id']}/photo-sharing", {"scope": "trip"})[0], 400)

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
            replies = [self.listing("ana"), self.ok("ana", "GET", "/api/photos/review"), self.ok("ana", "POST", f"/api/photos/{mine}", {"trip_id": self.trip}),
                       self.ok("ana", "POST", f"/api/photos/{torn}", {"trip_id": self.trip}), self.call("ben", "POST", f"/api/photos/{mine}", {"trip_id": self.trip})[1],
                       self.call("cy", "GET", f"/api/trips/{self.trip}/photos")[1], self.ok("ana", "GET", f"/api/trips/{self.trip}/photo-sharing"),
                       self.ok("ana", "POST", f"/api/trips/{self.trip}/photo-exclusions", {"photo_ids": [mine]}), self.ok("ana", "GET", "/api/photo-grants"),
                       self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-exclusions/{mine}"), self.ok("ana", "DELETE", f"/api/trips/{self.trip}/photo-sharing"),
                       self.ok("ana", "POST", f"/api/photo-sharing-prefs/{self.person['ana']}", {"share_all": True})]
        text = json.dumps(replies)
        for canary in (ASSET, URL, KEY, "immich-user-1", "asset", "api_key", "source_id"):
            self.assertNotIn(canary, text, canary)

    def test_assistants_never_reach_the_photo_routes(self):
        for pattern in ROUTES:
            self.assertTrue(mcp_access.blocked(pattern), pattern)
            for method in ("GET", "POST", "DELETE"):
                self.assertIsNone(mcp_http.needs(method, pattern), f"{method} {pattern}")


class PhotoViewers(Household):
    def setUp(self):
        super().setUp()
        self.jid, self.sid = self.jane.person_id, self.sam.person_id
        self.flight = self.add(self.jane, OUT, None, self.on(self.jid))
        self.trip = self.flight["trip_id"]
        self.sams = self.add(self.sam, {**OUT, "start_local": "2026-09-01T19:00", "end_local": "2026-09-02T07:10"}, None, self.on(self.sid))
        self.household = Viewer(None, household=True)
        self.c.orm.add_all([source_row(self.jid, "u-jane"), source_row(self.sid, "u-sam"), grant_row(self.jid, self.trip, by="u-jane"),
                            grant_row(self.sid, self.sams["trip_id"], by="u-sam")])
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
        self.assertIsNone(photos.decide(self.c, nobody, mine, self.trip, None))
        self.assertEqual(stored_decided(self.c, mine), None)

    def test_without_sign_in_photos_are_off(self):
        mine = self.photo(self.janes, self.trip, "2026-06-02T10:00", where=SOHO)
        torn = self.photo(self.sams_source, None, "2026-09-02T12:00", match="ambiguous")
        self.assertIsNone(photos.for_trip(self.c, self.household, self.trip))
        self.assertEqual(photos.needs_a_look(self.c, self.household), {"photos": []})
        self.assertIsNone(photos.decide(self.c, self.household, torn, self.sams["trip_id"], None))
        self.assertIsNone(photos.decide(self.c, self.household, mine, self.trip, None))
        self.assertEqual((stored_decided(self.c, mine), stored_decided(self.c, torn)), (None, None))

    def test_a_person_decides_only_their_own_librarys_photos(self):
        hers = self.photo(self.janes, self.trip, "2026-06-02T10:00", where=SOHO)
        self.assertIsNone(photos.decide(self.c, self.sam, hers, self.trip, None))
        self.assertEqual(photos.needs_a_look(self.c, self.sam), {"photos": []})
        self.assertIsNone(photos.for_trip(self.c, self.sam, self.trip))
        got = photos.decide(self.c, self.jane, hers, self.trip, None)
        self.assertEqual((got["id"], got["trip_id"], stored_decided(self.c, hers)), (hers, self.trip, "owner"))

    def test_the_offset_label_reads_as_utc_plus_or_minus(self):
        self.assertEqual([photos.offset_label(m) for m in (0, 60, -60, 330, -570, 765, -720)],
                         ["UTC", "UTC+01:00", "UTC−01:00", "UTC+05:30", "UTC−09:30", "UTC+12:45", "UTC−12:00"])

    def test_an_instant_is_read_in_utc_whatever_its_spelling(self):
        for text in ("2026-06-02T09:00:00+00:00", "2026-06-02T09:00:00Z", "2026-06-02T09:00:00", "2026-06-02T10:00:00+01:00"):
            self.assertEqual(photos.instant(text).isoformat(), "2026-06-02T09:00:00+00:00", text)


def stored_decided(conn, photo_id):
    row = conn.orm.get(Photo, photo_id)
    assert row is not None
    return row.decided_by


if __name__ == "__main__":
    unittest.main()
