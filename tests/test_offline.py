import json
import secrets
import time
import unittest
from datetime import date, timedelta

from sqlalchemy import delete, insert

from waypoint import oidc
from waypoint.domain import loyalty, offline, people
from waypoint.domain.visibility import Viewer
from waypoint.server import ROUTES
from waypoint.storage import db, secretbox, stored_mail
from waypoint.storage.models import AuthSession, Mailbox, Person, Trip, User
from tests.privacy import no_leaks
from tests.shared import DbCase, ServerCase

MESSAGE_CANARY = "message-canary-7c41e9"
AIRLINE_CANARY = "AIRLINE-CANARY-82913746"
TRAVELER_CANARY = "TRAVELER-CANARY-55120987"
TODAY = date.today()


def flight(start: date, end: date | None = None, **more):
    end = end or start
    return {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": f"{start.isoformat()}T19:00",
            "end_local": f"{end.isoformat()}T07:10", "confirmation": "QX7R2M", **more}


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


class Selection(DbCase):
    def setUp(self):
        super().setUp()
        oidc.remember_user(self.c, "u-ana", "ana@example.com", "Ana", None)
        self.ana = Viewer(people.person_for_sub(self.c, "u-ana"))

    def trip(self, start: date, end: date) -> int:
        from waypoint.domain import trips
        seg = trips.add_segment(self.c, self.ana, {**flight(start, end), "travelers": [{"person_id": self.ana.person_id, "name": None}]})
        assert seg is not None
        return seg["trip_id"]

    def test_the_trip_under_way_is_current(self):
        under_way = self.trip(days(-2), days(3))
        self.trip(days(2), days(4))
        self.assertEqual(offline.current_trip_id(self.c, self.ana, TODAY), under_way)

    def test_a_trip_that_starts_or_ends_today_is_under_way(self):
        starts = self.trip(TODAY, days(2))
        self.assertEqual(offline.current_trip_id(self.c, self.ana, TODAY), starts)

    def test_else_the_nearest_trip_starting_within_seven_days(self):
        self.trip(days(40), days(43))
        soon = self.trip(days(7), days(9))
        self.assertEqual(offline.current_trip_id(self.c, self.ana, TODAY), soon)
        nearer = self.trip(days(3), days(4))
        self.assertEqual(offline.current_trip_id(self.c, self.ana, TODAY), nearer)

    def test_a_trip_eight_days_out_or_already_over_is_not_current(self):
        self.trip(days(8), days(10))
        self.trip(days(-9), days(-1))
        self.assertIsNone(offline.current_trip_id(self.c, self.ana, TODAY))
        self.assertEqual(offline.projection(self.c, self.ana, TODAY), {"trip": None, "messages": []})

    def test_a_trip_without_dates_is_never_current(self):
        from waypoint.domain import trips
        made = trips.create_trip(self.c, self.ana, {"name": "Someday"})
        self.assertIsNotNone(made)
        self.assertIsNone(offline.current_trip_id(self.c, self.ana, TODAY))


