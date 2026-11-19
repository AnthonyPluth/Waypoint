import json
import sys
import unittest
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.test_mail_ai import BODY, FOOTER, GOOD, IDS, QUOTED, REPLY_CANARY, ScanAiCase
from tests.test_mail_followup import CODE, STAYS, follow
from tests.test_mail_scan import NOW, eml, plain_mail, refusing_ai_hosts
from waypoint import tls
from waypoint.domain.mail import ai, autoask, ingest, review, scan
from waypoint.server import routes
from waypoint.storage import db
from waypoint.storage.models import Mailbox, ReviewItem, ScannedMessage

DATE = b"Sun, 18 Oct 2026 09:10:00 -0400"
DAYS = {"new": b"Sun, 18 Oct 2026 09:10:00 -0400", "mid": b"Sat, 17 Oct 2026 09:10:00 -0400", "old": b"Fri, 16 Oct 2026 09:10:00 -0400"}


class AutoCase(ScanAiCase):
    def dated(self, *names):
        for name in names:
            self.add_mail(f"msg-{name}", eml("no_markup_ids").replace(DATE, DAYS[name]))

    def waiting(self):
        return self.read(lambda conn: sorted(conn.execute(select(ReviewItem.message_id).where(ReviewItem.auto_state == "waiting")).scalars()))

    def suggested(self):
        return self.read(lambda conn: sorted(conn.execute(select(ReviewItem.message_id).where(ReviewItem.suggestion.is_not(None))).scalars()))

    def tries(self):
        return self.read(lambda conn: conn.execute(select(ReviewItem.auto_tries)).scalar())


class SavedAddressTests(AutoCase):
    def test_a_scan_reaches_the_ai_only_while_an_ollama_address_is_saved(self):
        for saved, asked in ((False, 0), (True, 1)):
            with self.subTest(saved=saved):
                self.fake.reset()
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                    conn.execute(ScannedMessage.__table__.delete())
                self.turn_off()
                if saved:
                    self.turn_on()
                self.put("no_markup_ids")
                with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=bool(asked)):
                    result = self.scan()
                self.assertEqual((result.state, result.review), ("done", 1))
                self.assertEqual(len(self.fake.requests), asked)
                self.assertEqual((self.waiting(), len(self.suggested())), ([], asked))
                self.assertEqual(scan.summary(self.mailbox).ai_asked, asked)

    def test_with_an_address_saved_a_qualifying_message_gets_its_suggestion_during_the_scan(self):
        self.turn_on()
        self.put("no_markup_ids")
        self.assertEqual(self.scan().review, 1)
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["suggestion_error"], item["auto_read"]), ([GOOD], None, True))
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(self.segments(), [])
        self.assertEqual(self.waiting(), [])

    def test_the_switch_is_read_before_every_message_so_turning_it_off_stops_the_sending(self):
        self.turn_on()
        self.dated("new", "mid", "old")
        self.fake.on_request = lambda n: self.turn_off() if n == 1 else None
        self.assertEqual(self.scan().review, 3)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(self.suggested(), ["msg-new"])

    def test_only_a_scan_can_ask_the_ai(self):
        self.assertFalse([path for _, path, _ in routes.ROUTES if path.startswith("/api/review") and path.endswith("/suggest")])
        self.assertFalse(hasattr(scan, "suggest_now"))
        self.assertEqual([n for n in ("NoAi", "NotAskable") if hasattr(scan, n)], [])

    def test_turning_the_ai_off_stops_automatic_reading(self):
        self.turn_on()
        self.assertTrue(self.read(lambda conn: autoask.active(conn)))
        self.turn_off()
        self.assertFalse(self.read(lambda conn: autoask.active(conn)))

    def test_an_old_automatic_choice_in_the_settings_is_ignored_whatever_it_holds(self):
        for old in (None, "1", "2", "junk"):
            with self.subTest(old=old):
                self.fake.reset()
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                    conn.execute(ScannedMessage.__table__.delete())
                    db.set_setting(conn, "ai_auto", old)
                self.turn_on()
                self.put("no_markup_ids")
                self.assertEqual(self.scan().review, 1)
                self.assertEqual(len(self.fake.requests), 1)
                self.turn_off()
                self.fake.reset()
                self.assertEqual(self.scan(again=True).state, "done")
                self.assertEqual(self.fake.requests, [])

    def test_the_automatic_request_is_made_by_the_one_module_that_talks_to_the_ai(self):
        self.turn_on()
        self.put("no_markup_ids")
        callers = []
        real = tls.urlopen

        def recording(req, *args, **kwargs):
            if self.fake.url in getattr(req, "full_url", str(req)):
                callers.append(sys._getframe(1).f_globals["__name__"])
            return real(req, *args, **kwargs)

        with mock.patch.object(tls, "urlopen", recording):
            self.scan()
        self.assertEqual(callers, ["waypoint.domain.mail.ai"])

