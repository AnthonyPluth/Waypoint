import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date
from unittest import mock

from cryptography.hazmat.primitives import serialization

from tests.privacy import no_leaks
from tests.test_mapkit import KEY_ID, PEM, PRIVATE, TEAM_ID, parts, verifies
from tests.test_route_cache import RouteCacheCase
from tests.test_trip_roads import BOULDER, DENVER, SALT_LAKE
from waypoint import monitoring, tls
from waypoint.domain import driving_routes, maps, route_warming, tripmap
from waypoint.domain import trips as trip_domain
from waypoint.providers import mapkit
from waypoint.server import jobs
from waypoint.storage import db
from waypoint.storage.models import DrivingRoute

LATER = date(2027, 1, 1)
CREDS = mapkit.Credentials(PEM, KEY_ID, TEAM_ID)


def straight(start, end):
    return [[start[0], start[1]], [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.5], [end[0], end[1]]]


class Fetcher:
    def __init__(self, answer=straight):
        self.answer = answer
        self.calls = []

    def __call__(self, start, end):
        self.calls.append((start, end))
        return self.answer(start, end) if callable(self.answer) else self.answer


class Pauses:
    def __init__(self, stop_after=None):
        self.waits = []
        self.stop_after = stop_after

    def __call__(self, seconds):
        self.waits.append(seconds)
        return self.stop_after is not None and len(self.waits) >= self.stop_after


def refuse(code):
    def raiser(start, end):
        raise mapkit.Refused(f"{code}")
    return raiser


def run(fetch, pause=None, skip=None, **kw):
    return route_warming.run(LATER, fetch, pause or Pauses(), route_warming.Memory() if skip is None else skip, time.time, **kw)


