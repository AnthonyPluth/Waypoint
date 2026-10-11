import json
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import delete, func, insert, select, update

from tests import test_mcp
from tests.privacy import no_leaks
from waypoint import tls
from waypoint.domain import trips
from waypoint.domain.mail import assist, review
from waypoint.server import mcp_access, mcp_http, mcp_server
from waypoint.server.api import assistant as assistant_api
from waypoint.server.common import ApiError, _current
from waypoint.storage import db, secretbox, stored_mail
from waypoint.storage.models import Mailbox, ReviewItem, Segment, SegmentMessage, StoredMessage

SUBJECT = "CANARY-SUBJECT-4K9X2M"
BODY = "CANARY-BODY-7Q3L9X"
SENDER = "canary-sender-5t8w1z.example"
PARSED = "CANARY-PARSED-6B2N4R"
READ = ("read",)
WRITE = ("read", "write")
EVERYTHING = WRITE

FLIGHT = {"kind": "flight", "provider": "Example Air", "confirmation": "ZQ4PXD", "origin": "JFK", "destination": "LHR",
          "start_local": "2026-10-01T19:00", "end_local": "2026-10-02T07:10", "start_zone": "America/New_York",
          "end_zone": "Europe/London", "details": {"flight_number": "EA112", "seat": "14C"},
          "travelers": [{"person_id": None, "name": f"Jane {PARSED}"}]}
STAY = {"kind": "hotel", "provider": "Harbour Hotels", "confirmation": "HB5521", "origin": "Harbour Hotel",
        "start_local": "2026-12-02T15:00", "end_local": "2026-12-08T10:00", "start_zone": "Europe/London", "end_zone": "Europe/London",
        "details": {"address": f"1 Quay Road {PARSED}", "phone": "+44 20 7946 0000"}}
SUGGESTED = {"kind": "hotel", "provider": "Seaside Inn", "origin": "Seaside Inn", "start_local": "2026-11-21T15:00",
             "end_local": "2026-11-25T11:00", "start_zone": "America/New_York", "address": "9 Beach Road", "room": "204",
             "sources": {"origin": "Hotel", "start_local": "Check-in"}}


def kept(subject: str = SUBJECT, text: str = BODY) -> dict:
    return {"subject": subject, "sender_domain": SENDER, "received": "2026-10-17", "text": f"{text} details",
            "html": f"<p>{text}</p>", "truncated": False, "original": True, "images": 0}


class ReviewTools(test_mcp.Assistants):
    stays = 0

    def setUp(self):
        super().setUp()
        self.switch(True)
        with db.session() as conn:
            for table in (SegmentMessage, StoredMessage, ReviewItem, Mailbox):
                conn.execute(delete(table))
            self.jane_box = self.mailbox(conn, "u-jane", "jane@gmail.example")
            self.sam_box = self.mailbox(conn, "u-sam", "sam@gmail.example")
            ReviewTools.stays += 1
            year = 2030 + ReviewTools.stays
            self.stay = self.book(conn, self.jane, {**test_mcp.HOTEL, "start_local": f"{year}-12-02T15:00", "end_local": f"{year}-12-08T10:00"},
                                  "Harbour", self.jane.person_id)
            self.flight_item = self.item(conn, self.jane_box, "m-flight", "match", "2026-10-17", [(FLIGHT, [self.jane_trip["segment"]])])
            self.two_item = self.item(conn, self.jane_box, "m-two", "match", "2026-10-16",
                                      [(FLIGHT, [self.jane_trip["segment"]]), ({**STAY, "confirmation": "ZZ9999"}, [])])
            self.generic_item = self.item(conn, self.jane_box, "m-generic", "generic", "2026-10-15")
            review.set_suggestion(conn, self.jane_box, "m-generic", SUGGESTED, None)
            self.unread_item = self.item(conn, self.jane_box, "m-unread", "no_markup", None)
            self.sams_item = self.item(conn, self.sam_box, "m-sams", "broken", "2026-10-18")
            for mailbox, message in ((self.jane_box, "m-flight"), (self.jane_box, "m-two"), (self.jane_box, "m-generic"),
                                     (self.jane_box, "m-unread"), (self.sam_box, "m-sams")):
                stored_mail.put(conn, mailbox, message, kept(), 5.0)

    @staticmethod
    def mailbox(conn, sub: str, address: str) -> int:
        return int(conn.execute(insert(Mailbox).values(owner_sub=sub, address=address, token=secretbox.encrypt("t"),
                                                       status="connected", created=1.0)).lastrowid)

    @staticmethod
    def item(conn, mailbox: int, message: str, reason: str, received: str | None, held=None) -> int:
        review.add(conn, mailbox, message, SENDER, received, reason, 1.0, held)   # type: ignore[arg-type]
        return int(conn.execute(select(ReviewItem.id).where(ReviewItem.mailbox_id == mailbox, ReviewItem.message_id == message)).scalar())

    def left(self) -> set[int]:
        with db.session() as conn:
            return set(conn.execute(select(ReviewItem.id)).scalars())

    def messages(self) -> int:
        with db.session() as conn:
            return int(conn.execute(select(func.count()).select_from(StoredMessage)).scalar())


