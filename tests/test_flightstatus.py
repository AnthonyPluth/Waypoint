import json
import os
import threading
import unittest
import urllib.error
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from sqlalchemy import insert, select

from tests.privacy import no_leaks
from tests.shared import DbCase
from tests.test_trips import RouteCase
from waypoint import monitoring, oidc
from waypoint.domain import flightstatus, loyalty, people, trips
from waypoint.domain.visibility import Viewer
from waypoint.providers import flightstatus as service
from waypoint.server import jobs
from waypoint.storage import db
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import FlightStatus, Segment

FIXTURES = Path(__file__).parent / "fixtures" / "aerodatabox"
KEY = "test-rapidapi-key-8f3a91c2"
OUT = {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-11-20T19:00",
       "end_local": "2026-11-21T07:10", "provider": "Example Air", "details": {"flight_number": "EX 101", "terminal": "7"}}
BACK = {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": "2026-11-27T11:30",
        "end_local": "2026-11-27T14:35", "details": {"flight_number": "EX 102"}}
HOTEL = {"kind": "hotel", "origin": "Harbour Hotel", "start_local": "2026-11-21T15:00", "end_local": "2026-11-27T10:00",
         "start_zone": "Europe/London", "end_zone": "Europe/London"}
DEPARTS = datetime(2026, 11, 21, 0, 0, tzinfo=UTC)
ARRIVES = datetime(2026, 11, 21, 7, 10, tzinfo=UTC)
EARLY = DEPARTS - timedelta(hours=30)


