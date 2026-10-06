import base64
import json
import os
import threading
import time
import unittest
import urllib.parse
from datetime import date
from pathlib import Path
from unittest import mock

from sqlalchemy import insert, select, update

from tests.privacy import no_leaks
from tests.shared import TODAY, DbCase
from tests.test_gmail import CLIENT_ID, CLIENT_SECRET, FakeGoogle, Google, GoogleCase
from waypoint import oidc
from waypoint.domain import loyalty, people, trips
from waypoint.domain.mail import extract, ingest, query, review, scan
from waypoint.domain.visibility import Viewer
from waypoint.providers import gmail
from waypoint.server import jobs
from waypoint.storage import db, secretbox, stored_mail
from waypoint.storage.models import IgnoredSender, Mailbox, ReviewItem, ScannedMessage, Segment, SegmentMessage, SegmentTraveler, StoredMessage

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
NOW = 1_790_000_000.0
REFRESH, ADDRESS = "refresh-jane-1", "jane@gmail.example"
CANARIES = ("CANARY-BODY-FLIGHT-JSONLD-7Q2X", "CANARY-BODY-FLIGHT-MICRODATA-3K8D", "CANARY-BODY-HOTEL-5R1M",
            "CANARY-BODY-CAR-9T4V", "CANARY-BODY-TRAIN-2W6Z", "CANARY-BODY-NOMARKUP-6H9C", "CANARY-BODY-INCOMPLETE-4N7P",
            "CANARY-SUBJECT-NOMARKUP-8B3F", "CANARY-BODY-UTCLOCAL-4G8J", "CANARY-BODY-UTCCONV-6M2W", "CANARY-BODY-UTCNONE-9P5D",
            "CANARY-BODY-OFFSET-3C7H", "CANARY-BODY-OVERNIGHT-8R4Y")
UTC_FIXTURES = ("utc_marked_local_in_text", "utc_marked_converted_in_text", "utc_marked_no_times_in_text", "offset_marked_times",
                "utc_marked_overnight")


def eml(name: str) -> bytes:
    return (FIXTURES / f"{name}.eml").read_bytes()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class FakeGmail(FakeGoogle):

    def do_GET(self):
        g = self.server
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if url.path == "/gmail/v1/users/me/profile" and token in g.owners:
            return self.reply({"emailAddress": g.owners[token], "historyId": g.history_id})
        if not url.path.startswith("/gmail/v1/users/me/"):
            return super().do_GET()
        if token not in g.owners:
            return self.reply({"error": "unauthorized"}, 401)
        rest = url.path.removeprefix("/gmail/v1/users/me")
        if rest == "/messages":
            g.queries.append(q["q"])
            page = int(q.get("pageToken") or 0)
            ids = g.matches[page * g.page:(page + 1) * g.page]
            out = {"messages": [{"id": i, "threadId": i} for i in ids]} if ids else {"resultSizeEstimate": 0}
            if (page + 1) * g.page < len(g.matches):
                out["nextPageToken"] = str(page + 1)
            return self.reply(out)
        if rest.startswith("/messages/"):
            mid = urllib.parse.unquote(rest.removeprefix("/messages/"))
            assert q.get("format") == "raw", "a scan reads the raw message, nothing more"
            g.fetched.append(mid)
            if mid == g.fail_on:
                return self.reply({"error": "backend_error"}, 500)
            if mid not in g.mail:
                return self.reply({"error": "not_found"}, 404)
            return self.reply({"id": mid, "raw": b64(g.mail[mid])})
        if rest == "/history":
            g.history_calls.append(q)
            if g.history_gone:
                return self.reply({"error": "not_found"}, 404)
            return self.reply({"history": [{"messagesAdded": [{"message": {"id": i}} for i in g.added]}]})
        return self.reply({"error": "not_found"}, 404)


def reset(g) -> None:
    g.grants.clear(); g.live.clear(); g.revoked.clear(); g.calls.clear(); g.owners.clear(); g.emails.clear()
    g.refresh_fails, g.revoke_status = None, 200
    g.mail, g.matches, g.added, g.queries, g.fetched, g.history_calls = {}, [], [], [], [], []
    g.fail_on, g.history_gone, g.history_id, g.page = None, False, "200", 100


def serve_fake_gmail(case) -> Google:
    g = Google(FakeGmail)
    threading.Thread(target=g.serve_forever, daemon=True).start()
    case.addClassCleanup(g.server_close)
    case.addClassCleanup(g.shutdown)
    patch = mock.patch.object(gmail, "HOSTS", g.hosts())
    patch.start()
    case.addClassCleanup(patch.stop)
    return g


def guest(name, *aliases):
    return {"display_name": name, "first_name": None, "legal_name": None, "aliases": list(aliases)}


class ScanCase(DbCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET})
        env.start()
        cls.addClassCleanup(env.stop)
        cls.google = serve_fake_gmail(cls)

    def setUp(self):
        super().setUp()
        reset(self.google)
        scan._notices.clear()
        for sub, name in (("u-jane", "Jane Doe"), ("u-sam", "Sam Doe")):
            oidc.remember_user(self.c, sub, f"{sub}@example.com", name, None)
        self.jane = Viewer(people.person_for_sub(self.c, "u-jane"))
        self.sam = Viewer(people.person_for_sub(self.c, "u-sam"))
        self.mia = people.add_guest(self.c, guest("Mia Rose Doe", "DOE/MIA MISS"))["id"]
        assert self.jane.person_id is not None
        loyalty.add(self.c, {"person_id": self.jane.person_id, "kind": "airline", "program": "Other", "number": "FXLOY-4400123",
                             "expiry": None, "notes": None})
        self.mailbox = self.connect("u-jane", ADDRESS, REFRESH)

    def connect(self, owner, address, refresh) -> int:
        self.google.live.add(refresh)
        self.google.emails[refresh] = address
        self.c.execute(insert(Mailbox).values(owner_sub=owner, address=address, token=secretbox.encrypt(refresh),
                                              history_id="100", status="connected", created=1.0))
        mailbox_id = self.c.execute(select(Mailbox.id).where(Mailbox.address == address)).scalar()
        self.c.commit()
        return int(mailbox_id)

    def put(self, *names, as_id=None) -> list[str]:
        ids = []
        for name in names:
            mid = as_id or f"msg-{name}"
            self.google.mail[mid] = eml(name)
            if mid not in self.google.matches:
                self.google.matches.append(mid)
                self.google.added.append(mid)
            ids.append(mid)
        return ids

    def add_mail(self, mid: str, raw: bytes) -> None:
        self.google.mail[mid] = raw
        self.google.matches.append(mid)
        self.google.added.append(mid)

    def scan(self, mailbox_id=None, now=NOW, today=TODAY, again=False) -> scan.Result:
        return scan.scan(mailbox_id or self.mailbox, now, today, again)

    def read(self, fn):
        with db.session() as conn:
            return fn(conn)

    def segments(self, viewer=None) -> list[trips.SegmentOut]:
        who = viewer or self.jane
        return self.read(lambda conn: [s for t in trips.listing(conn, who) for s in t["segments"]])

    def row(self) -> dict:
        return self.read(lambda conn: db.rows(conn.execute(select(Mailbox).where(Mailbox.id == self.mailbox)))[0])

    def scanned(self) -> dict[str, str]:
        return self.read(lambda conn: dict(conn.execute(select(ScannedMessage.message_id, ScannedMessage.outcome)).fetchall()))

    def items(self, owner="u-jane") -> list[review.ItemOut]:
        return self.read(lambda conn: review.listing(conn, owner))


class SearchTests(ScanCase):
    def test_the_search_is_for_known_senders_and_booking_words_without_promotions_since_18_months_ago(self):
        self.assertEqual(self.scan().state, "done")
        [q] = self.google.queries
        self.assertTrue(q.startswith("((from:(aa.com OR delta.com"), q)
        self.assertIn('(confirmation OR itinerary OR reservation OR "e-ticket" OR booking OR cruise OR sailing)', q)
        self.assertIn("-category:promotions", q)
        self.assertTrue(q.endswith("after:2025/03/23"), q)
        self.assertLess(len(q), 3000)

    def test_the_search_covers_booking_agencies_travel_portals_and_cruise_lines(self):
        senders = set(query.SENDERS)
        self.assertLessEqual({"chasetravel.com", "capitalonetravel.com", "perk.com", "amextravel.com", "expedia.com"}, senders)
        self.assertLessEqual({"carnival.com", "royalcaribbean.com", "ncl.com", "princess.com", "vikingcruises.com", "disneycruise.com"}, senders)

    def test_each_branch_of_the_search_is_grouped_so_gmail_cant_read_the_or_across_them(self):
        q = query.build(date(2026, 1, 31))
        words = "(" + query._any(query.WORDS) + ")"
        subject = "(" + query._any(query.BANK_SUBJECT_WORDS) + ")"
        senders, banks = " OR ".join(query.SENDERS), " OR ".join(query.BANK_SENDERS)
        self.assertTrue(q.startswith(f"((from:({senders}) {words}) OR (from:({banks}) subject:{subject} {words})) -category:promotions"), q)

    def test_a_banks_mail_has_to_be_about_travel_to_be_searched(self):
        q = query.build(date(2026, 1, 31))
        self.assertIn(") OR (from:(chase.com OR capitalone.com OR americanexpress.com OR aexp.com) subject:(travel OR trip OR flight OR hotel OR cruise OR itinerary OR \"e-ticket\") (", q)
        self.assertNotIn("chase.com", query.SENDERS)
        self.assertNotIn("capitalone.com", query.SENDERS)

    def test_a_senders_ignored_by_its_owner_are_left_out_of_the_search(self):
        self.read(lambda conn: __import__("waypoint.domain.mail.review", fromlist=["x"]))
        self.assertEqual(query.build(date(2026, 1, 31), ["b.example", "a.example", "a.example"]).count("-from:"), 2)
        self.assertIn(" -from:a.example -from:b.example after:2026/01/31", query.build(date(2026, 1, 31), ["b.example", "a.example"]))

    def test_the_search_is_paged_and_only_ids_are_asked_for(self):
        self.google.page = 2
        ids = self.put("flight_jsonld", "hotel_jsonld", "car_jsonld", "train_jsonld", "no_markup")
        result = self.scan()
        self.assertEqual((result.state, result.messages), ("done", 5))
        self.assertEqual(sorted(self.google.fetched), sorted(ids))
        self.assertEqual(len(self.google.queries), 3)