class WarmingCase(RouteCacheCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(DrivingRoute.__table__.delete())

    def road_trip(self, *stays):
        first = self.book("ana", stays[0])
        for s in stays[1:]:
            self.book("ana", s, trip_id=first["trip_id"])
        return first["trip_id"]

    def two_drives(self):
        return self.road_trip(DENVER, SALT_LAKE, {**BOULDER, "start_local": "2026-06-09T15:00", "end_local": "2026-06-10T10:00"})


class FillingTests(WarmingCase):
    def test_a_missing_drive_is_fetched_and_stored_for_its_trip_and_a_cached_one_is_not_asked_again(self):
        trip = self.road_trip(DENVER, SALT_LAKE)
        fetch = Fetcher()
        got = run(fetch)
        self.assertEqual((got.fetched, got.left, got.stop), (1, False, False))
        self.assertEqual(len(fetch.calls), 1)
        self.assertEqual([r.trip_id for r in self.rows()], [trip])
        places = self.ok("ana", "GET", f"/api/trips/{trip}/places")
        status, reply = self.look_up("ana", trip, drive_of_places(places))
        self.assertEqual((status, len(reply["routes"])), (200, 1))
        again = Fetcher()
        self.assertEqual(run(again).fetched, 0)
        self.assertEqual(again.calls, [])

    def test_only_the_drives_without_a_stored_route_are_asked_for(self):
        trip = self.two_drives()
        places = self.ok("ana", "GET", f"/api/trips/{trip}/places")
        drive = drive_of_places(places)
        self.assertEqual(self.put("ana", trip, drive)[0], 200)
        fetch = Fetcher()
        self.assertEqual(run(fetch).fetched, 1)
        self.assertEqual(len(fetch.calls), 1)
        self.assertEqual(len(self.rows()), 2)

    def test_a_trip_that_has_not_ended_is_left_alone(self):
        self.road_trip(DENVER, SALT_LAKE)
        fetch = Fetcher()
        self.assertEqual(route_warming.run(date(2026, 6, 5), fetch, Pauses(), route_warming.Memory(), lambda: 1.0).fetched, 0)
        self.assertEqual(fetch.calls, [])

    def test_a_flight_is_never_a_drive_so_the_stays_either_side_are_not_joined_to_each_other(self):
        flight = {"kind": "flight", "origin": "DEN", "destination": "SLC", "start_local": "2026-06-04T09:00", "end_local": "2026-06-04T10:30"}
        trip = self.road_trip(DENVER, flight, SALT_LAKE)
        with db.session() as conn:
            out = trip_domain.get(conn, route_warming.HOUSEHOLD, trip)
            places = tripmap.places(conn, route_warming.HOUSEHOLD, trip)
            stays = [(s["latitude"], s["longitude"]) for s in places["stays"]]
            drives = route_warming.drives_of(out, places)
        self.assertEqual(len(drives), 2)
        self.assertFalse(any((d[0], d[1]) in stays and (d[2], d[3]) in stays for d in drives))

    def test_the_same_drive_on_two_trips_asks_apple_once_and_fills_both(self):
        self.road_trip(DENVER, SALT_LAKE)
        again = self.book("ana", {**DENVER, "start_local": "2027-06-02T15:00", "end_local": "2027-06-04T10:00"})
        self.book("ana", {**SALT_LAKE, "start_local": "2027-06-04T15:00", "end_local": "2027-06-08T10:00"}, trip_id=again["trip_id"])
        fetch = Fetcher()
        got = route_warming.run(date(2028, 1, 1), fetch, Pauses(), route_warming.Memory(), lambda: 1.0)
        self.assertEqual((got.fetched, len(fetch.calls)), (2, 1))
        self.assertEqual(len(self.rows()), 2)

    def test_a_trip_with_nothing_missing_is_not_worked_out_again_until_it_changes(self):
        trip = self.road_trip(DENVER, SALT_LAKE)
        memory = route_warming.Memory()
        self.assertEqual(run(Fetcher(), skip=memory).fetched, 1)
        self.assertEqual(run(Fetcher(), skip=memory).fetched, 0)
        with mock.patch.object(tripmap, "places", side_effect=AssertionError("worked out again")):
            self.assertEqual(run(Fetcher(), skip=memory).fetched, 0)
        self.book("ana", {**BOULDER, "start_local": "2026-06-09T15:00", "end_local": "2026-06-10T10:00"}, trip_id=trip)
        fetch = Fetcher()
        self.assertEqual(run(fetch, skip=memory).fetched, 1)

    def test_a_long_route_is_thinned_to_what_the_store_accepts(self):
        self.road_trip(DENVER, SALT_LAKE)

        def long(start, end):
            n = 12_000
            return [[start[0] + (end[0] - start[0]) * i / (n - 1), start[1] + (end[1] - start[1]) * i / (n - 1)] for i in range(n)]
        self.assertEqual(run(Fetcher(long)).fetched, 1)
        self.assertEqual(len(json.loads(self.rows()[0].path)), driving_routes.MAX_POINTS)


def drive_of_places(places):
    return {"start": {k: places["stays"][0][k] for k in ("latitude", "longitude")}, "end": {k: places["stays"][1][k] for k in ("latitude", "longitude")}}


class PacingAndFailureTests(WarmingCase):
    def test_the_cap_stops_a_run_and_says_there_is_more_and_the_pause_comes_between_calls(self):
        self.two_drives()
        fetch, pause = Fetcher(), Pauses()
        got = run(fetch, pause, limit=1, delay=7.0)
        self.assertEqual((got.fetched, got.left, len(fetch.calls), pause.waits), (1, True, 1, []))
        fetch, pause = Fetcher(), Pauses()
        got = run(fetch, pause, delay=7.0)
        self.assertEqual((got.fetched, got.left, len(fetch.calls), pause.waits), (1, False, 1, []))
        self.assertEqual(len(self.rows()), 2)

    def test_each_call_after_the_first_waits_first_and_shutting_down_ends_the_run(self):
        self.two_drives()
        fetch, pause = Fetcher(), Pauses(stop_after=1)
        got = run(fetch, pause, delay=7.0)
        self.assertEqual((got.fetched, got.stop, len(fetch.calls), pause.waits), (1, True, 1, [7.0]))
        with db.session() as conn:
            conn.execute(DrivingRoute.__table__.delete())
        fetch, pause = Fetcher(), Pauses()
        self.assertEqual(run(fetch, pause, delay=7.0).fetched, 2)
        self.assertEqual(pause.waits, [7.0])

    def test_a_provider_error_ends_the_run_without_raising_and_stores_nothing(self):
        self.two_drives()

        def down(start, end):
            raise mapkit.Unavailable("Apple answered 503")
        got = run(down)
        self.assertEqual((got.fetched, got.stop, got.refused, self.rows()), (0, True, False, []))

    def test_a_drive_apple_cannot_route_is_remembered_and_not_asked_again_in_this_process(self):
        self.road_trip(DENVER, SALT_LAKE)
        skip = route_warming.Memory()
        got = run(Fetcher(None), skip=skip)
        self.assertEqual((got.fetched, len(skip.gave_up), got.stop), (0, 1, False))
        again = Fetcher()
        self.assertEqual(run(again, skip=skip).fetched, 0)
        self.assertEqual(again.calls, [])

    def test_a_route_the_store_refuses_is_given_up_on(self):
        self.road_trip(DENVER, SALT_LAKE)
        skip = route_warming.Memory()
        got = run(Fetcher([[0.0, 0.0], [1.0, 1.0]]), skip=skip)
        self.assertEqual((got.fetched, len(skip.gave_up), self.rows()), (0, 1, []))

    def test_a_refused_key_stops_the_run_cleanly_and_the_job_stops_for_good_with_a_generic_line(self):
        self.two_drives()
        got = run(refuse(401))
        self.assertEqual((got.refused, got.stop, got.fetched), (True, True, 0))
        stop = threading.Event()
        with mock.patch.object(route_warming, "client", return_value=refuse(403)), mock.patch.object(monitoring, "log") as logged:
            self.assertIsNone(jobs.warm_driving_routes(stop, route_warming.Memory()))
        self.assertIn("Maps Server API", logged.call_args.args[0])
        self.assertEqual(self.rows(), [])


class JobTests(WarmingCase):
    def test_the_job_does_nothing_without_credentials_or_with_the_flag_off(self):
        self.road_trip(DENVER, SALT_LAKE)
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in (maps.KEY_FILE_ENV, maps.KEY_ID_ENV, maps.TEAM_ID_ENV):
                os.environ.pop(name, None)
            self.assertIsNone(route_warming.client())
            with mock.patch.object(tls, "urlopen") as opened:
                self.assertIsNone(jobs.warm_driving_routes(threading.Event(), route_warming.Memory()))
            opened.assert_not_called()
        with mock.patch.object(maps, "enabled", return_value=False), mock.patch.object(maps, "credentials", return_value=CREDS):
            self.assertIsNone(route_warming.client())
        self.assertEqual(self.rows(), [])

    def test_a_round_reports_counts_only_and_picks_how_long_to_wait(self):
        self.two_drives()
        stop = threading.Event()
        with mock.patch.object(monitoring, "log") as logged, mock.patch.object(route_warming, "client", return_value=Fetcher()), \
                mock.patch.object(route_warming, "PAUSE_SECONDS", 0.0), mock.patch.object(route_warming, "MAX_PER_RUN", 1):
            self.assertEqual(jobs.warm_driving_routes(stop, route_warming.Memory()), jobs.ROUTES_MORE_EVERY)
        self.assertEqual(logged.call_args.args[0], "Driving routes: 1 prepared, more to come.")
        self.assertEqual(len(self.rows()), 1)

    def test_a_round_that_raises_is_reported_without_its_text_and_tried_again_later(self):
        secret = "CANARY-ROUTE-5521"
        with mock.patch.object(route_warming, "client", side_effect=RuntimeError(secret)):
            out = io.StringIO()
            with mock.patch("sys.stderr", out):
                self.assertEqual(jobs.warm_driving_routes(threading.Event(), route_warming.Memory()), jobs.ROUTES_RETRY_EVERY)
        self.assertNotIn(secret, out.getvalue())
        self.assertIn("RuntimeError", out.getvalue())

    def test_a_round_never_logs_a_place_or_a_coordinate(self):
        trip = self.two_drives()
        places = self.ok("ana", "GET", f"/api/trips/{trip}/places")
        canaries = ("Mile High Inn", "Salt Flat Inn", "Flatiron Inn", f"{places['stays'][0]['latitude']},{places['stays'][0]['longitude']}", f"{places['stays'][0]['latitude']:.6f}")
        with no_leaks(self, *canaries):
            with mock.patch.object(route_warming, "client", return_value=Fetcher()), mock.patch.object(route_warming, "PAUSE_SECONDS", 0.0):
                jobs.warm_driving_routes(threading.Event(), route_warming.Memory())
            with mock.patch.object(route_warming, "client", return_value=refuse(401)):
                jobs.warm_driving_routes(threading.Event(), route_warming.Memory())
            with mock.patch.object(route_warming, "client", return_value=Fetcher(None)):
                jobs.warm_driving_routes(threading.Event(), route_warming.Memory())

    def test_the_thread_starts_with_the_others_waits_first_and_ends_when_told_to_stop(self):
        stop = threading.Event()
        stop.set()
        with mock.patch.object(jobs, "warm_map_data"), mock.patch.object(jobs.flightstatus, "forget_key_pause"), \
                mock.patch.object(jobs, "warm_driving_routes") as ran:
            started = jobs.start(stop)
            for t in started:
                t.join(5)
        self.addCleanup(jobs.photoqueue.disable)
        self.assertIn("driving-routes", [t.name for t in started])
        ran.assert_not_called()
        self.assertGreater(jobs.ROUTES_FIRST, 0)

    def test_the_loop_runs_a_round_after_the_first_wait_and_ends_when_a_round_says_stop(self):
        stop = threading.Event()
        with mock.patch.object(jobs, "ROUTES_FIRST", 0), mock.patch.object(jobs, "warm_driving_routes", return_value=None) as ran:
            jobs.keep_routes_warm(stop)
        ran.assert_called_once()


def seg(id, kind, origin=None, destination=None, start="2026-06-01T10:00", end="2026-06-01T11:00", itinerary=(), status="confirmed"):
    return {"id": id, "kind": kind, "status": status, "origin": origin, "destination": destination, "start_local": start, "end_local": end,
            "start_zone": "UTC", "end_zone": "UTC", "itinerary": list(itinerary)}


def places_of(airports=(), cities=(), stays=(), home=None):
    return {"home": home, "airports": [{"code": c, "city": n, "latitude": a, "longitude": b} for c, n, a, b in airports],
            "cities": [{"city": n, "latitude": a, "longitude": b} for n, a, b in cities],
            "stays": [{"segment_id": i, "latitude": a, "longitude": b, "precision": "street"} for i, a, b in stays], "roads": {"legs": [], "interstates": []}, "boundaries": []}


def stops(segments, places):
    return [(v.kind, v.name, v.via) for v in route_warming.stops_of({"segments": segments}, places)]


class StopTests(unittest.TestCase):
    CITIES = (("Alpha", 40.0, -100.0), ("Beta", 41.0, -99.0), ("Gamma", 43.0, -97.0))

    def test_a_flight_has_two_airports_and_a_hotel_reached_by_car_is_a_drive_from_the_landing(self):
        places = places_of(airports=(("AAA", "Alpha", 40.0, -100.0), ("BBB", "Beta", 41.0, -99.0)), cities=(("Gamma", 43.0, -97.0),))
        got = stops([seg(1, "flight", "AAA", "BBB"), seg(2, "hotel", "Inn, Main St", "Gamma", start="2026-06-01T15:00", end="2026-06-03T10:00")], places)
        self.assertEqual(got, [("airport", "Alpha", None), ("airport", "Beta", "flight"), ("stay", "Inn", None)])
        trip = {"segments": [seg(1, "flight", "AAA", "BBB"), seg(2, "hotel", "Inn, Main St", "Gamma", start="2026-06-01T15:00", end="2026-06-03T10:00")]}
        self.assertEqual(len(route_warming.drives_of(trip, places)), 1)

    def test_a_rental_car_is_dropped_when_the_trip_flies_or_when_a_stop_is_already_there(self):
        places = places_of(airports=(("AAA", "Alpha", 40.0, -100.0), ("BBB", "Beta", 41.0, -99.0)), cities=(("Gamma", 43.0, -97.0),))
        self.assertEqual(stops([seg(1, "flight", "AAA", "BBB"), seg(2, "car", "Gamma", "Gamma")], places), [("airport", "Alpha", None), ("airport", "Beta", "flight")])
        driven = places_of(cities=self.CITIES, stays=((2, 43.0, -97.0),))
        got = stops([seg(1, "hotel", "Inn", "Gamma", start="2026-06-01T10:00"), seg(2, "car", "Gamma", "Gamma", start="2026-06-01T12:00")], places_of(cities=self.CITIES, stays=((1, 43.0, -97.0), (2, 43.0, -97.0))))
        self.assertEqual(len(got), 1)
        self.assertEqual(len(stops([seg(2, "car", "Gamma", "Gamma")], driven)), 1)

    def test_a_train_is_not_a_drive_and_a_cruise_calls_at_its_ports_and_returns_to_where_it_began(self):
        places = places_of(cities=self.CITIES, stays=((3, 40.0, -100.0),))
        train = stops([seg(1, "train", "Alpha", "Beta")], places)
        self.assertEqual([t[2] for t in train], [None, "train"])
        cruise = stops([seg(3, "cruise", "Alpha, X", "Alpha, X", itinerary=[{"name": "Beta", "arrive_local": "2026-06-02T08:00", "depart_local": "2026-06-02T17:00"}, {"name": "Gamma", "arrive_local": None, "depart_local": None}])], places)
        self.assertEqual([c[2] for c in cruise], [None, "cruise", "cruise", "cruise"])

    def test_visits_of_a_trip_of_nothing_else_are_ordered_by_their_dates_and_cancelled_bookings_are_ignored(self):
        places = places_of(stays=((1, 40.0, -100.0), (2, 42.0, -98.0), (3, 45.0, -95.0)))
        got = stops([seg(2, "visit", None, "FR", start="2026-06-05T00:00", end="2026-06-06T00:00"), seg(1, "visit", None, "DE", start="2026-06-01T00:00", end="2026-06-02T00:00"),
                     seg(3, "visit", None, "IT", status="cancelled"), seg(4, "parking", "Lot")], places)
        self.assertEqual([g[0] for g in got], ["place", "place"])
        self.assertEqual(got[0][1], "DE")

    def test_a_road_trip_is_wrapped_at_home_unless_it_starts_or_ends_there_and_a_trip_with_a_flight_is_not(self):
        home = {"city": "Homeville", "latitude": 30.0, "longitude": -90.0}
        places = places_of(cities=self.CITIES, stays=((1, 40.0, -100.0), (2, 43.0, -97.0)), home=home)
        wrapped = stops([seg(1, "hotel", "Inn A", "Alpha", start="2026-06-01T10:00"), seg(2, "hotel", "Inn G", "Gamma", start="2026-06-03T10:00")], places)
        self.assertEqual([w[0] for w in wrapped], ["home", "stay", "stay", "home"])
        near = places_of(cities=self.CITIES, stays=((1, 30.0, -90.0), (2, 43.0, -97.0)), home=home)
        self.assertEqual([w[0] for w in stops([seg(1, "hotel", "Inn A", "Alpha", start="2026-06-01T10:00"), seg(2, "hotel", "Inn G", "Gamma", start="2026-06-03T10:00")], near)], ["stay", "stay", "home"])
        flying = places_of(airports=(("AAA", "Alpha", 40.0, -100.0), ("BBB", "Beta", 41.0, -99.0)), home=home)
        self.assertEqual([w[0] for w in stops([seg(1, "flight", "AAA", "BBB")], flying)], ["airport", "airport"])

    def test_the_same_airport_twice_in_a_row_is_one_stop_and_a_place_is_upgraded_to_the_stop_found_for_it(self):
        places = places_of(airports=(("AAA", "Alpha", 40.0, -100.0), ("BBB", "Beta", 41.0, -99.0)), cities=self.CITIES)
        got = stops([seg(1, "flight", "AAA", "BBB", start="2026-06-01T10:00", end="2026-06-01T11:00"),
                     seg(2, "flight", "BBB", "AAA", start="2026-06-01T12:00", end="2026-06-01T13:00")], places)
        self.assertEqual([g[0] for g in got], ["airport", "airport", "airport"])
        merged = stops([seg(1, "train", "Beta", "Alpha", start="2026-06-01T10:00"), seg(2, "flight", "AAA", "BBB", start="2026-06-01T12:00")], places)
        self.assertEqual([m[0] for m in merged], ["place", "airport", "airport"])


class ServerApiTests(unittest.TestCase):
    def setUp(self):
        self.sent = []

    def fake(self, *replies):
        queue = list(replies)

        def urlopen(req, timeout, **kw):
            self.sent.append(req)
            reply = queue.pop(0)
            if isinstance(reply, int):
                raise urllib.error.HTTPError(req.full_url, reply, "x", {}, io.BytesIO(b"{}"))
            if isinstance(reply, Exception):
                raise reply
            return io.BytesIO(reply if isinstance(reply, bytes) else json.dumps(reply).encode())
        return mock.patch.object(tls, "urlopen", urlopen)

    TOKEN = {"accessToken": "access-token-1", "expiresInSeconds": 1800}
    ROUTE = {"routes": [{"stepIndexes": [0, 1]}], "steps": [{"stepPathIndex": 0}, {"stepPathIndex": 1}],
             "stepPaths": [[{"latitude": 1.0, "longitude": 2.0}, {"latitude": 1.5, "longitude": 2.5}], [{"latitude": 1.5, "longitude": 2.5}, {"latitude": 3.0, "longitude": 4.0}]]}

    def test_the_server_token_is_signed_with_the_key_and_carries_no_origin_or_scope(self):
        token = mapkit.sign_server(CREDS, 1000.0)
        head, claims, _, _ = parts(token)
        self.assertEqual((head, claims), ({"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}, {"iss": TEAM_ID, "iat": 1000, "exp": 1000 + mapkit.TOKEN_LIFETIME}))
        self.assertTrue(verifies(token, PRIVATE.public_key()))

    def test_a_route_is_asked_for_with_an_access_token_and_comes_back_as_one_line(self):
        with self.fake(self.TOKEN, self.ROUTE):
            got = mapkit.Directions(CREDS).route((1.0, 2.0), (3.0, 4.0), 5000.0)
        self.assertEqual(got, [[1.0, 2.0], [1.5, 2.5], [3.0, 4.0]])
        token, directions = self.sent
        self.assertEqual((token.full_url, directions.full_url.split("?")[0]), ("https://maps-api.apple.com/v1/token", "https://maps-api.apple.com/v1/directions"))
        self.assertIn("transportType=Automobile", directions.full_url)
        self.assertEqual(directions.get_header("Authorization"), "Bearer access-token-1")
        self.assertTrue(token.get_header("Authorization").startswith("Bearer eyJ"))

    def test_the_access_token_is_reused_until_it_is_about_to_expire(self):
        client = mapkit.Directions(CREDS)
        with self.fake(self.TOKEN, self.ROUTE, self.ROUTE, {"accessToken": "access-token-2", "expiresInSeconds": 1800}, self.ROUTE):
            client.route((1.0, 2.0), (3.0, 4.0), 5000.0)
            client.route((1.0, 2.0), (3.0, 4.0), 5100.0)
            client.route((1.0, 2.0), (3.0, 4.0), 5000.0 + 1800)
        self.assertEqual(len(self.sent), 5)
        self.assertEqual(self.sent[-1].get_header("Authorization"), "Bearer access-token-2")

    def test_an_expired_access_token_is_replaced_once_and_the_request_repeated(self):
        with self.fake(self.TOKEN, 401, {"accessToken": "access-token-2", "expiresInSeconds": 1800}, self.ROUTE):
            self.assertEqual(len(mapkit.Directions(CREDS).route((1.0, 2.0), (3.0, 4.0), 5000.0) or []), 3)

    def test_401_and_403_are_a_refusal_and_a_second_401_after_a_new_token_is_too(self):
        for replies in ((401,), (403,), (self.TOKEN, 403), (self.TOKEN, 401, self.TOKEN, 401)):
            with self.fake(*replies), self.assertRaises(mapkit.Refused):
                mapkit.Directions(CREDS).route((1.0, 2.0), (3.0, 4.0), 5000.0)

    def test_a_server_error_rate_limit_timeout_or_junk_is_unavailable_and_no_route_is_none(self):
        for replies in ((500,), (429,), (urllib.error.URLError("x"),), (TimeoutError(),), (b"not json",), ({"nothing": 1},)):
            with self.fake(*replies), self.assertRaises(mapkit.Unavailable):
                mapkit.Directions(CREDS).route((1.0, 2.0), (3.0, 4.0), 5000.0)
        for reply in (404, {"routes": []}, {"routes": [{"stepIndexes": []}], "steps": [], "stepPaths": []}, "x"):
            with self.fake(self.TOKEN, reply):
                self.assertIsNone(mapkit.Directions(CREDS).route((1.0, 2.0), (3.0, 4.0), 5000.0))

    def test_a_reply_with_a_bad_point_or_index_is_no_route(self):
        bad_point = json.loads(json.dumps(self.ROUTE))
        bad_point["stepPaths"][0][0]["latitude"] = "x"
        bad_index = {**self.ROUTE, "routes": [{"stepIndexes": [7]}]}
        for body in (bad_point, bad_index, [], {"routes": [1], "steps": [], "stepPaths": []}):
            self.assertIsNone(mapkit.parse_path(body))

    def test_a_key_that_is_not_an_elliptic_curve_key_cannot_sign(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        pem = rsa.generate_private_key(65537, 2048).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with self.assertRaises(mapkit.Refused):
            mapkit.Directions(mapkit.Credentials(pem, KEY_ID, TEAM_ID)).route((1.0, 2.0), (3.0, 4.0), 1.0)

    def test_the_client_is_made_only_for_an_active_key(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "k.p8")
        with open(path, "wb") as f:
            f.write(PEM)
        env = {maps.FLAG_ENV: "on", maps.KEY_FILE_ENV: path, maps.KEY_ID_ENV: KEY_ID, maps.TEAM_ID_ENV: TEAM_ID, maps.PUBLIC_URL_ENV: "https://waypoint.example.test"}
        with mock.patch.dict(os.environ, env):
            self.assertIsNotNone(route_warming.client())
            with mock.patch.dict(os.environ, {maps.FLAG_ENV: "off"}):
                self.assertIsNone(route_warming.client())
            with mock.patch.dict(os.environ, {maps.PUBLIC_URL_ENV: ""}):
                self.assertIsNone(route_warming.client())


if __name__ == "__main__":
    unittest.main()