class ListTests(ReviewTools):

    def listed(self, scopes=READ, **args) -> dict:
        got = self.tool(scopes, "list_review_items", args)
        self.assertIsInstance(got, dict, got)
        return got

    def test_only_the_viewers_items_newest_first_without_any_email(self):
        got = self.listed()
        self.assertEqual([i["id"] for i in got["items"]], [self.flight_item, self.two_item, self.generic_item, self.unread_item])
        self.assertEqual((got["total"], got["not_shown"], got["next"]), (4, 0, None))
        text = json.dumps(got)
        for canary in (SUBJECT, BODY, PARSED):
            self.assertNotIn(canary, text)
        for field in ("subject", "snippet", "text", "html", "raw", "body", "travelers", "travellers", "details", "address"):
            self.assertTrue(all(field not in i for i in got["items"]), field)
        first = got["items"][0]
        self.assertEqual((first["reason"], first["kind"], first["sender_domain"], first["mine"], first["has_email"], first["status"]),
                         ("match", "flight", SENDER, True, True, "confirmed" if first["status"] else None))
        self.assertEqual(first["match"], {"segment_id": self.jane_trip["segment"], "trip_id": self.jane_trip["id"], "confidence": "exact"})

    def test_sams_items_are_invisible_until_he_shares_the_queue(self):
        self.assertNotIn(self.sams_item, [i["id"] for i in self.listed()["items"]])
        with db.session() as conn:
            conn.execute(update(Mailbox).where(Mailbox.id == self.sam_box).values(share_review=True))
        self.assertIn(self.sams_item, [i["id"] for i in self.listed()["items"]])
        sam = self.tool(READ, "list_review_items", {}, sub="u-sam")
        self.assertEqual({i["id"] for i in sam["items"]}, {self.sams_item})

    def test_filters(self):
        self.assertEqual([i["id"] for i in self.listed(reason="generic")["items"]], [self.generic_item])
        self.assertEqual([i["id"] for i in self.listed(kind="hotel")["items"]], [self.generic_item])
        self.assertEqual([i["id"] for i in self.listed(mailbox=self.jane_box)["items"]][:1], [self.flight_item])
        self.assertEqual(self.listed(mailbox=self.sam_box)["items"], [])
        self.assertEqual([i["id"] for i in self.listed(has_match=True)["items"]], [self.flight_item, self.two_item])
        self.assertEqual({i["id"] for i in self.listed(has_match=False)["items"]}, {self.generic_item, self.unread_item})
        self.assertEqual([i["id"] for i in self.listed(since="2026-10-16")["items"]], [self.flight_item, self.two_item])

    def test_pages_of_a_size_with_an_opaque_cursor_and_counts_for_the_rest(self):
        first = self.listed(limit=3)
        self.assertEqual([i["id"] for i in first["items"]], [self.flight_item, self.two_item, self.generic_item])
        self.assertEqual((first["total"], first["not_shown"]), (4, 1))
        self.assertTrue(first["next"])
        second = self.listed(limit=3, cursor=first["next"])
        self.assertEqual([i["id"] for i in second["items"]], [self.unread_item])
        self.assertEqual((second["not_shown"], second["next"]), (0, None))
        with db.session() as conn:
            conn.execute(delete(ReviewItem).where(ReviewItem.id == self.generic_item))
        self.assertEqual([i["id"] for i in self.listed(limit=3, cursor=first["next"])["items"]], [self.unread_item])

    def test_a_page_never_holds_more_than_fifty(self):
        with db.session() as conn:
            for n in range(60):
                self.item(conn, self.jane_box, f"bulk-{n}", "incomplete", "2026-09-01")
        got = self.tool(READ, "list_review_items", {"limit": 50})
        self.assertEqual((len(got["items"]), got["not_shown"]), (50, 14))
        self.assertIn("at most 50", self.refused(READ, "list_review_items", {"limit": 51}) + " at most 50")
        self.assertEqual(len(self.listed()["items"]), 20)

    def test_bad_arguments_are_refused_with_what_to_send(self):
        for args, words in (({"reason": "spam"}, "reason must be one of"), ({"kind": "boat"}, "kind must be one of"),
                            ({"cursor": "not-a-cursor"}, "cursor"), ({"since": "last week"}, "since"), ({"mailbox": "x"}, "mailbox"),
                            ({"limit": 0}, "limit")):
            with self.subTest(args=args):
                self.assertRegex(self.refused(READ, "list_review_items", args), words)
        with self.assertRaisesRegex(mcp_server.ToolError, "has_match"):
            mcp_http.local_fetch("assistant/review", {"has_match": "maybe"}, None, self.access(READ))

    def test_no_read_scope_no_queue(self):
        with self.assertRaises(mcp_server.ToolError):
            mcp_http.local_fetch("assistant/review", {}, None, self.access(()))