class FirstScanTests(ScanCase):
    def test_each_kind_of_booking_becomes_a_segment_at_its_places_wall_clock_time(self):
        self.put("flight_jsonld", "hotel_jsonld", "car_jsonld", "train_jsonld")
        result = self.scan()
        self.assertEqual(result, scan.Result("done", None, 4, 4, 0))
        by_kind = {s["kind"]: s for s in self.segments()}
        flight = by_kind["flight"]
        self.assertEqual((flight["start_local"], flight["start_zone"], flight["end_local"], flight["end_zone"]),
                         ("2026-11-20T19:00", "America/New_York", "2026-11-21T07:10", "Europe/London"))
        self.assertEqual((flight["origin"], flight["destination"], flight["provider"], flight["confirmation"], flight["source"]),
                         ("JFK", "LHR", "Example Air", "QX7M2K", "email"))
        self.assertEqual(flight["details"], {"flight_number": "EX 101", "terminal": "7", "seat": "21C", "cabin": "Economy"})
        self.assertEqual((flight["status"], flight["locked_fields"], flight["booked_by"]), ("confirmed", [], self.jane.person_id))
        hotel = by_kind["hotel"]
        self.assertEqual((hotel["start_local"], hotel["start_zone"], hotel["end_local"], hotel["origin"], hotel["destination"]),
                         ("2026-11-21T15:00", "Europe/London", "2026-11-27T10:00", "Harbour Hotel", None))
        car = by_kind["car"]
        self.assertEqual((car["start_local"], car["start_zone"], car["provider"], car["details"]["car_class"]),
                         ("2026-12-08T12:00", "America/Los_Angeles", "Example Rentals", "Compact"))
        train = by_kind["train"]
        self.assertEqual((train["start_zone"], train["end_zone"], train["end_local"]), ("Europe/London", "Europe/Paris", "2026-11-23T12:47"))

    def test_the_scan_ends_by_noting_where_it_got_to(self):
        self.put("flight_jsonld")
        self.google.history_id = "321"
        self.scan(now=NOW)
        row = self.row()
        self.assertEqual((row["last_scan"], row["history_id"], row["scan_error"]), (NOW, "321", None))
        self.assertEqual(self.scanned(), {"msg-flight_jsonld": "booking"})

    def test_a_message_is_never_read_twice(self):
        self.put("flight_jsonld", "no_markup")
        self.scan()
        self.assertEqual(sorted(self.google.fetched), ["msg-flight_jsonld", "msg-no_markup"])
        again = self.scan()
        self.assertEqual((again.state, again.messages), ("done", 0))
        self.assertEqual(len(self.google.fetched), 2)
        self.assertEqual((len(self.segments()), len(self.items())), (1, 1))

    def test_a_message_deleted_since_it_was_found_is_skipped_and_remembered(self):
        self.google.matches.append("msg-gone")
        self.put("flight_jsonld")
        self.assertEqual(self.scan().state, "done")
        self.assertEqual(self.scanned()["msg-gone"], "ignored")
        self.assertEqual((len(self.segments()), self.items()), (1, []))


class PassengerTests(ScanCase):
    def test_a_passenger_is_matched_by_loyalty_number_even_under_another_name(self):
        raw = eml("flight_jsonld").replace(b'"name": "Jane Doe"}', b'"name": "J. Q. Public"}')
        self.add_mail("m1", raw)
        self.scan()
        [seg] = self.segments()
        self.assertEqual([(t["person_id"], t["name"]) for t in seg["travelers"]], [(self.jane.person_id, "Jane Doe")])

    def test_a_passenger_is_matched_by_name_or_alias(self):
        self.put("hotel_jsonld", "flight_microdata")
        self.scan()
        names = {s["kind"] + s["origin"]: [t["person_id"] for t in s["travelers"]] for s in self.segments()}
        self.assertEqual(names, {"flightJFK": [self.mia], "hotelHarbour Hotel": [self.jane.person_id]})

    def test_a_name_nobody_matches_stays_who_is_this_and_only_the_booker_sees_it(self):
        self.read(lambda conn: people.edit(conn, self.mia, guest("Mia Rose Doe")))
        self.put("flight_microdata")
        self.scan()
        [seg] = self.segments()
        self.assertEqual([(t["person_id"], t["name"]) for t in seg["travelers"]], [(None, "DOE/MIA MISS")])
        self.assertEqual(self.segments(self.sam), [])
        found = self.read(lambda conn: trips.unmatched(conn, self.jane))
        self.assertEqual([(t.name, s["id"]) for t, s in found], [("DOE/MIA MISS", seg["id"])])
        self.assertEqual(self.read(lambda conn: trips.unmatched(conn, self.sam)), [])

    def test_naming_one_matches_every_booking_with_that_name_and_teaches_the_alias(self):
        self.read(lambda conn: people.edit(conn, self.mia, guest("Mia Rose Doe")))
        self.put("flight_microdata")
        raw = eml("flight_microdata").replace(b"PL4N9R", b"PL4N9S").replace(b"2026-12-08", b"2026-12-20")
        self.add_mail("again", raw)
        self.scan()
        [first, _second] = [t for t, _ in self.read(lambda conn: trips.unmatched(conn, self.jane))]
        with self.assertRaises(trips.Invalid):
            self.read(lambda conn: trips.name_traveler(conn, self.jane, first.id, 9999))
        done = self.read(lambda conn: trips.name_traveler(conn, self.jane, first.id, self.mia))
        self.assertEqual(done, 2)
        self.assertEqual(self.read(lambda conn: trips.unmatched(conn, self.jane)), [])
        self.assertEqual([[t["person_id"] for t in s["travelers"]] for s in self.segments()], [[self.mia], [self.mia]])
        self.assertEqual(self.read(lambda conn: people.get(conn, self.mia))["aliases"], ["DOE/MIA MISS"])
        self.assertEqual(len(self.segments(Viewer(self.mia))), 2)
        self.assertIsNone(self.read(lambda conn: trips.name_traveler(conn, self.jane, first.id, self.mia)))


class MergeTests(ScanCase):
    def changed(self, seg: bytes, **swaps) -> bytes:
        for old, new in swaps.items():
            seg = seg.replace(old.encode(), new.encode())
        return seg

    def test_a_later_email_for_the_same_booking_updates_it_and_marks_it_changed(self):
        self.put("flight_jsonld")
        self.scan()
        later = eml("flight_jsonld").replace(b"2026-11-20T19:00:00-05:00", b"2026-11-20T21:30:00-05:00").replace(b'"21C"', b'"30D"')
        self.add_mail("later", later)
        self.scan(now=NOW + 3600)
        [seg] = self.segments()
        self.assertEqual((seg["start_local"], seg["status"], seg["details"]["seat"]), ("2026-11-20T21:30", "changed", "30D"))

    def test_the_same_email_again_changes_nothing(self):
        self.put("flight_jsonld")
        self.scan()
        copy = eml("flight_jsonld")
        self.add_mail("copy", copy)
        self.assertEqual(self.scan(now=NOW + 3600).bookings, 0)
        [seg] = self.segments()
        self.assertEqual(seg["status"], "confirmed")

    def test_fields_a_person_edited_are_kept(self):
        self.put("flight_jsonld")
        self.scan()
        [seg] = self.segments()
        edited = self.read(lambda conn: trips.edit_segment(conn, self.jane, seg["id"], {"details": {"flight_number": "EX 101", "seat": "1A"}}))
        assert edited is not None
        self.assertEqual(edited["locked_fields"], ["details"])
        later = eml("flight_jsonld").replace(b"2026-11-20T19:00:00-05:00", b"2026-11-20T21:30:00-05:00").replace(b'"21C"', b'"30D"')
        self.add_mail("later", later)
        self.scan(now=NOW + 3600)
        [after] = self.segments()
        self.assertEqual((after["id"], after["details"]["seat"], after["start_local"]), (seg["id"], "1A", "2026-11-20T21:30"))
        self.assertEqual(after["locked_fields"], ["details"])

    def test_a_cancellation_cancels_and_a_person_may_have_locked_the_status(self):
        self.put("flight_jsonld")
        self.scan()
        cancel = eml("flight_jsonld").replace(b"ReservationConfirmed", b"ReservationCancelled")
        self.add_mail("cancel", cancel)
        self.scan(now=NOW + 3600)
        self.assertEqual(self.segments()[0]["status"], "cancelled")

    def test_a_cancellation_after_a_change_cancels_and_keeps_the_changed_time(self):
        self.put("flight_jsonld")
        self.scan()
        later = eml("flight_jsonld").replace(b"2026-11-20T19:00:00-05:00", b"2026-11-20T21:30:00-05:00")
        self.add_mail("later", later)
        self.scan(now=NOW + 3600)
        self.assertEqual(self.segments()[0]["status"], "changed")
        self.add_mail("cancel", later.replace(b"ReservationConfirmed", b"ReservationCancelled"))
        self.scan(now=NOW + 7200)
        [seg] = self.segments()
        self.assertEqual((seg["status"], seg["start_local"]), ("cancelled", "2026-11-20T21:30"))

    def test_the_same_confirmation_in_two_household_mailboxes_is_one_segment_both_owners_see(self):
        self.put("flight_microdata")
        self.scan()
        sam_box = self.connect("u-sam", "sam@gmail.example", "refresh-sam-1")
        self.scan(sam_box)
        self.assertEqual((len(self.segments(self.jane)), len(self.segments(self.sam)), len(self.segments(Viewer(self.mia)))), (1, 1, 1))
        self.assertEqual(self.segments(self.jane)[0]["id"], self.segments(self.sam)[0]["id"])

    def test_a_segment_nobody_got_the_confirmation_for_stays_unseen(self):
        self.put("flight_microdata")
        self.scan()
        self.assertEqual(len(self.segments(self.sam)), 0)

    def test_a_booking_without_a_confirmation_code_is_never_taken_for_another_segment(self):
        no_code = eml("hotel_jsonld").replace(b'  "reservationNumber": "H88231",\n', b"")
        self.assertNotEqual(no_code, eml("hotel_jsonld"))
        self.add_mail("first", no_code)
        self.scan()
        later = no_code.replace(b"2026-11-21T15:00", b"2026-11-21T16:00")
        self.add_mail("second", later)
        self.scan(now=NOW + 3600)
        self.assertEqual([s["confirmation"] for s in self.segments()], [None, None])

    def test_the_same_leg_on_another_date_is_a_new_segment_not_a_rewrite_of_the_old(self):
        self.put("flight_jsonld")
        self.scan()
        repeat = eml("flight_jsonld").replace(b"2026-11-20T19:00:00-05:00", b"2026-12-20T19:00:00-05:00").replace(
            b"2026-11-21T07:10:00+00:00", b"2026-12-21T07:10:00+00:00")
        self.add_mail("repeat", repeat)
        self.scan(now=NOW + 3600)
        segs = self.segments()
        self.assertEqual(sorted((s["start_local"], s["status"]) for s in segs), [("2026-11-20T19:00", "confirmed"), ("2026-12-20T19:00", "confirmed")])

    def moved_by(self, days: int) -> list[str]:
        self.put("flight_jsonld")
        self.scan()
        later = eml("flight_jsonld").replace(b"2026-11-20T19:00:00-05:00", f"2026-11-{20 + days}T19:00:00-05:00".encode()).replace(
            b"2026-11-21T07:10:00+00:00", f"2026-11-{21 + days}T07:10:00+00:00".encode())
        self.add_mail("later", later)
        self.scan(now=NOW + 3600)
        return sorted(s["start_local"] for s in self.segments())

    def test_a_start_three_days_off_is_the_same_booking(self):
        self.assertEqual(self.moved_by(3), ["2026-11-23T19:00"])

    def test_a_start_four_days_off_is_another_segment(self):
        self.assertEqual(self.moved_by(4), ["2026-11-20T19:00", "2026-11-24T19:00"])

    def test_another_flight_number_on_the_same_day_is_another_leg(self):
        self.put("flight_jsonld")
        self.scan()
        other = eml("flight_jsonld").replace(b'"flightNumber": "101"', b'"flightNumber": "909"')
        self.add_mail("other", other)
        self.scan(now=NOW + 3600)
        self.assertEqual(sorted(s["details"]["flight_number"] for s in self.segments()), ["EX 101", "EX 909"])

    def test_a_manual_segment_is_updated_by_the_email_about_it(self):
        seg = self.read(lambda conn: trips.add_segment(conn, self.jane, {
            "kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-11-20T18:00", "end_local": "2026-11-21T06:00",
            "confirmation": "qx7m2k", "provider": None}))
        assert seg is not None
        self.put("flight_jsonld")
        self.scan()
        [after] = self.segments()
        self.assertEqual((after["id"], after["source"], after["start_local"], after["status"]), (seg["id"], "manual", "2026-11-20T19:00", "changed"))


