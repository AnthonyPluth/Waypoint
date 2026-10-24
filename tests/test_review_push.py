import json
import os
import threading
import time
import unittest
from http.server import HTTPServer
from unittest import mock

from sqlalchemy import insert, select, update

from tests.privacy import no_leaks
from tests.test_mail_ai import GOOD, ScanAiCase
from tests.test_mail_scan import NOW, eml
from tests.test_reminders import ENDPOINT, subscription
from tests.test_webpush import PushService, decrypt, receiver
from waypoint.domain import reminders
from waypoint.domain.mail import ai, review, scan
from waypoint.providers import webpush
from waypoint.server import jobs
from waypoint.storage import db
from waypoint.storage.models import Mailbox, PushDevice, ReminderSent

VERDICT = json.dumps({"bookings": [], "not_a_booking": "promotion"})
ONE = "1 booking email needs your review"
TWO = "2 booking emails need your review"


class PushCase(ScanAiCase):
    def setUp(self):
        super().setUp()
        self.sent: list[tuple[int, dict]] = []
        self.failing: Exception | None = None
        patch = mock.patch.object(reminders, "sender", lambda conn, subject: self.send)
        patch.start()
        self.addCleanup(patch.stop)

    def send(self, device, message):
        if self.failing is not None:
            raise self.failing
        self.sent.append((device.id, message))

    def device(self, owner="u-jane", endpoint=ENDPOINT):
        with db.session() as conn:
            return reminders.add_device(conn, owner, *subscription(endpoint), time.time())["id"]

    def incomplete(self, *ids):
        for each in ids or ("m-incomplete",):
            self.add_mail(each, eml("incomplete"))

    def scan_job(self):
        jobs.scan_mailboxes()

    def remembered(self):
        return self.read(lambda conn: sorted(conn.execute(select(ReminderSent.owner_sub, ReminderSent.kind)).fetchall()))

    def bodies(self):
        return [m["body"] for _i, m in self.sent]


class WhenItGoesOutTests(PushCase):
    def test_a_scan_that_leaves_booking_emails_to_review_sends_one_count_to_the_person(self):
        self.device()
        self.incomplete("m-a", "m-b")
        self.scan_job()
        (_id, message), = self.sent
        self.assertEqual(message, {"title": "Booking emails to review", "tag": "review", "url": "/#review", "body": TWO})

    def test_one_email_is_said_in_the_singular(self):
        self.device()
        self.incomplete()
        self.scan_job()
        self.assertEqual(self.bodies(), [ONE])

    def test_every_device_of_the_person_gets_the_one_notification(self):
        first, second = self.device(), self.device(endpoint="https://push.example.com/send/second")
        self.incomplete()
        self.scan_job()
        self.assertEqual(sorted(i for i, _m in self.sent), sorted([first, second]))
        self.assertEqual(self.remembered(), [("u-jane", "review")])

    def test_the_automatic_reading_counts_the_suggestions_waiting_to_be_checked(self):
        self.turn_on()
        self.device()
        self.put("no_markup_ids")
        self.scan_job()
        self.assertEqual(self.bodies(), [ONE])
        [item] = self.items()
        self.assertEqual(item["suggestions"], [GOOD])

    def test_an_incomplete_booking_and_an_ambiguous_match_count_as_well(self):
        self.device()
        self.put("incomplete")
        self.scan_job()
        self.assertEqual(self.bodies(), [ONE])
        with db.session() as conn:
            review.add(conn, self.mailbox, "m-held", "example-air.example", "2026-10-18", "match", time.time(),
                       [({"kind": "hotel"}, [1])])   # type: ignore[list-item]
        with db.session() as conn:
            reminders.review_due(conn, 0.0, time.time(), self.send, [self.mailbox])
        self.assertEqual(self.bodies(), [ONE, ONE])

    def test_a_chained_scan_of_a_big_mailbox_is_still_one_notification(self):
        self.device()
        for n in range(4):
            self.add_mail(f"m-{n}", eml("incomplete"))
        with mock.patch.object(scan, "BUDGET", 0):
            self.scan_job()
        self.assertEqual(len(self.sent), 1)


