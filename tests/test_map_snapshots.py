import json
import unittest
import urllib.parse
from unittest import mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from tests.privacy import no_leaks
from tests.test_mapkit import KEY_ID, PEM, PRIVATE, TEAM_ID, Keys, key_line, unb64
from tests.test_trips import BOULDER, DENVER, HOTEL, SALT_LAKE, RouteCase

PHOENIX = {**DENVER, "origin": "Desert Inn", "destination": "Phoenix", "start_local": "2026-06-08T15:00", "end_local": "2026-06-10T10:00"}
from sqlalchemy import select

from waypoint.domain import map_snapshots, maps
from waypoint.storage import db
from waypoint.storage.models import Segment
from waypoint.providers import mapkit
from waypoint.server import mcp_access, mcp_http

CREDS = mapkit.Credentials(PEM, KEY_ID, TEAM_ID)
NOON = 1_700_000_000.0
START = (int(NOON) // 86400) * 86400
ALLOWED = ["center", "z", "size", "scale", "colorScheme", "poi", "lang", "expires", "teamId", "keyId", "signature"]


def query_of(url: str) -> list[tuple[str, str]]:
    return urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True)


def verifies(url: str, public) -> bool:
    signed, signature = url.removeprefix(mapkit.SNAPSHOT_URL).rsplit("&signature=", 1)
    raw = unb64(signature)
    try:
        public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), signed.encode(), ec.ECDSA(hashes.SHA256()))
    except Exception:
        return False
    return True