class ReviewTests(ScanCase):
    def test_mail_that_looked_like_a_booking_and_couldnt_be_read_is_queued_for_its_owner_alone(self):
        self.put("no_markup", "incomplete", "flight_jsonld")
        result = self.scan()
        self.assertEqual((result.messages, result.bookings, result.review), (3, 1, 2))
        items = self.items()
        self.assertEqual({(i["reason"], i["sender_domain"], i["received"]) for i in items},
                         {("no_markup", "example-air.example", "2026-10-17"), ("incomplete", "example-air.example", "2026-10-18")})
        nomarkup = next(i for i in items if i["reason"] == "no_markup")
        self.assertEqual((nomarkup["address"], set(nomarkup)), (ADDRESS, {"id", "address", "owner", "mine", "sender_domain", "subject", "has_email", "received", "reason", "gmail_url", "suggestion", "suggestion_error"}))
        self.assertEqual((nomarkup["subject"], nomarkup["has_email"]), ("Your itinerary: CANARY-SUBJECT-NOMARKUP-8B3F", True))
        self.assertEqual((nomarkup["owner"], nomarkup["mine"]), ("Jane Doe", True))
        self.assertEqual(nomarkup["gmail_url"], "https://mail.google.com/mail/?authuser=jane%40gmail.example#all/msg-no_markup")
        self.assertEqual(self.items("u-sam"), [])
        self.assertEqual(self.scanned(), {"msg-no_markup": "unreadable", "msg-incomplete": "unreadable", "msg-flight_jsonld": "booking"})

    def test_the_item_holds_neither_the_subject_nor_the_body_but_the_message_is_kept_encrypted(self):
        self.put("no_markup")
        with no_leaks(self, "CANARY-SUBJECT-NOMARKUP-8B3F", "CANARY-BODY-NOMARKUP-6H9C", database=self.path):
            self.scan()
        stored = self.read(lambda conn: dict(conn.execute(select(ReviewItem)).fetchone()))
        self.assertEqual(sorted(stored), ["created", "id", "mailbox_id", "message_id", "reason", "received", "sender_domain", "suggestion", "suggestion_error"])
        self.assertEqual((stored["sender_domain"], stored["received"]), ("example-air.example", "2026-10-17"))
        sealed = self.read(lambda conn: conn.execute(select(StoredMessage.content)).scalar())
        self.assertTrue(secretbox.is_encrypted(sealed))
        kept = self.read(lambda conn: stored_mail.get(conn, self.mailbox, "msg-no_markup"))
        assert kept
        self.assertEqual((kept["subject"], kept["sender_domain"], kept["received"]), ("Your itinerary: CANARY-SUBJECT-NOMARKUP-8B3F", "example-air.example", "2026-10-17"))
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C", kept["text"])
        assert kept["html"]
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C", kept["html"])

    def test_a_message_that_cannot_be_decoded_is_queued_as_broken(self):
        self.google.mail["bad"] = b""
        self.google.matches.append("bad")
        with mock.patch("waypoint.domain.mail.extract._decode", return_value=None):
            self.scan()
        [item] = self.items()
        self.assertEqual((item["reason"], item["sender_domain"]), ("broken", ""))
        self.assertEqual(self.read(lambda conn: review.ignore_sender(conn, "u-jane", item["id"])), None)

    def test_a_booking_that_cannot_be_placed_is_queued_not_guessed(self):
        unknown = eml("flight_jsonld").replace(b'"iataCode": "JFK"', b'"iataCode": "QQQ"')
        self.add_mail("m1", unknown)
        self.assertEqual(self.scan().review, 1)
        self.assertEqual(self.segments(), [])
        self.assertEqual(self.items()[0]["reason"], "incomplete")

    def test_an_items_message_can_be_fetched_again_from_gmail_for_its_owner_alone(self):
        self.put("no_markup")
        self.scan()
        [item] = self.items()
        with no_leaks(self, "CANARY-BODY-NOMARKUP-6H9C", database=self.path):
            text, html, cut = scan.preview("u-jane", item["id"])
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C", text)
        self.assertNotIn("<", text)
        assert html is not None
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C", html)
        self.assertTrue(html.startswith("<p>"))
        self.assertFalse(cut)
        with self.assertRaises(KeyError):
            scan.preview("u-sam", item["id"])
        with self.assertRaises(KeyError):
            scan.preview("u-jane", 9999)

    def test_a_long_message_is_cut_and_a_deleted_one_says_so(self):
        self.put("no_markup")
        self.scan()
        [item] = self.items()
        with mock.patch.object(extract, "KEPT_LIMIT", 20):
            text, _html, cut = scan.preview("u-jane", item["id"])
        self.assertEqual((len(text), cut), (20, True))
        del self.google.mail["msg-no_markup"]
        with self.assertRaises(gmail.MessageGone):
            scan.preview("u-jane", item["id"])

    def test_asking_the_ai_is_refused_while_it_is_off(self):
        self.put("no_markup")
        self.scan()
        [item] = self.items()
        with self.assertRaises(scan.NoAi):
            scan.suggest_now("u-jane", item["id"], NOW)
        self.assertEqual(self.google.fetched, ["msg-no_markup"])

    def test_the_log_says_what_stopped_messages_being_read_in_fixed_words_and_counts(self):
        unknown = eml("flight_jsonld").replace(b'"iataCode": "JFK"', b'"iataCode": "QQQ"')
        self.add_mail("unknown", unknown)
        other = eml("no_markup").replace(b"<html><body>", b'<html><head><script type="application/ld+json">{"@type":"EmailMessage"}</script></head><body>')
        self.add_mail("other", other)
        self.put("no_markup", "incomplete")
        real = scan.monitoring.log
        with mock.patch.object(scan.monitoring, "log", side_effect=real) as log, no_leaks(self, *CANARIES, database=self.path):
            self.scan()
        said = [c.args[0] for c in log.call_args_list]
        self.assertIn("What stopped messages being read: 1 × arrival time; 1 × departure time; 1 × destination airport; 1 × no structured booking data; 1 × structured data, but no reservation; 1 × unknown airport.", said)

    def test_a_message_with_one_booking_read_and_one_not_does_both(self):
        both = eml("flight_jsonld").replace(b"</script></head>", b"</script><script type=\"application/ld+json\">"
                                            b"{\"@type\":\"LodgingReservation\",\"reservationNumber\":\"H1\"}</script></head>")
        self.add_mail("m1", both)
        result = self.scan()
        self.assertEqual((result.bookings, result.review), (1, 1))
        self.assertEqual((len(self.segments()), self.items()[0]["reason"], self.scanned()["m1"]), (1, "incomplete", "booking"))

    def test_ignoring_a_sender_clears_its_items_and_later_mail_from_it_is_skipped(self):
        self.put("no_markup", "incomplete")
        self.scan()
        first = self.items()[0]
        self.assertIsNone(self.read(lambda conn: review.ignore_sender(conn, "u-sam", first["id"])))
        self.assertEqual(len(self.items()), 2)
        self.assertEqual(self.read(lambda conn: review.ignore_sender(conn, "u-jane", first["id"])), 2)
        self.assertEqual(self.items(), [])
        self.assertEqual(self.read(lambda conn: review.ignored(conn, self.mailbox)), ["example-air.example"])
        self.put("no_markup", as_id="msg-new")
        self.scan(now=NOW + 3600)
        self.assertIn(" -from:example-air.example ", self.google.queries[-1])
        self.assertEqual((self.items(), self.scanned()["msg-new"]), ([], "ignored"))
        self.assertEqual(self.segments(), [])

    def test_dismissing_an_item_leaves_it_remembered_as_read(self):
        self.put("no_markup")
        self.scan()
        [item] = self.items()
        self.assertFalse(self.read(lambda conn: review.dismiss(conn, "u-sam", item["id"])))
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", item["id"])))
        self.assertFalse(self.read(lambda conn: review.dismiss(conn, "u-jane", item["id"])))
        self.scan(now=NOW + 3600)
        self.assertEqual((self.items(), len(self.google.fetched)), ([], 1))
        self.assertEqual(self.read(lambda conn: review.count(conn, "u-jane")), 0)

    def test_disconnecting_takes_what_the_mailbox_kept(self):
        self.put("no_markup")
        self.scan()
        self.assertEqual(self.read(lambda conn: review.count(conn, "u-jane")), 1)
        with mock.patch.object(gmail, "_post", return_value={}):
            self.read(lambda conn: gmail.disconnect(conn, self.mailbox, "u-jane"))
        self.assertEqual((self.items(), self.scanned()), ([], {}))