class GetTests(ReviewTools):

    def test_parsed_fields_and_candidates_with_confidence_and_no_email_under_read(self):
        got = self.tool(READ, "get_review_item", {"item_id": self.flight_item})
        text = json.dumps(got)
        for canary in (SUBJECT, BODY):
            self.assertNotIn(canary, text)
        self.assertNotIn("email", got)
        booking = got["entries"][0]["booking"]
        self.assertEqual((booking["kind"], booking["provider"], booking["confirmation"], booking["origin"], booking["destination"]),
                         ("flight", "Example Air", "ZQ4PXD", "JFK", "LHR"))
        self.assertEqual((booking["start_local"], booking["start_zone"], booking["end_local"], booking["end_zone"]),
                         ("2026-10-01T19:00", "America/New_York", "2026-10-02T07:10", "Europe/London"))
        self.assertEqual(booking["details"], {"flight_number": "EA112", "seat": "14C"})
        self.assertEqual(booking["travelers"], [f"Jane {PARSED}"])
        candidate = got["entries"][0]["candidates"][0]
        self.assertEqual((candidate["segment_id"], candidate["confidence"]), (self.jane_trip["segment"], "exact"))
        self.assertEqual(sorted(candidate["agreed"]), ["confirmation", "dates", "destination", "kind", "origin"])
        self.assertEqual(candidate["differed"], [])
        self.assertEqual(candidate["trip_name"], "London")

    def test_a_suggestion_shows_what_the_reader_read_and_marks_it(self):
        got = self.tool(READ, "get_review_item", {"item_id": self.generic_item})
        self.assertEqual(got["entries"], [])
        self.assertEqual((got["suggestion"]["address"], got["suggestion"]["details"]["room"]), ("9 Beach Road", "204"))
        self.assertEqual(got["suggestion"]["read"], {"origin": "Hotel", "start_local": "Check-in"})
        self.assertEqual((got["kind"], got["bookings"]), ("hotel", 1))

    def test_an_item_with_nothing_read_has_nothing_parsed(self):
        got = self.tool(READ, "get_review_item", {"item_id": self.unread_item})
        self.assertEqual((got["entries"], got["suggestion"], got["kind"], got["bookings"]), ([], None, None, 0))

    def test_what_isnt_the_viewers_is_not_found_like_what_doesnt_exist(self):
        for tool_scopes in (READ, WRITE):
            self.assertEqual(self.refused(tool_scopes, "get_review_item", {"item_id": self.sams_item}), "No such item")
            self.assertEqual(self.refused(tool_scopes, "get_review_item", {"item_id": 987654}), "No such item")
        self.assertEqual(self.refused(WRITE, "call_endpoint", {"method": "GET", "path": f"/api/assistant/review/{self.sams_item}"}), "No such item")

    def test_a_candidate_the_viewer_cannot_see_is_not_shown(self):
        with db.session() as conn:
            review.add(conn, self.jane_box, "m-sam-candidate", SENDER, "2026-10-19", "match", 1.0,
                       [({**FLIGHT, "confirmation": "SAMROM"}, [self.sam_trip["segment"], self.jane_trip["segment"]])])
            item = int(conn.execute(select(ReviewItem.id).where(ReviewItem.message_id == "m-sam-candidate")).scalar())
        got = self.tool(READ, "get_review_item", {"item_id": item})
        self.assertEqual([c["segment_id"] for c in got["entries"][0]["candidates"]], [self.jane_trip["segment"]])
        self.assertNotIn("FCO", json.dumps(got))


