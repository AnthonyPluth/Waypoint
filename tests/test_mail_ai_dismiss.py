import json
import unittest
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.test_mail_ai import BODY, FOOTER, GOOD, IDS, QUOTED, REPLY_CANARY, KEY, ScanAiCase, serve_fake_ai
from tests.test_mail_scan import NOW, eml
from waypoint import tls
from waypoint.domain.mail import ai, review, scan
from waypoint.storage import db
from waypoint.storage.models import ReviewItem, ScannedMessage, StoredMessage

VERDICT = json.dumps({"bookings": [], "not_a_booking": "promotion"})
PROMOTION = "Dismissed: a promotion, not a booking."


class VerdictParseTests(unittest.TestCase):
    SENT = "Confirmation code: QW4R7T flight from BOS to DEN"

    def parse(self, reply):
        return ai.parse(reply if isinstance(reply, str) else json.dumps(reply), self.SENT)

    def refused(self, reply, text):
        with self.assertRaises(ai.AiError) as caught:
            self.parse(reply)
        self.assertEqual(str(caught.exception), text)

    def test_no_bookings_and_a_known_category_is_a_verdict(self):
        for category in ai.NOT_BOOKINGS:
            with self.subTest(category=category):
                self.assertEqual(self.parse({"bookings": [], "not_a_booking": category}), ai.Reading([], None, category))

    def test_the_category_is_matched_without_regard_to_case_or_spaces(self):
        self.assertEqual(self.parse({"bookings": [], "not_a_booking": "  Newsletter "}).not_a_booking, "newsletter")
        self.assertEqual(self.parse("```json\n" + VERDICT + "\n```").not_a_booking, "promotion")

    def test_no_bookings_without_the_verdict_is_still_no_booking_found(self):
        for reply in ({"bookings": []}, {}, {"bookings": [], "not_a_booking": None}, {"bookings": [], "note": "promotion"}):
            with self.subTest(reply=reply):
                self.refused(reply, ai.NO_BOOKING)

    def test_a_verdict_that_is_not_one_of_the_categories_is_no_verdict(self):
        for value in ("", "spam", "booking", True, 1, ["promotion"], {"promotion": 1}, "promotion newsletter"):
            with self.subTest(value=value):
                self.refused({"bookings": [], "not_a_booking": value}, ai.NO_BOOKING)

    def test_a_verdict_beside_a_booking_is_ignored(self):
        reading = self.parse({"bookings": [GOOD], "not_a_booking": "promotion"})
        self.assertEqual((reading.bookings, reading.not_a_booking), ([GOOD], None))

    def test_a_verdict_beside_bookings_that_cannot_be_used_is_a_bad_reply_not_a_dismissal(self):
        self.refused({"bookings": [{**GOOD, "confirmation": "ZZ9Y8X"}], "not_a_booking": "promotion"}, ai.BAD_REPLY)

    def test_a_verdict_without_the_bookings_list_is_a_bad_reply(self):
        self.refused({"not_a_booking": "promotion"}, ai.BAD_REPLY)

    def test_a_malformed_answer_is_a_bad_reply(self):
        for reply in ("not json", "[]", "null", '"promotion"', '{"bookings": [], "not_a_booking": "promotion"', json.dumps({"bookings": "none", "not_a_booking": "promotion"})):
            with self.subTest(reply=reply):
                self.refused(reply, ai.BAD_REPLY)

    def test_the_note_names_the_category_in_plain_words(self):
        self.assertEqual([ai.dismissed_note(c) for c in ai.NOT_BOOKINGS],
                         ["Dismissed: a promotion, not a booking.", "Dismissed: a loyalty or account statement, not a booking.",
                          "Dismissed: a newsletter, not a booking."])

    def test_the_prompt_asks_for_the_verdict_only_for_plain_cases(self):
        self.assertIn('"not_a_booking"', ai.SYSTEM)
        for word in ('"promotion"', '"statement"', '"newsletter"', "when you are unsure, leave it out", "cancellation"):
            self.assertIn(word, ai.SYSTEM)
        self.assertIn('If the email holds no booking, reply {"bookings": []}.', ai.SYSTEM)


class SuggestVerdictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = serve_fake_ai(cls)

    def setUp(self):
        self.fake.reset()
        self.local = ai.Config("local", "llama3", url=self.fake.url)

    def test_the_verdict_comes_back_with_the_reading_and_is_not_asked_again(self):
        self.fake.content = VERDICT
        reading = ai.suggest(self.local, "Save 10% on your next trip. Book now.")
        self.assertEqual((reading.bookings, reading.error, reading.not_a_booking), ([], None, "promotion"))
        self.assertEqual(len(self.fake.requests), 1)

    def test_an_answer_without_it_is_the_old_error(self):
        self.fake.content = json.dumps({"bookings": []})
        with self.assertRaises(ai.AiError) as caught:
            ai.suggest(self.local, "Save 10% on your next trip. Book now.")
        self.assertEqual(str(caught.exception), ai.NO_BOOKING)


class DismissCase(ScanAiCase):
    def asked_by_hand(self):
        self.turn_on(auto=False)
        self.put("no_markup_ids")
        self.assertEqual(self.scan().review, 1)
        [item] = self.items()
        self.fake.content = VERDICT
        return item

    def ai_fails_with(self, error):
        real = tls.urlopen

        def selective(req, *args, **kwargs):
            if self.fake.url in getattr(req, "full_url", str(req)):
                raise error
            return real(req, *args, **kwargs)
        return mock.patch.object(tls, "urlopen", selective)

    def stored(self):
        return self.read(lambda conn: conn.execute(select(StoredMessage.id)).fetchall())

    def outcomes(self):
        return self.scanned()


