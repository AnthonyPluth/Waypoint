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
from tests.shared import DbCase, ServerCase, fetch

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
        assert self.ana.person_id is not None
        made = trips.create_trip(self.c, self.ana, {"name": f"Trip {start}", "start_date": start.isoformat(), "end_date": end.isoformat(),
                                                    "people": [self.ana.person_id]})
        return made["id"]

    def ids(self) -> list[int]:
        return offline.saved_trip_ids(self.c, self.ana, TODAY)

    def test_trips_under_way_are_all_saved_soonest_to_end_first(self):
        later = self.trip(days(-2), days(6))
        sooner = self.trip(days(-1), days(3))
        self.assertEqual(self.ids(), [sooner, later])

    def test_a_trip_that_starts_or_ends_today_is_under_way(self):
        starts = self.trip(TODAY, days(2))
        ends = self.trip(days(-3), TODAY)
        self.assertEqual(sorted(self.ids()), sorted([starts, ends]))

    def test_every_trip_starting_within_seven_days_is_saved_nearest_first(self):
        edge = self.trip(days(7), days(9))
        near = self.trip(days(3), days(4))
        self.assertEqual(self.ids(), [near, edge])

    def test_the_next_upcoming_trip_is_saved_however_far_out(self):
        far = self.trip(days(200), days(203))
        self.trip(days(400), days(402))
        self.assertEqual(self.ids(), [far])

    def test_an_eight_day_trip_is_saved_when_it_is_the_next_one(self):
        eight = self.trip(days(8), days(10))
        self.trip(days(30), days(31))
        self.assertEqual(self.ids(), [eight])

    def test_under_way_and_soon_are_saved_and_a_far_trip_only_when_it_is_the_next_one(self):
        under_way = self.trip(days(-1), days(2))
        soon = self.trip(days(5), days(6))
        self.trip(days(30), days(32))
        self.trip(days(90), days(92))
        self.trip(days(-20), days(-15))
        self.assertEqual(self.ids(), [under_way, soon])

    def test_with_only_a_trip_under_way_and_far_ones_the_next_upcoming_is_added(self):
        under_way = self.trip(days(-1), days(2))
        far = self.trip(days(60), days(62))
        self.trip(days(120), days(122))
        self.assertEqual(self.ids(), [under_way, far])

    def test_a_far_next_trip_is_saved_along_with_one_under_way_and_one_soon_when_the_soon_one_is_not_first(self):
        under_way = self.trip(days(-1), days(40))
        soon = self.trip(days(2), days(3))
        self.trip(days(50), days(52))
        self.assertEqual(self.ids(), [under_way, soon])

    def test_trips_already_over_or_without_dates_are_never_saved(self):
        from waypoint.domain import trips
        self.trip(days(-9), days(-1))
        self.assertIsNotNone(trips.create_trip(self.c, self.ana, {"name": "Someday"}))
        self.assertEqual(self.ids(), [])
        self.assertEqual(offline.projection(self.c, self.ana, TODAY), {"trips": []})

    def test_the_cap_keeps_the_next_upcoming_trip(self):
        under_way = [self.trip(days(-1), days(n + 1)) for n in range(offline.MAX_TRIPS + 2)]
        far = self.trip(days(90), days(91))
        got = self.ids()
        self.assertEqual(len(got), offline.MAX_TRIPS)
        self.assertEqual(got[:-1], under_way[:offline.MAX_TRIPS - 1])
        self.assertEqual(got[-1], far)

    def test_the_cap_applies_to_soon_trips_too(self):
        soon = [self.trip(days(1 + n % 6), days(8)) for n in range(offline.MAX_TRIPS + 3)]
        self.assertEqual(len(self.ids()), offline.MAX_TRIPS)
        self.assertTrue(set(self.ids()) <= set(soon))

    def test_a_trip_the_viewer_cannot_see_is_never_saved(self):
        from waypoint.domain import trips
        oidc.remember_user(self.c, "u-ben", "ben@example.com", "Ben", None)
        ben = Viewer(people.person_for_sub(self.c, "u-ben"))
        hidden = trips.add_segment(self.c, ben, {**flight(days(1), days(2)), "travelers": [{"person_id": ben.person_id, "name": None}]})
        assert hidden is not None
        mine = self.trip(days(30), days(31))
        self.assertEqual(self.ids(), [mine])
        self.assertEqual([c["trip"]["id"] for c in offline.projection(self.c, self.ana, TODAY)["trips"]], [mine])


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

    def trip_with(self, who, start: date, end: date, fields: dict, travelers) -> dict:
        status, made = self.call(who, "POST", "/api/trips", {"name": f"Trip {fields['confirmation']}", "start_date": start.isoformat(),
                                                             "end_date": end.isoformat(), "people": [t["person_id"] for t in travelers]})
        self.assertEqual(status, 200, made)
        status, got = self.call(who, "POST", "/api/segments", {**fields, "trip_id": made["id"], "travelers": travelers})
        self.assertEqual(status, 200, got)
        return got

    def keep_message(self, segment_id: int, text: str, pictures=()) -> None:
        with db.session() as conn:
            box = conn.execute(insert(Mailbox).values(owner_sub="sub-ana", address=f"ana{segment_id}@gmail.example", token=secretbox.encrypt("t"),
                                                      status="connected", created=1.0)).lastrowid
            stored_mail.put(conn, box, f"m{segment_id}", {"subject": "Your itinerary", "sender_domain": "air.example", "received": "2026-10-01",
                                                          "text": text, "html": f"<p>{text}</p>", "truncated": False}, 1.0, pictures)   # type: ignore[arg-type]
            stored_mail.link(conn, segment_id, box, f"m{segment_id}")   # type: ignore[arg-type]

    def test_the_route_needs_sign_in(self):
        status, _ = self.req("GET", "/api/offline")
        self.assertEqual(status, 401)

    def test_only_a_trip_the_person_is_on_is_returned_and_nothing_for_anyone_else(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.book("cy", flight(days(2), days(4), confirmation="CY0000"), [{"person_id": self.person["cy"]}])
        mine = self.ok("ana")
        [only] = mine["trips"]
        self.assertEqual(only["trip"]["id"], seg["trip_id"])
        self.assertEqual([s["confirmation"] for s in only["trip"]["segments"]], ["QX7R2M"])
        self.assertEqual(self.ok("cy")["trips"][0]["trip"]["segments"][0]["confirmation"], "CY0000")
        self.assertEqual(self.ok("ben"), {"trips": []})

    def test_adding_a_traveller_shares_the_trip_and_taking_them_off_the_trip_takes_it_back(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.assertEqual(self.ok("ben")["trips"], [])
        self.call("ana", "POST", f"/api/segments/{seg['id']}", {"travelers": [{"person_id": self.person["ana"]}, {"person_id": self.person["ben"]}]})
        self.assertEqual([c["trip"]["id"] for c in self.ok("ben")["trips"]], [seg["trip_id"]])
        self.call("ana", "POST", f"/api/segments/{seg['id']}", {"travelers": [{"person_id": self.person["ana"]}]})
        self.assertEqual([c["trip"]["id"] for c in self.ok("ben")["trips"]], [seg["trip_id"]])
        self.call("ana", "POST", f"/api/trips/{seg['trip_id']}", {"people": [self.person["ana"]]})
        self.assertEqual(self.ok("ben")["trips"], [])

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
        self.assertEqual(sorted(t["name"] for t in body["trips"][0]["trip"]["segments"][0]["travelers"]), ["Ana", "DOE/GUEST MR"])

    def test_the_pictures_of_a_stored_message_are_never_part_of_the_device_copy(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.keep_message(seg["id"], MESSAGE_CANARY, [{"type": "image/png", "data": b"\x89PNG\r\n\x1a\nCANARY-PICTURE-BYTES-7N4D"}])
        got = self.ok("ana")
        [email] = got["trips"][0]["messages"][0]["emails"]
        self.assertEqual(email["images"], 0)
        self.assertNotIn("CANARY-PICTURE-BYTES-7N4D", json.dumps(got))
        self.assertNotIn("Q0FOQVJZLVBJQ1RVUkU", json.dumps(got))
        status, _headers, raw = fetch(self.base, "GET", f"/api/segments/{seg['id']}/emails/0/images/0", None, self.who["ana"])
        self.assertEqual((status, raw), (200, b"\x89PNG\r\n\x1a\nCANARY-PICTURE-BYTES-7N4D"))

    def test_the_stored_message_is_in_the_reply_only_for_someone_who_can_see_the_booking(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.keep_message(seg["id"], MESSAGE_CANARY)
        got = self.ok("ana")
        self.assertEqual([(m["segment_id"], [e["text"] for e in m["emails"]]) for m in got["trips"][0]["messages"]], [(seg["id"], [MESSAGE_CANARY])])
        self.assertEqual(got["trips"][0]["messages"][0]["emails"][0]["sender_domain"], "air.example")
        self.assertIn(f"<p>{MESSAGE_CANARY}</p>", got["trips"][0]["messages"][0]["emails"][0]["html"])
        self.assertNotIn(MESSAGE_CANARY, json.dumps(self.ok("ben")))
        self.assertNotIn(MESSAGE_CANARY, json.dumps(self.ok("cy")))

    def test_several_emails_on_one_booking_are_all_in_the_device_copy_newest_first(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        with db.session() as conn:
            box = conn.execute(insert(Mailbox).values(owner_sub="sub-ana", address="ana-many@gmail.example", token=secretbox.encrypt("t"),
                                                      status="connected", created=1.0)).lastrowid
            for n, created in ((1, 10.0), (2, 30.0), (3, 20.0)):
                stored_mail.put(conn, box, f"many{n}", {"subject": f"Email {n}", "sender_domain": "air.example", "received": "2026-10-01",
                                                        "text": f"{MESSAGE_CANARY} {n}", "html": None, "truncated": False}, created)   # type: ignore[arg-type]
                stored_mail.link(conn, seg["id"], box, f"many{n}")   # type: ignore[arg-type]
        got = self.ok("ana")
        self.assertEqual([e["subject"] for e in got["trips"][0]["messages"][0]["emails"]], ["Email 2", "Email 3", "Email 1"])
        self.assertEqual([e["images"] for e in got["trips"][0]["messages"][0]["emails"]], [0, 0, 0])
        self.assertNotIn(MESSAGE_CANARY, json.dumps(self.ok("ben")))

    def test_a_booking_with_no_stored_message_has_no_entry(self):
        self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.assertEqual(self.ok("ana")["trips"][0]["messages"], [])

    def test_times_keep_their_zones(self):
        self.book("ana", flight(days(1), days(2), destination="LHR", origin="JFK"), [{"person_id": self.person["ana"]}])
        seg = self.ok("ana")["trips"][0]["trip"]["segments"][0]
        self.assertEqual((seg["start_local"][11:], seg["start_zone"], seg["end_zone"]), ("19:00", "America/New_York", "Europe/London"))

    def test_reading_the_projection_logs_and_sends_nothing(self):
        seg = self.book("ana", flight(days(1), days(3)), [{"person_id": self.person["ana"]}])
        self.keep_message(seg["id"], MESSAGE_CANARY)
        with no_leaks(self, MESSAGE_CANARY):
            self.ok("ana")

    def test_several_trips_come_back_each_with_only_its_own_messages_and_no_canary_numbers(self):
        with db.session() as conn:
            loyalty.add(conn, {"person_id": self.person["ana"], "kind": "airline", "program": "Example Air", "number": AIRLINE_CANARY,
                               "expiry": None, "notes": None})
            loyalty.add(conn, {"person_id": self.person["ana"], "kind": "known_traveler", "program": "TSA PreCheck", "number": TRAVELER_CANARY,
                               "expiry": None, "notes": None})
        ana = [{"person_id": self.person["ana"]}]
        now = self.trip_with("ana", days(-1), days(2), flight(days(-1), days(2), confirmation="NOW001"), ana)
        soon = self.trip_with("ana", days(4), days(5), flight(days(4), days(5), confirmation="SOON01"), ana)
        far = self.trip_with("ana", days(100), days(103), flight(days(100), days(103), confirmation="FAR001"), ana)
        farther = self.trip_with("ana", days(200), days(203), flight(days(200), days(203), confirmation="FARTHER"), ana)
        hidden = self.trip_with("cy", days(3), days(4), flight(days(3), days(4), confirmation="HIDDEN"), [{"person_id": self.person["cy"]}])
        for n, seg in enumerate((now, soon, far, farther, hidden)):
            self.keep_message(seg["id"], f"{MESSAGE_CANARY}-{n}")
        got = self.ok("ana")
        self.assertEqual([c["trip"]["id"] for c in got["trips"]], [now["trip_id"], soon["trip_id"]])
        for copy, seg in zip(got["trips"], (now, soon), strict=True):
            self.assertEqual([m["segment_id"] for m in copy["messages"]], [seg["id"]])
        text = json.dumps(got)
        for gone in (f"{MESSAGE_CANARY}-2", f"{MESSAGE_CANARY}-3", f"{MESSAGE_CANARY}-4", "FAR001", "FARTHER", "HIDDEN", AIRLINE_CANARY, TRAVELER_CANARY):
            self.assertNotIn(gone, text)
        self.assertNotIn(MESSAGE_CANARY, json.dumps(self.ok("ben")))
        self.assertEqual([c["trip"]["id"] for c in self.ok("cy")["trips"]], [hidden["trip_id"]])
        with no_leaks(self, MESSAGE_CANARY):
            self.ok("ana")

    def test_the_next_upcoming_trip_far_out_is_saved_alone_with_its_messages(self):
        ana = [{"person_id": self.person["ana"]}]
        far = self.trip_with("ana", days(100), days(103), flight(days(100), days(103), confirmation="FAR001"), ana)
        self.trip_with("ana", days(200), days(203), flight(days(200), days(203), confirmation="FARTHER"), ana)
        self.keep_message(far["id"], MESSAGE_CANARY)
        got = self.ok("ana")
        self.assertEqual([c["trip"]["id"] for c in got["trips"]], [far["trip_id"]])
        self.assertEqual([e["text"] for e in got["trips"][0]["messages"][0]["emails"]], [MESSAGE_CANARY])
        self.assertNotIn("FARTHER", json.dumps(got))

    def test_the_route_is_a_get_and_the_only_one(self):
        self.assertEqual([m for m, p, *_ in ROUTES if p == "/api/offline"], ["GET"])


if __name__ == "__main__":
    unittest.main()