class WhoIsAskedTests(AutoCase):
    def test_shopping_codes_newsletters_replies_and_weak_mail_are_never_sent(self):
        self.turn_on()
        self.add_mail("shop", plain_mail("Shop <orders@shop.example>", "Your order has shipped", f"Tracking number 12345. {BODY}"))
        self.add_mail("code", plain_mail("Bank <alerts@bank.example>", "Your verification code", f"Your one-time code is 123456. {BODY}"))
        self.add_mail("news", plain_mail("Deals <hi@deals.example>", "Our weekly newsletter", f"Big sale, 50% off. {BODY}"))
        self.add_mail("reply", plain_mail("Pat <pat@friend.example>", "Re: your hotel booking", f"Sounds good. {BODY}"))
        self.add_mail("weak", plain_mail("Pat <pat@somewhere.example>", "Your hotel booking", f"Thanks for choosing us. {BODY}"))
        with no_leaks(self, BODY, database=self.path):
            result = self.scan()
        self.assertEqual((result.review, result.skipped), (0, 5))
        self.assertEqual(self.fake.requests, [])

    STAY_PRICE = {"kind": "hotel", "provider": "Harbour Hotel", "confirmation": "H88231", "origin": "Harbour Hotel",
                  "start_local": "2026-11-21T15:00", "end_local": "2026-11-27T10:00", "start_zone": "Europe/London",
                  "end_zone": "Europe/London", "price_minor": 48000, "price_currency": "USD"}

    def test_a_message_a_reader_made_a_booking_from_is_sent_while_the_booking_lacks_a_detail_and_the_answer_only_fills_it_in(self):
        self.turn_on()
        reply = {**self.STAY_PRICE, "start_local": "2026-11-22T15:00"}
        self.put("hotel_jsonld")
        with mock.patch.object(ai, "suggest", return_value=ai.Reading([reply])) as asked:
            self.assertEqual(self.scan().bookings, 1)
        [stay] = self.segments()
        self.assertEqual(asked.call_count, 1)
        self.assertEqual((stay["origin"], stay["start_local"], stay["price"]["amount_minor"]), ("Harbour Hotel", "2026-11-21T15:00", 48000))

    def test_an_answer_never_adds_a_traveller_to_the_booking(self):
        self.turn_on()
        reply = {**self.STAY_PRICE, "travelers": [{"name": "Sam Doe", "seat": "1A"}]}
        self.put("hotel_jsonld")
        with mock.patch.object(ai, "suggest", return_value=ai.Reading([reply])):
            self.scan()
        [stay] = self.segments()
        self.assertEqual(stay["price"]["amount_minor"], 48000)
        self.assertNotIn("Sam Doe", [t["name"] for t in stay["travelers"]])

    def test_a_duplicate_of_a_booking_that_already_has_everything_is_not_sent(self):
        self.turn_on()
        self.put("hotel_jsonld")
        with mock.patch.object(ai, "suggest", return_value=ai.Reading([self.STAY_PRICE])) as asked:
            self.scan()
            self.put("hotel_jsonld", as_id="msg-again")
            self.scan(now=NOW + 60)
        self.assertEqual((asked.call_count, len(self.segments())), (1, 1))

    def test_an_answer_for_a_booking_the_household_does_not_hold_adds_nothing(self):
        self.turn_on()
        self.put("hotel_jsonld")
        with mock.patch.object(ai, "suggest", return_value=ai.Reading([{**self.STAY_PRICE, "confirmation": "ZZ9999"}])):
            self.scan()
        [stay] = self.segments()
        self.assertEqual(stay["price"], None)

    def test_an_empty_answer_changes_nothing(self):
        self.turn_on()
        self.put("hotel_jsonld")
        with mock.patch.object(ai, "suggest", return_value=ai.Reading([])):
            self.scan()
        self.assertEqual([s["price"] for s in self.segments()], [None])

    def test_an_answer_missing_what_filing_needs_changes_nothing(self):
        self.turn_on()
        self.put("hotel_jsonld")
        incomplete = {k: v for k, v in self.STAY_PRICE.items() if k != "confirmation"}
        with mock.patch.object(ai, "suggest", return_value=ai.Reading([incomplete])):
            self.scan()
        self.assertEqual([s["price"] for s in self.segments()], [None])

    def test_no_time_left_in_the_scan_means_no_request(self):
        self.turn_on()
        self.put("hotel_jsonld")
        with mock.patch.object(scan, "BUDGET", 0), mock.patch.object(ai, "suggest") as asked:
            self.assertEqual(self.scan().bookings, 1)
        self.assertEqual(asked.call_count, 0)

    def test_a_booking_with_nothing_missing_is_never_sent(self):
        self.turn_on()
        self.put("flight_jsonld", "hotel_jsonld")
        with mock.patch.object(ingest, "segments_lack_details", return_value=False), mock.patch.object(ai, "suggest") as asked:
            self.assertEqual(self.scan().bookings, 2)
        self.assertEqual(asked.call_count, 0)

    def test_a_follow_up_of_a_booking_the_household_holds_is_never_sent(self):
        self.turn_on()
        self.put("hotel_jsonld")
        self.scan()
        self.fake.reset()
        self.add_mail("m-receipt", follow("Your receipt for your stay", f"Thanks. Your stay at the hotel is paid.\nReservation number: {CODE} {BODY}", STAYS))
        with no_leaks(self, BODY, database=self.path):
            result = self.scan(now=NOW + 60)
        self.assertEqual((result.review, self.scanned()["m-receipt"]), (0, "follow-up"))
        self.assertEqual(self.fake.requests, [])

    def test_a_picked_labels_message_counts_as_a_strong_signal(self):
        self.turn_on()
        raw = plain_mail("Pat <pat@friend.example>", "Notes", f"Dinner on Friday. {BODY}")
        self.google.mail["j1"] = raw
        self.google.label_mail["Label_1"] = ["j1"]
        self.google.mailbox_labels.append({"id": "Label_1", "name": "Trips", "type": "user"})
        with db.session() as conn:
            conn.execute(Mailbox.__table__.update().values(scan_labels=scan.encode_labels(["Label_1"])))
        self.fake.content = json.dumps({"bookings": []})
        self.scan()
        self.assertEqual(len(self.fake.requests), 1)

    def test_a_message_with_travel_markup_but_no_booking_is_sent(self):
        self.turn_on()
        self.fake.content = json.dumps({"bookings": []})
        self.put("incomplete")
        self.assertEqual(self.scan().review, 1)
        self.assertEqual(len(self.fake.requests), 1)