class ConcurrentScanTests(ScanCase):
    def test_a_second_scan_of_a_mailbox_that_is_being_scanned_is_busy_and_files_nothing_twice(self):
        self.put("flight_jsonld")
        inside, leave = threading.Event(), threading.Event()
        real = gmail.search

        def slow(*args, **kwargs):
            inside.set()
            leave.wait(5)
            return real(*args, **kwargs)
        results: list[scan.Result] = []
        with mock.patch.object(gmail, "search", slow):
            first = threading.Thread(target=lambda: results.append(self.scan()))
            first.start()
            self.assertTrue(inside.wait(5))
            self.assertEqual(self.scan().state, "busy")
            self.assertTrue(scan.running(self.mailbox))
            leave.set()
            first.join(10)
        self.assertEqual([r.state for r in results], ["done"])
        self.assertEqual(len(self.segments()), 1)
        self.assertFalse(scan.running(self.mailbox))

    def test_two_mailboxes_scanned_at_once_with_the_same_confirmation_make_one_segment(self):
        self.put("flight_jsonld")
        sam_box = self.connect("u-sam", "sam@gmail.example", "refresh-sam-1")
        real, lock = ingest.file_booking, threading.Lock()
        inside, most = [0], [0]

        def watched(*args, **kwargs):
            with lock:
                inside[0] += 1
                most[0] = max(most[0], inside[0])
            time.sleep(0.3)
            try:
                return real(*args, **kwargs)
            finally:
                with lock:
                    inside[0] -= 1
        with mock.patch.object(ingest, "file_booking", watched):
            threads = [threading.Thread(target=self.scan, args=(box,)) for box in (self.mailbox, sam_box)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(20)
        self.assertEqual(most[0], 1)
        segs = self.read(lambda conn: conn.orm.scalars(select(Segment)).all())
        self.assertEqual(len(segs), 1)
        self.assertEqual((len(self.segments(self.jane)), len(self.segments(self.sam))), (1, 1))


class LaterScanTests(ScanCase):
    def first(self):
        self.put("flight_jsonld")
        self.google.history_id = "300"
        self.scan(now=NOW)
        self.google.queries.clear()

    def test_a_later_scan_takes_what_history_says_came_among_what_the_search_finds(self):
        self.first()
        self.put("hotel_jsonld", "car_jsonld", "train_jsonld")
        self.google.added = ["msg-hotel_jsonld", "msg-car_jsonld", "msg-not-found-by-search"]
        self.google.history_id = "310"
        result = self.scan(now=NOW + 4 * 3600)
        self.assertEqual((result.state, result.messages), ("done", 2))
        self.assertEqual(self.google.history_calls[-1]["startHistoryId"], "300")
        self.assertEqual(self.google.history_calls[-1]["historyTypes"], "messageAdded")
        self.assertEqual(sorted(self.google.fetched[1:]), ["msg-car_jsonld", "msg-hotel_jsonld"])
        self.assertEqual((self.row()["history_id"], self.row()["last_scan"]), ("310", NOW + 4 * 3600))
        self.assertTrue(self.google.queries[-1].endswith("after:2026-09-19".replace("-", "/")), self.google.queries[-1])

    def test_when_google_no_longer_has_the_history_the_search_by_date_covers_it(self):
        self.first()
        self.put("hotel_jsonld")
        self.google.history_gone = True
        result = self.scan(now=NOW + 4 * 3600)
        self.assertEqual((result.state, result.messages), ("done", 1))
        self.assertEqual(len(self.segments()), 2)

    def test_a_first_scan_that_never_finished_looks_back_the_full_18_months_again(self):
        self.put("flight_jsonld")
        self.google.fail_on = "msg-flight_jsonld"
        self.assertEqual(self.scan().state, "failed")
        self.google.fail_on = None
        self.scan()
        self.assertEqual(len(self.google.history_calls), 0)
        self.assertTrue(all(q.endswith("after:2025/03/23") for q in self.google.queries))


class FailureTests(ScanCase):
    def test_a_scan_that_fails_halfway_keeps_the_last_good_state_and_says_what_failed(self):
        self.put("flight_jsonld", "hotel_jsonld", "car_jsonld")
        self.google.fail_on = "msg-hotel_jsonld"
        self.google.history_id = "999"
        with mock.patch("waypoint.providers.gmail.time.sleep"):
            result = self.scan()
        self.assertEqual((result.state, result.error, result.messages), ("failed", "Google refused a request while reading the mailbox.", 1))
        row = self.row()
        self.assertEqual((row["scan_error"], row["last_scan"], row["history_id"]), ("Google refused a request while reading the mailbox.", None, "100"))
        self.assertEqual(self.scanned(), {"msg-flight_jsonld": "booking"})
        self.assertEqual(len(self.segments()), 1)
        [m] = self.read(lambda conn: gmail.listing(conn, "u-jane"))
        self.assertEqual(m["scan_error"], "Google refused a request while reading the mailbox.")
        self.google.fail_on = None
        self.google.fetched.clear()
        self.assertEqual(self.scan(now=NOW + 3600).state, "done")
        self.assertEqual(sorted(self.google.fetched), ["msg-car_jsonld", "msg-hotel_jsonld"])
        row = self.row()
        self.assertEqual((row["scan_error"], row["last_scan"], row["history_id"]), (None, NOW + 3600, "999"))
        self.assertEqual(len(self.segments()), 3)

    def test_a_failed_scan_leaves_an_earlier_good_state_as_it_was(self):
        self.put("flight_jsonld")
        self.scan(now=NOW)
        good = self.row()
        self.put("hotel_jsonld")
        self.google.fail_on = "msg-hotel_jsonld"
        self.google.added = ["msg-hotel_jsonld"]
        with mock.patch("waypoint.providers.gmail.time.sleep"):
            self.assertEqual(self.scan(now=NOW + 3600).state, "failed")
        row = self.row()
        self.assertEqual((row["last_scan"], row["history_id"]), (good["last_scan"], good["history_id"]))
        self.assertIsNotNone(row["scan_error"])

    def test_google_unreachable_midway_is_a_failure_with_its_own_words(self):
        self.put("flight_jsonld")
        with mock.patch.object(gmail, "_get", side_effect=OSError("down")):
            result = self.scan()
        self.assertEqual((result.state, result.error), ("failed", "Couldn’t reach Google while reading the mailbox."))

    def test_a_bug_while_scanning_says_so_without_the_details(self):
        self.put("flight_jsonld")
        with mock.patch.object(scan.extract, "read", side_effect=RuntimeError("CANARY-BUG-DETAILS-1X9Z")):
            result = self.scan()
        self.assertEqual((result.state, result.error), ("failed", scan.FAILED_GENERALLY))
        self.assertNotIn("CANARY", self.row()["scan_error"])

    def test_a_message_that_cannot_be_filed_is_queued_rather_than_stopping_every_scan(self):
        self.put("flight_jsonld", "hotel_jsonld")
        real = ingest.file_booking
        with mock.patch.object(ingest, "file_booking", side_effect=lambda conn, viewer, b, again=False, touched=None: (
                (_ for _ in ()).throw(RuntimeError("CANARY-FILE-DETAILS-2Y8W")) if b.kind == "flight" else real(conn, viewer, b, again, touched))):
            result = self.scan()
        self.assertEqual((result.state, result.messages, result.bookings, result.review), ("done", 2, 1, 1))
        self.assertEqual(self.scanned(), {"msg-flight_jsonld": "unreadable", "msg-hotel_jsonld": "booking"})
        self.assertEqual(self.items()[0]["reason"], "incomplete")

    def test_a_busy_database_stops_the_scan_to_try_again(self):
        from sqlalchemy.exc import OperationalError
        self.put("flight_jsonld")
        busy = OperationalError("insert", {}, Exception("database is locked"))
        with mock.patch.object(ingest, "file_booking", side_effect=busy), mock.patch.object(db, "is_busy", return_value=True):
            result = self.scan()
        self.assertEqual((result.state, result.error), ("failed", scan.FAILED_GENERALLY))
        self.assertEqual(self.scanned(), {})


class CouldntStartTests(ScanCase):
    def assert_nothing_recorded(self):
        row = self.row()
        self.assertEqual((row["scan_error"], row["last_scan"], row["history_id"]), (None, None, "100"))
        self.assertEqual((self.google.queries, self.scanned()), ([], {}))

    def test_a_connection_google_no_longer_honours_isnt_a_failed_scan(self):
        self.put("flight_jsonld")
        self.google.refresh_fails = "revoked"
        result = self.scan()
        self.assertEqual((result.state, result.error), ("not_started", "Google no longer lets Waypoint read this mailbox."))
        self.assertEqual(self.row()["status"], "reconnect")
        self.assert_nothing_recorded()

    def test_google_unreachable_before_the_scan_starts_isnt_a_failed_scan(self):
        self.google.refresh_fails = "unavailable"
        self.assertEqual(self.scan().state, "not_started")
        self.assert_nothing_recorded()

    def test_an_owner_who_has_no_person_yet_isnt_a_failed_scan(self):
        other = self.connect("u-nobody", "nobody@gmail.example", "refresh-nobody")
        result = self.scan(other)
        self.assertEqual((result.state, result.error), ("not_started", scan.NO_PERSON))
        self.assertEqual(self.google.queries, [])

    def test_why_a_scan_couldnt_start_is_told_until_one_does(self):
        self.google.refresh_fails = "unavailable"
        self.assertEqual(scan.notice(self.mailbox), None)
        self.scan()
        self.assertEqual(scan.notice(self.mailbox), "Google refused to refresh the connection just now.")
        [m] = self.read(lambda conn: gmail.listing(conn, "u-jane"))
        self.assertIsNone(m["scan_error"])
        self.google.refresh_fails = None
        self.scan()
        self.assertIsNone(scan.notice(self.mailbox))

    def test_a_notice_stays_through_a_busy_ask_and_goes_when_the_mailbox_does(self):
        self.google.refresh_fails = "unavailable"
        self.scan()
        with scan._lock:
            scan._running.add(self.mailbox)
        try:
            self.assertEqual(self.scan(), scan.Result("busy"))
        finally:
            with scan._lock:
                scan._running.discard(self.mailbox)
        self.assertIsNotNone(scan.notice(self.mailbox))
        scan.forget(self.mailbox)
        self.assertIsNone(scan.notice(self.mailbox))

    def test_a_mailbox_that_isnt_there_isnt_a_failed_scan(self):
        self.assertEqual(self.scan(9999), scan.Result("not_started", scan.GONE))

    def test_a_scan_already_running_makes_the_next_ask_busy(self):
        with scan._lock:
            scan._running.add(self.mailbox)
        try:
            self.assertTrue(scan.running(self.mailbox))
            self.assertEqual(self.scan(), scan.Result("busy"))
            self.assertFalse(jobs.scan_now(self.mailbox))
        finally:
            with scan._lock:
                scan._running.discard(self.mailbox)
        self.assertFalse(scan.running(self.mailbox))

    def test_a_long_scan_gets_a_new_access_token(self):
        self.put("flight_jsonld", "hotel_jsonld")
        ticks = iter([0, TOKEN_AFTER, TOKEN_AFTER, TOKEN_AFTER * 2, TOKEN_AFTER * 2, TOKEN_AFTER * 2, TOKEN_AFTER * 2])
        with mock.patch.object(scan.time, "monotonic", lambda: next(ticks, TOKEN_AFTER * 3)):
            self.assertEqual(self.scan().state, "done")
        self.assertGreaterEqual(len([c for c in self.google.calls if c[1].get("grant_type") == "refresh_token"]), 2)


TOKEN_AFTER = scan.TOKEN_LIFE + 1


class JobTests(ScanCase):
    def test_the_job_scans_every_connected_mailbox_but_not_one_that_needs_reconnecting(self):
        other = self.connect("u-sam", "sam@gmail.example", "refresh-sam-1")
        self.read(lambda conn: conn.execute(update(Mailbox).where(Mailbox.id == other).values(status="reconnect")))
        self.put("flight_jsonld")
        jobs.scan_mailboxes()
        self.assertEqual(len(self.segments()), 1)
        self.assertEqual(self.read(lambda conn: list(conn.execute(select(ScannedMessage.mailbox_id)).scalars())), [self.mailbox])

    def test_the_job_does_nothing_without_a_google_client_and_survives_a_failure(self):
        self.put("flight_jsonld")
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}):
            jobs.scan_mailboxes()
        self.assertEqual(self.google.queries, [])
        with mock.patch.object(scan, "scan_all", side_effect=RuntimeError("boom")):
            jobs.scan_mailboxes()

    def test_scan_now_scans_in_the_background(self):
        self.put("flight_jsonld")
        self.assertTrue(jobs.scan_now(self.mailbox))
        for _ in range(100):
            if self.row()["last_scan"] is not None and not scan.running(self.mailbox):
                break
            time.sleep(0.1)
        self.assertEqual(len(self.segments()), 1)

    def test_scan_now_survives_a_failure(self):
        with mock.patch.object(scan, "scan", side_effect=RuntimeError("boom")):
            self.assertTrue(jobs.scan_now(self.mailbox))
            time.sleep(0.2)