class AskAiDismissTests(DismissCase):
    def test_ask_ai_dismisses_the_item_and_returns_the_reason(self):
        item = self.asked_by_hand()
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=True):
            note = scan.suggest_now("u-jane", item["id"], NOW)
        self.assertEqual(note, PROMOTION)
        self.assertEqual((self.items(), self.read(lambda conn: review.count(conn, "u-jane"))), ([], 0))

    def test_the_stored_email_goes_and_the_scan_still_remembers_the_message(self):
        item = self.asked_by_hand()
        self.assertEqual(len(self.stored()), 1)
        scan.suggest_now("u-jane", item["id"], NOW)
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.outcomes(), {"msg-no_markup_ids": "unreadable"})

    def test_the_next_scan_does_not_queue_it_again_or_ask_again(self):
        item = self.asked_by_hand()
        scan.suggest_now("u-jane", item["id"], NOW)
        asked = len(self.fake.requests)
        self.turn_on()
        result = self.scan(now=NOW + 60)
        self.assertEqual((result.review, result.messages, self.items()), (0, 0, []))
        self.assertEqual((len(self.fake.requests), self.stored()), (asked, []))

    def test_it_stays_gone_when_the_mailbox_is_looked_through_again(self):
        item = self.asked_by_hand()
        scan.suggest_now("u-jane", item["id"], NOW)
        self.turn_on()
        self.assertEqual(self.scan(now=NOW + 60, backfill=True).review, 0)
        self.assertEqual(self.items(), [])

    def test_only_the_item_that_was_read_is_dismissed_not_the_ones_grouped_with_it(self):
        self.turn_on(auto=False)
        for message_id in ("m-a", "m-b", "m-c"):
            self.google.mail[message_id] = eml("no_markup_ids")
        with db.session() as conn:
            for message_id in ("m-a", "m-b", "m-c"):
                review.add(conn, self.mailbox, message_id, "example-air.example", "2026-10-17", "no_markup", NOW, reference="QW4R7T")
        [grouped] = self.items()
        self.assertEqual(grouped["count"], 3)
        self.fake.content = VERDICT
        ids = {message: self.read(lambda conn, m=message: conn.execute(select(ReviewItem.id).where(ReviewItem.message_id == m)).scalar())
               for message in ("m-a", "m-b", "m-c")}
        self.assertEqual(scan.suggest_now("u-jane", ids["m-b"], NOW), PROMOTION)
        left = self.read(lambda conn: sorted(conn.execute(select(ReviewItem.message_id)).scalars()))
        self.assertEqual(left, ["m-a", "m-c"])
        [still] = self.items()
        self.assertEqual(still["count"], 2)

    def test_no_booking_found_without_the_verdict_leaves_the_item_in_review(self):
        item = self.asked_by_hand()
        self.fake.content = json.dumps({"bookings": []})
        self.assertIsNone(scan.suggest_now("u-jane", item["id"], NOW))
        [kept] = self.items()
        self.assertEqual((kept["suggestions"], kept["suggestion_error"]), ([], ai.NO_BOOKING))
        self.assertEqual(len(self.stored()), 1)

    def test_an_answer_with_a_booking_never_dismisses_even_with_the_verdict(self):
        item = self.asked_by_hand()
        self.fake.content = json.dumps({"bookings": [GOOD], "not_a_booking": "promotion"})
        self.assertIsNone(scan.suggest_now("u-jane", item["id"], NOW))
        [kept] = self.items()
        self.assertEqual(kept["suggestions"], [GOOD])

    def test_a_failing_service_a_bad_answer_and_a_bug_never_dismiss(self):
        item = self.asked_by_hand()
        cases = ((500, "{}", ai.FAILED), (200, "not json at all " + REPLY_CANARY, ai.BAD_REPLY),
                 (200, '{"bookings": [], "not_a_booking": "promotion"', ai.BAD_REPLY), (401, "{}", ai.REFUSED), (429, "{}", ai.LIMITED))
        for status, content, expected in cases:
            with self.subTest(status=status, content=content[:20]):
                self.fake.status, self.fake.content = status, content
                with no_leaks(self, REPLY_CANARY, database=self.path):
                    self.assertIsNone(scan.suggest_now("u-jane", item["id"], NOW))
                [kept] = self.items()
                self.assertEqual((kept["id"], kept["suggestion_error"]), (item["id"], expected))
        with mock.patch.object(ai, "suggest", side_effect=RuntimeError("boom")):
            self.assertIsNone(scan.suggest_now("u-jane", item["id"], NOW))
        [kept] = self.items()
        self.assertEqual(kept["suggestion_error"], scan.SUGGESTION_FAILED)

    def test_an_unreachable_service_never_dismisses(self):
        item = self.asked_by_hand()
        with self.ai_fails_with(OSError("down")):
            self.assertIsNone(scan.suggest_now("u-jane", item["id"], NOW))
        [kept] = self.items()
        self.assertEqual(kept["suggestion_error"], ai.UNREACHABLE)

    def test_hosted_mode_dismisses_the_same_way_and_sends_nothing_it_should_not(self):
        import os
        env = mock.patch.dict(os.environ, {ai.KEY_ENV: KEY})
        env.start()
        self.addCleanup(env.stop)
        self.turn_on("openrouter", auto=False)
        from waypoint.storage import settings_keys as sk
        with db.session() as conn:
            db.set_setting(conn, sk.AI_OPENROUTER_MODEL, "some/model")
        self.put("no_markup_ids")
        self.scan()
        [item] = self.items()
        self.fake.content = VERDICT
        with mock.patch.object(ai, "HOSTS", ai.Hosts(self.fake.url + "/api/v1", allow_http=True)):
            with no_leaks(self, *IDS, QUOTED, FOOTER, database=self.path):
                note = scan.suggest_now("u-jane", item["id"], NOW)
        self.assertEqual(note, PROMOTION)
        self.assertEqual(self.items(), [])