class ConfidenceTests(unittest.TestCase):

    def seg(self, **kw) -> Segment:
        base = {"kind": "flight", "confirmation": "ZQ4PXD", "provider": "Example Air", "origin": "JFK", "destination": "LHR",
                "start_local": "2026-10-01T19:00", "end_local": "2026-10-02T07:10"}
        return Segment(**{**base, **kw})

    def test_exact_when_the_codes_agree_and_nothing_disagrees(self):
        got = assist.judge(FLIGHT, self.seg(confirmation="zq4 pxd", provider="Example Air Inc"))
        self.assertEqual(got["confidence"], "exact")
        self.assertEqual(got["differed"], [])
        self.assertEqual(sorted(got["agreed"]), ["confirmation", "dates", "destination", "kind", "origin", "provider"])

    def test_likely_when_the_codes_agree_but_something_differs(self):
        got = assist.judge(FLIGHT, self.seg(destination="CDG", provider="Other Air"))
        self.assertEqual(got["confidence"], "likely")
        self.assertEqual(sorted(got["differed"]), ["destination", "provider"])
        self.assertIn("confirmation", got["agreed"])

    def test_likely_without_a_code_when_the_rest_agrees(self):
        got = assist.judge({**FLIGHT, "confirmation": None}, self.seg(confirmation=None))
        self.assertEqual(got["confidence"], "likely")
        self.assertNotIn("confirmation", got["agreed"] + got["differed"])

    def test_possible_when_the_codes_differ_or_too_little_agrees(self):
        different = assist.judge(FLIGHT, self.seg(confirmation="OTHER1"))
        self.assertEqual(different["confidence"], "possible")
        self.assertIn("confirmation", different["differed"])
        later = assist.judge(FLIGHT, self.seg(confirmation="OTHER1", start_local="2026-11-01T19:00", end_local="2026-11-02T07:10"))
        self.assertEqual((later["confidence"], "dates" in later["differed"]), ("possible", True))
        thin = assist.judge({"kind": "flight", "start_local": "2026-10-01T19:00", "end_local": "2026-10-02T07:10"},
                            self.seg(confirmation=None, provider=None, origin=None, destination=None))
        self.assertEqual(thin["confidence"], "possible")
        unreadable = assist.judge({"kind": "flight", "start_local": "soon"}, self.seg(confirmation=None))
        self.assertNotIn("dates", unreadable["agreed"] + unreadable["differed"])

    def test_places_compare_as_names_too(self):
        stay = self.seg(kind="hotel", origin="The Harbour Hotel", destination=None, confirmation="HB5521")
        got = assist.judge({**STAY, "origin": "Harbour Hotel"}, stay)
        self.assertIn("origin", got["agreed"])

    def test_the_same_inputs_always_give_the_same_answer_and_no_ai_or_network_is_used(self):
        answers = []
        with mock.patch.object(tls, "urlopen", side_effect=AssertionError("went out")):
            for _ in range(3):
                answers.append(assist.judge(FLIGHT, self.seg(destination="CDG")))
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(answers[1], answers[2])
        source = (Path(assist.__file__)).read_text()
        self.assertNotRegex(source, r"import ai\b|from \. import .*\bai\b|tls|urlopen")


class MatchTests(ReviewTools):

    def test_attaching_to_a_segment_gives_it_the_code_and_the_message_and_removes_the_item(self):
        with db.session() as conn:
            seg = trips.get(conn, self.jane, self.stay["id"])["segments"][0]
        self.assertIsNone(seg["confirmation"])
        item = self.item_for_stay()
        got = self.tool(WRITE, "match_review_item", {"item_id": item, "segment_id": seg["id"]})
        self.assertEqual((got["ok"], got["segment_id"], got["trip_id"]), (True, seg["id"], self.stay["id"]))
        with db.session() as conn:
            after = trips.get(conn, self.jane, self.stay["id"])["segments"][0]
            self.assertEqual(after["confirmation"], "HB5521")
            self.assertTrue(after["has_email"])
        self.assertNotIn(item, self.left())

    def item_for_stay(self) -> int:
        with db.session() as conn:
            stored_mail.put(conn, self.jane_box, "m-stay", kept(), 5.0)
            return self.item(conn, self.jane_box, "m-stay", "match", "2026-10-20", [(STAY, [])])

    def test_adding_the_booking_to_an_existing_trip(self):
        item = self.item_for_stay()
        got = self.tool(WRITE, "match_review_item", {"item_id": item, "trip_id": self.stay["id"]})
        self.assertEqual((got["ok"], got["trip_id"]), (True, self.stay["id"]))
        self.assertNotIn(item, self.left())
        with db.session() as conn:
            self.assertEqual(len(trips.get(conn, self.jane, self.stay["id"])["segments"]), 2)

    def test_one_of_several_bookings_is_chosen_by_entry_and_the_others_stay(self):
        self.assertIn("say which one", self.refused(WRITE, "match_review_item", {"item_id": self.two_item, "segment_id": self.jane_trip["segment"]}))
        got = self.tool(WRITE, "match_review_item", {"item_id": self.two_item, "entry": 1, "segment_id": self.jane_trip["segment"]})
        self.assertTrue(got["ok"])
        self.assertIn(self.two_item, self.left())
        self.assertEqual([e["entry"] for e in self.tool(READ, "get_review_item", {"item_id": self.two_item})["entries"]], [2])
        self.assertIn("isn’t one of the bookings", self.refused(WRITE, "match_review_item", {"item_id": self.two_item, "entry": 7, "trip_id": self.stay["id"]}))

    def test_refusals_leave_everything_as_it_was(self):
        before = self.left()
        mine, sams = self.jane_trip["segment"], self.sam_trip["segment"]
        for args, words in (({"item_id": self.sams_item, "segment_id": mine}, "No such item"),
                            ({"item_id": 987654, "segment_id": mine}, "No such item"),
                            ({"item_id": self.flight_item, "segment_id": sams}, "No such segment"),
                            ({"item_id": self.flight_item, "trip_id": self.sam_trip["id"]}, "No such trip"),
                            ({"item_id": self.flight_item}, "not both and not neither"),
                            ({"item_id": self.flight_item, "segment_id": mine, "trip_id": self.jane_trip["id"]}, "not both and not neither"),
                            ({"item_id": self.generic_item, "segment_id": mine}, "no booking Waypoint read"),
                            ({"item_id": self.unread_item, "trip_id": self.jane_trip["id"]}, "no booking Waypoint read")):
            with self.subTest(args=args):
                self.assertIn(words, self.refused(WRITE, "match_review_item", args))
        self.assertEqual(self.left(), before)

    def test_it_needs_the_scope_and_the_switch_and_says_which_setting(self):
        args = {"item_id": self.flight_item, "segment_id": self.jane_trip["segment"]}
        self.assertIn("reconnect", self.refused(READ, "match_review_item", args))
        self.switch(False)
        self.assertIn("Let assistants change trips", self.refused(WRITE, "match_review_item", args))
        self.assertIn("Settings", self.refused(WRITE, "match_review_item", args))
        self.assertIn(self.flight_item, self.left())

    def test_a_household_member_cannot_match_into_a_trip_they_are_not_on(self):
        with db.session() as conn:
            conn.execute(update(Mailbox).where(Mailbox.id == self.jane_box).values(share_review=True))
        self.assertIn("No such", self.refused(WRITE, "match_review_item", {"item_id": self.flight_item, "segment_id": self.jane_trip["segment"]}, sub="u-sam"))
        self.assertIn(self.flight_item, self.left())