class PriceAsNameTests(AutoCase):
    STAY = {"kind": "hotel", "provider": "Harbour Hotel", "confirmation": "H88231", "origin": "Harbour Hotel", "start_local": "2026-11-21T15:00",
            "end_local": "2026-11-24T11:00", "start_zone": "Europe/London", "end_zone": "Europe/London", "address": "1 Quay Street, London"}
    TEXT = ("Your hotel reservation is confirmed.\nReservation H88231 at Harbour Hotel, 1 Quay Street, London.\nHotel: $401.30\n"
            f"Check-in: November 21, 2026\nCheck-out: November 24, 2026\nTotal: $401.30\n{BODY}\n")

    def chase(self):
        self.add_mail("chase", plain_mail("Card Travel <travel@card-travel.example>", "Your reservation is confirmed", self.TEXT))

    def test_the_price_is_not_filed_as_the_hotel_and_the_mail_waits_in_review_with_the_ai_off(self):
        self.turn_off()
        self.chase()
        with no_leaks(self, BODY, database=self.path):
            result = self.scan()
        self.assertEqual((result.bookings, result.review, self.segments(), self.fake.requests), (0, 1, [], []))

    def test_the_ai_fills_in_the_hotel_once_an_address_is_saved_with_no_other_setting(self):
        self.turn_on()
        self.fake.content = json.dumps(self.STAY)
        self.chase()
        with no_leaks(self, BODY, database=self.path, sent_ok=True):
            self.scan()
        self.assertEqual(self.items(), [])
        [stay] = self.segments()
        self.assertEqual((stay["kind"], stay["origin"], stay["confirmation"], stay["start_local"], stay["end_local"], stay["details"].get("address")),
                         ("hotel", "Harbour Hotel", "H88231", "2026-11-21T15:00", "2026-11-24T11:00", "1 Quay Street, London"))
        self.assertEqual(len(self.fake.requests), 1)
        self.assertIn("Hotel: $401.30", self.fake.requests[0][2]["messages"][1]["content"])

    def test_the_fixed_readers_own_dates_are_kept_when_the_ai_says_otherwise(self):
        self.turn_on()
        self.fake.content = json.dumps({**self.STAY, "start_local": "2026-12-05T15:00", "end_local": "2026-12-08T11:00"})
        self.chase()
        self.scan()
        [stay] = self.segments()
        self.assertEqual((stay["start_local"], stay["end_local"], stay["confirmation"]), ("2026-11-21T15:00", "2026-11-24T11:00", "H88231"))

    def test_a_failed_ai_call_keeps_what_the_fixed_reader_found_in_review_and_the_scan_goes_on(self):
        self.turn_on()
        self.fake.status = 500
        self.chase()
        with no_leaks(self, BODY, database=self.path, sent_ok=True):
            result = self.scan()
        self.assertEqual((result.state, self.segments()), ("done", []))
        [item] = self.items()
        self.assertEqual((item["suggestion_error"], item["auto_read"], [s.get("kind") for s in item["suggestions"]]), (ai.FAILED, False, ["hotel"]))
        self.assertEqual(self.waiting(), ["chase"])


