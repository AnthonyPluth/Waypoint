import json
import secrets
import time
from datetime import date, timedelta

from sqlalchemy import delete, insert, select

from waypoint import oidc
from waypoint.domain import offline, people, trips
from waypoint.domain.visibility import Viewer
from waypoint.storage import db, secretbox, stored_mail
from waypoint.storage.models import AuthSession, Mailbox, Person, ReviewItem, StoredMessage, Trip, User
from tests.privacy import no_leaks
from tests.shared import ServerCase

SUBJECT_CANARY = "SUBJECT-CANARY-60418273"
BODY_CANARY = "body-canary-9f3a7c21"
PICTURE_CANARY = b"\x89PNG\r\n\x1a\nCANARY-PICTURE-BYTES-3K8V"
TODAY = date.today()


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


def flight(start: date, end: date | None = None, **more):
    end = end or start
    return {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": f"{start.isoformat()}T19:00",
            "end_local": f"{end.isoformat()}T07:10", "confirmation": "QX7R2M", **more}


def message(message_id: str) -> dict:
    return {"subject": f"{SUBJECT_CANARY} {message_id}", "sender_domain": "air.example", "received": "2026-10-01",
            "text": f"{BODY_CANARY} {message_id}", "html": None, "truncated": False}


class ClearEmailsTests(ServerCase):
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint",
           "OIDC_ALLOWED_EMAILS": "ana@example.com,cy@example.com"}

    def setUp(self):
        with db.session() as conn:
            for table in (Trip, Mailbox, AuthSession, User, Person):
                conn.execute(delete(table))
        self.who = {n: self.sign_in(f"sub-{n}", f"{n}@example.com", n.title()) for n in ("ana", "cy")}
        with db.session() as conn:
            self.person = {n: people.person_for_sub(conn, f"sub-{n}") for n in self.who}
            self.box = int(conn.execute(insert(Mailbox).values(owner_sub="sub-ana", address="ana@gmail.example", token=secretbox.encrypt("t"),
                                                               status="connected", created=1.0)).lastrowid)

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

    def book(self, start: date, end: date, **more) -> dict:
        status, got = self.call("ana", "POST", "/api/segments", {**flight(start, end, **more), "travelers": [{"person_id": self.person["ana"]}]})
        self.assertEqual(status, 200, got)
        return got

    def keep(self, message_id: str, *segment_ids: int, pictures=(), review_item=False) -> None:
        with db.session() as conn:
            stored_mail.put(conn, self.box, message_id, message(message_id), 1.0, pictures)   # type: ignore[arg-type]
            for segment_id in segment_ids:
                stored_mail.link(conn, segment_id, self.box, message_id)
            if review_item:
                conn.execute(insert(ReviewItem).values(mailbox_id=self.box, message_id=message_id, sender_domain="air.example",
                                                       reason="no_markup", created=1.0))

    def kept(self) -> set[str]:
        with db.session() as conn:
            return {str(m) for m in conn.execute(select(StoredMessage.message_id)).scalars()}

    def trip(self, who, trip_id):
        status, got = self.call(who, "GET", f"/api/trips/{trip_id}")
        self.assertEqual(status, 200, got)
        return got

    def clear(self, who, trip_id):
        return self.call(who, "POST", f"/api/trips/{trip_id}/emails/clear", {})

    def test_it_removes_only_this_trips_messages_and_keeps_what_something_else_still_needs(self):
        out_a, out_b = self.book(days(-20), days(-19)), self.book(days(-18), days(-17), confirmation="OUTB22")
        other = self.book(days(40), days(41), confirmation="NEXT99")
        self.assertEqual(out_a["trip_id"], out_b["trip_id"])
        self.assertNotEqual(out_a["trip_id"], other["trip_id"])
        self.keep("alone", out_a["id"], pictures=[{"type": "image/png", "data": PICTURE_CANARY}])
        self.keep("two-bookings", out_a["id"], out_b["id"])
        self.keep("shared-with-another-trip", out_b["id"], other["id"])
        self.keep("waiting", out_b["id"], review_item=True)
        self.keep("other-only", other["id"])
        trip_id = out_a["trip_id"]
        got = self.trip("ana", trip_id)
        self.assertEqual((got["emails"], got["can_clear_emails"]), (4, True))
        self.assertTrue(all(s["has_email"] for s in got["segments"]))
        with no_leaks(self, SUBJECT_CANARY, BODY_CANARY, "CANARY-PICTURE-BYTES-3K8V"):
            status, body = self.clear("ana", trip_id)
        self.assertEqual((status, body), (200, {"removed": 2}))
        self.assertEqual(self.kept(), {"shared-with-another-trip", "waiting", "other-only"})
        got = self.trip("ana", trip_id)
        self.assertEqual((got["emails"], got["can_clear_emails"]), (0, False))
        self.assertFalse(any(s["has_email"] for s in got["segments"]))
        self.assertTrue(self.trip("ana", other["trip_id"])["segments"][0]["has_email"])
        status, emails = self.call("ana", "GET", f"/api/segments/{other['id']}/emails")
        self.assertEqual(sorted(e["text"] for e in emails["emails"]),
                         [f"{BODY_CANARY} other-only", f"{BODY_CANARY} shared-with-another-trip"])

    def test_images_go_with_the_message(self):
        seg = self.book(days(-20), days(-19))
        self.keep("pictured", seg["id"], pictures=[{"type": "image/png", "data": PICTURE_CANARY}])
        with db.session() as conn:
            self.assertIsNotNone(stored_mail.image_for_segment(conn, seg["id"], 0, 0))
        self.assertEqual(self.clear("ana", seg["trip_id"]), (200, {"removed": 1}))
        with db.session() as conn:
            self.assertIsNone(stored_mail.image_for_segment(conn, seg["id"], 0, 0))
            self.assertEqual(conn.execute(select(StoredMessage.id)).fetchall(), [])

    def test_clearing_twice_removes_nothing_the_second_time(self):
        seg = self.book(days(-20), days(-19))
        self.keep("m", seg["id"])
        self.assertEqual(self.clear("ana", seg["trip_id"]), (200, {"removed": 1}))
        self.assertEqual(self.clear("ana", seg["trip_id"]), (200, {"removed": 0}))

    def test_a_trip_that_has_no_messages_removes_none(self):
        seg = self.book(days(-20), days(-19))
        self.assertEqual(self.trip("ana", seg["trip_id"])["can_clear_emails"], False)
        self.assertEqual(self.clear("ana", seg["trip_id"]), (200, {"removed": 0}))

    def test_a_trip_that_has_not_ended_seven_days_ago_is_refused_and_keeps_its_messages(self):
        for number, (name, start, end) in enumerate((("coming", days(5), days(6)), ("under-way", days(-1), days(2)),
                                                     ("six-days", days(-8), days(-6)))):
            with self.subTest(name):
                seg = self.book(start, end, confirmation=f"TRIP{number}X")
                self.keep(f"m-{name}", seg["id"])
                got = self.trip("ana", seg["trip_id"])
                self.assertEqual((got["emails"], got["can_clear_emails"]), (1, False))
                status, body = self.clear("ana", seg["trip_id"])
                self.assertEqual(status, 400)
                self.assertIn("at least 7 days ago", body["error"])
                self.assertIn(f"m-{name}", self.kept())
                self.assertEqual(self.trip("ana", seg["trip_id"])["emails"], 1)

    def test_seven_days_after_the_end_is_the_first_day_it_works(self):
        seg = self.book(days(-9), days(-7))
        self.keep("m", seg["id"])
        self.assertEqual(self.trip("ana", seg["trip_id"])["can_clear_emails"], True)
        self.assertEqual(self.clear("ana", seg["trip_id"]), (200, {"removed": 1}))

    def test_a_trip_with_no_dates_is_refused(self):
        status, made = self.call("ana", "POST", "/api/trips", {"name": "Someday"})
        self.assertEqual(status, 200, made)
        self.assertEqual(made["can_clear_emails"], False)
        self.assertEqual(self.clear("ana", made["id"])[0], 400)

    def test_someone_who_cannot_see_the_trip_gets_the_same_answer_as_for_one_that_does_not_exist(self):
        seg = self.book(days(-20), days(-19))
        self.keep("m", seg["id"])
        hidden = self.clear("cy", seg["trip_id"])
        missing = self.clear("cy", seg["trip_id"] + 999)
        self.assertEqual(hidden, missing)
        self.assertEqual(hidden[0], 404)
        self.assertEqual(self.kept(), {"m"})
        self.assertEqual(self.clear("ana", seg["trip_id"]), (200, {"removed": 1}))

    def test_the_route_needs_sign_in(self):
        seg = self.book(days(-20), days(-19))
        self.keep("m", seg["id"])
        status, _ = self.req("POST", f"/api/trips/{seg['trip_id']}/emails/clear", {})
        self.assertEqual(status, 401)
        self.assertEqual(self.kept(), {"m"})

    def test_what_is_logged_is_a_count_only(self):
        seg = self.book(days(-20), days(-19), confirmation="LOGCODE77")
        self.keep("m", seg["id"])
        with no_leaks(self, SUBJECT_CANARY, BODY_CANARY, "LOGCODE77"):
            self.clear("ana", seg["trip_id"])