class WhenItDoesNotTests(PushCase):
    def test_nothing_goes_out_for_a_scan_that_leaves_nothing_to_review(self):
        self.device()
        self.put("flight_jsonld", "hotel_jsonld")
        self.scan_job()
        self.assertEqual((len(self.segments()), self.items(), self.sent, self.remembered()), (2, [], [], []))

    def test_an_unread_email_that_might_be_a_booking_sends_nothing(self):
        self.device()
        self.put("no_markup_ids", "no_markup")
        self.scan_job()
        self.assertEqual((len(self.items()), self.sent, self.remembered()), (2, [], []))

    def test_an_email_the_ai_read_with_no_booking_and_no_verdict_sends_nothing(self):
        self.turn_on()
        self.fake.content = json.dumps({"bookings": []})
        self.device()
        self.put("no_markup_ids")
        self.scan_job()
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["suggestion_error"], self.sent, self.remembered()), ([], ai.NO_BOOKING, [], []))

    def test_an_email_the_ai_could_not_be_asked_about_sends_nothing(self):
        self.turn_on()
        self.fake.status = 500
        self.device()
        self.put("no_markup_ids")
        self.scan_job()
        self.assertEqual((len(self.items()), self.sent), (1, []))

    def test_only_the_items_that_hold_a_booking_are_counted_beside_ones_that_do_not(self):
        self.device()
        self.put("no_markup_ids")
        self.incomplete("m-a")
        self.scan_job()
        self.assertEqual((len(self.items()), self.bodies()), (2, [ONE]))

    def test_the_query_counts_incomplete_and_match_items_and_those_with_suggestions_only(self):
        reasons = ("no_markup", "broken", "generic", "incomplete", "match")
        with db.session() as conn:
            for reason in reasons:
                review.add(conn, self.mailbox, f"m-{reason}", "example-air.example", "2026-10-18", reason, time.time())   # type: ignore[arg-type]
            review.add(conn, self.mailbox, "m-suggested", "example-air.example", "2026-10-18", "broken", time.time())
            review.set_suggestions(conn, self.mailbox, "m-suggested", [GOOD], None)   # type: ignore[list-item]
            review.add(conn, self.mailbox, "m-emptied", "example-air.example", "2026-10-18", "broken", time.time())
            review.set_suggestions(conn, self.mailbox, "m-emptied", [], None)
        with db.session() as conn:
            found = review.arrived(conn, "u-jane", 0.0, [self.mailbox])
        self.assertEqual(sorted(found), sorted(f"{self.mailbox}/m-{each}" for each in ("incomplete", "match", "suggested")))

    def test_a_scan_that_only_dismissed_emails_as_not_bookings_sends_nothing(self):
        self.turn_on()
        self.fake.content = VERDICT
        self.device()
        self.put("no_markup_ids")
        self.scan_job()
        self.assertEqual((self.items(), scan.summary(self.mailbox).dismissed, self.sent, self.remembered()), ([], 1, [], []))

    def test_dismissed_emails_are_left_out_of_the_count_beside_ones_that_stay(self):
        self.turn_on()
        self.device()
        answers = [VERDICT, json.dumps(GOOD)]
        self.fake.on_request = lambda n: setattr(self.fake, "content", answers[n - 1])
        original = b"Sun, 18 Oct 2026 09:10:00 -0400"
        self.add_mail("msg-new", eml("no_markup_ids"))
        self.add_mail("msg-old", eml("no_markup_ids").replace(original, b"Fri, 16 Oct 2026 09:10:00 -0400"))
        self.scan_job()
        self.assertEqual(self.bodies(), [ONE])
        self.assertEqual(scan.summary(self.mailbox).dismissed, 1)

    def test_a_scan_with_no_new_mail_sends_nothing_and_an_item_is_never_told_twice(self):
        self.device()
        self.incomplete()
        self.scan_job()
        self.scan_job()
        self.assertEqual(self.bodies(), [ONE])
        with db.session() as conn:
            self.assertEqual(reminders.review_due(conn, 0.0, time.time(), self.send, [self.mailbox]), 0)
        self.assertEqual(len(self.sent), 1)

    def test_a_later_scan_counts_only_its_own_new_items(self):
        self.device()
        self.incomplete()
        self.scan_job()
        time.sleep(0.01)
        self.add_mail("m-more", eml("incomplete"))
        self.scan_job()
        self.assertEqual(self.bodies(), [ONE, ONE])
        self.assertEqual(len(self.remembered()), 2)

    def test_a_person_who_turned_it_off_is_told_nothing(self):
        self.device()
        with db.session() as conn:
            reminders.set_prefs(conn, "u-jane", {"check_in": True, "day_of": True, "review": False})
        self.incomplete()
        self.scan_job()
        self.assertEqual((self.sent, self.remembered(), len(self.items())), ([], [], 1))

    def test_turning_the_other_two_off_does_not_turn_this_one_off(self):
        self.device()
        with db.session() as conn:
            reminders.set_prefs(conn, "u-jane", {"check_in": False, "day_of": False, "review": True})
        self.incomplete()
        self.scan_job()
        self.assertEqual(self.bodies(), [ONE])

    def test_a_person_with_no_device_is_told_nothing_and_nothing_is_recorded(self):
        self.incomplete()
        self.scan_job()
        self.assertEqual((self.sent, self.remembered()), ([], []))

    def test_ask_ai_does_not_notify(self):
        self.device()
        self.turn_on(auto=False)
        self.put("no_markup_ids")
        with mock.patch.object(reminders, "review_due") as due:
            self.scan()
            [item] = self.items()
            scan.suggest_now("u-jane", item["id"], NOW)
        due.assert_not_called()
        self.assertEqual(self.sent, [])


