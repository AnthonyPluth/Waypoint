import json
import unittest
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.test_mail_ai import BODY, FOOTER, GOOD, IDS, QUOTED, REPLY_CANARY, ScanAiCase
from tests.test_mail_scan import NOW, eml
from waypoint import tls
from waypoint.domain.mail import ai, review, scan
from waypoint.storage import db
from waypoint.storage.models import ReviewItem, ScannedMessage, StoredMessage

CATEGORIES = ("promotion", "statement", "newsletter")
VERDICT = json.dumps({"bookings": [], "not_a_booking": "promotion"})


class VerdictParseTests(unittest.TestCase):
    SENT = "Confirmation code: QW4R7T flight from BOS to DEN"

    def parse(self, reply):
        return ai.parse(reply if isinstance(reply, str) else json.dumps(reply), self.SENT)

    def refused(self, reply, text):
        with self.assertRaises(ai.AiError) as caught:
            self.parse(reply)
        self.assertEqual(str(caught.exception), text)

    def test_no_bookings_is_no_booking_found_whatever_the_model_says_about_the_email(self):
        for category in (*CATEGORIES, "receipt", "notification", "  Newsletter ", True, ["promotion"], None, ""):
            with self.subTest(category=category):
                self.refused({"bookings": [], "not_a_booking": category}, ai.NO_BOOKING)

    def test_the_reading_has_no_verdict_to_act_on(self):
        self.assertFalse(hasattr(ai.Reading([]), "not_a_booking"))
        self.assertFalse(hasattr(ai, "dismissed_note"))
        self.assertFalse(hasattr(ai, "NOT_BOOKINGS"))

    def test_a_verdict_beside_a_booking_changes_nothing_about_the_booking(self):
        reading = self.parse({"bookings": [GOOD], "not_a_booking": "promotion"})
        self.assertEqual((reading.bookings, reading.error), ([GOOD], None))

    def test_a_verdict_beside_bookings_that_cannot_be_used_is_a_bad_reply(self):
        self.refused({"bookings": [{**GOOD, "confirmation": "ZZ9Y8X"}], "not_a_booking": "promotion"}, ai.BAD_REPLY)

    def test_a_malformed_answer_is_a_bad_reply(self):
        for reply in ("not json", "[]", "null", '"promotion"', '{"bookings": [], "not_a_booking": "promotion"', json.dumps({"bookings": "none", "not_a_booking": "promotion"})):
            with self.subTest(reply=reply):
                self.refused(reply, ai.BAD_REPLY)

    def test_the_prompt_no_longer_asks_for_a_verdict(self):
        for word in ('"not_a_booking"', '"promotion"', '"statement"', '"newsletter"', "plainly not about a booking"):
            self.assertNotIn(word, ai.SYSTEM)
        self.assertIn('If the email holds no booking, reply {"bookings": []}.', ai.SYSTEM)


class VerdictCase(ScanAiCase):
    def saved_later(self, name="promo_ids"):
        self.turn_off()
        self.put(name)
        self.assertEqual(self.scan().review, 1)
        self.turn_on()
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


class LaterAddressVerdictTests(VerdictCase):
    def test_an_item_asked_about_after_the_address_is_saved_stays_in_review_and_the_email_stored_for_every_category(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.setUp()
                item = self.saved_later()
                self.fake.content = json.dumps({"bookings": [], "not_a_booking": category})
                with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=True):
                    self.ask_about(item["id"])
                [kept] = self.items()
                self.assertEqual((kept["id"], kept["suggestions"], kept["suggestion_error"]), (item["id"], [], ai.NO_BOOKING))
                self.assertEqual(self.read(lambda conn: review.count(conn, "u-jane")), 1)
                self.assertEqual(len(self.stored()), 1)
                self.assertEqual(self.outcomes(), {"msg-promo_ids": "unreadable"})

    def test_the_item_can_still_be_dismissed_by_a_person_which_is_what_deletes_the_email(self):
        item = self.saved_later()
        self.ask_about(item["id"])
        self.assertEqual(len(self.stored()), 1)
        with db.session() as conn:
            review.dismiss(conn, "u-jane", item["id"])
        self.assertEqual((self.items(), self.stored()), ([], []))

    def test_the_grouped_items_all_stay_when_one_of_them_is_asked_about_later(self):
        self.turn_on()
        for message_id in ("m-a", "m-b", "m-c"):
            self.google.mail[message_id] = eml("promo_ids")
        with db.session() as conn:
            for message_id in ("m-a", "m-b", "m-c"):
                review.add(conn, self.mailbox, message_id, "example-air.example", "2026-10-17", "no_markup", NOW, reference="QW4R7T")
        self.fake.content = VERDICT
        middle = self.read(lambda conn: conn.execute(select(ReviewItem.id).where(ReviewItem.message_id == "m-b")).scalar())
        self.ask_about(middle)
        self.assertEqual(self.read(lambda conn: sorted(conn.execute(select(ReviewItem.message_id)).scalars())), ["m-a", "m-b", "m-c"])

    def test_an_answer_with_a_booking_is_filed_as_before_with_or_without_the_verdict(self):
        for extra in ({}, {"not_a_booking": "promotion"}):
            with self.subTest(extra=extra):
                self.setUp()
                item = self.saved_later("no_markup_ids")
                self.fake.content = json.dumps({"bookings": [GOOD], **extra})
                self.ask_about(item["id"])
                [kept] = self.items()
                self.assertEqual(kept["suggestions"], [GOOD])

    def test_a_failing_service_a_bad_answer_and_a_bug_leave_the_item_with_its_error(self):
        item = self.saved_later()
        cases = ((500, "{}", ai.FAILED), (200, "not json at all " + REPLY_CANARY, ai.BAD_REPLY),
                 (200, '{"bookings": [], "not_a_booking": "promotion"', ai.BAD_REPLY), (401, "{}", ai.REFUSED), (429, "{}", ai.LIMITED))
        for status, content, expected in cases:
            with self.subTest(status=status, content=content[:20]):
                self.fake.status, self.fake.content = status, content
                with no_leaks(self, REPLY_CANARY, database=self.path):
                    self.ask_about(item["id"])
                [kept] = self.items()
                self.assertEqual((kept["id"], kept["suggestion_error"]), (item["id"], expected))
        with mock.patch.object(ai, "suggest", side_effect=RuntimeError("boom")):
            self.ask_about(item["id"])
        [kept] = self.items()
        self.assertEqual(kept["suggestion_error"], scan.SUGGESTION_FAILED)

    def test_an_unreachable_service_leaves_the_item_with_its_error(self):
        item = self.saved_later()
        with self.ai_fails_with(OSError("down")):
            self.ask_about(item["id"])
        [kept] = self.items()
        self.assertEqual(kept["suggestion_error"], ai.UNREACHABLE)