class CreateTests(ReviewTools):

    def test_a_suggestion_becomes_a_segment_with_overrides_and_the_message_stays_with_it(self):
        got = self.tool(WRITE, "create_segment_from_review_item",
                        {"item_id": self.generic_item, "fields": {"details": {"room": "310"}, "confirmation": "SEA777"}})
        self.assertEqual((got["kind"], got["origin"], got["confirmation"], got["source"]), ("hotel", "Seaside Inn", "SEA777", "manual"))
        self.assertEqual(got["details"], {"address": "9 Beach Road", "room": "310"})
        self.assertTrue(got["has_email"])
        self.assertNotIn(self.generic_item, self.left())
        self.assertEqual(self.messages(), 5)

    def test_a_read_booking_becomes_a_segment_in_the_trip_it_falls_into(self):
        got = self.tool(WRITE, "create_segment_from_review_item", {"item_id": self.flight_item, "fields": {"details": {"seat": "22A"}}})
        self.assertEqual((got["kind"], got["confirmation"], got["source"]), ("flight", "ZQ4PXD", "email"))
        self.assertEqual(got["details"], {"flight_number": "EA112", "seat": "22A"})
        self.assertNotIn(self.flight_item, self.left())

    def test_with_several_bookings_it_asks_which_and_leaves_the_rest(self):
        self.assertIn("say which one", self.refused(WRITE, "create_segment_from_review_item", {"item_id": self.two_item}))
        self.assertIn("isn’t one of the bookings", self.refused(WRITE, "create_segment_from_review_item", {"item_id": self.two_item, "entry": 9}))
        got = self.tool(WRITE, "create_segment_from_review_item", {"item_id": self.two_item, "entry": 2})
        self.assertEqual((got["kind"], got["confirmation"]), ("hotel", "ZZ9999"))
        self.assertEqual([e["entry"] for e in self.tool(READ, "get_review_item", {"item_id": self.two_item})["entries"]], [1])

    def test_an_item_with_nothing_read_is_filled_in_by_hand(self):
        fields = {"kind": "car", "provider": "Hertz", "origin": "Denver Airport", "destination": "Denver Airport",
                  "start_local": "2026-12-02T15:00", "end_local": "2026-12-08T10:00", "start_zone": "America/Denver"}
        got = self.tool(WRITE, "create_segment_from_review_item", {"item_id": self.unread_item, "fields": fields})
        self.assertEqual((got["kind"], got["provider"]), ("car", "Hertz"))
        self.assertNotIn(self.unread_item, self.left())

    def test_the_same_validation_as_adding_by_hand_and_a_refusal_changes_nothing(self):
        before = (self.left(), self.messages())
        for args, words in (({"item_id": self.unread_item}, "Choose what this is"),
                            ({"item_id": self.generic_item, "fields": {"end_local": "2026-11-20T10:00"}}, "ends before it starts"),
                            ({"item_id": self.generic_item, "fields": {"start_zone": "Mars/Base"}}, "time zone"),
                            ({"item_id": self.generic_item, "fields": {"manage_url": "ftp://x"}}, "https://"),
                            ({"item_id": self.generic_item, "fields": {"address": "1 Road"}}, "isn't a field of a segment"),
                            ({"item_id": self.sams_item, "fields": {}}, "No such item"),
                            ({"item_id": 987654, "fields": {}}, "No such item")):
            with self.subTest(args=args):
                self.assertIn(words, self.refused(WRITE, "create_segment_from_review_item", args))
        self.assertEqual((self.left(), self.messages()), before)

    def test_it_needs_the_scope_and_the_switch(self):
        self.assertIn("reconnect", self.refused(READ, "create_segment_from_review_item", {"item_id": self.generic_item}))
        self.switch(False)
        self.assertIn("switched off", self.refused(WRITE, "create_segment_from_review_item", {"item_id": self.generic_item}))
        self.assertIn(self.generic_item, self.left())