class SnapshotUrlTests(unittest.TestCase):
    def url(self, **changes):
        args = {"creds": CREDS, "center": (39.74, -104.99), "zoom": 9, "size": (358, 168), "scale": 2, "scheme": "dark", "lang": "en-US", "now": NOON, **changes}
        return mapkit.snapshot_url(**args)

    def test_it_is_the_snapshot_address_with_the_signature_last_and_valid(self):
        url = self.url()
        self.assertTrue(url.startswith("https://snapshot.apple-mapkit.com/api/v1/snapshot?"))
        self.assertEqual([k for k, _ in query_of(url)], ALLOWED)
        self.assertEqual(dict(query_of(url)) | {"signature": "", "expires": ""}, {"center": "39.74,-104.99", "z": "9", "size": "358x168", "scale": "2", "colorScheme": "dark", "poi": "0",
                                                                                        "lang": "en-US", "expires": "", "teamId": TEAM_ID, "keyId": KEY_ID, "signature": ""})
        self.assertTrue(verifies(url, PRIVATE.public_key()))
        self.assertFalse(verifies(url, ec.generate_private_key(ec.SECP256R1()).public_key()))

    def test_expires_is_inside_the_signed_string_and_two_days_on(self):
        url = self.url()
        self.assertEqual(dict(query_of(url))["expires"], str(int(NOON) + 2 * 86400))
        self.assertTrue(verifies(url.replace("expires=", "expires=9"), PRIVATE.public_key()) is False)

    def test_the_centre_is_never_sent_closer_than_a_hundredth_of_a_degree(self):
        self.assertEqual(dict(query_of(self.url(center=(39.7392123, -104.9903456))))["center"], "39.74,-104.99")

    def test_what_apple_wouldnt_draw_is_refused(self):
        for changes in ({"size": (49, 168)}, {"size": (358, 641)}, {"zoom": 2}, {"zoom": 21}, {"scale": 4}, {"scheme": "sepia"}, {"center": (91.0, 0.0)}, {"center": (0.0, 181.0)}):
            with self.subTest(changes):
                with self.assertRaises(ValueError):
                    self.url(**changes)

    def test_a_key_that_isnt_elliptic_is_refused(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        pem = rsa.generate_private_key(65537, 2048).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with self.assertRaises(ValueError):
            self.url(creds=mapkit.Credentials(pem, KEY_ID, TEAM_ID))


class FitTests(unittest.TestCase):
    def test_two_cities_a_day_apart_fit_a_card_at_a_regional_zoom(self):
        found = map_snapshots.fit([(39.74, -104.99), (40.76, -111.89)], 358, 168)
        self.assertIsNotNone(found)
        self.assertTrue(5 <= found.zoom <= 7, found)
        self.assertAlmostEqual(found.longitude, -108.44, delta=0.1)

    def test_places_within_30_km_of_each_other_get_a_map_at_a_close_zoom(self):
        found = map_snapshots.fit([(39.74, -104.99), (39.80, -104.90)], 358, 168)
        self.assertIsNotNone(found)
        self.assertTrue(10 <= found.zoom <= map_snapshots.MAX_ZOOM)
        self.assertEqual((found.width, found.height), (358, 168))

    def test_places_spread_wide_but_all_near_the_first_are_judged_by_the_widest_pair(self):
        self.assertIsNotNone(map_snapshots.fit([(39.74, -104.99), (39.80, -104.90), (39.76, -104.95), (39.9, -105.1)], 358, 168))

    def test_two_places_either_side_of_the_date_line_are_one_regional_map(self):
        found = map_snapshots.fit([(-17.755, 177.443), (-16.69, -179.877)], 358, 168)
        self.assertIsNotNone(found)
        self.assertGreaterEqual(found.zoom, 5)
        self.assertEqual((found.width, found.height), (358, 168))
        self.assertTrue(found.longitude > 178 or found.longitude < -179.5, found)
        self.assertTrue(-180 <= found.longitude <= 180)

    def test_unwrapping_picks_the_shortest_interval(self):
        self.assertEqual(sorted(map_snapshots._unwrapped([177.4, -179.9])), [177.4, 180.1])
        self.assertEqual(map_snapshots._unwrapped([-73.78, -0.45]), [-73.78, -0.45])

    def test_the_zoom_never_passes_city_level(self):
        found = map_snapshots.fit([(39.74, -104.99), (40.10, -104.9)], 358, 168)
        self.assertTrue(7 <= found.zoom <= map_snapshots.MAX_ZOOM)

    def test_every_stop_lands_inside_the_card_with_room_round_it(self):
        points = [(39.74, -104.99), (40.76, -111.89), (36.17, -115.14)]
        found = map_snapshots.fit(points, 358, 168)
        cx, cy = map_snapshots._world(found.latitude, found.longitude)
        for lat, lon in points:
            x, y = map_snapshots._world(lat, lon)
            self.assertLessEqual(abs(x - cx) * 2 ** found.zoom, 358 / 2 - 20)
            self.assertLessEqual(abs(y - cy) * 2 ** found.zoom, 168 / 2 - 20)

    def test_no_place_or_one_place_is_no_map(self):
        self.assertIsNone(map_snapshots.fit([], 358, 168))
        self.assertIsNone(map_snapshots.fit([(39.74, -104.99)], 358, 168))

    def test_a_tiny_route_is_a_city_level_map(self):
        found = map_snapshots.fit([(39.74, -104.99), (39.7401, -104.9901)], 358, 168)
        self.assertEqual((found.zoom, found.width, found.height), (12, 358, 168))

    def test_a_short_card_does_not_divide_by_zero(self):
        for size in ((358, 56), (56, 56), (56, 168)):
            found = map_snapshots.fit([(39.74, -104.99), (40.76, -111.89)], *size)
            self.assertIsNotNone(found, size)
            self.assertTrue(map_snapshots.MIN_SIDE <= found.width <= map_snapshots.MAX_SIDE, (size, found))
            self.assertTrue(map_snapshots.MIN_SIDE <= found.height <= map_snapshots.MAX_SIDE, (size, found))

    def test_a_trip_wider_than_zoom_3_shows_gets_a_larger_image_at_zoom_3_to_show_scaled_down(self):
        found = map_snapshots.fit([(40.64, -73.78), (51.47, -0.45)], 358, 168)
        self.assertEqual(found.zoom, 3)
        self.assertGreater(found.width, 358)
        self.assertLessEqual(max(found.width, found.height), 640)
        self.assertAlmostEqual(found.width / found.height, 358 / 168, delta=0.02)
        shown = 358 / found.width
        cx, cy = map_snapshots._world(found.latitude, found.longitude)
        for lat, lon in [(40.64, -73.78), (51.47, -0.45)]:
            x, y = map_snapshots._world(lat, lon)
            self.assertLessEqual(abs(x - cx) * 8 * shown, 358 / 2 - 28 + 1)
            self.assertLessEqual(abs(y - cy) * 8 * shown, 168 / 2 - 28 + 1)

    def test_a_trip_that_fits_at_a_normal_zoom_keeps_the_card_size(self):
        found = map_snapshots.fit([(39.74, -104.99), (40.76, -111.89)], 358, 168)
        self.assertEqual((found.width, found.height), (358, 168))

    def test_a_very_wide_trip_gets_a_640_pixel_zoom_3_image_centred_on_the_route_and_clipped(self):
        found = map_snapshots.fit([(37.62, -122.38), (51.47, -0.45)], 352, 168)
        self.assertEqual((found.zoom, found.width), (3, 640))
        self.assertAlmostEqual(found.width / found.height, 352 / 168, delta=0.02)
        self.assertAlmostEqual(found.longitude, -61.4, delta=1)
        wide = map_snapshots.fit([(51.47, -0.45), (-33.94, 151.18)], 352, 168)
        self.assertEqual((wide.zoom, wide.width), (3, 640))

    def test_a_route_over_the_pacific_is_centred_across_the_date_line(self):
        found = map_snapshots.fit([(33.94, -118.4), (-33.94, 151.18)], 352, 168)
        self.assertEqual(found.zoom, 3)
        self.assertAlmostEqual(found.longitude, -163.6, delta=1)
        tokyo = map_snapshots.fit([(37.62, -122.38), (35.55, 139.78)], 352, 168)
        self.assertTrue(tokyo.longitude > 170 or tokyo.longitude < -170, tokyo)


class SnapshotCase(RouteCase, Keys):
    def setUp(self):
        RouteCase.setUp(self)
        Keys.setUp(self)
        self.configure()
        map_snapshots._address.cache_clear()

    def road_trip(self, who="ana", second=SALT_LAKE):
        first = self.book(who, DENVER)
        self.book(who, second, trip_id=first["trip_id"])
        return first["trip_id"]

    def snapshots(self, who, *trips, w=358, h=168, extra=""):
        query = "&".join([*(f"trip={t}" for t in trips), f"w={w}", f"h={h}"]) + extra
        return self.call(who, "GET", f"/api/map-snapshots?{query}")


class RouteTests(SnapshotCase):
    def test_a_trip_you_are_on_gets_an_address_for_its_area(self):
        trip = self.road_trip()
        status, body = self.snapshots("ana", trip)
        self.assertEqual(status, 200, body)
        [snap] = body["snapshots"]
        self.assertEqual((snap["trip_id"], snap["width"], snap["height"]), (trip, 358, 168))
        self.assertTrue(5 <= snap["zoom"] <= 7)
        asked = dict(query_of(snap["url"]))
        self.assertEqual(asked["center"], f"{snap['center']['latitude']:.2f},{snap['center']['longitude']:.2f}")
        self.assertEqual((asked["z"], asked["size"], asked["scale"], asked["colorScheme"], asked["poi"], asked["lang"]), (str(snap["zoom"]), "358x168", "2", "dark", "0", "en-US"))
        self.assertTrue(verifies(snap["url"], PRIVATE.public_key()))

    def test_the_signed_query_holds_only_the_allowed_parameters_and_no_stop(self):
        trip = self.road_trip()
        places = self.ok("ana", "GET", f"/api/trips/{trip}/places")
        _, body = self.snapshots("ana", trip)
        url = body["snapshots"][0]["url"]
        self.assertEqual([k for k, _ in query_of(url)], ALLOWED)
        for stop in places["stays"]:
            for number in (stop["latitude"], stop["longitude"]):
                self.assertNotIn(f"{number:.3f}", urllib.parse.unquote(url))
        self.assertNotIn("trip", urllib.parse.urlsplit(url).query)
        for name in ("Denver", "Salt", "Inn"):
            self.assertNotIn(name, url)
        self.assertEqual(sorted(body["snapshots"][0]), ["center", "height", "trip_id", "url", "width", "zoom"])

    def test_a_trip_you_are_not_on_is_left_out_like_one_with_no_route(self):
        mine = self.road_trip("ana")
        theirs = self.road_trip("cy", BOULDER)
        status, body = self.snapshots("ana", mine, theirs, 987654)
        self.assertEqual(status, 200)
        self.assertEqual([s["trip_id"] for s in body["snapshots"]], [mine])
        self.assertEqual(self.snapshots("ana", theirs), (200, {"snapshots": []}))
        self.assertEqual(self.snapshots("ben", mine), (200, {"snapshots": []}))

    def test_a_trip_with_fewer_than_two_places_is_left_out(self):
        lonely = self.book("ana", DENVER)["trip_id"]
        self.assertEqual(self.snapshots("ana", lonely), (200, {"snapshots": []}))

    def test_a_transatlantic_trip_gets_a_larger_image_at_zoom_3_and_a_wider_one_a_clipped_640_pixel_image(self):
        flown = self.book("ana", {**HOTEL, "kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-06-01T19:00", "end_local": "2026-06-02T07:10"})["trip_id"]
        [snap] = self.snapshots("ana", flown)[1]["snapshots"]
        self.assertEqual((snap["zoom"], snap["width"] > 358, max(snap["width"], snap["height"]) <= 640), (3, True, True))
        self.assertEqual(dict(query_of(snap["url"]))["size"], f"{snap['width']}x{snap['height']}")
        far = self.book("ana", {**HOTEL, "kind": "flight", "origin": "LHR", "destination": "SYD", "start_local": "2026-07-01T19:00", "end_local": "2026-07-02T07:10"})["trip_id"]
        [wide] = self.snapshots("ana", far)[1]["snapshots"]
        self.assertEqual((wide["zoom"], wide["width"]), (3, 640))

    def test_two_stays_in_one_metro_still_get_a_map(self):
        near = {**DENVER, "origin": "Boulder Inn", "destination": "Boulder", "start_local": "2026-06-04T15:00", "end_local": "2026-06-06T10:00"}
        trip = self.road_trip("ana", near)
        [snap] = self.snapshots("ana", trip)[1]["snapshots"]
        self.assertGreaterEqual(snap["zoom"], 8)
        self.assertEqual((snap["width"], snap["height"]), (358, 168))

    def test_a_past_country_visit_in_a_mixed_trip_does_not_widen_the_map(self):
        trip = self.road_trip("ana", BOULDER)
        before = self.snapshots("ana", trip)[1]["snapshots"][0]
        self.book("ana", {"kind": "visit", "destination": "JP", "start_local": "2026-06-09T00:00", "end_local": "2026-06-10T00:00"}, trip_id=trip)
        places = self.ok("ana", "GET", f"/api/trips/{trip}/places")
        self.assertTrue(any(s["longitude"] > 100 for s in places["stays"]))
        after = self.snapshots("ana", trip)[1]["snapshots"][0]
        self.assertEqual((after["center"], after["zoom"]), (before["center"], before["zoom"]))

    def test_a_train_with_a_stored_arrival_has_two_stops_and_a_map(self):
        trip = self.book("ana", {"kind": "train", "origin": "Denver", "destination": "Nowhere Station", "start_local": "2026-06-02T08:00", "end_local": "2026-06-02T12:00",
                                 "start_zone": "America/Denver", "end_zone": "America/Denver"})["trip_id"]
        with db.session() as conn:
            for seg in conn.orm.scalars(select(Segment).where(Segment.trip_id == trip)):
                seg.latitude, seg.longitude, seg.geo_precision = 40.76, -111.89, "address"
        [snap] = self.snapshots("ana", trip)[1]["snapshots"]
        self.assertLess(snap["center"]["longitude"], -105.5)

    def test_a_cruise_gets_a_map_from_its_ports(self):
        cruise = self.book("ana", {"kind": "cruise", "origin": "Miami", "destination": "Miami", "start_local": "2026-06-01T16:00", "end_local": "2026-06-08T07:00", "start_zone": "America/New_York", "end_zone": "America/New_York",
                                   "itinerary": [{"name": "Nassau", "arrive_local": "2026-06-03T08:00", "depart_local": "2026-06-03T17:00", "zone": "America/New_York"}]})["trip_id"]
        self.assertEqual(len(self.snapshots("ana", cruise)[1]["snapshots"]), 1)

    def test_at_most_twelve_trips_and_sizes_inside_what_apple_draws(self):
        trip = self.road_trip()
        self.assertEqual(self.snapshots("ana", *range(1, 13))[0], 200)
        for bad in (self.snapshots("ana", *range(1, 14)), self.snapshots("ana"), self.snapshots("ana", "x"), self.snapshots("ana", trip, w=49), self.snapshots("ana", trip, w=641),
                    self.snapshots("ana", trip, h="tall"), self.snapshots("ana", trip, h=-168), self.call("ana", "GET", f"/api/map-snapshots?trip={trip}&h=168")):
            self.assertEqual(bad[0], 400, bad)

    def test_a_card_is_asked_in_the_viewers_language(self):
        trip = self.road_trip()
        for lang, shown in (("es-MX", "es-MX"), ("fr", "fr"), ("en-GB", "en-GB"), ("not a language", "en-US"), ("x&signature=1", "en-US")):
            with self.subTest(lang):
                _, body = self.snapshots("ana", trip, extra=f"&lang={urllib.parse.quote(lang)}")
                self.assertEqual(dict(query_of(body["snapshots"][0]["url"]))["lang"], shown)

    def test_with_no_key_or_the_flag_off_it_signs_nothing(self):
        trip = self.road_trip()
        for changes in ({maps.FLAG_ENV: "off"}, {maps.KEY_FILE_ENV: None}, {maps.PUBLIC_URL_ENV: None}):
            with self.subTest(changes):
                self.configure(**changes)
                with mock.patch.object(mapkit, "snapshot_url", side_effect=AssertionError("signed without MapKit")):
                    self.assertEqual(self.snapshots("ana", trip), (200, {"snapshots": []}))

    def test_an_assistant_cant_reach_it(self):
        self.assertTrue(mcp_access.blocked("/api/map-snapshots"))
        self.assertIsNone(mcp_http.needs("GET", "/api/map-snapshots"))

    def test_signed_out_it_is_refused(self):
        status, _ = self.req("GET", "/api/map-snapshots?trip=1&w=358&h=168")
        self.assertIn(status, (401, 403))

    def test_nothing_is_cached_by_the_browser_for_the_signing_route(self):
        trip = self.road_trip()
        from tests.shared import fetch
        _, headers, _ = fetch(self.base, "GET", f"/api/map-snapshots?trip={trip}&w=358&h=168", None, {"X-Waypoint": "1", **self.who["ana"]})
        self.assertEqual(headers["Cache-Control"], "no-store")


class KeptAddressTests(SnapshotCase):
    def test_the_same_card_gets_the_same_address_all_day_so_apple_counts_one_snapshot(self):
        trip = self.road_trip()
        morning = self.at(START + 3600)
        with morning:
            first = self.snapshots("ana", trip)[1]["snapshots"][0]["url"]
        evening = self.at(START + 3600 * 10)
        with evening, mock.patch.object(mapkit, "snapshot_url", side_effect=AssertionError("signed again within the day")):
            self.assertEqual(self.snapshots("ana", trip)[1]["snapshots"][0]["url"], first)

    def test_an_address_outlives_the_day_it_is_kept_for(self):
        trip = self.road_trip()
        with self.at(START + 86399):
            url = self.snapshots("ana", trip)[1]["snapshots"][0]["url"]
        self.assertGreaterEqual(int(dict(query_of(url))["expires"]) - (START + 86399), 86400)

    def test_the_next_day_signs_again(self):
        trip = self.road_trip()
        with self.at(START):
            first = self.snapshots("ana", trip)[1]["snapshots"][0]["url"]
        with self.at(START + 86400):
            second = self.snapshots("ana", trip)[1]["snapshots"][0]["url"]
        self.assertNotEqual(first, second)
        self.assertGreater(int(dict(query_of(second))["expires"]), int(dict(query_of(first))["expires"]))

    def test_a_trip_that_moved_gets_the_new_area_not_the_kept_one(self):
        trip = self.road_trip()
        before = self.snapshots("ana", trip)[1]["snapshots"][0]
        self.book("ana", PHOENIX, trip_id=trip)
        after = self.snapshots("ana", trip)[1]["snapshots"][0]
        self.assertNotEqual((before["center"], before["zoom"]), (after["center"], after["zoom"]))
        self.assertEqual(dict(query_of(after["url"]))["center"], f"{after['center']['latitude']:.2f},{after['center']['longitude']:.2f}")

    def at(self, now):
        return mock.patch("waypoint.server.api.map_snapshots.time", mock.Mock(time=lambda: now))


class PrivacyTests(SnapshotCase):
    def test_the_key_and_its_ids_are_never_logged_or_sent_on(self):
        trip = self.road_trip()
        with no_leaks(self, key_line(), KEY_ID, TEAM_ID, self.path):
            status, body = self.snapshots("ana", trip)
            self.snapshots("cy", trip)
            self.snapshots("ana", 999)
            self.snapshots("ana", trip, w=1)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["snapshots"]), 1)

    def test_the_server_never_fetches_the_image(self):
        trip = self.road_trip()
        with mock.patch("waypoint.tls.urlopen", side_effect=AssertionError("the server reached out")), mock.patch("waypoint.tls.post_http2", side_effect=AssertionError("the server reached out")):
            self.assertEqual(self.snapshots("ana", trip)[0], 200)

    def test_the_reply_names_the_key_id_and_team_id_apple_needs_but_never_the_key(self):
        trip = self.road_trip()
        text = json.dumps(self.snapshots("ana", trip)[1])
        self.assertIn(KEY_ID, text)
        for secret in (key_line(), "PRIVATE KEY", self.path):
            self.assertNotIn(secret, text)

    def test_the_route_is_registered_once_and_only_for_get(self):
        from waypoint import server
        self.assertEqual([(m, p) for m, p, *_ in server.ROUTES if "map-snapshots" in p], [("GET", "/api/map-snapshots")])


if __name__ == "__main__":
    unittest.main()