class WhoIsToldTests(PushCase):
    def test_only_people_who_can_see_the_items_are_told(self):
        self.device("u-jane")
        self.device("u-sam", "https://push.example.com/send/sam")
        self.incomplete()
        self.scan_job()
        self.assertEqual(self.remembered(), [("u-jane", "review")])
        self.assertEqual(len(self.sent), 1)

    def test_when_the_household_shares_review_the_others_are_told_their_own_count(self):
        self.device("u-jane")
        self.device("u-sam", "https://push.example.com/send/sam")
        self.read(lambda conn: conn.execute(update(Mailbox).where(Mailbox.id == self.mailbox).values(share_review=True)))
        self.incomplete()
        self.scan_job()
        self.assertEqual(self.remembered(), [("u-jane", "review"), ("u-sam", "review")])
        self.assertEqual(self.bodies(), [ONE, ONE])

    def test_a_person_is_told_once_for_all_their_mailboxes(self):
        other = self.connect("u-jane", "jane2@gmail.example", "refresh-jane-2")
        self.device()
        self.incomplete()
        self.scan_job()
        self.assertTrue(other)
        self.assertEqual(self.bodies(), [TWO])

    def test_a_scan_counts_only_the_mailboxes_it_scanned(self):
        other = self.connect("u-jane", "jane2@gmail.example", "refresh-jane-2")
        self.device()
        with db.session() as conn:
            review.add(conn, other, "m-elsewhere", "example-air.example", "2026-10-18", "incomplete", time.time())
        with db.session() as conn:
            self.assertEqual(reminders.review_due(conn, 0.0, time.time(), self.send, [self.mailbox]), 0)
            self.assertEqual(reminders.review_due(conn, 0.0, time.time(), self.send, []), 0)
        self.assertEqual(self.sent, [])
        with db.session() as conn:
            self.assertEqual(reminders.review_due(conn, 0.0, time.time(), self.send, [self.mailbox, other]), 1)
        self.assertEqual(self.bodies(), [ONE])

    def test_a_mailbox_another_scan_is_still_reading_is_left_to_that_scan(self):
        other = self.connect("u-jane", "jane2@gmail.example", "refresh-jane-2")
        self.device()
        self.incomplete()
        with db.session() as conn:
            review.add(conn, other, "m-elsewhere", "example-air.example", "2026-10-18", "incomplete", time.time())
        with mock.patch.object(scan, "_running", {other}):
            self.scan_job()
        self.assertEqual(self.bodies(), [ONE])

    def test_a_person_who_can_no_longer_sign_in_is_told_nothing(self):
        self.device()
        self.incomplete()
        with mock.patch.object(reminders, "lapsed", return_value=True):
            self.scan_job()
        self.assertEqual((self.sent, self.remembered()), ([], []))