class DismissTests(ReviewTools):

    def test_dismissing_removes_the_item_and_its_stored_message(self):
        got = self.tool(WRITE, "dismiss_review_item", {"item_id": self.unread_item, "reason": "not_travel", "note": "a newsletter"})
        self.assertEqual(got, {"ok": True, "reason": "not_travel"})
        self.assertNotIn(self.unread_item, self.left())
        self.assertEqual(self.messages(), 4)

    def test_a_message_a_booking_was_made_from_is_kept(self):
        with db.session() as conn:
            stored_mail.link(conn, self.jane_trip["segment"], self.jane_box, "m-unread")
        self.tool(WRITE, "dismiss_review_item", {"item_id": self.unread_item, "reason": "duplicate"})
        self.assertEqual(self.messages(), 5)

    def test_the_reason_is_a_fixed_list_and_the_note_is_short(self):
        for args, words in (({"item_id": self.generic_item, "reason": "boring"}, "Give a reason"),
                            ({"item_id": self.generic_item}, "Give a reason"),
                            ({"item_id": self.generic_item, "reason": "other", "note": "x" * 201}, "too long"),
                            ({"item_id": self.generic_item, "reason": "other", "note": 5}, "as text"),
                            ({"item_id": self.sams_item, "reason": "other"}, "No such item"),
                            ({"item_id": 987654, "reason": "other"}, "No such item")):
            with self.subTest(args=args):
                self.assertIn(words, self.refused(WRITE, "dismiss_review_item", args))
        self.assertIn(self.generic_item, self.left())

    def test_every_fixed_reason_dismisses(self):
        with db.session() as conn:
            ids = [self.item(conn, self.jane_box, f"d-{r}", "incomplete", None) for r in assist.DISMISS_REASONS]
        for item, reason in zip(ids, assist.DISMISS_REASONS, strict=True):
            self.assertEqual(self.tool(WRITE, "dismiss_review_item", {"item_id": item, "reason": reason, "note": "plain words"})["reason"], reason)
        self.assertFalse(set(ids) & self.left())

    def test_it_needs_the_scope_and_the_switch_and_says_which_setting(self):
        args = {"item_id": self.generic_item, "reason": "not_travel"}
        self.assertIn("reconnect", self.refused(READ, "dismiss_review_item", args))
        self.switch(False)
        self.assertIn("“Let assistants change trips”", self.refused(WRITE, "dismiss_review_item", args))
        self.assertIn(self.generic_item, self.left())

    def test_only_dismissing_is_marked_destructive_among_the_new_tools(self):
        new = {"match_review_item", "create_segment_from_review_item", "dismiss_review_item", "list_review_items", "get_review_item"}
        marked = {t["name"] for t in mcp_server.ALL_TOOLS if t["name"] in new and t.get("destructive")}
        self.assertEqual(marked, {"dismiss_review_item"})
        by = {t["name"]: t for t in mcp_server.ALL_TOOLS}
        self.assertIn("Destructive", by["dismiss_review_item"]["description"])
        for name in new - {"dismiss_review_item"}:
            self.assertNotIn("Destructive", by[name]["description"])
        for name in ("match_review_item", "create_segment_from_review_item", "dismiss_review_item"):
            self.assertIn("Ask the person", by[name]["description"])
            self.assertEqual(by[name]["needs"], ("write",))
        for name in ("list_review_items", "get_review_item"):
            self.assertEqual(by[name]["needs"], ("read",))
            self.assertFalse(by[name].get("write"))

    def test_no_new_tool_removes_a_segment_trip_person_or_mailbox(self):
        with db.session() as conn:
            counts = [int(conn.execute(select(func.count()).select_from(t)).scalar() or 0) for t in (Segment, Mailbox)]
        for name, args in (("match_review_item", {"item_id": self.flight_item, "segment_id": self.jane_trip["segment"]}),
                           ("create_segment_from_review_item", {"item_id": self.generic_item}),
                           ("dismiss_review_item", {"item_id": self.unread_item, "reason": "other"})):
            self.assertIsInstance(self.tool(WRITE, name, args), dict)
        with db.session() as conn:
            self.assertEqual(int(conn.execute(select(func.count()).select_from(Mailbox)).scalar() or 0), counts[1])
            self.assertEqual(int(conn.execute(select(func.count()).select_from(Segment)).scalar() or 0), counts[0] + 1)