class AutomaticDismissTests(DismissCase):
    def test_the_scan_dismisses_the_item_and_counts_it_without_naming_it(self):
        self.turn_on()
        self.fake.content = VERDICT
        self.put("no_markup_ids")
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=True):
            result = self.scan()
        self.assertEqual((result.state, result.review, self.items()), ("done", 0, []))
        found = scan.summary(self.mailbox)
        self.assertEqual((found.dismissed, found.ai_asked, found.review), (1, 1, 0))
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.outcomes(), {"msg-no_markup_ids": "unreadable"})
        self.assertEqual(self.waiting_items(), [])

    def waiting_items(self):
        return self.read(lambda conn: list(conn.execute(select(ReviewItem.id)).scalars()))

    def dated(self):
        original = b"Sun, 18 Oct 2026 09:10:00 -0400"
        for name, day in (("new", original), ("mid", b"Sat, 17 Oct 2026 09:10:00 -0400"), ("old", b"Fri, 16 Oct 2026 09:10:00 -0400")):
            self.add_mail(f"msg-{name}", eml("no_markup_ids").replace(original, day))

    def test_the_next_scan_neither_queues_nor_asks_about_it_again(self):
        self.turn_on()
        self.fake.content = VERDICT
        self.put("no_markup_ids")
        self.scan()
        for later, kwargs in ((NOW + 60, {}), (NOW + 120, {"backfill": True})):
            result = self.scan(now=later, **kwargs)
            self.assertEqual((result.review, self.items()), (0, []))
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(scan.summary(self.mailbox).dismissed, 0)

    def test_only_the_dismissed_items_are_counted_beside_the_ones_that_stay(self):
        self.turn_on()
        self.dated()
        answers = [VERDICT, json.dumps(GOOD), json.dumps({"bookings": []})]
        self.fake.on_request = lambda n: setattr(self.fake, "content", answers[n - 1])
        result = self.scan()
        self.assertEqual(result.review, 2)
        found = scan.summary(self.mailbox)
        self.assertEqual((found.dismissed, found.ai_asked, found.review), (1, 3, 2))
        self.assertEqual(self.read(lambda conn: sorted(conn.execute(select(ReviewItem.message_id)).scalars())), ["msg-mid", "msg-old"])

    def test_an_answer_with_a_booking_is_never_dismissed(self):
        self.turn_on()
        self.fake.content = json.dumps({"bookings": [GOOD], "not_a_booking": "promotion"})
        self.put("no_markup_ids")
        self.assertEqual(self.scan().review, 1)
        [item] = self.items()
        self.assertEqual((item["suggestions"], scan.summary(self.mailbox).dismissed), ([GOOD], 0))

    def test_no_booking_without_the_verdict_stays_in_review_and_is_not_counted(self):
        self.turn_on()
        self.fake.content = json.dumps({"bookings": []})
        self.put("no_markup_ids")
        self.assertEqual(self.scan().review, 1)
        self.assertEqual((self.items()[0]["suggestion_error"], scan.summary(self.mailbox).dismissed), (ai.NO_BOOKING, 0))

    def test_errors_timeouts_and_unreadable_answers_never_dismiss(self):
        for status, content in ((500, "{}"), (200, "not json"), (200, '{"bookings": [], "not_a_booking": "promotion"'), (200, "[" + VERDICT + "]")):
            with self.subTest(status=status, content=content[:20]):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                    conn.execute(ScannedMessage.__table__.delete())
                self.fake.reset()
                self.fake.status, self.fake.content = status, content
                self.turn_on()
                self.put("no_markup_ids")
                self.assertEqual(self.scan().review, 1)
                self.assertEqual(scan.summary(self.mailbox).dismissed, 0)
                self.assertEqual(len(self.items()), 1)

    def test_a_request_that_times_out_never_dismisses(self):
        self.turn_on()
        self.put("no_markup_ids")
        with self.ai_fails_with(TimeoutError("slow")):
            self.assertEqual(self.scan().review, 1)
        self.assertEqual((len(self.items()), scan.summary(self.mailbox).dismissed), (1, 0))

    def test_a_dismissal_is_not_an_unfiled_item_for_the_review_count(self):
        self.turn_on()
        self.fake.content = VERDICT
        self.put("no_markup_ids", "hotel_jsonld")
        result = self.scan()
        self.assertEqual((result.bookings, result.review), (1, 0))
        found = scan.summary(self.mailbox)
        self.assertEqual((found.bookings, found.review, found.dismissed), (1, 0, 1))

    def test_nothing_of_the_email_the_answer_or_the_dismissal_is_logged_stored_or_summarised(self):
        self.turn_on()
        self.fake.content = json.dumps({"bookings": [], "not_a_booking": "promotion", "note": REPLY_CANARY})
        self.put("no_markup_ids")
        said = []
        real = scan.monitoring.log
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, REPLY_CANARY, database=self.path, sent_ok=True), \
                mock.patch.object(scan.monitoring, "log", side_effect=lambda text, *a, **k: (said.append(text), real(text, *a, **k))[1]):
            self.scan()
        self.assertTrue(any("1 dismissed as not bookings" in t for t in said))
        self.assertFalse([t for t in said for k in (BODY, REPLY_CANARY, "Your trip is booked") if k in t])
        self.assertTrue(all(isinstance(v, (int, bool)) for v in json.loads(scan.encode(scan.summary(self.mailbox))).values()))


if __name__ == "__main__":
    unittest.main()