class FailureTests(PushCase):
    def test_a_push_service_that_cannot_be_reached_does_not_break_the_scan_and_is_tried_again(self):
        device = self.device()
        self.failing = RuntimeError("couldn't reach the push service")
        self.incomplete()
        started = time.time() - 5
        self.scan_job()
        self.assertEqual((self.sent, self.remembered(), len(self.items())), ([], [], 1))
        self.assertIsNotNone(self.row()["last_scan"])
        self.assertIsNone(self.row()["scan_error"])
        self.assertEqual(self.read(lambda conn: [d.id for d in conn.orm.scalars(select(PushDevice)).all()]), [device])
        self.failing = None
        with db.session() as conn:
            self.assertEqual(reminders.review_due(conn, started, time.time(), self.send, [self.mailbox]), 1)
        self.assertEqual(self.bodies(), [ONE])

    def test_a_device_the_push_service_has_forgotten_is_dropped_and_the_scan_goes_on(self):
        self.device()
        self.failing = webpush.Gone("gone")
        self.incomplete()
        self.scan_job()
        self.assertEqual((self.read(lambda conn: conn.orm.scalars(select(PushDevice)).all()), len(self.items())), ([], 1))

    def test_a_failure_in_the_whole_step_is_reported_without_what_was_in_the_mail(self):
        self.device()
        self.incomplete()
        with mock.patch.object(reminders, "review_due", side_effect=RuntimeError("boom")), \
                mock.patch.object(jobs.monitoring, "report") as report:
            self.scan_job()
        report.assert_called_once()
        self.assertEqual(report.call_args.kwargs, {"values": False})
        self.assertEqual(len(self.items()), 1)

    def test_the_manual_scan_notifies_too_and_survives_a_failure(self):
        self.device()
        self.incomplete()
        self.assertTrue(jobs.scan_now(self.mailbox))
        for _ in range(100):
            if self.row()["last_scan"] is not None and not scan.running(self.mailbox):
                break
            time.sleep(0.1)
        for _ in range(50):
            if self.sent:
                break
            time.sleep(0.1)
        self.assertEqual(self.bodies(), [ONE])
        with mock.patch.object(reminders, "review_due", side_effect=RuntimeError("boom")), mock.patch.object(jobs.monitoring, "report") as report:
            jobs.notify_review(0.0, [self.mailbox])
        report.assert_called_once()

    def test_a_scan_that_fails_part_way_still_tells_about_what_it_queued(self):
        self.device()
        self.incomplete()
        def partly(today, scanned):
            scanned.append(self.mailbox)
            scan.run(self.mailbox, today)
            raise RuntimeError("boom")
        with mock.patch.object(scan, "scan_all", side_effect=partly), mock.patch.object(jobs.monitoring, "report"):
            self.scan_job()
        self.assertEqual(self.bodies(), [ONE])


class PrivacyTests(PushCase):
    SUBJECT = "CANARY-SUBJECT-PUSH-4T8W"
    SENDER = "CANARY-SENDER-PUSH-7Q2M"
    CODE = "CANARYPUSH9"
    NAME = "CANARY-TRAVELLER-PUSH-3F6H"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
        cls.service = HTTPServer(("127.0.0.1", 0), PushService)
        threading.Thread(target=cls.service.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.service.server_close)
        cls.addClassCleanup(cls.service.shutdown)

    def test_what_reaches_the_push_service_is_a_count_and_nothing_of_the_email(self):
        key, p256dh, auth = receiver()
        with db.session() as conn:
            conn.execute(insert(PushDevice).values(owner_sub="u-jane", endpoint=f"http://127.0.0.1:{self.service.server_port}/push/review",
                                                   p256dh=p256dh, auth=webpush.b64u(auth), created=time.time()))
        mail = (eml("incomplete")
                .replace(b"From: Example Air", f"From: Example Air {self.SENDER}".encode())
                .replace(b"Subject: Your itinerary (partial)", f"Subject: Your itinerary (partial) {self.SUBJECT}".encode())
                .replace(b"<p>CANARY", f"<p>{self.NAME} CANARY".encode())
                .replace(b"AB1CD2", self.CODE.encode()))
        self.add_mail("m-canary", mail)
        PushService.received.clear()
        canaries = ("CANARY-BODY-INCOMPLETE-4N7P", self.SUBJECT, self.SENDER, self.CODE, self.NAME)
        with mock.patch.object(reminders, "sender", self.real_sender), no_leaks(self, *canaries, database=self.path):
            self.scan_job()
        [(path, headers, body)] = PushService.received
        payload = decrypt(body, key, auth)
        self.assertEqual(payload, {"title": "Booking emails to review", "tag": "review", "url": "/#review", "body": ONE})
        wire = json.dumps(payload) + body.decode("latin-1") + str(dict(headers)) + path
        for canary in canaries:
            self.assertNotIn(canary, wire)
        self.assertEqual(len(self.items()), 1)

    def real_sender(self, conn, subject):
        vapid, _public = webpush.vapid_keys(conn)

        def send(device, message):
            webpush.send({"endpoint": device.endpoint, "p256dh": device.p256dh, "auth": device.auth}, message, vapid, subject)
        return send

    def test_the_message_is_made_of_a_count_alone(self):
        for waiting in (1, 2, 40):
            message = reminders.review_message(waiting)
            self.assertEqual(sorted(message), ["body", "tag", "title", "url"])
            self.assertEqual(message["body"], f"{waiting} booking email{' needs' if waiting == 1 else 's need'} your review")

    def test_nothing_is_stored_of_the_item_but_its_ids(self):
        self.device()
        self.incomplete()
        with no_leaks(self, "CANARY-BODY-INCOMPLETE-4N7P", database=self.path):
            self.scan_job()
        refs = self.read(lambda conn: list(conn.execute(select(ReminderSent.ref)).scalars()))
        self.assertEqual(refs, [f"{self.mailbox}/m-incomplete"])


if __name__ == "__main__":
    unittest.main()