class EveryMessageTests(AutoCase):
    def test_every_qualifying_message_is_asked_in_one_scan_with_no_cap(self):
        self.turn_on()
        for n in range(25):
            self.add_mail(f"msg-{n}", eml("no_markup_ids"))
        self.assertEqual(self.scan().review, 25)
        self.assertEqual((len(self.fake.requests), len(self.suggested()), self.waiting()), (25, 25, []))
        self.assertEqual(scan.summary(self.mailbox).ai_asked, 25)

    def test_the_most_a_failing_item_is_asked_is_three_times(self):
        self.assertEqual(autoask.TRIES, 3)

    def test_an_item_that_was_in_review_when_the_address_was_saved_is_asked_by_the_next_scan(self):
        self.turn_off()
        self.put("no_markup_ids")
        self.scan()
        self.assertEqual((self.fake.requests, self.waiting()), ([], []))
        self.turn_on()
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=True):
            self.scan(now=NOW + 60)
        self.assertEqual(len(self.fake.requests), 1)
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["suggestion_error"], item["auto_read"]), ([GOOD], None, True))
        self.assertEqual(self.waiting(), [])


class RequeueTests(AutoCase):
    def stranded(self, name="m-x", reason="no_markup", outcome=None, mail=None, error=None, suggestions=None):
        self.google.mail[name] = mail or eml("no_markup_ids")

        def hold(conn):
            review.add(conn, self.mailbox, name, "example-air.example", "2026-10-17", reason, NOW)
            scan._record(conn, self.mailbox, name, outcome or scan.UNREADABLE, NOW)
            if suggestions or error:
                review.set_suggestions(conn, self.mailbox, name, suggestions or [], error)
        self.read(hold)

    def test_items_waiting_when_the_address_is_saved_are_queued_and_read_by_the_next_scan(self):
        self.stranded("m-a")
        self.stranded("m-b", reason="incomplete")
        self.turn_off()
        self.scan()
        self.assertEqual((self.fake.requests, self.waiting()), ([], []))
        self.turn_on()
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=True):
            self.scan(now=NOW + 60)
        self.assertEqual((len(self.fake.requests), self.waiting(), self.suggested()), (2, [], ["m-a", "m-b"]))

    def test_an_item_whose_tries_ran_out_is_queued_again_by_a_later_scan_and_read_once_the_service_answers(self):
        self.turn_on()
        self.fake.status = 500
        self.put("no_markup_ids")
        for later in range(3):
            self.scan(now=NOW + 60 * later)
        self.assertEqual((len(self.fake.requests), self.tries(), self.waiting()), (3, autoask.TRIES, []))
        self.fake.status = 200
        self.scan(now=NOW + 300)
        [item] = self.items()
        self.assertEqual((len(self.fake.requests), item["suggestions"], item["suggestion_error"], item["auto_read"]), (4, [GOOD], None, True))

    def test_an_item_the_ai_could_not_answer_after_its_own_retry_is_queued_again_by_a_later_scan(self):
        self.turn_on()
        self.fake.content = "not json"
        self.put("no_markup_ids")
        self.scan()
        self.assertEqual(self.waiting(), [])
        self.fake.content = json.dumps(GOOD)
        self.scan(now=NOW + 60)
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["auto_read"]), ([GOOD], True))

    def test_an_item_the_ai_found_no_booking_in_is_not_queued_again(self):
        self.turn_on()
        self.fake.content = json.dumps({"bookings": []})
        self.put("no_markup_ids")
        self.scan()
        self.assertEqual(len(self.fake.requests), 1)
        for later in range(1, 4):
            self.scan(now=NOW + 60 * later)
        self.assertEqual((len(self.fake.requests), self.items()[0]["suggestion_error"]), (1, ai.NO_BOOKING))

    def test_an_item_that_already_holds_an_ai_suggestion_is_not_queued_again(self):
        self.turn_on()
        self.put("no_markup_ids")
        self.scan()
        self.assertEqual(len(self.fake.requests), 1)
        self.scan(now=NOW + 60)
        self.assertEqual(len(self.fake.requests), 1)

    def test_what_the_scan_would_not_send_is_never_queued(self):
        self.turn_on()
        self.stranded("m-weak", mail=plain_mail("Pat <pat@somewhere.example>", "Your hotel booking", f"Thanks for choosing us. {BODY}"))
        self.stranded("m-match", reason="match")
        self.stranded("m-booked", reason="incomplete", outcome=scan.BOOKING)
        self.stranded("m-hold", error=ai.NO_BOOKING)
        self.stranded("m-said", suggestions=[GOOD])
        with no_leaks(self, BODY, database=self.path):
            self.scan()
            self.scan(now=NOW + 60)
        self.assertEqual((self.fake.requests, self.waiting(), self.suggested()), ([], [], ["m-said"]))
        self.assertEqual(self.read(lambda conn: conn.execute(select(ReviewItem.auto_tries).where(ReviewItem.message_id == "m-weak")).scalar()), autoask.CAP)

    def test_a_message_the_scan_would_send_from_its_head_is_queued_though_its_item_is_old(self):
        self.turn_on()
        self.stranded("m-strong", mail=plain_mail("Example Air <hi@example-air.example>", "Your flight itinerary", f"Flight QW 410. {BODY}"))
        self.scan()
        self.assertGreaterEqual(len(self.fake.requests), 1)
        self.assertEqual(self.waiting(), [])

    def test_nothing_is_queued_while_no_address_is_saved(self):
        self.turn_off()
        self.stranded()
        with refusing_ai_hosts(self, []):
            self.scan()
        self.assertEqual(self.waiting(), [])

    def test_a_message_gone_from_the_mailbox_is_left_as_it_is(self):
        self.turn_on()
        self.stranded()
        del self.google.mail["m-x"]
        self.assertEqual(self.scan().state, "done")
        self.assertEqual((self.fake.requests, len(self.items())), ([], 1))