class UtcMarkedTimesTests(ScanCase):

    def only(self, name) -> trips.SegmentOut:
        self.put(name)
        self.scan()
        [seg] = self.segments()
        return seg

    def test_times_marked_utc_that_the_text_shows_as_local_are_the_airports_wall_clock(self):
        seg = self.only("utc_marked_local_in_text")
        self.assertEqual((seg["start_local"], seg["start_zone"], seg["end_local"], seg["end_zone"], seg["check_times"]),
                         ("2026-12-04T09:00", "America/Chicago", "2026-12-04T11:10", "America/Denver", False))

    def test_times_marked_utc_that_the_text_shows_converted_stay_converted(self):
        seg = self.only("utc_marked_converted_in_text")
        self.assertEqual((seg["start_local"], seg["end_local"], seg["check_times"]), ("2026-12-04T09:00", "2026-12-04T11:10", False))

    def test_times_marked_utc_with_no_times_in_the_text_go_to_review_when_distance_cannot_tell_either(self):
        self.put("utc_marked_no_times_in_text")
        result = self.scan()
        self.assertEqual((result.bookings, result.review, self.segments()), (0, 1, []))

    def test_times_marked_utc_settled_only_by_distance_are_filed_and_flagged(self):
        silent = eml("utc_marked_overnight").replace(b"Departs Los Angeles 10:30 PM", b"").replace(b"Arrives New York 6:55 AM", b"")
        self.add_mail("silent", silent)
        self.scan()
        [seg] = self.segments()
        self.assertEqual((seg["start_local"], seg["end_local"], seg["check_times"]), ("2026-12-10T22:30", "2026-12-11T06:55", True))

    def test_a_real_offset_is_kept_and_not_flagged(self):
        seg = self.only("offset_marked_times")
        self.assertEqual((seg["start_local"], seg["end_local"], seg["check_times"]), ("2026-12-04T09:00", "2026-12-04T11:10", False))

    def test_an_overnight_flight_across_zones_has_a_sane_duration(self):
        seg = self.only("utc_marked_overnight")
        self.assertEqual((seg["start_local"], seg["start_zone"], seg["end_local"], seg["end_zone"]),
                         ("2026-12-10T22:30", "America/Los_Angeles", "2026-12-11T06:55", "America/New_York"))
        hours = (trips.instant(seg["end_local"], seg["end_zone"]) - trips.instant(seg["start_local"], seg["start_zone"])).total_seconds() / 3600
        self.assertTrue(4 < hours < 7, hours)

    def test_every_flight_here_ends_after_it_starts(self):
        self.put(*UTC_FIXTURES)
        self.scan()
        segs = self.segments()
        self.assertEqual(len(segs), 4)
        for s in segs:
            hours = (trips.instant(s["end_local"], s["end_zone"]) - trips.instant(s["start_local"], s["start_zone"])).total_seconds() / 3600
            self.assertTrue(0 < hours < 8, (s["confirmation"], hours))

    def flagged(self) -> trips.SegmentOut:
        silent = eml("utc_marked_overnight").replace(b"Departs Los Angeles 10:30 PM", b"").replace(b"Arrives New York 6:55 AM", b"")
        self.add_mail("silent", silent)
        self.scan()
        [seg] = self.segments()
        self.assertTrue(seg["check_times"])
        return seg

    def test_the_note_stays_until_a_person_edits_or_confirms_the_times(self):
        seg = self.flagged()
        kept = self.read(lambda conn: trips.edit_segment(conn, self.jane, seg["id"], {"details": {"seat": "4B"}}))
        assert kept is not None
        self.assertTrue(kept["check_times"])
        confirmed = self.read(lambda conn: trips.edit_segment(conn, self.jane, seg["id"], {"start_local": seg["start_local"], "end_local": seg["end_local"]}))
        assert confirmed is not None
        self.assertEqual((confirmed["check_times"], confirmed["start_local"]), (False, "2026-12-10T22:30"))
        self.assertTrue({"start_local", "end_local"} <= set(confirmed["locked_fields"]))
        self.scan(now=NOW + 60, again=True)
        [after] = self.segments()
        self.assertEqual((after["check_times"], after["start_local"]), (False, "2026-12-10T22:30"))

    def test_editing_the_times_clears_the_note(self):
        seg = self.flagged()
        edited = self.read(lambda conn: trips.edit_segment(conn, self.jane, seg["id"], {"start_local": "2026-12-10T22:00"}))
        assert edited is not None
        self.assertEqual((edited["check_times"], edited["start_local"]), (False, "2026-12-10T22:00"))


class RereadTests(ScanCase):

    def wrong(self, seg, start, end):
        def run(conn):
            conn.execute(update(Segment).where(Segment.id == seg["id"]).values(start_local=start, end_local=end))
        self.read(run)

    def test_a_segment_with_wrong_times_is_corrected_without_a_new_search_or_a_duplicate(self):
        self.put("utc_marked_local_in_text")
        self.scan()
        [seg] = self.segments()
        self.wrong(seg, "2026-12-04T03:00", "2026-12-04T04:10")
        before = self.row()
        result = self.scan(now=NOW + 3600, again=True)
        self.assertEqual((result.state, result.messages, result.bookings), ("done", 1, 1))
        [after] = self.segments()
        self.assertEqual((after["id"], after["start_local"], after["end_local"], after["status"]),
                         (seg["id"], "2026-12-04T09:00", "2026-12-04T11:10", "confirmed"))
        self.assertEqual(len(self.google.queries), 1)
        self.assertEqual({k: self.row()[k] for k in ("last_scan", "history_id", "scan_error")},
                         {k: before[k] for k in ("last_scan", "history_id", "scan_error")})
        self.assertEqual(self.scanned(), {"msg-utc_marked_local_in_text": "booking"})

    def test_a_time_a_person_edited_is_kept(self):
        self.put("utc_marked_local_in_text")
        self.scan()
        [seg] = self.segments()
        self.wrong(seg, "2026-12-04T03:00", "2026-12-04T04:10")
        self.read(lambda conn: trips.edit_segment(conn, self.jane, seg["id"], {"end_local": "2026-12-04T11:20"}))
        self.scan(now=NOW + 3600, again=True)
        [after] = self.segments()
        self.assertEqual((after["start_local"], after["end_local"]), ("2026-12-04T09:00", "2026-12-04T11:20"))

    def test_only_messages_that_made_bookings_are_read_again(self):
        self.put("utc_marked_local_in_text", "no_markup", "incomplete")
        self.scan()
        self.google.fetched.clear()
        result = self.scan(now=NOW + 3600, again=True)
        self.assertEqual(self.google.fetched, ["msg-utc_marked_local_in_text"])
        self.assertEqual((result.messages, result.review), (1, 0))
        self.assertEqual(len(self.items()), 2)

    def test_a_message_deleted_since_keeps_what_came_of_it(self):
        self.put("utc_marked_local_in_text")
        self.scan()
        del self.google.mail["msg-utc_marked_local_in_text"]
        self.assertEqual(self.scan(now=NOW + 3600, again=True).state, "done")
        self.assertEqual(self.scanned(), {"msg-utc_marked_local_in_text": "booking"})
        self.assertEqual(len(self.segments()), 1)

    def test_a_failure_says_so_and_leaves_the_last_good_state(self):
        self.put("utc_marked_local_in_text")
        self.scan()
        before = self.row()
        self.google.fail_on = "msg-utc_marked_local_in_text"
        with mock.patch("waypoint.providers.gmail.time.sleep"):
            result = self.scan(now=NOW + 3600, again=True)
        self.assertEqual(result.state, "failed")
        self.assertEqual(self.row()["last_scan"], before["last_scan"])
        self.assertEqual(self.scanned(), {"msg-utc_marked_local_in_text": "booking"})

    def test_a_reading_that_still_cannot_settle_the_times_flags_them(self):
        silent = eml("utc_marked_overnight").replace(b"Departs Los Angeles 10:30 PM", b"").replace(b"Arrives New York 6:55 AM", b"")
        self.add_mail("silent", silent)
        self.scan()
        self.read(lambda conn: conn.execute(update(Segment).values(check_times=False)))
        self.scan(now=NOW + 3600, again=True)
        [seg] = self.segments()
        self.assertTrue(seg["check_times"])

    def test_a_scan_already_running_makes_the_next_ask_busy(self):
        with scan._lock:
            scan._running.add(self.mailbox)
        try:
            self.assertTrue(scan.running(self.mailbox))
            self.assertEqual(self.scan(), scan.Result("busy"))
            self.assertFalse(jobs.scan_now(self.mailbox))
        finally:
            with scan._lock:
                scan._running.discard(self.mailbox)
        self.assertFalse(scan.running(self.mailbox))

    def test_a_long_scan_gets_a_new_access_token(self):
        self.put("flight_jsonld", "hotel_jsonld")
        ticks = iter([0, TOKEN_AFTER, TOKEN_AFTER, TOKEN_AFTER * 2, TOKEN_AFTER * 2, TOKEN_AFTER * 2, TOKEN_AFTER * 2])
        with mock.patch.object(scan.time, "monotonic", lambda: next(ticks, TOKEN_AFTER * 3)):
            self.assertEqual(self.scan().state, "done")
        self.assertGreaterEqual(len([c for c in self.google.calls if c[1].get("grant_type") == "refresh_token"]), 2)