class PrivacyTests(ReviewTools):

    def everything(self) -> None:
        self.linked_message()
        for scopes in (READ, WRITE):
            self.tool(scopes, "list_review_items", {})
            self.tool(scopes, "list_review_items", {"limit": 1})
            for item in (self.flight_item, self.two_item, self.generic_item, self.unread_item, self.sams_item):
                self.tool(scopes, "get_review_item", {"item_id": item})
        self.tool(EVERYTHING, "match_review_item", {"item_id": self.flight_item, "segment_id": self.jane_trip["segment"]})
        self.tool(EVERYTHING, "create_segment_from_review_item", {"item_id": self.generic_item})
        self.tool(EVERYTHING, "dismiss_review_item", {"item_id": self.unread_item, "reason": "other", "note": "no text"})

    def linked_message(self) -> None:
        with db.session() as conn:
            stored_mail.link(conn, self.jane_trip["segment"], self.jane_box, "m-flight")

    def test_the_subject_and_body_are_never_printed_logged_sent_or_in_the_clear(self):
        with no_leaks(self, SUBJECT, BODY, database=self.path), no_leaks(self, SENDER, PARSED):
            self.everything()

    def test_under_read_the_subject_and_body_never_appear_in_any_response(self):
        self.linked_message()
        seen = []
        for name, args in (("list_review_items", {}), ("get_review_item", {"item_id": self.flight_item}),
                           ("get_review_item", {"item_id": self.generic_item}), ("get_review_item", {"item_id": self.unread_item}),
                           ("get_trip", {"trip_id": self.jane_trip["id"]}), ("upcoming", {"days": 365}),
                           ("call_endpoint", {"method": "GET", "path": "/api/assistant/review"})):
            seen.append(json.dumps(self.tool(WRITE, name, args), ensure_ascii=False))
        for text in seen:
            self.assertNotIn(SUBJECT, text)
            self.assertNotIn(BODY, text)
        self.assertNotIn(SUBJECT, mcp_server._about(mcp_http.fetch_for(self.access(WRITE))))

    def test_no_loyalty_number_is_in_any_review_response(self):
        with db.session() as conn:
            conn.execute(update(ReviewItem).where(ReviewItem.id == self.flight_item).values(
                matches=json.dumps([{"id": 1, "booking": {**FLIGHT, "loyalty": test_mcp.JANE_NUMBER, "details": {**FLIGHT["details"], "ff": test_mcp.JANE_NUMBER}},
                                     "candidates": [self.jane_trip["segment"]]}])))
        with no_leaks(self, test_mcp.JANE_NUMBER, test_mcp.SAM_NUMBER):
            text = json.dumps([self.tool(EVERYTHING, "get_review_item", {"item_id": self.flight_item}),
                               self.tool(EVERYTHING, "list_review_items", {})])
        self.assertNotIn(test_mcp.JANE_NUMBER, text)
        self.assertNotIn(test_mcp.JANE_NUMBER[-4:], text)

    def test_responses_are_bounded_and_carry_no_markup(self):
        long = "y" * 5000
        with db.session() as conn:
            conn.execute(update(ReviewItem).where(ReviewItem.id == self.flight_item).values(
                matches=json.dumps([{"id": 1, "booking": {**FLIGHT, "provider": long, "details": {"address": long, "phone": long, "cabin": long}},
                                     "candidates": []}])))
        got = self.tool(READ, "get_review_item", {"item_id": self.flight_item})["entries"][0]["booking"]
        self.assertEqual(len(got["provider"]), assist.MAX_FIELD)
        self.assertEqual(len(got["address"]), trips.ADDRESS_LIMIT)
        self.assertEqual(len(got["phone"]), assist.MAX_FIELD)
        self.assertEqual(len(got["details"]["cabin"]), assist.MAX_FIELD)


class RouteTests(ReviewTools):

    def call(self, handler, *args, **kwargs):
        _current.user = {"sub": "u-jane"}
        try:
            with db.session() as conn:
                return handler(conn, *args, **kwargs)
        finally:
            _current.user = None

    def test_the_routes_refuse_what_they_cannot_read(self):
        for q, words in (({"has_match": ["maybe"]}, "has_match"), ({"reason": ["spam"]}, "reason"), ({"limit": ["x"]}, "limit"),
                         ({"mailbox": ["abc"]}, "mailbox"), ({"since": ["x"]}, "since")):
            with self.subTest(q=q), self.assertRaisesRegex(ApiError, words):
                self.call(assistant_api.api_assistant_review, q, {})

    def test_the_body_routes_refuse_what_they_cannot_read(self):
        item = str(self.flight_item)
        for handler, body, words in ((assistant_api.api_assistant_review_match, {"entry": "x"}, "entry"),
                                     (assistant_api.api_assistant_review_match, {"segment_id": "x"}, "No such segment"),
                                     (assistant_api.api_assistant_review_create, {"entry": "x"}, "entry"),
                                     (assistant_api.api_assistant_review_dismiss, {"reason": "other", "note": 5}, "text")):
            with self.subTest(body=body), self.assertRaisesRegex(ApiError, words):
                self.call(handler, {}, body, item)
        for handler in (assistant_api.api_assistant_review_item, assistant_api.api_assistant_review_match,
                        assistant_api.api_assistant_review_create, assistant_api.api_assistant_review_dismiss):
            with self.assertRaisesRegex(ApiError, "No such item"):
                self.call(handler, {}, {"reason": "other"}, "x")