class FailureTests(AutoCase):
    def test_a_reply_that_stays_unusable_after_thinking_is_asked_for_again_by_later_scans_for_three_rounds_only(self):
        self.turn_on()
        self.fake.content = "not json"
        self.put("no_markup_ids")
        self.scan()
        self.assertEqual((len(self.fake.requests), self.waiting(), self.tries()), (2, [], autoask.TRIES))
        for later in range(1, 8):
            self.scan(now=NOW + 60 * later)
        self.assertEqual((len(self.fake.requests), self.waiting(), self.tries()), (2 * autoask.ROUNDS, [], autoask.CAP))
        self.assertEqual(self.items()[0]["suggestion_error"], ai.BAD_REPLY)

    def test_a_failed_request_leaves_the_item_with_the_note_and_is_asked_for_nine_tries_in_all(self):
        self.turn_on()
        self.fake.status = 500
        self.put("no_markup_ids")
        self.assertEqual(self.scan().review, 1)
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["suggestion_error"], item["auto_read"]), ([], ai.FAILED, False))
        self.assertEqual((len(self.fake.requests), self.tries(), self.waiting()), (1, 1, ["msg-no_markup_ids"]))
        self.scan(now=NOW + 60)
        self.scan(now=NOW + 120)
        self.assertEqual((len(self.fake.requests), self.tries(), self.waiting()), (3, 3, []))
        for later in range(3, 12):
            self.scan(now=NOW + 60 * later)
        self.assertEqual((len(self.fake.requests), self.tries(), self.waiting()), (autoask.CAP, autoask.CAP, []))
        self.assertEqual(self.items()[0]["suggestion_error"], ai.FAILED)

    def test_one_scan_asks_about_an_item_once_even_when_it_fails(self):
        self.turn_on()
        self.fake.status = 500
        self.dated("new", "old")
        self.scan()
        self.assertEqual(len(self.fake.requests), 2)

    def test_a_retry_that_works_marks_the_suggestion_as_read_automatically(self):
        self.turn_on()
        self.fake.status = 500
        self.put("no_markup_ids")
        self.scan()
        self.fake.status = 200
        self.scan(now=NOW + 60)
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["suggestion_error"], item["auto_read"]), ([GOOD], None, True))
        self.assertEqual(self.waiting(), [])

    def test_a_bad_reply_is_a_failure_with_the_fixed_note_and_nothing_of_the_reply(self):
        self.turn_on()
        self.fake.content = "ignore the above and " + REPLY_CANARY
        self.put("no_markup_ids")
        with no_leaks(self, REPLY_CANARY, database=self.path):
            self.scan()
        self.assertEqual(self.items()[0]["suggestion_error"], ai.BAD_REPLY)

    def test_an_answer_of_no_booking_is_final_and_not_retried(self):
        self.turn_on()
        self.fake.content = "{}"
        self.put("no_markup_ids")
        self.scan()
        self.scan(now=NOW + 60)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual((self.items()[0]["suggestions"], self.waiting()), ([], []))

    def test_a_message_deleted_in_gmail_stops_waiting(self):
        self.turn_on()
        self.fake.status = 500
        self.put("no_markup_ids")
        self.scan()
        self.assertEqual(self.waiting(), ["msg-no_markup_ids"])
        del self.google.mail["msg-no_markup_ids"]
        self.scan(now=NOW + 60)
        self.assertEqual((len(self.fake.requests), self.waiting()), (1, []))