class OfflineAfterClearTests(ServerCase):
    def test_the_device_copy_no_longer_carries_the_removed_messages(self):
        with db.session() as conn:
            for table in (Trip, Mailbox, AuthSession, User, Person):
                conn.execute(delete(table))
            oidc.remember_user(conn, "u-ana", "ana@example.com", "Ana", None)
            ana = Viewer(people.person_for_sub(conn, "u-ana"))
            seg = trips.add_segment(conn, ana, {**flight(days(-2), days(3)), "travelers": [{"person_id": ana.person_id, "name": None}]})
            assert seg is not None
            box = int(conn.execute(insert(Mailbox).values(owner_sub="u-ana", address="ana@gmail.example", token=secretbox.encrypt("t"),
                                                          status="connected", created=1.0)).lastrowid)
            stored_mail.put(conn, box, "m", message("m"), 1.0)   # type: ignore[arg-type]
            stored_mail.link(conn, seg["id"], box, "m")
            self.assertIn(BODY_CANARY, json.dumps(offline.projection(conn, ana, TODAY)))
            with no_leaks(self, SUBJECT_CANARY, BODY_CANARY):
                with self.assertRaises(trips.Invalid):
                    trips.clear_emails(conn, ana, seg["trip_id"], TODAY)
                self.assertEqual(trips.clear_emails(conn, ana, seg["trip_id"], days(10)), 1)
            self.assertNotIn(BODY_CANARY, json.dumps(offline.projection(conn, ana, TODAY)))
            self.assertEqual(offline.projection(conn, ana, TODAY)["messages"], [])