TOKEN_AFTER = scan.TOKEN_LIFE + 1


class KeptMessageTests(ScanCase):

    def kept(self) -> set[str]:
        return self.read(lambda conn: {m for (m,) in conn.execute(select(StoredMessage.message_id))})

    def item_id(self, reason="no_markup") -> int:
        return next(i["id"] for i in self.items() if i["reason"] == reason)

    def by_hand(self, **fields) -> int:
        seg = self.read(lambda conn: trips.add_segment(conn, self.jane, {"kind": "flight", "origin": "JFK", "destination": "SFO",
                                                                         "start_local": "2026-12-08T08:00", "end_local": "2026-12-08T11:20", **fields}))
        assert seg
        return seg["id"]

    def test_a_scan_keeps_the_messages_of_items_and_bookings_and_no_others(self):
        self.put("flight_jsonld", "no_markup", "incomplete")
        sender = "example-air.example"
        self.scan()
        self.assertEqual(self.kept(), {"msg-flight_jsonld", "msg-no_markup", "msg-incomplete"})
        self.read(lambda conn: db.insert_ignore(conn, IgnoredSender, {"mailbox_id": self.mailbox, "domain": sender}, key=["mailbox_id", "domain"]))
        self.read(lambda conn: conn.execute(StoredMessage.__table__.delete()))
        self.add_mail("ignored-one", eml("no_markup"))
        self.assertEqual(self.scan(now=NOW + 60).messages, 1)
        self.assertEqual(self.kept(), set())

    def test_a_booking_keeps_each_message_that_made_or_updated_it(self):
        self.put("flight_jsonld")
        self.scan()
        [seg] = self.segments()
        self.assertTrue(seg["has_email"])
        self.add_mail("msg-again", eml("flight_jsonld"))
        self.scan(now=NOW + 60)
        emails = self.read(lambda conn: trips.emails_of(conn, self.jane, seg["id"]))
        assert emails is not None
        self.assertEqual(len(emails), 2)
        self.assertEqual({e["sender_domain"] for e in emails}, {"example-air.example"})
        self.assertIsNone(self.read(lambda conn: trips.emails_of(conn, self.sam, seg["id"])))
        self.assertIsNone(self.read(lambda conn: trips.emails_of(conn, self.jane, 99999)))

    def test_dismissing_an_item_deletes_its_message_with_it(self):
        self.put("no_markup", "incomplete")
        self.scan()
        item = self.item_id()
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", item)))
        self.assertEqual(self.kept(), {"msg-incomplete"})

    def test_a_booking_added_from_an_item_keeps_the_message_for_as_long_as_the_booking_exists(self):
        self.put("no_markup")
        self.scan()
        item, seg = self.item_id(), self.by_hand()
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", item, (self.jane, seg))))
        self.assertEqual(self.kept(), {"msg-no_markup"})
        emails = self.read(lambda conn: trips.emails_of(conn, self.jane, seg))
        assert emails
        self.assertEqual(emails[0]["subject"], "Your itinerary: CANARY-SUBJECT-NOMARKUP-8B3F")
        self.assertTrue(self.read(lambda conn: trips.delete_segment(conn, self.jane, seg)))
        self.assertEqual(self.kept(), set())

    def test_a_booking_the_asker_cannot_see_does_not_keep_the_message(self):
        self.put("no_markup")
        self.scan()
        item = self.item_id()
        theirs = self.read(lambda conn: trips.add_segment(conn, self.sam, {"kind": "flight", "origin": "JFK", "destination": "SFO",
                                                                           "start_local": "2026-12-09T08:00", "end_local": "2026-12-09T11:20"}))
        assert theirs
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", item, (self.jane, theirs["id"]))))
        self.assertEqual(self.kept(), set())

    def test_deleting_a_trip_deletes_the_messages_only_its_bookings_held(self):
        self.put("flight_jsonld")
        self.scan()
        [seg] = self.segments()
        self.assertEqual(self.kept(), {"msg-flight_jsonld"})
        self.assertTrue(self.read(lambda conn: trips.delete_trip(conn, self.jane, seg["trip_id"])))
        self.assertEqual(self.kept(), set())

    def test_ignoring_a_sender_deletes_the_messages_of_the_items_that_leave(self):
        self.put("no_markup", "incomplete")
        self.scan()
        self.assertTrue(self.read(lambda conn: review.ignore_sender(conn, "u-jane", self.item_id())) is not None)
        self.assertEqual(self.kept(), set())

    def test_a_message_that_could_not_be_filed_is_kept_with_its_item(self):
        self.put("flight_jsonld")
        with mock.patch.object(ingest, "file_booking", side_effect=RuntimeError("CANARY-FILE-DETAILS-2Y8W")):
            self.scan()
        self.assertEqual(self.kept(), {"msg-flight_jsonld"})
        self.assertEqual(self.items()[0]["has_email"], True)


class PrivacyTests(ScanCase):
    def test_email_stays_on_the_server(self):
        self.put("flight_jsonld", "flight_microdata", "hotel_jsonld", "car_jsonld", "train_jsonld", "no_markup", "incomplete", *UTC_FIXTURES)
        with no_leaks(self, *CANARIES, database=self.path):
            result = self.scan()
            again = self.scan(now=NOW + 60, again=True)
        self.assertEqual((result.state, result.messages, result.bookings, result.review), ("done", 12, 9, 3))
        self.assertEqual((again.state, again.messages, again.review), ("done", 9, 0))

    def test_what_a_failed_scan_logs_and_says_holds_none_of_it(self):
        self.put("flight_jsonld", "no_markup")
        self.google.fail_on = "msg-no_markup"
        with no_leaks(self, *CANARIES, "CANARY-BUG-DETAILS-3Z7Q", database=self.path), mock.patch("waypoint.providers.gmail.time.sleep"):
            self.assertEqual(self.scan().state, "failed")
        with no_leaks(self, *CANARIES, "CANARY-BUG-DETAILS-3Z7Q", database=self.path):
            with mock.patch.object(scan.extract, "read", side_effect=RuntimeError("CANARY-BUG-DETAILS-3Z7Q")):
                self.google.fail_on = None
                self.assertEqual(self.scan().state, "failed")
        self.assertNotIn("CANARY", json.dumps(self.row(), default=str))

    def test_the_canaries_are_really_in_the_fixtures(self):
        text = b"".join(p.read_bytes() for p in FIXTURES.glob("*.eml")).decode()
        for canary in CANARIES:
            self.assertIn(canary, text)

    def test_a_scan_sends_gmail_nothing_but_ids_and_a_search(self):
        self.put("flight_jsonld")
        sent = []
        real = scan.gmail.tls.urlopen

        def spy(req, *a, **k):
            sent.append(req.full_url if hasattr(req, "full_url") else str(req))
            return real(req, *a, **k)
        with mock.patch.object(scan.gmail.tls, "urlopen", spy):
            self.scan()
        self.assertTrue(sent)
        self.assertTrue(all(u.startswith(self.google.hosts().api) or u.startswith(self.google.hosts().token) for u in sent), sent)