class OfflineRouteTests(ServerCase):
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint",
           "OIDC_ALLOWED_EMAILS": "ana@example.com,ben@example.com,cy@example.com"}

    def setUp(self):
        with db.session() as conn:
            for table in (Trip, Mailbox, AuthSession, User, Person):
                conn.execute(delete(table))
        self.who = {n: self.sign_in(f"sub-{n}", f"{n}@example.com", n.title()) for n in ("ana", "ben", "cy")}
        with db.session() as conn:
            self.person = {n: people.person_for_sub(conn, f"sub-{n}") for n in self.who}

    def sign_in(self, sub, email, name) -> dict:
        token = secrets.token_urlsafe(24)
        now = time.time()
        with db.session() as conn:
            conn.execute(insert(AuthSession).values(token_hash=oidc._hash(token), sub=sub, email=email, name=name,
                                                    created=now, expires=now + 86400))
            oidc.remember_user(conn, sub, email, name, None, now)
        return {"Cookie": f"waypoint_session={token}"}

    def call(self, who, method, path, body=None):
        return self.req(method, path, body if method != "GET" else None, self.who[who])

    def ok(self, who, path="/api/offline"):
        status, got = self.call(who, "GET", path)
        self.assertEqual(status, 200, got)
        return got

    def book(self, who, fields, travelers):
        status, got = self.call(who, "POST", "/api/segments", {**fields, "travelers": travelers})
        self.assertEqual(status, 200, got)
        return got

    def keep_message(self, segment_id: int, text: str) -> None:
        with db.session() as conn:
            box = conn.execute(insert(Mailbox).values(owner_sub="sub-ana", address=f"ana{segment_id}@gmail.example", token=secretbox.encrypt("t"),
                                                      status="connected", created=1.0)).lastrowid
            stored_mail.put(conn, box, f"m{segment_id}", {"subject": "Your itinerary", "sender_domain": "air.example", "received": "2026-10-01",
                                                          "text": text, "html": f"<p>{text}</p>", "truncated": False}, 1.0)   # type: ignore[arg-type]
            stored_mail.link(conn, segment_id, box, f"m{segment_id}")   # type: ignore[arg-type]

    def test_the_route_needs_sign_in(self):
        status, _ = self.req("GET", "/api/offline")
        self.assertEqual(status, 401)

    def test_only_a_trip_the_person_is_on_is_returned_and_nothing_for_anyone_else(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.book("cy", flight(days(2), days(4), confirmation="CY0000"), [{"person_id": self.person["cy"]}])
        mine = self.ok("ana")
        self.assertEqual(mine["trip"]["id"], seg["trip_id"])
        self.assertEqual([s["confirmation"] for s in mine["trip"]["segments"]], ["QX7R2M"])
        self.assertEqual(self.ok("cy")["trip"]["segments"][0]["confirmation"], "CY0000")
        self.assertEqual(self.ok("ben"), {"trip": None, "messages": []})

    def test_adding_a_traveller_shares_the_trip_and_removing_one_takes_it_back(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.assertIsNone(self.ok("ben")["trip"])
        self.call("ana", "POST", f"/api/segments/{seg['id']}", {"travelers": [{"person_id": self.person["ana"]}, {"person_id": self.person["ben"]}]})
        self.assertEqual(self.ok("ben")["trip"]["id"], seg["trip_id"])
        self.call("ana", "POST", f"/api/segments/{seg['id']}", {"travelers": [{"person_id": self.person["ana"]}]})
        self.assertIsNone(self.ok("ben")["trip"])

    def test_no_loyalty_or_known_traveler_number_is_in_the_reply(self):
        with db.session() as conn:
            loyalty.add(conn, {"person_id": self.person["ana"], "kind": "airline", "program": "Example Air", "number": AIRLINE_CANARY,
                               "expiry": None, "notes": None})
            loyalty.add(conn, {"person_id": self.person["ana"], "kind": "known_traveler", "program": "TSA PreCheck", "number": TRAVELER_CANARY,
                               "expiry": None, "notes": None})
        self.book("ana", flight(days(1), days(3), provider="Example Air", details={"flight_number": "XA12"}),
                  [{"person_id": self.person["ana"]}, {"person_id": None, "name": "DOE/GUEST MR"}])
        status, body = self.call("ana", "GET", "/api/offline")
        self.assertEqual(status, 200)
        text = json.dumps(body)
        self.assertNotIn(AIRLINE_CANARY, text)
        self.assertNotIn(TRAVELER_CANARY, text)
        self.assertEqual(sorted(t["name"] for t in body["trip"]["segments"][0]["travelers"]), ["Ana", "DOE/GUEST MR"])

    def test_the_stored_message_is_in_the_reply_only_for_someone_who_can_see_the_booking(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.keep_message(seg["id"], MESSAGE_CANARY)
        got = self.ok("ana")
        self.assertEqual([(m["segment_id"], [e["text"] for e in m["emails"]]) for m in got["messages"]], [(seg["id"], [MESSAGE_CANARY])])
        self.assertEqual(got["messages"][0]["emails"][0]["sender_domain"], "air.example")
        self.assertIn(f"<p>{MESSAGE_CANARY}</p>", got["messages"][0]["emails"][0]["html"])
        self.assertNotIn(MESSAGE_CANARY, json.dumps(self.ok("ben")))
        self.assertNotIn(MESSAGE_CANARY, json.dumps(self.ok("cy")))

    def test_a_booking_with_no_stored_message_has_no_entry(self):
        self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.assertEqual(self.ok("ana")["messages"], [])

    def test_times_keep_their_zones(self):
        self.book("ana", flight(days(1), days(2), destination="LHR", origin="JFK"), [{"person_id": self.person["ana"]}])
        seg = self.ok("ana")["trip"]["segments"][0]
        self.assertEqual((seg["start_local"][11:], seg["start_zone"], seg["end_zone"]), ("19:00", "America/New_York", "Europe/London"))

    def test_reading_the_projection_logs_and_sends_nothing(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.keep_message(seg["id"], MESSAGE_CANARY)
        with no_leaks(self, MESSAGE_CANARY):
            self.ok("ana")

    def test_the_route_is_a_get_and_the_only_one(self):
        self.assertEqual([m for m, p, *_ in ROUTES if p == "/api/offline"], ["GET"])


if __name__ == "__main__":
    unittest.main()