def fixture(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def status(name: str, origin: str | None = None) -> service.Status:
    found = service.parse(fixture(name), origin)
    assert found
    return found


FLIGHT = flightstatus.Flight("EX101", "2026-11-20", "JFK", DEPARTS, ARRIVES)


class FakeService(HTTPServer):

    def __init__(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def do_GET(self):
                self.server.calls.append({"path": self.path, "headers": dict(self.headers)})   # type: ignore[attr-defined]
                code, body = self.server.answer   # type: ignore[attr-defined]
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        super().__init__(("127.0.0.1", 0), Handler)
        self.calls: list[dict] = []
        self.answer: tuple[int, object] = (200, fixture("delayed_gate_change"))


def serve_fake(case) -> FakeService:
    fake = FakeService()
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    case.addCleanup(fake.server_close)
    case.addCleanup(fake.shutdown)
    patches = [mock.patch.dict(os.environ, {"RAPIDAPI_KEY": KEY, "WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT": ""}),
               mock.patch.object(service, "HOSTS", service.Hosts(base=f"http://127.0.0.1:{fake.server_port}", allow_http=True))]
    for p in patches:
        p.start()
        case.addCleanup(p.stop)
    return fake


class ParseTests(unittest.TestCase):
    def test_a_flight_on_time(self):
        s = status("on_time")
        self.assertEqual(s, service.Status(
            state="scheduled", origin="JFK", destination="LHR", dep_scheduled="2026-11-20T19:00", dep_zone="America/New_York",
            dep_terminal="7", dep_gate="B22", arr_scheduled="2026-11-21T07:10", arr_zone="Europe/London", arr_terminal="5"))

    def test_a_delay_with_a_gate_change(self):
        s = status("delayed_gate_change")
        self.assertEqual((s.state, s.dep_scheduled, s.dep_estimated, s.dep_gate, s.arr_estimated, s.arr_gate),
                         ("delayed", "2026-11-20T19:00", "2026-11-20T19:50", "B24", "2026-11-21T08:05", "A10"))

    def test_a_flight_expected_late_is_delayed_from_15_minutes(self):
        self.assertEqual(status("expected_but_late").state, "delayed")
        late = fixture("expected_but_late")
        late[0]["departure"]["revisedTime"]["local"] = "2026-11-20 19:14-05:00"
        self.assertEqual(service.parse(late).state, "scheduled")   # type: ignore[union-attr]
        late[0]["departure"]["revisedTime"]["local"] = "2026-11-20 19:15-05:00"
        self.assertEqual(service.parse(late).state, "delayed")   # type: ignore[union-attr]

    def test_departed_landed_cancelled_and_diverted(self):
        departed = status("departed")
        self.assertEqual((departed.state, departed.dep_actual, departed.arr_estimated), ("departed", "2026-11-20T19:12", "2026-11-21T07:05"))
        landed = status("landed")
        self.assertEqual((landed.state, landed.arr_actual, landed.arr_gate), ("landed", "2026-11-21T07:03", "A12"))
        self.assertEqual(status("cancelled").state, "cancelled")
        self.assertEqual(status("diverted").state, "diverted")

    def test_an_unknown_flight_has_no_status(self):
        for body in (fixture("unknown_flight"), None, {}, "oops", 7, [None, "x", {}]):
            with self.subTest(body=body):
                self.assertIsNone(service.parse(body))

    def test_times_are_the_airports_wall_clock_times_with_their_zones_never_converted(self):
        s = status("on_time")
        self.assertEqual((s.dep_scheduled, s.dep_zone), ("2026-11-20T19:00", "America/New_York"))
        odd = fixture("on_time")
        odd[0]["departure"]["scheduledTime"]["local"] = "2026-03-01 22:15+13:00"
        self.assertEqual(service.parse(odd).dep_scheduled, "2026-03-01T22:15")   # type: ignore[union-attr]
        for bad in ("soon", "", None, 5):
            odd[0]["departure"]["scheduledTime"]["local"] = bad
            self.assertIsNone(service.parse(odd).dep_scheduled)   # type: ignore[union-attr]

    def test_the_leg_that_leaves_from_the_booked_airport(self):
        self.assertEqual(status("two_legs", "JFK").destination, "DUB")
        second = status("two_legs", "dub")
        self.assertEqual((second.state, second.dep_gate, second.destination), ("delayed", "C4", "LHR"))
        self.assertIsNone(service.parse(fixture("two_legs"), "AKL"))
        self.assertEqual(service.parse(fixture("two_legs")).origin, "JFK")   # type: ignore[union-attr]

    def test_every_status_the_service_has_maps_to_one_of_ours(self):
        for given, ours in (("Expected", "scheduled"), ("CheckIn", "scheduled"), ("Boarding", "scheduled"),
                            ("GateClosed", "scheduled"), ("Delayed", "delayed"), ("Departed", "departed"),
                            ("EnRoute", "departed"), ("Approaching", "departed"), ("Arrived", "landed"),
                            ("Canceled", "cancelled"), ("CanceledUncertain", "cancelled"), ("Diverted", "diverted"),
                            ("Unknown", "unknown"), ("Something new", "unknown"), (None, "unknown")):
            body = fixture("on_time")
            body[0]["status"] = given
            self.assertEqual(service.parse(body).state, ours, given)   # type: ignore[union-attr]
            self.assertIn(ours, service.STATES)

    def test_flight_numbers(self):
        for given, want in (("EX 101", "EX101"), ("ex101", "EX101"), (" NZ-6 ", "NZ6"), ("B6 1234", "B61234"), ("UA 8A", "UA8A"), ("UA 8AB", None),
                            ("EX101/../x", None), ("EX101?key=1", None), ("", None), (None, None), ("E", None), ("EX12345", None)):
            self.assertEqual(service.normalize(given), want, given)


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.fake = serve_fake(self)

    def test_the_request_goes_to_rapidapi_for_one_flight_and_date_with_both_headers(self):
        s = service.fetch("EX101", "2026-11-20", "JFK")
        assert s
        self.assertEqual(s.state, "delayed")
        (call,) = self.fake.calls
        self.assertEqual(call["path"], "/flights/number/EX101/2026-11-20")
        sent = {k.lower(): v for k, v in call["headers"].items()}
        self.assertEqual(sent["x-rapidapi-key"], KEY)
        self.assertEqual(sent["x-rapidapi-host"], "aerodatabox.p.rapidapi.com")
        self.assertEqual(set(sent) - {"host", "accept", "user-agent", "connection", "accept-encoding"},
                         {"x-rapidapi-key", "x-rapidapi-host"}, "nothing else is sent")

    def test_it_asks_rapidapis_host_over_https_by_default(self):
        self.assertEqual(service.Hosts(), service.Hosts(base="https://aerodatabox.p.rapidapi.com", allow_http=False))
        self.assertEqual(service.HOST, "aerodatabox.p.rapidapi.com")

    def test_nothing_is_asked_without_a_key_or_for_something_that_isnt_a_flight(self):
        with mock.patch.dict(os.environ, {"RAPIDAPI_KEY": " "}):
            self.assertFalse(service.configured())
            with self.assertRaises(service.NotConfigured):
                service.fetch("EX101", "2026-11-20")
        for number, day in (("EX101/../x", "2026-11-20"), ("EX101", "2026-11-20/x"), ("ex101", "2026-11-20"), ("EX101", "tomorrow")):
            with self.assertRaises(service.Unavailable):
                service.fetch(number, day)
        self.assertEqual(self.fake.calls, [])

    def test_an_unknown_flight_is_none_and_the_other_answers_are_errors(self):
        for code, body in ((200, []), (200, {}), (204, {}), (404, {"message": "no flight"})):
            self.fake.answer = (code, body)
            self.assertIsNone(service.fetch("EX101", "2026-11-20"), (code, body))
        for code, error in ((429, service.RateLimited), (401, service.Refused), (403, service.Refused), (500, service.Unavailable),
                            (502, service.Unavailable)):
            self.fake.answer = (code, {"message": "no"})
            with self.assertRaises(error):
                service.fetch("EX101", "2026-11-20")

    def test_an_answer_it_cant_read_or_a_service_it_cant_reach_is_unavailable(self):
        with mock.patch.object(service.tls, "urlopen") as op:
            op.return_value.__enter__.return_value.read.return_value = b"<html>"
            with self.assertRaises(service.Unavailable):
                service.fetch("EX101", "2026-11-20")
            op.return_value.__enter__.return_value.read.return_value = b"  "
            self.assertIsNone(service.fetch("EX101", "2026-11-20"))
            op.side_effect = urllib.error.URLError("no route")
            with self.assertRaises(service.Unavailable):
                service.fetch("EX101", "2026-11-20")
            op.side_effect = TimeoutError()
            with self.assertRaises(service.Unavailable):
                service.fetch("EX101", "2026-11-20")

    def test_the_key_is_never_in_the_log_or_an_error_message(self):
        failures = [(429, service.RateLimited), (401, service.Refused), (500, service.Unavailable)]
        with no_leaks(self, KEY, sent_ok=True):
            for code, error in failures:
                self.fake.answer = (code, {"message": f"bad key {KEY}", "key": KEY})
                with self.assertRaises(error) as caught:
                    service.fetch("EX101", "2026-11-20")
                self.assertNotIn(KEY, str(caught.exception))
                self.assertNotIn(KEY, repr(caught.exception.__cause__))
                monitoring.report(caught.exception)
                monitoring.report(caught.exception, values=False)
            with mock.patch.object(service.tls, "urlopen", side_effect=urllib.error.URLError(f"failed for X-RapidAPI-Key: {KEY}")):
                with self.assertRaises(service.Unavailable) as caught:
                    service.fetch("EX101", "2026-11-20")
                self.assertNotIn(KEY, str(caught.exception))
                monitoring.report(caught.exception)

    def test_monitoring_hides_the_key_wherever_it_turns_up(self):
        for text in (f"request failed: X-RapidAPI-Key: {KEY}", f"{{'X-RapidAPI-Key': '{KEY}'}}", f"x-rapidapi-key={KEY}",
                     f"the key was {KEY} today"):
            with mock.patch.dict(os.environ, {"RAPIDAPI_KEY": KEY}):
                self.assertNotIn(KEY, monitoring.scrub(text), text)
            self.assertNotIn(KEY, monitoring.scrub(text.replace("the key was", "x-rapidapi-key:")), text)
        with mock.patch.dict(os.environ, {"RAPIDAPI_KEY": "short"}):
            self.assertEqual(monitoring.scrub("a short answer"), "a short answer")


class ScheduleTests(unittest.TestCase):
    def test_the_five_checks(self):
        names = [n for _, n in flightstatus.checkpoints(FLIGHT)]
        times = [t for t, _ in flightstatus.checkpoints(FLIGHT)]
        self.assertEqual(names, ["24h", "3h", "1h", "20m", "arrival"])
        self.assertEqual(times, [DEPARTS - timedelta(hours=24), DEPARTS - timedelta(hours=3), DEPARTS - timedelta(hours=1),
                                 DEPARTS - timedelta(minutes=20), ARRIVES])

    def test_nothing_is_fetched_more_than_24_hours_out(self):
        self.assertFalse(flightstatus.due(FLIGHT, DEPARTS - timedelta(hours=24, minutes=1), None, None))
        self.assertFalse(flightstatus.due(FLIGHT, DEPARTS - timedelta(days=30), None, None))
        self.assertTrue(flightstatus.due(FLIGHT, DEPARTS - timedelta(hours=24), None, None))

    def test_each_check_is_made_once(self):
        at = {n: t for t, n in flightstatus.checkpoints(FLIGHT)}
        last = at["24h"] + timedelta(minutes=3)
        for now, want in ((at["24h"] + timedelta(hours=5), False), (at["3h"] - timedelta(minutes=1), False), (at["3h"], True)):
            self.assertEqual(flightstatus.due(FLIGHT, now, last, "scheduled"), want, now)
        for early, name in (("24h", "3h"), ("3h", "1h"), ("1h", "20m"), ("20m", "arrival")):
            self.assertFalse(flightstatus.due(FLIGHT, at[name] - timedelta(seconds=1), at[early], "scheduled"), name)
            self.assertTrue(flightstatus.due(FLIGHT, at[name], at[early], "scheduled"), name)
            self.assertFalse(flightstatus.due(FLIGHT, at[name] + timedelta(minutes=1), at[name], "scheduled"), name)

    def test_a_flight_costs_at_most_five_calls_however_often_the_scheduler_asks(self):
        last: datetime | None = None
        calls = []
        now = EARLY
        while now < ARRIVES + timedelta(hours=10):
            if flightstatus.due(FLIGHT, now, last, "scheduled"):
                calls.append(now)
                last = now
            now += timedelta(minutes=1)
        self.assertEqual(calls, [t for t, _ in flightstatus.checkpoints(FLIGHT)])

    def test_after_downtime_only_the_latest_missed_check_is_made(self):
        now = DEPARTS - timedelta(minutes=30)
        self.assertTrue(flightstatus.due(FLIGHT, now, None, None))
        self.assertFalse(flightstatus.due(FLIGHT, now, now, "scheduled"))

    def test_nothing_after_landing_or_a_cancellation_or_a_long_time_after_arrival(self):
        mid = DEPARTS - timedelta(minutes=30)
        for state in ("landed", "cancelled", "diverted"):
            self.assertFalse(flightstatus.due(FLIGHT, mid, None, state), state)
            self.assertFalse(flightstatus.due(FLIGHT, ARRIVES, None, state), state)
        self.assertTrue(flightstatus.due(FLIGHT, ARRIVES + flightstatus.LATE, None, "departed"))
        self.assertFalse(flightstatus.due(FLIGHT, ARRIVES + flightstatus.LATE + timedelta(minutes=1), None, None))

    def test_from_90_percent_only_the_one_hour_check_is_made(self):
        at = {n: t for t, n in flightstatus.checkpoints(FLIGHT)}
        for name in ("24h", "3h"):
            self.assertFalse(flightstatus.due(FLIGHT, at[name], None, None, reduced=True), name)
        self.assertTrue(flightstatus.due(FLIGHT, at["1h"], None, None, reduced=True))
        self.assertTrue(flightstatus.due(FLIGHT, at["1h"], at["24h"], "scheduled", reduced=True))
        for name in ("20m", "arrival"):
            self.assertFalse(flightstatus.due(FLIGHT, at[name], at["1h"], "scheduled", reduced=True), name)

    def test_the_limit_comes_from_the_environment(self):
        for given, want in (("50", 50), (" 12 ", 12), ("", 400), ("abc", 400), ("0", 400), ("-3", 400), ("2.5", 400)):
            with mock.patch.dict(os.environ, {"WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT": given}):
                self.assertEqual(flightstatus.limit(), want, given)
        with mock.patch.dict(os.environ):
            os.environ.pop("WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT", None)
            self.assertEqual(flightstatus.limit(), 400)


class Household(DbCase):

    def setUp(self):
        super().setUp()
        self.fake = serve_fake(self)
        for sub, name in (("u-jane", "Jane Doe"), ("u-sam", "Sam Doe")):
            oidc.remember_user(self.c, sub, f"{sub}@example.com", name, None)
        self.jane = Viewer(people.person_for_sub(self.c, "u-jane"))
        self.sam = Viewer(people.person_for_sub(self.c, "u-sam"))
        self.mia = people.add_guest(self.c, {"display_name": "Mia Doe", "first_name": None, "legal_name": None, "aliases": []})["id"]

    def book(self, who, fields=OUT, travelers=None):
        got = trips.add_segment(self.c, who, {**fields, "travelers": [{"person_id": i, "name": None} for i in travelers or [who.person_id]]})
        assert got
        return got

    def when(self, name: str, extra: timedelta = timedelta()) -> datetime:
        return {n: t for t, n in flightstatus.checkpoints(FLIGHT)}[name] + extra

    def cached(self) -> FlightStatus | None:
        self.c.orm.expire_all()
        return self.c.orm.get(FlightStatus, ("EX101", "2026-11-20"))

    def used(self, now: datetime | None = None) -> int:
        other = db.connect(self.path)
        try:
            return flightstatus.usage(other, now or self.when("24h")).used
        finally:
            other.close()

    def set_used(self, n: int, month: str = "2026-11") -> None:
        db.set_setting(self.c, sk.FLIGHT_STATUS_MONTH, month)
        db.set_setting(self.c, sk.FLIGHT_STATUS_CALLS, str(n))
        self.c.commit()


class CheckTests(Household):
    def test_a_flight_with_no_times_is_not_watched(self):
        self.book(self.jane, {**OUT, "start_local": "2026-11-20T00:00", "end_local": "2026-11-20T05:00",
                              "details": {"flight_number": "EX 101", "time_unknown": "yes"}})
        self.assertEqual(flightstatus.watching(self.c, self.when("3h")), [])

    def test_one_call_answers_for_every_traveller_and_segment_on_a_flight(self):
        self.book(self.jane, OUT, travelers=[self.jane.person_id, self.sam.person_id, self.mia])
        self.book(self.sam, {**OUT, "confirmation": "ZZ9PLU"})
        self.book(self.jane, BACK)
        self.assertEqual([f.number for f in flightstatus.watching(self.c, self.when("3h"))], ["EX101"])
        self.assertEqual(flightstatus.run_due(self.c, self.when("3h")), 1)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.fake.calls[0]["path"], "/flights/number/EX101/2026-11-20")
        self.assertEqual(self.cached().state, "delayed")   # type: ignore[union-attr]
        self.assertEqual(flightstatus.run_due(self.c, self.when("3h", timedelta(minutes=5))), 0)
        self.assertEqual(len(self.fake.calls), 1)

    def test_what_is_watched_is_a_flight_with_a_number_near_today_that_isnt_cancelled(self):
        self.book(self.jane, OUT)
        self.book(self.jane, HOTEL)
        self.book(self.jane, {**OUT, "start_local": "2026-12-20T19:00", "end_local": "2026-12-21T07:10", "details": {"flight_number": "EX 7"}})
        self.book(self.jane, {**OUT, "start_local": "2026-11-20T09:00", "end_local": "2026-11-20T21:10", "details": {"seat": "1A"}})
        gone = self.book(self.jane, {**OUT, "details": {"flight_number": "EX 5"}})
        trips.edit_segment(self.c, self.jane, gone["id"], {"status": "cancelled"})
        self.assertEqual([f.number for f in flightstatus.watching(self.c, self.when("3h"))], ["EX101"])
        self.assertEqual(flightstatus.watching(self.c, self.when("3h", timedelta(days=60))), [])
        self.assertEqual(flightstatus.watching(self.c, self.when("3h", -timedelta(days=60))), [])
        (f,) = flightstatus.watching(self.c, self.when("3h"))
        self.assertEqual((f.day, f.origin, f.departs, f.arrives), ("2026-11-20", "JFK", DEPARTS, ARRIVES))

    def test_nothing_is_fetched_without_a_key(self):
        self.book(self.jane)
        with mock.patch.dict(os.environ, {"RAPIDAPI_KEY": ""}):
            self.assertEqual(flightstatus.run_due(self.c, self.when("3h")), 0)
        self.assertEqual(self.fake.calls, [])

    def test_an_unknown_flight_is_kept_as_one_so_it_isnt_asked_again_until_the_next_check(self):
        self.book(self.jane)
        self.fake.answer = (200, [])
        self.assertEqual(flightstatus.run_due(self.c, self.when("3h")), 1)
        self.assertEqual(self.cached().state, "unknown")   # type: ignore[union-attr]
        self.assertEqual(flightstatus.run_due(self.c, self.when("3h", timedelta(minutes=30))), 0)
        self.assertEqual(flightstatus.overview(self.c, self.jane, self.when("3h"))["statuses"], [])
        self.assertEqual(flightstatus.run_due(self.c, self.when("1h")), 1)

    def test_every_check_from_a_day_out_to_the_arrival_is_made_and_no_more(self):
        self.book(self.jane)
        now = EARLY
        while now < ARRIVES + timedelta(hours=8):
            flightstatus.run_due(self.c, now)
            now += timedelta(minutes=5)
        self.assertEqual(len(self.fake.calls), 5)
        self.assertEqual(self.used(ARRIVES), 5)

    def test_a_landed_flight_is_left_alone(self):
        self.book(self.jane)
        self.fake.answer = (200, fixture("landed"))
        self.assertEqual(flightstatus.run_due(self.c, self.when("20m")), 1)
        self.assertEqual(flightstatus.run_due(self.c, ARRIVES), 0)
        self.assertEqual(len(self.fake.calls), 1)

    def test_answers_go_seven_days_after_the_flight(self):
        for day in ("2026-11-12", "2026-11-13", "2026-11-14", "2026-11-20"):
            self.c.execute(insert(FlightStatus).values(flight_number="EX9", date=day, state="landed", fetched_at=1.0))
        flightstatus.purge(self.c, datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
        self.c.orm.expire_all()
        self.assertEqual(sorted(r.date for r in self.c.orm.scalars(select(FlightStatus)).all()), ["2026-11-14", "2026-11-20"])
        self.book(self.jane)
        self.assertEqual(flightstatus.run_due(self.c, datetime(2026, 11, 28, 12, 0, tzinfo=UTC)), 0)
        self.c.orm.expire_all()
        self.assertEqual(list(self.c.orm.scalars(select(FlightStatus)).all()), [])


class BudgetTests(Household):
    def setUp(self):
        super().setUp()
        self.book(self.jane)

    def test_calls_are_counted_for_the_month_and_kept(self):
        self.assertEqual(self.used(), 0)
        flightstatus.run_due(self.c, self.when("24h"))
        flightstatus.run_due(self.c, self.when("3h"))
        self.assertEqual(self.used(), 2)
        u = flightstatus.usage(self.c, self.when("3h"))
        self.assertEqual((u.month, u.used, u.limit, u.paused), ("2026-11", 2, 400, None))

    def test_the_counter_starts_again_in_a_new_month(self):
        self.set_used(380, month="2026-10")
        self.assertEqual(flightstatus.usage(self.c, self.when("24h")).used, 0)
        flightstatus.run_due(self.c, self.when("24h"))
        self.assertEqual(self.used(), 1)
        self.assertEqual(db.get_setting(self.c, sk.FLIGHT_STATUS_MONTH), "2026-11")
        self.set_used(5, month="not a month")
        self.assertEqual(self.used(), 0)
        self.set_used(0)
        db.set_setting(self.c, sk.FLIGHT_STATUS_CALLS, "lots")
        self.assertEqual(self.used(), 0)

    def test_at_90_percent_scheduled_checks_stop_except_the_one_hour_check(self):
        self.set_used(359)
        self.assertFalse(flightstatus.usage(self.c, self.when("24h")).reduced)
        self.set_used(360)
        self.assertTrue(flightstatus.usage(self.c, self.when("24h")).reduced)
        self.assertEqual(flightstatus.run_due(self.c, self.when("24h")), 0)
        self.assertEqual(flightstatus.run_due(self.c, self.when("3h")), 0)
        self.assertEqual(flightstatus.run_due(self.c, self.when("1h")), 1)
        self.assertEqual(flightstatus.run_due(self.c, self.when("20m")), 0)
        self.assertEqual(flightstatus.run_due(self.c, ARRIVES), 0)
        self.assertEqual(self.used(), 361)

    def test_at_the_limit_nothing_is_fetched_and_the_card_says_until_when(self):
        self.set_used(400)
        for name in ("24h", "3h", "1h", "20m", "arrival"):
            self.assertEqual(flightstatus.run_due(self.c, self.when(name)), 0, name)
        self.assertEqual(self.fake.calls, [])
        u = flightstatus.usage(self.c, self.when("1h"))
        assert u.paused
        self.assertEqual((u.paused.reason, u.paused.until.astimezone().date(), u.paused.until.astimezone().hour),
                         ("limit", date(2026, 12, 1), 0))
        over = flightstatus.overview(self.c, self.jane, self.when("1h"))
        self.assertEqual((over["used"], over["limit"], over["paused"]["reason"]), (400, 400, "limit"))   # type: ignore[index]
        self.set_used(0, month="2026-10")
        self.assertIsNone(flightstatus.usage(self.c, self.when("1h")).paused)

    def test_the_limit_is_the_households_to_set(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT": "10"}):
            self.set_used(8)
            self.assertFalse(flightstatus.usage(self.c, self.when("3h")).reduced)
            self.set_used(9)
            self.assertTrue(flightstatus.usage(self.c, self.when("3h")).reduced)
            self.assertEqual(flightstatus.run_due(self.c, self.when("3h")), 0)
            self.set_used(10)
            self.assertEqual(flightstatus.run_due(self.c, self.when("1h")), 0)

    def test_a_429_pauses_fetching_for_an_hour(self):
        self.fake.answer = (429, {"message": "Too many requests"})
        now = self.when("3h")
        self.assertEqual(flightstatus.run_due(self.c, now), 1)
        u = flightstatus.usage(self.c, now)
        assert u.paused
        self.assertEqual((u.paused.reason, u.paused.until), ("rate", now + timedelta(hours=1)))
        self.fake.answer = (200, fixture("on_time"))
        self.assertEqual(flightstatus.run_due(self.c, now + timedelta(minutes=30)), 0)
        self.assertEqual(flightstatus.run_due(self.c, now + timedelta(minutes=59)), 0)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertIsNone(flightstatus.usage(self.c, now + timedelta(hours=1, seconds=1)).paused)
        self.assertEqual(flightstatus.run_due(self.c, now + timedelta(hours=1, minutes=1)), 0)
        self.assertEqual(flightstatus.run_due(self.c, self.when("1h")), 1)
        self.assertEqual(self.cached().state, "scheduled")   # type: ignore[union-attr]

    def test_a_key_rapidapi_refuses_pauses_too_and_a_garbled_pause_is_none(self):
        self.fake.answer = (403, {"message": "You are not subscribed to this API."})
        now = self.when("3h")
        self.assertEqual(flightstatus.run_due(self.c, now), 1)
        u = flightstatus.usage(self.c, now)
        self.assertEqual((u.paused.reason if u.paused else None), "key")
        for junk in ("", "null", "{", '{"until": "x"}', '{"until": 1e30, "reason": "rate"}',
                     json.dumps({"until": (now + timedelta(hours=1)).timestamp(), "reason": "limit"}), "[1]"):
            db.set_setting(self.c, sk.FLIGHT_STATUS_PAUSED, junk)
            self.assertIsNone(flightstatus.usage(self.c, now).paused, junk)

    def test_a_failed_call_still_counts_and_uses_up_its_check(self):
        self.fake.answer = (500, {"message": "oops"})
        now = self.when("3h")
        out, err = _captured(lambda: flightstatus.run_due(self.c, now))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.used(), 1)
        self.assertIn("Flight status: The flight status service had a problem.", out)
        self.assertNotIn("EX101", out + err)
        self.assertEqual(self.cached().state, "unknown")   # type: ignore[union-attr]
        for minutes in (5, 10, 60):
            self.assertEqual(flightstatus.run_due(self.c, now + timedelta(minutes=minutes)), 0)
        self.fake.answer = (200, fixture("on_time"))
        self.assertEqual(flightstatus.run_due(self.c, self.when("1h")), 1)
        self.assertEqual(self.cached().state, "scheduled")   # type: ignore[union-attr]
        self.assertEqual(self.used(), 2)

    def test_a_failed_call_keeps_the_answer_held(self):
        self.assertEqual(flightstatus.run_due(self.c, self.when("24h")), 1)
        self.fake.answer = (500, {})
        self.assertEqual(flightstatus.run_due(self.c, self.when("3h")), 1)
        self.assertEqual(self.cached().state, "delayed")   # type: ignore[union-attr]
        self.assertEqual(flightstatus.run_due(self.c, self.when("3h", timedelta(minutes=30))), 0)

    def test_a_long_outage_costs_no_more_than_the_five_checks_and_survives_a_restart(self):
        self.fake.answer = (500, {"message": "down"})
        now = EARLY
        while now < ARRIVES + timedelta(hours=8):
            _captured(lambda at=now: flightstatus.run_due(self.c, at))
            now += timedelta(minutes=5)
        self.assertEqual(len(self.fake.calls), 5)
        self.assertEqual(self.used(ARRIVES), 5)


def _captured(fn):
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        fn()
    return out.getvalue(), err.getvalue()


class RefreshTests(Household):
    def setUp(self):
        super().setUp()
        self.seg = self.book(self.jane, OUT, travelers=[self.jane.person_id, self.sam.person_id])
        self.hotel = self.book(self.jane, HOTEL)

    def refresh(self, now: datetime, who: Viewer | None = None, seg: int | None = None):
        return flightstatus.refresh(self.c, who or self.jane, seg or self.seg["id"], now)

    def test_refresh_fetches_now_and_counts_a_call(self):
        got = self.refresh(self.when("3h"))
        assert got
        (s,) = got["statuses"]
        self.assertEqual((s["segment_id"], s["state"], s["dep_gate"], s["delay_minutes"]), (self.seg["id"], "delayed", "B24", 50))
        self.assertEqual((got["enabled"], got["used"], got["limit"], got["paused"]), (True, 1, 400, None))
        self.assertEqual(len(self.fake.calls), 1)

    def test_refresh_shows_the_held_answer_when_it_is_under_15_minutes_old(self):
        now = self.when("3h")
        self.refresh(now)
        for minutes in (0, 1, 14):
            got = self.refresh(now + timedelta(minutes=minutes))
            assert got
            self.assertEqual((len(got["statuses"]), got["used"]), (1, 1))
        self.assertEqual(len(self.fake.calls), 1)
        self.refresh(now + timedelta(minutes=15))
        self.assertEqual((len(self.fake.calls), self.used(now)), (2, 2))

    def test_a_flight_that_is_over_is_not_fetched_again(self):
        self.fake.answer = (200, fixture("landed"))
        now = ARRIVES
        self.refresh(now)
        got = self.refresh(now + timedelta(days=1))
        assert got
        self.assertEqual((got["statuses"][0]["state"], len(self.fake.calls)), ("landed", 1))

    def test_refresh_is_for_a_flight_you_can_see_and_that_has_a_number(self):
        self.assertIsNone(self.refresh(self.when("3h"), Viewer(None), self.seg["id"]))
        stranger = Viewer(people.add_guest(self.c, {"display_name": "Joan", "first_name": None, "legal_name": None, "aliases": []})["id"])
        self.assertIsNone(self.refresh(self.when("3h"), stranger))
        self.assertIsNone(self.refresh(self.when("3h"), seg=99999))
        self.assertEqual(self.fake.calls, [])
        with self.assertRaises(flightstatus.NotAFlight):
            self.refresh(self.when("3h"), seg=self.hotel["id"])
        bare = self.book(self.jane, {**OUT, "details": {}, "start_local": "2026-11-22T09:00", "end_local": "2026-11-22T21:00"})
        with self.assertRaises(flightstatus.NotAFlight):
            self.refresh(self.when("3h"), seg=bare["id"])
        with mock.patch.dict(os.environ, {"RAPIDAPI_KEY": ""}), self.assertRaises(service.NotConfigured):
            self.refresh(self.when("3h"))

    def test_refresh_while_paused_makes_no_call_and_says_why(self):
        self.set_used(400)
        got = self.refresh(self.when("3h"))
        assert got
        self.assertEqual((got["statuses"], got["paused"]["reason"] if got["paused"] else None), ([], "limit"))
        self.set_used(1)
        self.fake.answer = (429, {})
        with self.assertRaises(service.RateLimited):
            self.refresh(self.when("3h"))
        self.assertEqual(self.used(), 2)
        self.fake.answer = (200, fixture("on_time"))
        got = self.refresh(self.when("3h", timedelta(minutes=20)))
        assert got
        self.assertEqual((got["paused"]["reason"] if got["paused"] else None, got["statuses"]), ("rate", []))
        self.assertEqual(len(self.fake.calls), 1)

    def test_refresh_after_a_failure_keeps_the_old_answer(self):
        self.refresh(self.when("3h"))
        self.fake.answer = (500, {})
        with self.assertRaises(service.Unavailable):
            self.refresh(self.when("3h", timedelta(minutes=20)))
        got = flightstatus.overview(self.c, self.jane, self.when("3h", timedelta(minutes=20)))
        self.assertEqual([s["state"] for s in got["statuses"]], ["delayed"])


class WhoSeesAStatus(Household):
    def test_a_status_shows_only_on_the_segments_the_viewer_can_see(self):
        mine = self.book(self.jane, OUT, travelers=[self.jane.person_id, self.mia])
        self.c.execute(insert(FlightStatus).values(
            flight_number="EX101", date="2026-11-20", state="delayed", origin="JFK", destination="LHR",
            dep_scheduled="2026-11-20T19:00", dep_estimated="2026-11-20T19:50", dep_zone="America/New_York", dep_gate="B24",
            arr_scheduled="2026-11-21T07:10", arr_zone=None, fetched_at=DEPARTS.timestamp()))
        self.assertEqual([s["segment_id"] for s in flightstatus.overview(self.c, self.jane, EARLY)["statuses"]], [mine["id"]])
        self.assertEqual(flightstatus.overview(self.c, self.sam, EARLY)["statuses"], [])
        self.assertEqual(flightstatus.overview(self.c, Viewer(None), EARLY)["statuses"], [])
        self.assertEqual(len(flightstatus.overview(self.c, Viewer(None, household=True), EARLY)["statuses"]), 1)
        self.assertEqual(flightstatus.overview(self.c, self.sam, EARLY)["limit"], 400)

    def test_a_status_for_another_leg_of_the_flight_number_isnt_shown(self):
        seg = self.book(self.jane, OUT)
        self.c.execute(insert(FlightStatus).values(flight_number="EX101", date="2026-11-20", state="delayed", origin="DUB",
                                                   fetched_at=1.0))
        self.assertEqual(flightstatus.overview(self.c, self.jane, EARLY)["statuses"], [])
        self.c.execute(FlightStatus.__table__.update().values(origin="jfk"))
        self.c.orm.expire_all()
        self.assertEqual([s["segment_id"] for s in flightstatus.overview(self.c, self.jane, EARLY)["statuses"]], [seg["id"]])

    def test_times_come_with_their_zones_and_fall_back_to_the_segments(self):
        seg = self.book(self.jane)
        self.c.execute(insert(FlightStatus).values(flight_number="EX101", date="2026-11-20", state="departed", dep_actual="2026-11-20T19:12",
                                                   dep_scheduled="2026-11-20T19:00", fetched_at=ARRIVES.timestamp()))
        (s,) = flightstatus.overview(self.c, self.jane, EARLY)["statuses"]
        self.assertEqual((s["dep_zone"], s["arr_zone"], s["delay_minutes"], s["fetched_at"]),
                         (seg["start_zone"], seg["end_zone"], 12, "2026-11-21T07:10:00+00:00"))

    def test_without_a_key_there_is_nothing_to_show(self):
        self.book(self.jane)
        self.c.execute(insert(FlightStatus).values(flight_number="EX101", date="2026-11-20", state="delayed", fetched_at=1.0))
        with mock.patch.dict(os.environ, {"RAPIDAPI_KEY": ""}):
            over = flightstatus.overview(self.c, self.jane, EARLY)
        self.assertEqual((over["enabled"], over["statuses"]), (False, []))


class NeverTheBookingTests(Household):
    def rows(self) -> list[dict]:
        self.c.orm.expire_all()
        return [{c.name: getattr(s, c.name) for c in Segment.__table__.columns} for s in self.c.orm.scalars(select(Segment)).all()]

    def test_a_status_never_changes_a_segments_stored_fields(self):
        seg = self.book(self.jane, OUT, travelers=[self.jane.person_id, self.sam.person_id])
        trips.edit_segment(self.c, self.jane, seg["id"], {"details": {"flight_number": "EX 101", "terminal": "8"}})
        before = self.rows()
        for name, now in (("delayed_gate_change", self.when("3h")), ("cancelled", self.when("1h")), ("diverted", self.when("20m")),
                          ("landed", ARRIVES)):
            self.c.execute(FlightStatus.__table__.delete())
            self.fake.answer = (200, fixture(name))
            flightstatus.refresh(self.c, self.jane, seg["id"], now + timedelta(hours=1))
            flightstatus.run_due(self.c, now)
            flightstatus.overview(self.c, self.jane, now)
            self.assertEqual(self.rows(), before, name)
        self.assertEqual(self.cached().state, "landed")   # type: ignore[union-attr]
        self.assertEqual(trips.get_segment(self.c, self.jane, seg["id"])["status"], "confirmed")   # type: ignore[index]
        self.assertEqual(trips.get_segment(self.c, self.jane, seg["id"])["locked_fields"], ["details"])   # type: ignore[index]


class LeakTests(Household):
    def test_a_status_check_sends_only_the_flight_number_and_date(self):
        canaries = ("CANARY-TRAVELLER-Q7ZX", "CANARY-CONFIRM-48213", "CANARY-LOYALTY-99887766")
        self.c.execute(insert(FlightStatus).values(flight_number="ZZ1", date="2026-01-01", state="landed", fetched_at=1.0))
        guest = people.add_guest(self.c, {"display_name": canaries[0], "first_name": "Canary", "legal_name": canaries[0], "aliases": [canaries[0]]})
        loyalty.add(self.c, {"person_id": guest["id"], "kind": "airline", "program": "Example Miles", "number": canaries[2],
                             "expiry": None, "notes": None})
        seg = self.book(self.jane, {**OUT, "confirmation": canaries[1]}, travelers=[self.jane.person_id, guest["id"]])
        self.c.commit()
        with no_leaks(self, *canaries):
            self.assertEqual(flightstatus.run_due(self.c, self.when("3h")), 1)
            flightstatus.refresh(self.c, self.jane, seg["id"], self.when("3h", timedelta(hours=1)))
        self.assertEqual(len(self.fake.calls), 2)
        for call in self.fake.calls:
            self.assertEqual(call["path"], "/flights/number/EX101/2026-11-20")
            self.assertEqual({k.lower() for k in call["headers"]} - {"host", "accept", "user-agent", "connection", "accept-encoding"},
                             {"x-rapidapi-key", "x-rapidapi-host"})


class JobTests(Household):
    def test_the_scheduler_round_checks_the_flights_due_and_reports_a_failure_without_its_text(self):
        self.book(self.jane)
        with mock.patch.object(flightstatus, "run_due", return_value=0) as run:
            jobs.check_flights()
        (_, now), _ = run.call_args
        self.assertIsNotNone(now.tzinfo)
        secret = "CANARY-ROW-5521"
        with mock.patch.object(flightstatus, "run_due", side_effect=RuntimeError(secret)):
            out, err = _captured(jobs.check_flights)
        self.assertNotIn(secret, out + err)
        self.assertIn("RuntimeError", err)

    def test_a_refused_key_stops_pausing_fetching_when_waypoint_starts_again(self):
        flightstatus._pause(self.c, self.when("3h"), "key")
        self.assertIsNotNone(flightstatus.usage(self.c, self.when("3h")).paused)
        flightstatus.forget_key_pause(self.c)
        self.assertIsNone(flightstatus.usage(self.c, self.when("3h")).paused)
        flightstatus._pause(self.c, self.when("3h"), "rate")
        flightstatus.forget_key_pause(self.c)
        self.assertEqual(flightstatus.usage(self.c, self.when("3h")).paused.reason, "rate")   # type: ignore[union-attr]
        for junk in ("", "{", "[1]"):
            db.set_setting(self.c, sk.FLIGHT_STATUS_PAUSED, junk)
            flightstatus.forget_key_pause(self.c)

    def test_the_jobs_start_and_stop(self):
        stop = threading.Event()
        stop.set()
        with mock.patch.object(jobs, "sweep_lapsed") as sweep, mock.patch.object(jobs, "check_flights") as check, \
                mock.patch.object(jobs, "send_reminders") as remind:
            for t in jobs.start(stop):
                t.join(5)
                self.assertFalse(t.is_alive())
        sweep.assert_called_once()
        check.assert_called_once()
        remind.assert_called_once()


class StatusRoutes(RouteCase):
    env = {**RouteCase.env, "RAPIDAPI_KEY": KEY}

    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(FlightStatus.__table__.delete())
            for k in (sk.FLIGHT_STATUS_CALLS, sk.FLIGHT_STATUS_MONTH, sk.FLIGHT_STATUS_PAUSED):
                db.set_setting(conn, k, None)
        self.mine = self.book("ana", OUT, travelers=[{"person_id": self.person["ana"]}])
        self.hotel = self.book("ana", HOTEL, trip_id=self.mine["trip_id"])
        self.fetch = mock.patch.object(service, "fetch", return_value=status("delayed_gate_change"))
        self.fetched = self.fetch.start()
        self.addCleanup(self.fetch.stop)

    def test_the_list_has_the_month_and_the_statuses_of_the_viewers_flights(self):
        with db.session() as conn:
            conn.execute(insert(FlightStatus).values(flight_number="EX101", date="2026-11-20", state="delayed", origin="JFK",
                                                     dep_gate="B24", fetched_at=time_now()))
        ana = self.ok("ana", "GET", "/api/flight-status")
        self.assertEqual((ana["enabled"], ana["used"], ana["limit"], ana["paused"]), (True, 0, 400, None))
        self.assertRegex(ana["month"], r"^\d{4}-\d\d$")
        self.assertEqual([(s["segment_id"], s["state"], s["dep_gate"]) for s in ana["statuses"]], [(self.mine["id"], "delayed", "B24")])
        ben = self.ok("ben", "GET", "/api/flight-status")
        self.assertEqual((ben["statuses"], ben["used"], ben["limit"]), ([], 0, 400))

    def test_without_a_key_it_says_so_and_shows_nothing(self):
        with mock.patch.dict(os.environ, {"RAPIDAPI_KEY": ""}):
            got = self.ok("ana", "GET", "/api/flight-status")
            status_code, err = self.call("ana", "POST", f"/api/flight-status/{self.mine['id']}")
        self.assertEqual((got["enabled"], got["statuses"]), (False, []))
        self.assertEqual(status_code, 400)
        self.assertIn("RAPIDAPI_KEY", err["error"])

    def test_refresh_fetches_and_counts(self):
        got = self.ok("ana", "POST", f"/api/flight-status/{self.mine['id']}")
        self.assertEqual([(s["segment_id"], s["state"], s["dep_estimated"]) for s in got["statuses"]],
                         [(self.mine["id"], "delayed", "2026-11-20T19:50")])
        self.assertEqual(got["used"], 1)
        self.fetched.assert_called_once_with("EX101", "2026-11-20", "JFK")
        again = self.ok("ana", "POST", f"/api/flight-status/{self.mine['id']}")
        self.assertEqual((again["used"], len(again["statuses"])), (1, 1))
        self.fetched.assert_called_once()
        self.assertEqual(self.ok("ana", "GET", "/api/flight-status")["used"], 1)

    def test_a_stranger_gets_the_404_of_a_segment_that_isnt_there_and_nothing_is_fetched(self):
        for who in ("ben", "cy"):
            gone = self.call(who, "POST", "/api/flight-status/99999")
            theirs = self.call(who, "POST", f"/api/flight-status/{self.mine['id']}")
            self.assertEqual((theirs, gone), (gone, (404, {"error": "No such segment"})), who)
        self.assertEqual(self.call("ana", "POST", "/api/flight-status/abc")[0], 404)
        self.fetched.assert_not_called()
        self.assertEqual(self.ok("ana", "GET", "/api/flight-status")["used"], 0)

    def test_a_segment_that_isnt_a_flight_is_a_400(self):
        status_code, err = self.call("ana", "POST", f"/api/flight-status/{self.hotel['id']}")
        self.assertEqual(status_code, 400)
        self.assertIn("flight number", err["error"])
        self.fetched.assert_not_called()

    def test_a_service_failure_is_a_502_with_a_fixed_message_never_the_key(self):
        for error in (service.RateLimited("RapidAPI says Waypoint has made too many flight status requests."),
                      service.Refused("RapidAPI didn’t accept RAPIDAPI_KEY."), service.Unavailable("Couldn’t reach the flight status service.")):
            self.fetched.side_effect = error
            with no_leaks(self, KEY, sent_ok=True):
                status_code, err = self.call("ana", "POST", f"/api/flight-status/{self.mine['id']}")
            self.assertEqual((status_code, err), (502, {"error": str(error)}))
            self.assertNotIn(KEY, json.dumps(err))
            with db.session() as conn:
                db.set_setting(conn, sk.FLIGHT_STATUS_PAUSED, None)


def time_now() -> float:
    return datetime.now(UTC).timestamp()


if __name__ == "__main__":
    unittest.main()