class MailScanApiTests(GoogleCase):
    fake = FakeGmail

    def setUp(self):
        super().setUp()
        reset(self.google)
        with db.session() as conn:
            for table in (SegmentMessage, StoredMessage, ReviewItem, ScannedMessage, SegmentTraveler, Segment):
                conn.execute(table.__table__.delete())
            conn.execute(__import__("sqlalchemy").delete(__import__("waypoint.storage.models", fromlist=["Trip"]).Trip))
        self.ana_box = self.connect_mailbox("ana", "ana@gmail.example", "refresh-ana")

    def connect_mailbox(self, who, address, refresh) -> int:
        self.connect(who, address, refresh)
        return next(m["id"] for m in self.mailboxes(who) if m["address"] == address)

    def put(self, *names):
        for name in names:
            self.google.mail[f"m-{name}"] = eml(name)
            self.google.matches.append(f"m-{name}")

    def scan_now(self, who="ana", box=None):
        status, body = self.call(who, "POST", f"/api/mailboxes/{box or self.ana_box}/scan", {})
        self.assertEqual(status, 200, body)
        for _ in range(100):
            [m] = [m for m in self.mailboxes(who) if m["id"] == (box or self.ana_box)]
            if m["last_scan"] and not m["scanning"]:
                return m
            time.sleep(0.1)
        self.fail("the scan didn't finish")

    def test_scan_now_runs_a_scan_and_the_mailbox_says_how_it_went(self):
        self.put("flight_jsonld", "no_markup")
        self.assertEqual(self.mailboxes()[0]["scanning"], False)
        m = self.scan_now()
        self.assertEqual((m["scan_error"], m["scanning"]), (None, False))
        self.assertTrue(m["last_scan"].endswith("+00:00"))
        status, state = self.call("ana", "GET", "/api/state")
        self.assertEqual((status, state["review_count"]), (200, 2))
        self.assertEqual(self.call("ben", "GET", "/api/state")[1]["review_count"], 0)

    def test_connecting_again_forgets_why_a_scan_couldnt_start(self):
        scan._notices[self.ana_box] = "Something."
        self.connect("ana", "ana@gmail.example", "refresh-ana-2")
        self.assertIsNone(scan.notice(self.ana_box))

    def test_disconnecting_forgets_why_a_scan_couldnt_start(self):
        scan._notices[self.ana_box] = "Something."
        with mock.patch.object(gmail, "_post", return_value={}):
            self.assertEqual(self.call("ana", "DELETE", f"/api/mailboxes/{self.ana_box}")[0], 200)
        self.assertIsNone(scan.notice(self.ana_box))

    def test_a_failed_scan_is_in_the_mailbox_list(self):
        self.put("flight_jsonld")
        self.google.fail_on = "m-flight_jsonld"
        with mock.patch("waypoint.providers.gmail.time.sleep"):
            self.call("ana", "POST", f"/api/mailboxes/{self.ana_box}/scan", {})
            for _ in range(100):
                [m] = self.mailboxes()
                if m["scan_error"]:
                    break
                time.sleep(0.1)
        self.assertEqual((m["scan_error"], m["last_scan"]), ("Google refused a request while reading the mailbox.", None))

    def test_read_bookings_again_corrects_the_mailboxes_stored_times(self):
        self.put("utc_marked_local_in_text")
        self.scan_now()
        with db.session() as conn:
            conn.execute(update(Segment).values(start_local="2026-12-04T03:00", end_local="2026-12-04T04:10"))
        status, body = self.call("ana", "POST", f"/api/mailboxes/{self.ana_box}/reread", {})
        self.assertEqual((status, body), (200, {"started": True}))
        for _ in range(100):
            [m] = self.mailboxes()
            with db.session() as conn:
                start = conn.execute(select(Segment.start_local)).scalar()
            if start == "2026-12-04T09:00" and not m["scanning"]:
                break
            time.sleep(0.1)
        self.assertEqual(start, "2026-12-04T09:00")

    def test_nobody_reads_another_members_mailbox_again(self):
        status, body = self.call("ben", "POST", f"/api/mailboxes/{self.ana_box}/reread", {})
        self.assertEqual((status, body["error"]), (404, "Not found"))
        self.assertEqual(self.call("ben", "POST", "/api/mailboxes/abc/reread", {})[0], 404)
        self.assertEqual(self.google.fetched, [])

    def test_nobody_scans_or_sees_another_members_mailbox(self):
        status, body = self.call("ben", "POST", f"/api/mailboxes/{self.ana_box}/scan", {})
        self.assertEqual((status, body["error"]), (404, "Not found"))
        self.assertEqual(self.call("ben", "POST", "/api/mailboxes/abc/scan", {})[0], 404)
        self.assertEqual(self.google.queries, [])

    def test_the_review_queue_is_its_owners_alone(self):
        self.put("no_markup", "incomplete")
        self.scan_now()
        status, mine = self.call("ana", "GET", "/api/review")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(i["reason"] for i in mine["items"]), ["incomplete", "no_markup"])
        item = next(i for i in mine["items"] if i["reason"] == "no_markup")
        self.assertEqual((item["address"], item["sender_domain"], item["received"]), ("ana@gmail.example", "example-air.example", "2026-10-17"))
        self.assertEqual(self.call("ben", "GET", "/api/review")[1], {"items": [], "who": [], "ai": False})
        for method, path in (("DELETE", f"/api/review/{item['id']}"), ("POST", f"/api/review/{item['id']}/ignore")):
            status, body = self.call("ben", method, path, {} if method == "POST" else None)
            self.assertEqual((status, body["error"]), (404, "No such item"), path)
        self.assertEqual(len(self.call("ana", "GET", "/api/review")[1]["items"]), 2)

    def share(self, who="ana", box=None, on=True):
        return self.call(who, "POST", f"/api/mailboxes/{box or self.ana_box}/share", {"share": on})

    def test_a_mailbox_shares_its_queue_with_the_household_only_when_its_owner_says_so(self):
        self.put("no_markup", "incomplete")
        self.scan_now()
        self.assertFalse(self.mailboxes()[0]["share_review"])
        self.assertEqual(self.call("ben", "GET", "/api/review")[1]["items"], [])
        self.assertEqual(self.call("ben", "GET", "/api/state")[1]["review_count"], 0)
        self.assertEqual(self.share(), (200, {"ok": True}))
        self.assertTrue(self.mailboxes()[0]["share_review"])
        seen = self.call("ben", "GET", "/api/review")[1]["items"]
        self.assertEqual(sorted(i["reason"] for i in seen), ["incomplete", "no_markup"])
        self.assertEqual({(i["address"], i["owner"], i["mine"], i["gmail_url"]) for i in seen}, {("ana@gmail.example", "Ana", False, None)})
        self.assertTrue(all(i["mine"] and i["gmail_url"] for i in self.call("ana", "GET", "/api/review")[1]["items"]))
        self.assertEqual(self.call("ben", "GET", "/api/state")[1]["review_count"], 2)
        self.assertEqual(self.share(on=False)[0], 200)
        self.assertEqual(self.call("ben", "GET", "/api/review")[1]["items"], [])
        self.assertEqual(self.call("ben", "GET", "/api/state")[1]["review_count"], 0)

    def test_only_a_mailboxs_owner_changes_whether_it_is_shared(self):
        self.assertEqual(self.share("ben")[0], 404)
        self.assertEqual(self.share("ben", "abc")[0], 404)
        self.assertEqual(self.share("ana", 9999)[0], 404)
        self.assertFalse(self.mailboxes()[0]["share_review"])
        self.share()
        self.assertEqual(self.share("ben", on=False)[0], 404)
        self.assertTrue(self.mailboxes()[0]["share_review"])
        self.assertEqual(self.call("ben", "POST", f"/api/mailboxes/{self.ana_box}/share", {"share": "false"}), (404, {"error": "Not found"}))
        self.assertEqual(self.call("ana", "POST", f"/api/mailboxes/{self.ana_box}/share", {"share": "false"})[0], 200)
        self.assertFalse(self.mailboxes()[0]["share_review"])

    def test_the_household_can_dismiss_a_shared_item_but_nothing_that_reads_the_owners_gmail(self):
        self.put("no_markup", "incomplete")
        self.scan_now()
        first, second = self.call("ana", "GET", "/api/review")[1]["items"]
        self.assertEqual(self.call("ben", "DELETE", f"/api/review/{first['id']}")[0], 404)
        self.share()
        fetched = len(self.google.fetched)
        self.assertEqual(self.call("ben", "GET", f"/api/review/{first['id']}/preview")[0], 200)
        self.assertEqual(self.call("ben", "POST", f"/api/review/{first['id']}/suggest", {})[0], 404)
        self.assertEqual(self.call("ben", "POST", f"/api/review/{first['id']}/ignore", {})[0], 404)
        self.assertEqual(len(self.google.fetched), fetched)
        self.assertEqual(self.call("ben", "DELETE", f"/api/review/{first['id']}"), (200, {"ok": True}))
        self.assertEqual([i["id"] for i in self.call("ana", "GET", "/api/review")[1]["items"]], [second["id"]])
        self.assertEqual(self.call("ben", "DELETE", f"/api/review/{first['id']}")[0], 404)

    def test_the_household_sees_a_shared_items_subject_and_can_read_it_but_never_its_gmail_id(self):
        self.put("no_markup", "incomplete")
        self.scan_now()
        self.share()
        with no_leaks(self, "CANARY-SUBJECT-NOMARKUP-8B3F", "CANARY-BODY-NOMARKUP-6H9C", "CANARY-BODY-INCOMPLETE-4N7P"):
            reply = self.call("ben", "GET", "/api/review")[1]
            self.call("ben", "GET", "/api/state")
        self.assertEqual(len(reply["items"]), 2)
        self.assertIn("CANARY-SUBJECT-NOMARKUP-8B3F", json.dumps(reply))
        for canary in ("CANARY-BODY-NOMARKUP-6H9C", "CANARY-BODY-INCOMPLETE-4N7P", "msg-no_markup", "authuser"):
            self.assertNotIn(canary, json.dumps(reply))
        shown = next(i for i in reply["items"] if i["reason"] == "no_markup")
        status, body = self.call("ben", "GET", f"/api/review/{shown['id']}/preview")
        self.assertEqual(status, 200)
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C", body["text"])
        self.assertEqual(body["subject"], "Your itinerary: CANARY-SUBJECT-NOMARKUP-8B3F")
        self.share(on=False)
        self.assertEqual(self.call("ben", "GET", f"/api/review/{shown['id']}/preview")[0], 404)

    def test_a_member_who_loses_access_takes_what_their_mailbox_shared_with_them(self):
        self.put("no_markup")
        self.scan_now()
        self.share()
        self.assertEqual(len(self.call("ben", "GET", "/api/review")[1]["items"]), 1)
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ben@example.com"}), mock.patch.object(gmail, "_post", return_value={}):
            self.assertEqual(self.call("ben", "GET", "/api/review")[1]["items"], [])
        self.assertEqual(self.mailboxes("ben"), [])

    def test_the_messages_a_booking_was_made_from_are_read_by_whoever_can_see_the_booking_alone(self):
        self.put("flight_jsonld")
        self.scan_now()
        [trip] = self.call("ana", "GET", "/api/trips")[1]["trips"]
        [seg] = trip["segments"]
        self.assertTrue(seg["has_email"])
        status, body = self.call("ana", "GET", f"/api/segments/{seg['id']}/emails")
        self.assertEqual(status, 200)
        [email] = body["emails"]
        self.assertEqual(set(email), {"subject", "sender_domain", "received", "text", "html", "truncated"})
        self.assertEqual(email["sender_domain"], "example-air.example")
        self.assertEqual(self.call("ben", "GET", f"/api/segments/{seg['id']}/emails"), (404, {"error": "No such segment"}))
        self.assertEqual(self.call("ana", "GET", "/api/segments/99999/emails"), (404, {"error": "No such segment"}))
        self.assertTrue(all("emails" not in t for t in self.call("ben", "GET", "/api/trips")[1]["trips"]))

    def test_dismissing_with_the_booking_it_became_keeps_the_message_and_with_none_deletes_it(self):
        self.put("no_markup", "incomplete")
        self.scan_now()
        first, second = sorted(self.call("ana", "GET", "/api/review")[1]["items"], key=lambda i: i["reason"], reverse=True)
        booked = self.call("ana", "POST", "/api/segments", {"kind": "flight", "origin": "JFK", "destination": "SFO",
                                                            "start_local": "2026-12-08T08:00", "end_local": "2026-12-08T11:20"})[1]
        self.assertEqual(self.call("ana", "DELETE", f"/api/review/{first['id']}?segment={booked['id']}"), (200, {"ok": True}))
        [email] = self.call("ana", "GET", f"/api/segments/{booked['id']}/emails")[1]["emails"]
        self.assertEqual(email["subject"], "Your itinerary: CANARY-SUBJECT-NOMARKUP-8B3F")
        self.assertEqual(self.call("ana", "DELETE", f"/api/review/{second['id']}"), (200, {"ok": True}))
        with db.session() as conn:
            self.assertEqual(len(conn.execute(__import__("sqlalchemy").select(StoredMessage.id)).fetchall()), 1)
        self.assertEqual(self.call("ana", "DELETE", f"/api/review/{second['id']}?segment=zz")[0], 400)

    def test_a_booking_that_isnt_the_askers_is_never_given_the_message(self):
        self.put("no_markup")
        self.scan_now()
        [item] = self.call("ana", "GET", "/api/review")[1]["items"]
        bens = self.call("ben", "POST", "/api/segments", {"kind": "flight", "origin": "JFK", "destination": "SFO",
                                                          "start_local": "2026-12-09T08:00", "end_local": "2026-12-09T11:20"})[1]
        self.assertEqual(self.call("ana", "DELETE", f"/api/review/{item['id']}?segment={bens['id']}"), (200, {"ok": True}))
        self.assertEqual(self.call("ben", "GET", f"/api/segments/{bens['id']}/emails")[1], {"emails": []})
        with db.session() as conn:
            self.assertEqual(conn.execute(__import__("sqlalchemy").select(StoredMessage.id)).fetchall(), [])
        self.assertEqual(self.call("ana", "DELETE", f"/api/review/{item['id']}?segment=abc")[0], 400)

    def test_a_mailbox_that_goes_takes_the_messages_kept_from_it(self):
        self.put("no_markup", "flight_jsonld")
        self.scan_now()
        with db.session() as conn:
            self.assertEqual(len(conn.execute(__import__("sqlalchemy").select(StoredMessage.id)).fetchall()), 2)
        with mock.patch.object(gmail, "_post", return_value={}):
            self.assertEqual(self.call("ana", "DELETE", f"/api/mailboxes/{self.ana_box}")[0], 200)
        with db.session() as conn:
            self.assertEqual(conn.execute(__import__("sqlalchemy").select(StoredMessage.id)).fetchall(), [])
            self.assertEqual(conn.execute(__import__("sqlalchemy").select(SegmentMessage.segment_id)).fetchall(), [])

    def test_a_mailbox_that_goes_takes_what_it_shared_with_it(self):
        self.put("no_markup")
        self.scan_now()
        self.share()
        self.assertEqual(len(self.call("ben", "GET", "/api/review")[1]["items"]), 1)
        with mock.patch.object(gmail, "_post", return_value={}):
            self.assertEqual(self.call("ana", "DELETE", f"/api/mailboxes/{self.ana_box}")[0], 200)
        self.assertEqual(self.call("ben", "GET", "/api/review")[1]["items"], [])

    def test_dismissing_and_ignoring(self):
        self.put("no_markup", "incomplete")
        self.scan_now()
        first, second = self.call("ana", "GET", "/api/review")[1]["items"]
        self.assertEqual(self.call("ana", "DELETE", f"/api/review/{first['id']}")[1], {"ok": True})
        self.assertEqual(self.call("ana", "DELETE", f"/api/review/{first['id']}")[0], 404)
        self.assertEqual(self.call("ana", "POST", f"/api/review/{second['id']}/ignore", {})[1], {"ok": True})
        self.assertEqual(self.call("ana", "GET", "/api/review")[1]["items"], [])
        self.assertEqual(self.call("ana", "DELETE", "/api/review/9999")[0], 404)
        self.assertEqual(self.call("ana", "POST", "/api/review/9999/ignore", {})[0], 404)
        self.assertEqual(self.call("ana", "DELETE", "/api/review/x")[0], 404)
        self.assertEqual(self.call("ana", "POST", "/api/review/x/ignore", {})[0], 404)

    def test_who_is_this_lists_the_names_on_the_members_own_trips_and_matches_them(self):
        with db.session() as conn:
            self.mia = people.add_guest(conn, guest("Mia Doe"))["id"]
        self.put("flight_microdata")
        self.scan_now()
        status, mine = self.call("ana", "GET", "/api/review")
        [who] = mine["who"]
        self.assertEqual((who["name"], who["kind"], who["origin"], who["destination"], who["start_local"], who["start_zone"], who["provider"]),
                         ("DOE/MIA MISS", "flight", "JFK", "SFO", "2026-12-08T08:00", "America/New_York", "Example Air"))
        self.assertEqual(self.call("ben", "GET", "/api/review")[1]["who"], [])
        self.assertEqual(self.call("ana", "GET", "/api/state")[1]["review_count"], 1)
        self.assertEqual(self.call("ben", "POST", f"/api/review/who/{who['id']}", {"person_id": self.mia})[0], 404)
        for bad, message in (({}, "Choose someone from People, or add a guest"),
                             ({"person_id": self.mia, "new_guest": "X"}, "Choose a person, or add a guest, not both"),
                             ({"new_guest": 5}, 'Send "new_guest" as text'),
                             ({"person_id": 99999}, "Choose someone from People"),
                             ({"person_id": "abc"}, "Choose someone from People")):
            status, body = self.call("ana", "POST", f"/api/review/who/{who['id']}", bad)
            self.assertEqual((status, body["error"]), (400, message), bad)
        status, body = self.call("ana", "POST", f"/api/review/who/{who['id']}", {"person_id": self.mia})
        self.assertEqual((status, body), (200, {"ok": True, "matched": 1}))
        self.assertEqual(self.call("ana", "GET", "/api/review")[1]["who"], [])
        self.assertEqual(self.call("ana", "POST", f"/api/review/who/{who['id']}", {"person_id": self.mia})[0], 404)
        self.assertEqual(self.call("ana", "POST", "/api/review/who/zz", {"person_id": self.mia})[0], 404)

    def test_a_kept_message_is_read_without_gmail_and_only_by_those_who_see_the_item(self):
        self.put("no_markup")
        self.scan_now()
        [item] = self.call("ana", "GET", "/api/review")[1]["items"]
        fetched = len(self.google.fetched)
        status, body = self.call("ana", "GET", f"/api/review/{item['id']}/preview")
        self.assertEqual(status, 200)
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C", body["text"])
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C", body["html"])
        self.assertFalse(body["truncated"])
        self.assertEqual(self.call("ben", "GET", f"/api/review/{item['id']}/preview")[0], 404)
        self.assertEqual(self.call("ana", "GET", "/api/review/9999/preview")[0], 404)
        del self.google.mail["m-no_markup"]
        self.assertEqual(self.call("ana", "GET", f"/api/review/{item['id']}/preview")[0], 200)
        self.assertEqual(len(self.google.fetched), fetched)

    def test_an_item_from_before_messages_were_kept_is_fetched_for_its_owner_alone_and_kept_from_then_on(self):
        self.put("no_markup")
        self.scan_now()
        [item] = self.call("ana", "GET", "/api/review")[1]["items"]
        with db.session() as conn:
            conn.execute(StoredMessage.__table__.delete())
        self.assertEqual(self.call("ana", "GET", "/api/review")[1]["items"][0]["has_email"], False)
        self.share()
        status, body = self.call("ben", "GET", f"/api/review/{item['id']}/preview")
        self.assertEqual((status, body["error"]), (404, "This message wasn’t kept. Its owner can open it in Gmail."))
        status, body = self.call("ana", "GET", f"/api/review/{item['id']}/preview")
        self.assertEqual(status, 200)
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C", body["text"])
        self.assertEqual(body["subject"], "Your itinerary: CANARY-SUBJECT-NOMARKUP-8B3F")
        self.assertEqual(self.call("ben", "GET", f"/api/review/{item['id']}/preview")[0], 200)
        del self.google.mail["m-no_markup"]
        with db.session() as conn:
            conn.execute(StoredMessage.__table__.delete())
        status, body = self.call("ana", "GET", f"/api/review/{item['id']}/preview")
        self.assertEqual((status, body["error"]), (404, "That message is no longer in Gmail."))

    def test_asking_the_ai_needs_it_on_and_is_the_owners_alone(self):
        self.put("no_markup")
        self.scan_now()
        [item] = self.call("ana", "GET", "/api/review")[1]["items"]
        self.assertFalse(self.call("ana", "GET", "/api/review")[1]["ai"])
        status, body = self.call("ana", "POST", f"/api/review/{item['id']}/suggest", {})
        self.assertEqual((status, body["error"]), (400, "Turn on AI suggestions in Settings first."))
        self.assertEqual(self.call("ben", "POST", f"/api/review/{item['id']}/suggest", {})[0], 404)
        self.assertEqual(self.call("ana", "POST", "/api/review/9999/suggest", {})[0], 404)

    def test_who_is_this_can_add_a_guest(self):
        self.put("flight_microdata")
        self.scan_now()
        [who] = self.call("ana", "GET", "/api/review")[1]["who"]
        status, body = self.call("ana", "POST", f"/api/review/who/{who['id']}", {"new_guest": "  Mia Rose Doe  "})
        self.assertEqual((status, body["matched"]), (200, 1))
        names = [p["display_name"] for p in self.call("ana", "GET", "/api/people")[1]["people"]]
        self.assertIn("Mia Rose Doe", names)


if __name__ == "__main__":
    unittest.main()