class SegmentAddressTests(ReviewTools):

    CAR = {"kind": "car", "provider": "Hertz", "origin": "Denver Airport", "destination": "Denver Airport", "start_local": "2026-12-02T15:00",
           "end_local": "2026-12-08T10:00", "start_zone": "America/Denver", "end_zone": "America/Denver",
           "details": {"car_class": "SUV", "vehicle": "Ford"}}
    CRUISE = {"kind": "cruise", "provider": "Acme Cruises", "origin": "Miami", "destination": "Miami", "start_local": "2026-12-02T15:00",
              "end_local": "2026-12-08T10:00", "start_zone": "America/New_York", "end_zone": "America/New_York",
              "details": {"ship": "Sea Star", "deck": "7", "room": "7001"}}

    def test_an_address_added_to_a_rental_or_a_cruise_keeps_the_rest_of_its_details(self):
        for base in (self.CAR, self.CRUISE):
            seg = self.tool(WRITE, "add_segment", {"fields": base})
            got = self.tool(WRITE, "update_segment", {"segment_id": seg["id"], "fields": {"details": {"address": "123 Main St, Miami FL"}}})
            self.assertEqual(got["details"], {**base["details"], "address": "123 Main St, Miami FL"})

    def test_a_detail_is_cleared_by_sending_it_empty(self):
        seg = self.tool(WRITE, "add_segment", {"fields": self.CRUISE})
        got = self.tool(WRITE, "update_segment", {"segment_id": seg["id"], "fields": {"details": {"deck": "", "address": "Pier 4"}}})
        self.assertEqual(got["details"], {"ship": "Sea Star", "room": "7001", "address": "Pier 4"})

    def test_an_address_sent_outside_details_is_refused_not_dropped(self):
        seg = self.tool(WRITE, "add_segment", {"fields": self.CAR})
        for name, args in (("update_segment", {"segment_id": seg["id"], "fields": {"address": "1 Road"}}),
                           ("add_segment", {"fields": {**self.CAR, "address": "1 Road"}})):
            got = self.refused(WRITE, name, args)
            self.assertIn("address isn't a field of a segment, so nothing was changed", got)
            self.assertIn("inside details", got)
        self.assertRegex(self.refused(WRITE, "update_segment", {"segment_id": seg["id"], "fields": "address"}), "object")

    def test_a_field_the_form_rejects_comes_back_as_the_reason(self):
        seg = self.tool(WRITE, "add_segment", {"fields": self.CAR})
        self.assertIn("Details can hold only", self.refused(WRITE, "update_segment", {"segment_id": seg["id"], "fields": {"details": {"street": "x"}}}))
        self.assertIn("details", self.refused(WRITE, "update_segment", {"segment_id": seg["id"], "fields": {"details": "1 Road"}}))

    def test_the_connection_that_cannot_write_is_told_why_and_what_to_do(self):
        seg = self.tool(WRITE, "add_segment", {"fields": self.CAR})
        args = {"segment_id": seg["id"], "fields": {"details": {"address": "x"}}}
        self.assertIn("reconnect Waypoint in the assistant and allow “Change trips”", self.refused(READ, "update_segment", args))
        self.switch(False)
        got = self.refused(WRITE, "update_segment", args)
        self.assertIn("Turn on “Let assistants change trips” in Waypoint under Settings", got)
        about = mcp_server._about(mcp_http.fetch_for(self.access(WRITE)))
        self.assertIn("Everything is read-only. Changes are switched off. Turn on “Let assistants change trips”", about)
        self.assertNotIn("update_segment", {t["name"] for t in mcp_server.offered(mcp_http.fetch_for(self.access(WRITE)))})
        self.assertIn("this connection can only read", mcp_server._about(mcp_http.fetch_for(self.access(READ))).replace("This", "this", 1))

    def test_a_segment_that_is_not_theirs_is_not_found(self):
        self.assertIn("No such", self.refused(WRITE, "update_segment", {"segment_id": self.sam_trip["segment"], "fields": {"details": {"address": "x"}}}))


class EveryNewRouteTests(unittest.TestCase):

    def test_every_new_route_is_for_signed_in_people_and_none_is_blocked_for_the_wrong_reason(self):
        from waypoint.server import ROUTES
        mine = [(m, p) for m, p, *_ in ROUTES if p.startswith("/api/assistant/")]
        self.assertEqual(len(mine), 5)
        for m, p in mine:
            self.assertFalse(mcp_access.blocked(p), p)
            self.assertIsNotNone(mcp_http.needs(m, p), p)


if __name__ == "__main__":
    unittest.main()