class AutomaticVerdictTests(VerdictCase):
    def waiting_items(self):
        return self.read(lambda conn: sorted(conn.execute(select(ReviewItem.message_id)).scalars()))

    def test_a_scan_leaves_the_item_in_review_and_the_email_stored_for_every_category(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.setUp()
                self.turn_on()
                self.fake.content = json.dumps({"bookings": [], "not_a_booking": category})
                self.put("promo_ids")
                with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=True):
                    result = self.scan()
                self.assertEqual((result.state, result.review), ("done", 1))
                [kept] = self.items()
                self.assertEqual(kept["suggestion_error"], ai.NO_BOOKING)
                self.assertEqual((len(self.stored()), self.waiting_items()), (1, ["msg-promo_ids"]))
                found = scan.summary(self.mailbox)
                self.assertEqual((found.ai_asked, found.review, found.dismissed_known, found.dismissed_older), (1, 1, 0, 0))

    def test_the_message_is_asked_about_once_and_the_item_stays_on_later_scans(self):
        self.turn_on()
        self.fake.content = VERDICT
        self.put("promo_ids")
        self.scan()
        for later, kwargs in ((NOW + 60, {}), (NOW + 120, {"backfill": True})):
            self.scan(now=later, **kwargs)
            self.assertEqual(self.waiting_items(), ["msg-promo_ids"])
        self.assertEqual(len(self.fake.requests), 1)

    def test_a_verdict_on_one_email_does_not_touch_the_others(self):
        self.turn_on()
        for name, day, fixture in (("new", b"Sun, 18 Oct 2026 09:10:00 -0400", "promo_ids"), ("mid", b"Sat, 17 Oct 2026 09:10:00 -0400", "no_markup_ids"),
                                   ("old", b"Fri, 16 Oct 2026 09:10:00 -0400", "no_markup_ids")):
            self.add_mail(f"msg-{name}", eml(fixture).replace(b"Sun, 18 Oct 2026 09:10:00 -0400", day))
        answers = [VERDICT, json.dumps(GOOD), json.dumps({"bookings": []})]
        self.fake.on_request = lambda n: setattr(self.fake, "content", answers[n - 1])
        self.assertEqual(self.scan().review, 3)
        found = scan.summary(self.mailbox)
        self.assertEqual((found.ai_asked, found.review), (3, 3))
        self.assertEqual(self.waiting_items(), ["msg-mid", "msg-new", "msg-old"])

    def test_an_answer_with_a_booking_is_filed_as_before_even_with_the_verdict(self):
        self.turn_on()
        self.fake.content = json.dumps({"bookings": [GOOD], "not_a_booking": "promotion"})
        self.put("no_markup_ids")
        self.assertEqual(self.scan().review, 1)
        [item] = self.items()
        self.assertEqual(item["suggestions"], [GOOD])

    def test_errors_timeouts_and_unreadable_answers_leave_the_item_in_review(self):
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
                self.assertEqual(len(self.items()), 1)

    def test_a_request_that_times_out_leaves_the_item_in_review(self):
        self.turn_on()
        self.put("no_markup_ids")
        with self.ai_fails_with(TimeoutError("slow")):
            self.assertEqual(self.scan().review, 1)
        self.assertEqual(len(self.items()), 1)

    def test_a_booking_beside_a_verdict_email_is_still_added(self):
        self.turn_on()
        self.fake.content = VERDICT
        self.put("promo_ids", "hotel_jsonld")
        result = self.scan()
        self.assertEqual((result.bookings, result.review), (1, 1))

    def test_nothing_of_the_email_or_the_answer_is_logged_stored_in_the_clear_or_summarised(self):
        self.turn_on()
        self.fake.content = json.dumps({"bookings": [], "not_a_booking": "promotion", "note": REPLY_CANARY})
        self.put("promo_ids")
        said = []
        real = scan.monitoring.log
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, REPLY_CANARY, database=self.path, sent_ok=True), \
                mock.patch.object(scan.monitoring, "log", side_effect=lambda text, *a, **k: (said.append(text), real(text, *a, **k))[1]):
            self.scan()
        self.assertFalse([t for t in said for k in (BODY, REPLY_CANARY, "Your trip is booked") if k in t])
        self.assertFalse([t for t in said if "dismissed as not" in t])
        self.assertTrue(all(isinstance(v, (int, bool)) for v in json.loads(scan.encode(scan.summary(self.mailbox))).values()))


if __name__ == "__main__":
    unittest.main()