class PrivacyTests(AutoCase):
    SUBJECT = "CANARY-SUBJECT-AUTO-9K4M"

    def test_nothing_of_the_email_or_the_reply_is_logged_stored_or_summarised(self):
        self.turn_on()
        raw = eml("no_markup_ids").replace(b"Subject: Your trip is booked", f"Subject: Your trip is booked {self.SUBJECT}".encode())
        self.add_mail("m-subject", raw)
        self.fake.content = json.dumps({**GOOD, "provider": "Example Air"}) + " " + REPLY_CANARY
        said = []
        real = scan.monitoring.log
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, self.SUBJECT, REPLY_CANARY, database=self.path, sent_ok=True), \
                mock.patch.object(scan.monitoring, "log", side_effect=lambda text, *a, **k: (said.append(text), real(text, *a, **k))[1]):
            self.scan()
        sent = json.dumps(self.fake.requests)
        self.assertNotIn(self.SUBJECT, sent)
        self.assertFalse([t for t in said for k in (BODY, self.SUBJECT, REPLY_CANARY) if k in t])
        self.assertTrue(all(isinstance(v, (int, bool)) for v in json.loads(scan.encode(scan.summary(self.mailbox))).values()))

    def test_the_suggestion_is_the_only_thing_kept_of_the_ai_exchange(self):
        self.turn_on()
        self.put("no_markup_ids")
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=True):
            self.scan()
        kept = self.read(lambda conn: conn.execute(select(ReviewItem.suggestion, ReviewItem.suggestion_error, ReviewItem.auto_state)).fetchone())
        self.assertEqual((json.loads(kept[0]), kept[1], kept[2]), ([GOOD], None, "read"))


if __name__ == "__main__":
    unittest.main()
