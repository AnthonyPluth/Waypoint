import json
import sys
import unittest
from datetime import timedelta
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.shared import TODAY
from tests.test_mail_ai import BODY, FOOTER, GOOD, IDS, QUOTED, REPLY_CANARY, ScanAiCase
from tests.test_mail_followup import CODE, STAYS, follow
from tests.test_mail_scan import NOW, eml, plain_mail
from waypoint import tls
from waypoint.domain.mail import ai, autoask, scan
from waypoint.storage import db
from waypoint.storage import settings_keys as sk
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


class TwoSwitchTests(AutoCase):
    def switches(self, fallback, automatic):
        if fallback:
            self.turn_on(auto=automatic)
        else:
            with db.session() as conn:
                db.set_setting(conn, sk.AI_AUTO, "1" if automatic else None)

    def test_a_scan_reaches_the_ai_only_with_both_switches_on(self):
        for fallback, automatic in ((False, False), (True, False), (False, True)):
            with self.subTest(fallback=fallback, automatic=automatic):
                self.fake.reset()
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                    conn.execute(ScannedMessage.__table__.delete())
                self.turn_off()
                self.switches(fallback, automatic)
                self.put("no_markup_ids")
                with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path):
                    result = self.scan()
                self.assertEqual((result.state, result.review), ("done", 1))
                self.assertEqual(self.fake.requests, [])
                self.assertEqual((self.waiting(), self.suggested()), ([], []))
                self.assertEqual(scan.summary(self.mailbox).ai_asked, 0)

    def test_with_both_on_a_qualifying_message_gets_its_suggestion_during_the_scan(self):
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
        self.fake.on_request = lambda n: self.switches(True, False) if n == 1 else None
        self.assertEqual(self.scan().review, 3)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(self.suggested(), ["msg-new"])

    def test_turning_the_fallback_off_turns_the_automatic_switch_off_with_it(self):
        self.turn_on()
        self.assertTrue(self.read(lambda conn: autoask.switched_on(conn)))
        self.turn_off()
        self.assertFalse(self.read(lambda conn: autoask.switched_on(conn)))

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

    def test_the_automatic_request_is_the_same_request_ask_ai_makes(self):
        self.turn_on()
        self.put("no_markup_ids")
        self.scan()
        [item] = self.items()
        scan.suggest_now("u-jane", item["id"], NOW)
        first, second = self.fake.requests
        self.assertEqual((first[0], first[2]), (second[0], second[2]))
        self.assertEqual(first[1].get("Authorization"), second[1].get("Authorization"))
        self.assertFalse(self.items()[0]["auto_read"])

    def test_the_automatic_request_carries_the_same_provider_settings_as_ask_ai(self):
        import os
        from tests.test_mail_ai import KEY
        env = mock.patch.dict(os.environ, {ai.KEY_ENV: KEY})
        env.start()
        self.addCleanup(env.stop)
        self.turn_on("openrouter")
        with db.session() as conn:
            db.set_setting(conn, sk.AI_OPENROUTER_MODEL, "some/model")
        self.put("no_markup_ids")
        with mock.patch.object(ai, "HOSTS", ai.Hosts(self.fake.url + "/api/v1", allow_http=True)):
            self.scan()
            [item] = self.items()
            scan.suggest_now("u-jane", item["id"], NOW)
        first, second = self.fake.requests
        self.assertEqual(first[2]["provider"], {"data_collection": "deny", "zdr": True})
        self.assertEqual(first[2], second[2])


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

    def test_a_message_a_reader_made_a_booking_from_is_never_sent(self):
        self.turn_on()
        self.put("flight_jsonld", "hotel_jsonld")
        self.assertEqual(self.scan().bookings, 2)
        self.assertEqual(self.fake.requests, [])

    def test_a_follow_up_of_a_booking_the_household_holds_is_never_sent(self):
        self.turn_on()
        self.put("hotel_jsonld")
        self.scan()
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
        self.scan()
        self.assertEqual(len(self.fake.requests), 1)

    def test_a_message_with_travel_markup_but_no_booking_is_sent(self):
        self.turn_on()
        self.put("incomplete")
        self.assertEqual(self.scan().review, 1)
        self.assertEqual(len(self.fake.requests), 1)


class CapTests(AutoCase):
    def test_a_scan_asks_at_most_its_cap_newest_first_and_the_rest_wait_for_the_next(self):
        self.turn_on()
        self.dated("old", "new", "mid")
        with mock.patch.object(autoask, "PER_SCAN", 2):
            self.assertEqual(self.scan().review, 3)
            self.assertEqual(self.suggested(), ["msg-mid", "msg-new"])
            self.assertEqual(self.waiting(), ["msg-old"])
            found = scan.summary(self.mailbox)
            self.assertEqual((found.ai_asked, found.ai_today, found.ai_waiting), (2, 2, 1))
            self.scan(now=NOW + 60)
        self.assertEqual(self.suggested(), ["msg-mid", "msg-new", "msg-old"])
        self.assertEqual(self.waiting(), [])
        self.assertEqual(len(self.fake.requests), 3)
        found = scan.summary(self.mailbox)
        self.assertEqual((found.ai_asked, found.ai_today, found.ai_waiting), (1, 3, 0))

    def test_a_day_asks_at_most_its_cap_and_the_next_day_carries_on(self):
        self.turn_on()
        self.dated("new", "mid", "old")
        with mock.patch.object(autoask, "PER_DAY", 2):
            self.scan()
            self.scan(now=NOW + 60)
            self.assertEqual(self.suggested(), ["msg-mid", "msg-new"])
            self.assertEqual(self.waiting(), ["msg-old"])
            self.assertEqual(len(self.fake.requests), 2)
            self.scan(now=NOW + 86400, today=TODAY + timedelta(days=1))
        self.assertEqual(self.suggested(), ["msg-mid", "msg-new", "msg-old"])
        self.assertEqual(self.read(lambda conn: conn.execute(select(Mailbox.ai_day_count)).scalar()), 1)

    def test_the_caps_are_20_a_scan_and_100_a_day_in_one_place(self):
        self.assertEqual((autoask.PER_SCAN, autoask.PER_DAY, autoask.TRIES), (20, 100, 3))

    def test_an_item_that_was_already_waiting_when_the_switch_was_off_is_not_asked(self):
        self.turn_on(auto=False)
        self.put("no_markup_ids")
        self.scan()
        self.turn_on(auto=True)
        self.scan(now=NOW + 60)
        self.assertEqual(self.fake.requests, [])


class FailureTests(AutoCase):
    def test_a_failed_request_leaves_the_item_with_the_note_and_is_retried_at_most_twice(self):
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
        self.scan(now=NOW + 180)
        self.assertEqual(len(self.fake.requests), 3)
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
        self.dated("new", "old")
        with mock.patch.object(autoask, "PER_SCAN", 1):
            self.scan()
            del self.google.mail["msg-old"]
            self.scan(now=NOW + 60)
        self.assertEqual((len(self.fake.requests), self.waiting()), (1, []))

    def test_a_person_asking_by_hand_takes_the_item_out_of_the_automatic_queue(self):
        self.turn_on()
        self.fake.status = 500
        self.put("no_markup_ids")
        self.scan()
        self.fake.status = 200
        [item] = self.items()
        scan.suggest_now("u-jane", item["id"], NOW)
        self.assertEqual(self.waiting(), [])
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["auto_read"]), ([GOOD], False))


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
