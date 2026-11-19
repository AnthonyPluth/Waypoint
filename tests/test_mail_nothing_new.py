import base64
import json
import unittest
from email.utils import parsedate_to_datetime
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.test_mail_ai import ScanAiCase
from tests.test_mail_newer import BODY_CANARY, revised
from tests.test_mail_scan import NOW
from waypoint import tls
from waypoint.domain import trips
from waypoint.domain.mail import ai, extract, newer, nothing_new, query, review, scan
from waypoint.storage import db, stored_mail
from waypoint.storage.models import ReviewItem, Segment, StoredMessage

BODY = "CANARY-BODY-NOTHING-NEW-4T8Q"
NAME = "CANARY-NAME-NOTHING-NEW-7C2R"
FOOTER = "CANARY-FOOTER-NOTHING-NEW-9V5M"
CANARIES = (BODY, NAME, FOOTER)
SUBJECT = "Your upcoming flight: online check-in is open"
REMINDER = "Your flight EX 101 from JFK to LHR departs on 20 November."
OLD_TEXT = "Flight EX 101 from JFK to LHR, booking QX7M2K, leaves 20 November."
SAME = {"kind": "flight", "provider": "Example Air", "origin": "JFK", "destination": "LHR", "start_local": "2026-11-20T19:00",
        "end_local": "2026-11-21T07:10", "flight_number": "EX 101"}
FULL = {**SAME, "confirmation": "QX7M2K"}
EARLIER = "Sat, 10 Oct 2026 09:30:00 -0400"
LATER = "Wed, 14 Oct 2026 09:30:00 -0400"
SAME_DAY = "Mon, 12 Oct 2026 09:30:00 -0400"
VERDICT = {"bookings": [], "not_a_booking": "promotion"}
CHECK_IN = f"{REMINDER} Online check-in is open."
CHANGED_TRIP_SUBJECTS = ("Your flight and hotel have been cancelled", "Schedule change for your flight and hotel", "Refund for your flight and hotel",
                        "Your flight and hotel are delayed")
CHANGED_SUBJECTS = ("Your flight has been cancelled", "Schedule change for your flight", "Refund for your flight", "Your flight is delayed")


AGENT = "Agent Travel <trips@agent-travel.example>"


def mail(body: str, subject: str = SUBJECT, date: str = SAME_DAY, ident: str = "x", sender: str = "Example Air <reservations@example-air.example>") -> bytes:
    return (f"From: {sender}\nTo: traveller@gmail.example\nSubject: {subject}\nDate: {date}\n"
            f"Message-ID: <{ident}@example-air.example>\nMIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n"
            f"{body}\n{BODY} {NAME}\n-- \n{FOOTER}\n").encode()


class NothingNewCase(ScanAiCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(query, "SENDERS", (*query.SENDERS, "example-air.example", "agent-travel.example"))
        patch.start()
        self.addCleanup(patch.stop)
        self.put("flight_jsonld")
        self.assertEqual(self.scan().bookings, 1)
        [self.known] = self.segments()
        self.turn_on()
        self.tick = 0

    def counted(self) -> tuple[int, int]:
        found = scan.summary(self.mailbox)
        return found.dismissed_known, found.dismissed_older

    def read_mail(self, body: str, reply: dict, name: str = "reminder", subject: str = SUBJECT, date: str = SAME_DAY,
                  sender: str = "Example Air <reservations@example-air.example>", arrived: str | None = None) -> scan.Result:
        self.tick += 60
        raw = mail(body, subject, date, name, sender)
        self.assertTrue(all(k.encode() in raw for k in CANARIES))
        self.add_mail(name, raw)
        if arrived is not None:
            self.google.arrived[name] = str(int(parsedate_to_datetime(arrived).timestamp() * 1000))
        self.fake.content = json.dumps(reply)
        with no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
            return self.scan(now=NOW + self.tick)

    def kept(self) -> list[dict]:
        return self.items()

    def stored(self) -> list[int]:
        return self.read(lambda conn: list(conn.execute(select(StoredMessage.id)).scalars()))

    def add_flight(self, viewer, number="EX 101", confirmation="AB1C2D", **changes):
        fields = {"kind": "flight", "status": "confirmed", "provider": "Example Air", "confirmation": confirmation, "origin": "JFK",
                  "destination": "LHR", "start_local": "2026-11-20T19:00", "start_zone": "America/New_York",
                  "end_local": "2026-11-21T07:10", "end_zone": "Europe/London", "details": {"flight_number": number}, **changes}
        return self.read(lambda conn: trips.add_segment(conn, viewer, fields))

    def assess(self, said, received=None, convert=False, sign=None, sender="example-air.example"):
        def run(conn):
            fields = scan._ai_fields(conn, said) if convert else None
            return nothing_new.assess(conn, self.jane, said, fields, received, sign or nothing_new.Signals(False), sender)
        return self.read(run)

    def edit_known(self, **changes):
        self.read(lambda conn: trips.edit_segment(conn, self.jane, self.known["id"], changes))


class AlreadyKnownTests(NothingNewCase):
    def attached(self) -> list[stored_mail.Attached]:
        return self.read(lambda conn: stored_mail.attached(conn, self.known["id"]))

    def test_a_reminder_that_repeats_the_booking_is_attached_to_it_and_counted_by_reason(self):
        result = self.read_mail(REMINDER, SAME)
        self.assertEqual((result.state, result.review, self.kept()), ("done", 0, []))
        self.assertEqual(self.counted(), (1, 0))
        self.assertEqual(self.scanned()["reminder"], "booking")
        self.assertEqual(len(self.stored()), 2)
        self.assertEqual([a["message_id"] for a in self.attached()], ["msg-flight_jsonld", "reminder"])

    def test_a_later_reminder_that_agrees_with_the_booking_becomes_its_newest_email_without_changing_it(self):
        before = self.segments()
        self.read_mail(REMINDER, SAME, date=LATER)
        self.assertEqual(self.segments(), before)
        self.assertEqual(max(a["received"] or "" for a in self.attached()), "2026-10-14")

    def test_the_trip_is_untouched_by_the_dismissed_reminder(self):
        before = self.segments()
        self.read_mail(REMINDER, SAME)
        self.assertEqual(self.segments(), before)

    def test_it_is_logged_as_counts_and_codes_only(self):
        said = []
        real = scan.monitoring.log
        with mock.patch.object(scan.monitoring, "log", side_effect=lambda text, *a, **k: (said.append(text), real(text, *a, **k))[1]):
            self.read_mail(REMINDER, SAME)
        self.assertTrue(any("1 attached as nothing new (1 × already known, 0 × older copy)" in t for t in said))
        self.assertFalse([t for t in said for k in (*CANARIES, "EX 101", "QX7M2K", SUBJECT) if k in t])

    def test_the_next_scan_does_not_ask_again(self):
        self.read_mail(REMINDER, SAME)
        asked = len(self.fake.requests)
        self.assertEqual(self.scan(now=NOW + 600, backfill=True).review, 0)
        self.assertEqual((len(self.fake.requests), self.kept()), (asked, []))

    def test_the_known_traveller_on_their_own_seat_adds_nothing(self):
        reply = {**SAME, "travelers": [{"name": "Jane Doe", "seat": "21C"}]}
        self.read_mail(f"{REMINDER}\nJane Doe 21C", reply)
        self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))

    def test_a_complete_reading_of_a_known_flight_is_kept_with_the_booking_and_never_dismissed(self):
        self.read_mail(f"{REMINDER}\nBooking QX7M2K", FULL, sender=AGENT)
        self.assertEqual((self.kept(), self.counted(), self.scanned()["reminder"]), ([], (0, 0), "booking"))
        self.assertEqual(len(self.read(lambda conn: stored_mail.attached(conn, self.known["id"]))), 2)

    def test_a_newer_identical_email_is_kept_so_a_message_dated_between_them_replaces_nothing(self):
        self.read_mail(f"{REMINDER}\nBooking QX7M2K", FULL, date=LATER, sender=AGENT)
        self.assertEqual(self.counted(), (0, 0))
        between = {"kind": "flight", "status": "confirmed", "provider": "Example Air", "confirmation": "QX7M2K", "origin": "JFK", "destination": "LHR",
                   "start_local": "2026-11-20T17:00", "start_zone": "America/New_York", "end_local": "2026-11-21T05:10", "end_zone": "Europe/London",
                   "details": {"flight_number": "EX 101"}}
        decision = self.read(lambda conn: newer.decide(conn, self.jane, between, "2026-10-13", False))
        self.assertEqual((decision.action, decision.segment_id), ("older", self.known["id"]))

    def stay(self) -> dict:
        stay = {"kind": "hotel", "provider": "Example Stays", "confirmation": "HT5K9P", "origin": "Harbour Hotel", "start_local": "2026-12-01T15:00",
                "end_local": "2026-12-04T11:00", "start_zone": "Europe/London", "end_zone": "Europe/London", "status": "confirmed", "details": {}}
        return self.read(lambda conn: trips.add_segment(conn, self.jane, stay))

    def test_a_complete_reading_of_a_known_stay_with_a_room_number_keeps_the_email_with_the_stay(self):
        held = self.stay()
        reply = {"kind": "hotel", "provider": "Example Stays", "confirmation": "HT5K9P", "origin": "Harbour Hotel",
                 "start_local": "2026-12-01T15:00", "end_local": "2026-12-04T11:00", "start_zone": "Europe/London", "end_zone": "Europe/London"}
        self.read_mail("Your stay at Harbour Hotel starts on 1 December. Example Stays HT5K9P. Your room number is 4401.", reply,
                       subject="Your hotel stay: check-in details")
        self.assertEqual((self.kept(), self.counted(), self.scanned()["reminder"]), ([], (0, 0), "booking"))
        self.assertEqual([a["message_id"] for a in self.read(lambda conn: stored_mail.attached(conn, held["id"]))], ["reminder"])


class MustStayInReviewTests(NothingNewCase):
    def stays(self, body: str, reply: dict, **kwargs) -> None:
        result = self.read_mail(body, reply, **kwargs)
        self.assertEqual(result.state, "done")
        self.assertEqual(len(self.kept()), 1)
        self.assertEqual(self.counted(), (0, 0))

    def test_the_models_own_nothing_new_verdict_never_dismisses_when_a_field_differs(self):
        self.stays(REMINDER, {**SAME, "start_local": "2026-11-20T19:30", "nothing_new": True, "not_a_booking": "promotion"})

    def test_the_models_nothing_new_verdict_is_not_what_dismisses_an_identical_one_either(self):
        self.read_mail(REMINDER, {**SAME, "nothing_new": False})
        self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))

    def test_any_one_field_that_differs_or_is_new_keeps_it(self):
        text = (f"{REMINDER} Also LGW, EX 102, Other Air, Business, Mia Rose Doe 14B, Jane Doe 22A, 1 Quay Road, total USD 120.00.")
        cases = {
            "departure": {**SAME, "start_local": "2026-11-20T19:30"},
            "arrival": {**SAME, "end_local": "2026-11-21T07:40"},
            "date": {**SAME, "start_local": "2026-11-21T19:00", "end_local": "2026-11-22T07:10"},
            "arrival airport": {**SAME, "destination": "LGW"},
            "flight number": {**SAME, "flight_number": "EX 102"},
            "provider": {**SAME, "provider": "Other Air"},
            "cabin": {**SAME, "cabin": "Business"},
            "price": {**SAME, "total": "120.00", "currency": "USD"},
            "new traveller": {**SAME, "travelers": [{"name": "Mia Rose Doe", "seat": "14B"}]},
            "other seat": {**SAME, "travelers": [{"name": "Jane Doe", "seat": "22A"}]},
        }
        for what, reply in cases.items():
            with self.subTest(what=what):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.stays(text, reply, name=f"m-{what.replace(' ', '-')}")

    def test_a_cancellation_a_change_or_a_refund_never_dismisses_even_with_the_same_fields(self):
        for what, line in (("cancelled", "Your flight EX 101 from JFK to LHR has been cancelled."),
                           ("change", "Schedule change: your flight EX 101 from JFK to LHR now departs later."),
                           ("refund", "Your refund for flight EX 101 from JFK to LHR is on its way."),
                           ("delay", "Your flight EX 101 from JFK to LHR is delayed."),
                           ("rebooked", "We rebooked you on flight EX 101 from JFK to LHR."),
                           ("gate", "Your flight EX 101 from JFK to LHR leaves from gate B12."),
                           ("seat", "Your flight EX 101 from JFK to LHR: pick your seat.")):
            with self.subTest(what=what):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.stays(line, SAME, name=f"c-{what}")

    def test_a_change_stated_only_in_the_subject_keeps_an_identical_body_in_review(self):
        for n, subject in enumerate(CHANGED_SUBJECTS):
            with self.subTest(subject=subject):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.stays(CHECK_IN, SAME, name=f"subj-{n}", subject=subject)

    def test_the_parsers_revision_signal_alone_keeps_it_in_review(self):
        with mock.patch.object(scan.extract, "guard", return_value=("", True)):
            self.stays(CHECK_IN, SAME, name="revises")

    def test_a_harmless_subject_still_dismisses(self):
        self.read_mail(CHECK_IN, SAME, subject="Your upcoming flight: online check-in is open")
        self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))

    def test_a_named_passenger_without_a_seat_who_is_not_on_the_booking_keeps_it_in_review(self):
        for n, who in enumerate(("Mia Rose Doe", "Alex Stranger", "Jane Doe and Alex Stranger")):
            with self.subTest(who=who):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.stays(f"{CHECK_IN}\nPassenger: {who}", SAME, name=f"pax-{n}")

    def test_a_named_passenger_already_on_the_booking_still_dismisses(self):
        self.read_mail(f"{CHECK_IN}\nPassenger: Jane Doe", SAME)
        self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))

    def test_a_flight_another_household_booking_also_holds_is_not_known_even_when_only_one_is_visible(self):
        self.add_flight(self.sam, "EX 101", "SM7777")
        self.stays(REMINDER, SAME)

    def test_a_flight_nobody_can_see_is_not_known(self):
        self.add_flight(self.sam, "EX 777", "SM7777")
        self.stays("Your flight EX 777 from JFK to LHR departs on 20 November.", {**SAME, "flight_number": "EX 777"})

    def test_a_flight_no_booking_holds_is_not_known(self):
        self.stays("Your flight EX 555 from JFK to LHR departs on 20 November.", {**SAME, "flight_number": "EX 555"})

    def test_two_visible_bookings_that_fit_make_the_match_unsure(self):
        self.add_flight(self.jane, "EX 101", "AB1C2D")
        self.stays(REMINDER, SAME)

    def test_a_booking_that_is_not_confirmed_is_not_a_match(self):
        for status in ("cancelled", "changed"):
            with self.subTest(status=status):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                    conn.execute(Segment.__table__.update().values(status=status))
                self.stays(REMINDER, SAME, name=f"s-{status}")

    def test_a_flight_on_another_day_or_between_other_airports_is_not_a_match(self):
        self.stays(REMINDER, {**SAME, "start_local": "2026-11-27T19:00", "end_local": "2026-11-28T07:10"}, name="day")
        with db.session() as conn:
            conn.execute(ReviewItem.__table__.delete())
        self.stays("Your flight EX 101 from BOS to DEN departs on 20 November.", {**SAME, "origin": "BOS", "destination": "DEN"}, name="airports")

    def test_a_hotel_with_a_field_that_differs_is_filed_as_before_and_not_counted(self):
        stay = {"kind": "hotel", "provider": "Example Stays", "confirmation": "HT5K9P", "origin": "Harbour Hotel", "start_local": "2026-12-01T15:00",
                "end_local": "2026-12-04T11:00", "start_zone": "Europe/London", "end_zone": "Europe/London", "status": "confirmed", "details": {}}
        self.read(lambda conn: trips.add_segment(conn, self.jane, stay))
        reply = {"kind": "hotel", "provider": "Example Stays", "confirmation": "HT5K9P", "origin": "Harbour Hotel",
                 "start_local": "2026-12-01T15:00", "end_local": "2026-12-05T11:00", "start_zone": "Europe/London", "end_zone": "Europe/London"}
        self.read_mail("Your stay at Harbour Hotel runs to 5 December. Example Stays HT5K9P", reply, subject="Your hotel stay: check-in details")
        self.assertEqual(self.counted(), (0, 0))
        self.assertEqual((self.scanned()["reminder"], self.segments()[-1]["status"], self.segments()[-1]["end_local"]), ("booking", "changed", "2026-12-05T11:00"))

    def test_a_reading_that_lost_a_booking_or_has_two_unknown_ones_stays(self):
        self.stays(REMINDER, {"bookings": [SAME, {**SAME, "flight_number": "EX 202", "origin": "LHR", "destination": "JFK"}]})

    def test_a_service_that_cannot_be_reached_or_answers_badly_never_dismisses(self):
        real = tls.urlopen

        def down(req, *args, **kwargs):
            if self.fake.url in getattr(req, "full_url", str(req)):
                raise OSError("down")
            return real(req, *args, **kwargs)
        self.add_mail("down", mail(REMINDER, ident="down"))
        with mock.patch.object(tls, "urlopen", down), no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
            self.assertEqual(self.scan(now=NOW + 60).review, 1)
        self.assertEqual((len(self.kept()), self.counted()), (1, (0, 0)))
        for status, content in ((500, "{}"), (200, "not json")):
            with self.subTest(status=status):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.fake.status, self.fake.content = status, content
                self.add_mail(f"e-{status}", mail(REMINDER, ident=f"e{status}"))
                with no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
                    self.scan(now=NOW + 120 + status)
                self.assertEqual(len(self.kept()), 1)
        self.assertEqual(self.counted(), (0, 0))

    def test_a_mailbox_whose_ai_reading_is_off_never_dismisses_and_never_asks(self):
        self.turn_off()
        self.add_mail("off", mail(REMINDER, ident="off"))
        self.fake.content = json.dumps(SAME)
        with no_leaks(self, *CANARIES, database=self.path):
            result = self.scan(now=NOW + 60)
        self.assertEqual((result.review, len(self.kept()), self.fake.requests, self.counted()), (1, 1, [], (0, 0)))

    def test_a_review_item_that_holds_matches_to_settle_is_left_alone(self):
        with db.session() as conn:
            conn.execute(ReviewItem.__table__.delete())
        self.add_mail("held", mail(REMINDER, ident="held"))
        self.scan(now=NOW + 60)
        [item] = self.kept()
        with db.session() as conn:
            conn.execute(ReviewItem.__table__.update().values(matches="[]", auto_state=None))
            filed = scan._file_ai(conn, self.mailbox, "held", [SAME], None, None, NOW, signals=nothing_new.signals(REMINDER), dismiss_known=True)
        self.assertEqual((filed.known, filed.cleared, item["id"]), (None, 0, self.kept()[0]["id"]))


class OlderCopyTests(NothingNewCase):
    def test_an_older_message_is_attached_without_changing_the_booking_or_becoming_its_newest_email(self):
        reply = {**FULL, "start_local": "2026-11-20T18:00"}
        self.read_mail(OLD_TEXT, reply, date=EARLIER, sender=AGENT)
        self.assertEqual((self.kept(), self.counted()), ([], (0, 1)))
        self.assertEqual((self.segments()[0]["start_local"], self.segments()[0]["status"]), ("2026-11-20T19:00", "confirmed"))
        self.assertEqual(self.scanned()["reminder"], "booking")
        held = self.read(lambda conn: stored_mail.attached(conn, self.known["id"]))
        self.assertEqual(sorted(a["received"] or "" for a in held), ["2026-10-10", "2026-10-12"])

    def test_a_cancellation_or_change_in_another_language_keeps_it_in_review(self):
        for n, line in enumerate(("Votre vol EX 101 de JFK à LHR est annulé.", "Ihr Flug EX 101 von JFK nach LHR wurde storniert.",
                                  "EX 101 JFK-LHR のフライトはキャンセルされました。", "Su vuelo EX 101 de JFK a LHR fue anulado.")):
            with self.subTest(line=line):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.read_mail(line, SAME, name=f"lang-{n}")
                self.assertEqual((len(self.kept()), self.counted()), (1, (0, 0)))
                self.read_mail(line, {**FULL, "start_local": "2026-11-20T18:00"}, name=f"lang-old-{n}", date=EARLIER, sender=AGENT)
                self.assertEqual(self.counted(), (0, 0))

    def test_an_older_cancellation_or_change_is_never_counted_as_nothing_new(self):
        for what, line in (("cancel", "Flight EX 101 from JFK to LHR, booking QX7M2K, was cancelled."),
                           ("change", "Flight EX 101 from JFK to LHR, booking QX7M2K, has a schedule change.")):
            with self.subTest(what=what):
                self.read_mail(line, {**FULL, "start_local": "2026-11-20T18:00"}, name=f"o-{what}", date=EARLIER, sender=AGENT)
                self.assertEqual(self.counted(), (0, 0))
                self.assertEqual(self.segments()[0]["start_local"], "2026-11-20T19:00")

    def filed_directly(self, subject: str, name: str):
        earlier = {**FULL, "start_local": "2026-11-20T18:00"}
        with db.session() as conn:
            review.add(conn, self.mailbox, name, "agent-travel.example", "2026-10-10", "no_markup", NOW)
            return scan._file_ai(conn, self.mailbox, name, [earlier], None, None, NOW, signals=nothing_new.signals(OLD_TEXT, subject), dismiss_known=True)

    def test_an_older_message_with_a_change_only_in_the_subject_is_not_dismissed_as_a_copy(self):
        self.assertEqual(self.filed_directly("Your upcoming flight", "os-ok").known, "older_copy")
        for n, subject in enumerate(CHANGED_SUBJECTS):
            with self.subTest(subject=subject):
                self.assertIsNone(self.filed_directly(subject, f"os-{n}").known)

    def test_an_older_message_naming_a_passenger_who_is_not_on_the_booking_is_not_dismissed_as_a_copy(self):
        self.read_mail(f"{OLD_TEXT}\nPassenger: Mia Rose Doe", {**FULL, "start_local": "2026-11-20T18:00"}, name="op", date=EARLIER, sender=AGENT)
        self.assertEqual(self.counted(), (0, 0))

    def test_a_newer_message_with_a_different_time_is_not_dismissed(self):
        self.read_mail(OLD_TEXT, {**FULL, "start_local": "2026-11-20T21:30"}, date=LATER, sender=AGENT)
        self.assertEqual(self.counted(), (0, 0))
        self.assertEqual(self.segments()[0]["start_local"], "2026-11-20T21:30")

    def test_an_older_message_for_a_booking_that_is_not_the_only_match_stays(self):
        self.add_flight(self.jane, "EX 101", "QX7M2K", start_local="2026-11-20T19:00")
        self.read_mail(OLD_TEXT, FULL, date=EARLIER, sender=AGENT)
        self.assertEqual(self.counted(), (0, 0))


class VerdictStaysTests(NothingNewCase):
    CATEGORIES = ("promotion", "statement", "newsletter", "receipt", "notification")
    BODIES = {
        "plain marketing": "Thank you for being a customer. Save on your next purchase this week.",
        "time": "Sale ends at 11:59 pm tonight.",
        "airports": "Fly from Boston (BOS) to Denver (DEN) this winter.",
        "confirmation": "Your confirmation code is ZZ9Y8X.",
        "booking reference": "Thank you for your payment. Booking reference: QXMKZB",
        "flight": "Take flight EX 101 for less.",
        "passenger": "Passenger Jane Doe, thank you.",
        "check in": "Online check-in is open for your trip.",
        "cancellation": "Your booking was cancelled. Save 10 percent on your next trip.",
        "cancellation in german": "Ihre Buchung wurde storniert. Sparen Sie diese Woche.",
        "cancellation in japanese": "ご予約はキャンセルされました。今週のセール。",
        "fare change": "Fare change: save on your next trip.",
    }

    def stays(self, body: str, category: str, name: str, subject: str = "Your trip: save on flights and hotels") -> None:
        with db.session() as conn:
            conn.execute(ReviewItem.__table__.delete())
            stored_mail.prune(conn)
        result = self.read_mail(body, {"bookings": [], "not_a_booking": category}, name=name, subject=subject)
        self.assertEqual(result.state, "done")
        [item] = self.kept()
        self.assertEqual(item["suggestion_error"], ai.NO_BOOKING)
        self.assertEqual(len(self.stored()), 2)
        self.assertEqual(self.counted(), (0, 0))
        self.assertEqual(self.scanned()[name], "unreadable")

    def test_every_verdict_on_every_kind_of_text_leaves_the_email_stored_and_in_review(self):
        for what, line in self.BODIES.items():
            for category in self.CATEGORIES:
                with self.subTest(what=what, category=category):
                    self.stays(line, category, f"v-{what}-{category}".replace(" ", "-"))

    def test_a_verdict_on_an_email_whose_subject_states_a_change_stays(self):
        for n, subject in enumerate(CHANGED_TRIP_SUBJECTS):
            with self.subTest(subject=subject):
                self.stays("Thank you for being a customer.", "promotion", f"vs-{n}", subject)

    def test_the_revision_signal_alone_keeps_a_verdict_in_review(self):
        with mock.patch.object(scan.extract, "guard", return_value=("", True)):
            self.stays("Thank you for being a customer.", "promotion", "rv")

    def test_a_person_dismissing_the_item_is_what_deletes_the_email(self):
        self.stays("Thank you for being a customer.", "promotion", "mine")
        [item] = self.kept()
        with db.session() as conn:
            review.dismiss(conn, "u-jane", item["id"])
        self.assertEqual((self.kept(), len(self.stored())), ([], 1))

    def test_an_answer_with_a_booking_beside_the_verdict_is_not_a_verdict(self):
        result = self.read_mail(REMINDER, {"bookings": [SAME], "not_a_booking": "promotion"}, name="booked")
        self.assertEqual((result.state, self.counted()), ("done", (1, 0)))


class ComparisonTests(NothingNewCase):
    def test_every_field_the_email_states_must_already_be_held(self):
        self.assertEqual(self.assess(SAME), "already_known")
        differing = {"confirmation": "ZZ9Y8X", "address": "1 Quay Road", "phone": "+44 117 555 0100", "room": "4401", "ship": "Example Star",
                     "deck": "9", "cabin": "Business", "price_minor": 12000, "provider": "Other Air",
                     "start_zone": "Europe/London", "end_zone": "America/New_York", "origin": "BOS"}
        for name, value in differing.items():
            with self.subTest(field=name):
                self.assertIsNone(self.assess({**SAME, name: value}))

    def test_fields_the_booking_holds_may_be_repeated(self):
        self.assertEqual(self.assess({**FULL, "cabin": "Economy", "start_zone": "America/New_York", "end_zone": "Europe/London"}), "already_known")

    def test_a_price_equal_to_the_held_one_adds_nothing_and_a_price_where_none_is_held_is_new(self):
        self.assertIsNone(self.assess({**SAME, "price_minor": 12000, "price_currency": "USD"}))
        self.read(lambda conn: trips.edit_segment(conn, self.jane, self.known["id"], {"price": {"amount_minor": 12000, "currency": "USD"}}))
        self.assertEqual(self.assess({**SAME, "price_minor": 12000, "price_currency": "USD"}), "already_known")
        self.assertIsNone(self.assess({**SAME, "price_minor": 13000, "price_currency": "USD"}))

    def test_a_confirmation_the_booking_does_not_hold_is_new(self):
        self.read(lambda conn: trips.edit_segment(conn, self.jane, self.known["id"], {"confirmation": None}))
        self.assertIsNone(self.assess(FULL))

    def test_a_flight_needs_its_number_its_date_and_an_airport_to_match(self):
        self.assertIsNone(self.assess({k: v for k, v in SAME.items() if k != "flight_number"}))
        self.assertIsNone(self.assess({**SAME, "origin": "BOS", "destination": "DEN"}))
        self.assertIsNone(self.assess({**SAME, "start_local": ""}))
        self.assertEqual(self.assess({**SAME, "destination": "LHR", "origin": "JFK"}), "already_known")

    def test_a_stay_is_matched_by_confirmation_and_compared_field_by_field(self):
        stay = {"kind": "hotel", "provider": "Example Stays", "confirmation": "HT5K9P", "origin": "Harbour Hotel", "start_local": "2026-12-01T15:00",
                "end_local": "2026-12-04T11:00", "start_zone": "Europe/London", "end_zone": "Europe/London", "status": "confirmed",
                "details": {"address": "1 Quay Road"}}
        self.read(lambda conn: trips.add_segment(conn, self.jane, stay))
        said = {"kind": "hotel", "provider": "Example Stays", "confirmation": "HT5K9P", "origin": "Harbour Hotel", "start_local": "2026-12-01T15:00",
                "end_local": "2026-12-04T11:00", "start_zone": "Europe/London", "end_zone": "Europe/London", "address": "1 Quay Road"}
        self.assertIsNone(self.assess(said, convert=True))
        self.assertIsNone(self.assess({**said, "address": "2 Quay Road"}, convert=True))
        self.assertIsNone(self.assess({**said, "confirmation": "ZZ9Y8X"}, convert=True))
        self.assertIsNone(self.assess({k: v for k, v in said.items() if k != "start_zone"}))
        self.assertIsNone(self.assess({**said, "start_local": "2026-12-02T15:00"}, convert=True))

    def test_an_older_message_is_a_copy_only_when_it_is_dated_before_the_attached_one(self):
        earlier = {**FULL, "start_local": "2026-11-20T18:00"}
        self.assertEqual(self.assess(earlier, received="2026-10-10", convert=True), "older_copy")
        self.assertIsNone(self.assess(earlier, received="2026-10-12", convert=True))
        self.assertIsNone(self.assess(FULL, received="2026-10-10", convert=True))
        self.assertEqual(self.assess(FULL, received="2026-10-10"), "already_known")
        self.assertIsNone(self.assess({**FULL, "start_local": "2026-11-20T21:30"}, received="2026-10-14", convert=True))
        self.assertIsNone(self.assess({**FULL, "start_local": "2026-11-20T21:30"}, received=None, convert=True))


class OlderCopyComparisonTests(NothingNewCase):
    EARLIER_TIMES = {**FULL, "start_local": "2026-11-20T18:00", "end_local": "2026-11-21T06:10"}

    def older(self, **more):
        return self.assess({**self.EARLIER_TIMES, **more}, received="2026-10-10", convert=True)

    def test_an_older_copy_that_adds_nothing_but_superseded_times_is_dismissed(self):
        self.assertEqual(self.older(), "older_copy")
        self.assertEqual(self.older(start_zone="America/New_York", end_zone="Europe/London", cabin="Economy"), "older_copy")

    def test_an_older_copy_with_another_seat_for_a_known_traveller_is_still_a_copy(self):
        self.assertEqual(self.older(travelers=[{"name": "Jane Doe", "seat": "30A"}]), "older_copy")

    def test_an_older_copy_that_states_anything_the_booking_lacks_is_kept(self):
        extras = {"price": {"price_minor": 12000, "price_currency": "USD"}, "cabin": {"cabin": "Business"}, "company": {"provider": "Other Air"},
                  "traveller": {"travelers": [{"name": "Mia Rose Doe", "seat": "14B"}]}, "address": {"address": "1 Quay Road"},
                  "phone": {"phone": "+44 117 555 0100"}, "confirmation": {"confirmation": "ZZ9Y8X"}, "number": {"flight_number": "EX 102"}}
        for what, more in extras.items():
            with self.subTest(what=what):
                self.assertIsNone(self.older(**more))

    def test_an_older_copy_of_a_booking_that_is_not_confirmed_is_kept(self):
        for status in ("changed", "cancelled"):
            with self.subTest(status=status):
                with db.session() as conn:
                    conn.execute(Segment.__table__.update().values(status=status))
                self.assertIsNone(self.older())
        with db.session() as conn:
            conn.execute(Segment.__table__.update().values(status="confirmed"))
        self.assertEqual(self.older(), "older_copy")

    def test_an_older_copy_that_mentions_a_room_rate_or_vehicle_is_kept(self):
        for line in ("Your room number is 4401.", "Deluxe King Room", "Your suite is ready", "Breakfast included", "Nightly rate 150.00",
                     "Vehicle: compact or similar"):
            with self.subTest(line=line):
                self.assertIsNone(self.older_signed(line))
        self.assertEqual(self.older_signed("See you soon."), "older_copy")

    def older_signed(self, text: str):
        return self.assess(self.EARLIER_TIMES, received="2026-10-10", convert=True, sign=nothing_new.signals(text))

    def test_an_older_copy_may_print_only_its_own_or_the_booking_s_seats_and_times(self):
        self.assertEqual(self.older_signed("Departs 18:00, lands 06:10"), "older_copy")
        self.assertIsNone(self.older_signed("Departs 18:00, check-in closes 17:15"))
        self.assertIsNone(self.older_signed("Jane Doe 30A"))
        self.assertEqual(self.assess({**self.EARLIER_TIMES, "travelers": [{"name": "Jane Doe", "seat": "30A"}]}, received="2026-10-10", convert=True,
                                     sign=nothing_new.signals("Jane Doe 30A")), "older_copy")
        self.assertEqual(self.older_signed("Jane Doe 21C"), "older_copy")

    def test_an_older_copy_with_a_total_the_booking_already_holds_is_dismissed(self):
        self.read(lambda conn: trips.edit_segment(conn, self.jane, self.known["id"], {"price": {"amount_minor": 12000, "currency": "USD"}}))
        self.assertEqual(self.older(price_minor=12000, price_currency="USD"), "older_copy")
        self.assertIsNone(self.older(price_minor=13000, price_currency="USD"))

    def test_an_older_confirmation_with_a_total_waits_in_review_and_changes_nothing_on_the_booking(self):
        self.read_mail(f"{OLD_TEXT} Total USD 120.00", {**self.EARLIER_TIMES, "total": "120.00", "currency": "USD"}, date=EARLIER, sender=AGENT)
        self.assertEqual((self.counted(), len(self.kept())), ((0, 0), 1))
        self.assertEqual((self.segments()[0]["price"], self.segments()[0]["start_local"]), (None, "2026-11-20T19:00"))

    def test_names_codes_flights_and_unextracted_details_the_comparison_cannot_see_keep_an_email(self):
        sign = nothing_new.signals
        self.assertIsNone(self.assess(SAME, sign=sign("Passenger: Alex Stranger")))
        self.assertIsNone(self.assess(SAME, sign=sign("Confirmation code ZZ9Y8X")))
        self.assertEqual(self.assess(SAME, sign=sign("Confirmation code QX7M2K")), "already_known")
        self.assertIsNone(self.assess(SAME, sign=sign("Your ticket is 0161234567890")))


class UnextractedDetailTests(NothingNewCase):
    def test_details_the_model_never_extracts_keep_an_identical_reminder_in_review(self):
        lines = {"ticket": "Ticket number 0161234567890.", "loyalty": "Frequent flyer number ZZ12345.", "baggage": "Baggage: 2 checked bags.",
                 "link": "Manage it at https://example-air.example/trip/abc.", "total": "Total paid USD 120.00.", "meal": "Your meal choice is vegetarian.",
                 "itinerary": "See your itinerary for connections."}
        for what, line in lines.items():
            with self.subTest(what=what):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                result = self.read_mail(f"{CHECK_IN}\n{line}", SAME, name=f"u-{what}")
                self.assertEqual((result.state, len(self.kept()), self.counted()), ("done", 1, (0, 0)))

    def test_a_second_flight_in_the_text_the_model_did_not_return_keeps_it(self):
        result = self.read_mail(f"{CHECK_IN} Return flight EX 102 from LHR to JFK departs on 27 November.", SAME, name="return")
        self.assertEqual((result.state, len(self.kept()), self.counted()), ("done", 1, (0, 0)))

    def test_a_confirmation_code_that_is_not_the_matched_bookings_keeps_it(self):
        self.read_mail(f"{CHECK_IN} Confirmation code: ZZ9Y8X", SAME, name="code")
        self.assertEqual((len(self.kept()), self.counted()), (1, (0, 0)))

    def test_covers_compares_the_flight_numbers_in_the_text_with_those_returned(self):
        both = [SAME, {**SAME, "flight_number": "EX 102"}]
        self.assertTrue(nothing_new.covers(nothing_new.signals("Flight EX 101 and EX 102 on 20 NOV"), both))
        self.assertFalse(nothing_new.covers(nothing_new.signals("Flight EX 101 and EX 102"), [SAME]))
        self.assertTrue(nothing_new.covers(nothing_new.signals("Nothing here"), [SAME]))


    def test_a_leg_the_reading_left_out_keeps_it_however_its_number_is_written(self):
        for n, leg in enumerate(("EX-102", "ex 102", "ex-102", "EX0102", "Flight No.: ex 102", "| EX102 |")):
            with self.subTest(leg=leg):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                result = self.read_mail(f"{CHECK_IN} Return flight {leg} from LHR to JFK on 27 November.", SAME, name=f"leg-{n}")
                self.assertEqual((result.state, len(self.kept()), self.counted()), ("done", 1, (0, 0)))

    def test_a_total_in_any_currency_keeps_an_identical_reminder(self):
        for n, line in enumerate(("Total JPY 12,000.", "Paid CHF 120.00.", "₹ 5,000 for seats.", "120.00 SEK")):
            with self.subTest(line=line):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.read_mail(f"{CHECK_IN} {line}", SAME, name=f"cur-{n}")
                self.assertEqual((len(self.kept()), self.counted()), (1, (0, 0)))


    def test_the_same_flight_listed_on_another_day_keeps_it_when_only_one_day_was_returned(self):
        for n, other in enumerate(("27 November", "Nov 27", "2026-11-27", "27/11", "11月27日")):
            with self.subTest(other=other):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                result = self.read_mail(f"{CHECK_IN} Flight EX 101 from JFK to LHR also on {other}.", SAME, name=f"day-{n}")
                self.assertEqual((result.state, len(self.kept()), self.counted()), ("done", 1, (0, 0)))

    def test_every_day_the_text_names_must_be_a_day_the_reading_returned(self):
        self.assertTrue(nothing_new.covers(nothing_new.signals("EX 101 on 20 November, landing 21 Nov"), [SAME]))
        self.assertFalse(nothing_new.covers(nothing_new.signals("EX 101 on 20 November and 27 November"), [SAME]))
        self.assertTrue(nothing_new.covers(nothing_new.signals("EX 101 on 20/11"), [SAME]))
        self.assertTrue(nothing_new.covers(nothing_new.signals("EX 101 on 11/20/2026"), [SAME]))


    def test_a_printed_seat_the_booking_does_not_hold_keeps_it_in_any_layout(self):
        for n, line in enumerate(("Passenger: Jane Doe 22A", "Jane Doe | 22A", "Jane Doe — 22a", "Row 22, 22A")):
            with self.subTest(line=line):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                result = self.read_mail(f"{CHECK_IN}\n{line}", SAME, name=f"seat-{n}")
                self.assertEqual((result.state, len(self.kept()), self.counted()), ("done", 1, (0, 0)))

    def test_a_printed_seat_the_booking_holds_still_dismisses(self):
        self.read_mail(f"{CHECK_IN}\nPassenger: Jane Doe 21C", SAME)
        self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))

    def test_a_time_of_day_the_booking_does_not_hold_keeps_it(self):
        for n, line in enumerate(("Check-in closes at 17:30.", "Check-in closes 5:30 pm.", "Check-in closes 17h30.")):
            with self.subTest(line=line):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                result = self.read_mail(f"{CHECK_IN} {line}", SAME, name=f"clock-{n}")
                self.assertEqual((result.state, len(self.kept()), self.counted()), ("done", 1, (0, 0)))

    def test_a_time_written_as_an_hour_alone_that_the_booking_does_not_hold_keeps_it(self):
        for n, line in enumerate(("Check-in closes at 5 pm.", "Check-in closes 5pm.", "Check-in closes 5 p.m.", "Check-in closes 5PM.",
                                  "L’enregistrement ferme à 17 h.", "Check-in closes at noon.")):
            with self.subTest(line=line):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                result = self.read_mail(f"{CHECK_IN} {line}", SAME, name=f"hour-{n}")
                self.assertEqual((result.state, len(self.kept()), self.counted()), ("done", 1, (0, 0)))

    def test_the_booking_s_own_time_written_as_an_hour_alone_still_dismisses(self):
        self.read_mail(f"{CHECK_IN} Departs 7 pm.", SAME)
        self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))
        for text in ("Departs 7 p.m.", "Departs 7pm", "Départ 19h", "Departs 19時"):
            with self.subTest(text=text):
                self.assertEqual(nothing_new.signals(text).clocks, frozenset({(19, 0)}))

    def test_the_booking_s_own_times_may_be_printed(self):
        self.read_mail(f"{CHECK_IN} Departs 7:00 pm, lands 07:10.", SAME)
        self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))


OUTSIDER = "Example Air Alerts <alerts@example-air-alerts.example>"
LOOKALIKE = "Example Air <trips@exampleair.lookalike.example>"
FAR_FUTURE = "Fri, 10 Oct 2031 09:30:00 -0400"
ARRIVED = "Tue, 13 Oct 2026 09:30:00 -0400"


class WhoMayAttachTests(NothingNewCase):
    def attached(self) -> list[stored_mail.Attached]:
        return self.read(lambda conn: stored_mail.attached(conn, self.known["id"]))

    def stays_in_review(self) -> None:
        self.assertEqual((len(self.kept()), self.counted()), (1, (0, 0)))
        self.assertEqual([a["message_id"] for a in self.attached()], ["msg-flight_jsonld"])
        self.assertNotEqual(self.scanned()["reminder"], "booking")

    def test_a_reminder_from_the_sender_of_an_email_kept_with_the_booking_is_attached(self):
        for n, sender in enumerate(("Example Air <reservations@example-air.example>", "Example Air <news@alerts.example-air.example>")):
            with self.subTest(sender=sender):
                self.read_mail(REMINDER, SAME, name=f"same-{n}", sender=sender)
                self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))
                self.assertIn(f"same-{n}", [a["message_id"] for a in self.attached()])

    def test_an_identical_reminder_from_another_sender_domain_stays_in_review(self):
        self.read_mail(REMINDER, SAME, sender=OUTSIDER)
        self.stays_in_review()

    def test_a_sender_whose_domain_only_names_the_airline_stays_in_review(self):
        self.read_mail(REMINDER, SAME, sender=LOOKALIKE)
        self.stays_in_review()

    def test_a_reminder_from_another_sender_that_carries_the_booking_s_code_is_attached(self):
        self.read_mail(f"{REMINDER} Booking reference QX7M2K.", SAME, sender=OUTSIDER)
        self.assertEqual((self.kept(), self.counted()), ([], (1, 0)))
        self.assertEqual([a["message_id"] for a in self.attached()], ["msg-flight_jsonld", "reminder"])

    def test_an_older_copy_needs_the_code_in_its_text_or_the_booking_s_own_sender(self):
        earlier = {**FULL, "start_local": "2026-11-20T18:00"}
        self.assertEqual(self.assess(earlier, received="2026-10-10", convert=True), "older_copy")
        self.assertIsNone(self.assess(earlier, received="2026-10-10", convert=True, sender="example-air-alerts.example"))
        self.assertEqual(self.assess(earlier, received="2026-10-10", convert=True, sender="example-air-alerts.example",
                                     sign=nothing_new.signals(OLD_TEXT)), "older_copy")

    def forwarded(self, body: str, sender: str, subject: str = f"Fwd: {SUBJECT}", marker: str = "---------- Forwarded message ---------") -> None:
        text = f"{marker}\nFrom: Example Air <reservations@example-air.example>\nSubject: Your upcoming flight\n\n{body}"
        self.read_mail(text, SAME, subject=subject, sender=sender)

    def test_a_forward_shaped_reminder_from_an_outside_sender_naming_the_airline_in_its_body_stays_in_review(self):
        self.forwarded(REMINDER, OUTSIDER)
        self.stays_in_review()

    def test_a_forward_shaped_reminder_stays_in_review_however_it_is_marked(self):
        for n, (subject, marker) in enumerate(((SUBJECT, "---------- Forwarded message ---------"), (f"Fwd: {SUBJECT}", "Begin forwarded message:"),
                                               (f"FW: {SUBJECT}", "Begin forwarded message:"))):
            with self.subTest(subject=subject, marker=marker):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.tick += 60
                text = f"{marker}\nFrom: Example Air <reservations@example-air.example>\nSubject: Your upcoming flight\n\n{REMINDER}"
                self.add_mail(f"fw-{n}", mail(text, subject, SAME_DAY, f"fw-{n}", OUTSIDER))
                self.fake.content = json.dumps(SAME)
                with no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
                    self.scan(now=NOW + self.tick)
                self.assertEqual((self.counted(), self.scanned()[f"fw-{n}"]), ((0, 0), "unreadable"))
                self.assertNotIn(f"fw-{n}", [a["message_id"] for a in self.attached()])

    def test_even_the_booking_s_own_sender_forwarding_a_reminder_without_the_code_stays_in_review(self):
        self.forwarded(REMINDER, "Example Air <reservations@example-air.example>")
        self.stays_in_review()

    def test_a_household_member_s_forward_that_carries_the_booking_s_code_is_still_a_follow_up(self):
        self.forwarded(f"{REMINDER} Booking reference QX7M2K.", "Jane Doe <jane@gmail.example>")
        self.assertEqual((self.kept(), self.scanned()["reminder"]), ([], "follow-up"))

    def only_kept_from(self, domain: str, seg: dict | None = None) -> None:
        seg = seg or self.add_flight(self.jane, "EX 202", "ZT4P8Q")
        content = {"subject": "Booked", "sender_domain": domain, "received": "2026-10-12", "text": "Booked.", "html": None,
                   "truncated": False, "original": True, "images": 0}
        def link(conn):
            stored_mail.put(conn, self.mailbox, f"kept-{domain}", content, NOW)
            stored_mail.link(conn, seg["id"], self.mailbox, f"kept-{domain}")
        self.read(link)

    def test_a_sender_is_trusted_at_the_kept_domain_or_below_it_never_above_it(self):
        self.only_kept_from("alerts.example-air.example")
        said = {**SAME, "flight_number": "EX 202"}
        self.assertEqual(self.assess(said, sender="alerts.example-air.example"), "already_known")
        self.assertEqual(self.assess(said, sender="news.alerts.example-air.example"), "already_known")
        self.assertIsNone(self.assess(said, sender="example-air.example"))
        self.assertIsNone(self.assess(said, sender="other.example-air.example"))
        self.assertIsNone(self.assess(said, sender="badalerts.example-air.example"))

    def refuses_users_of(self, domain: str) -> None:
        self.only_kept_from(domain)
        said = {**SAME, "flight_number": "EX 202"}
        coded = nothing_new.signals("EX 202 JFK to LHR. Booking reference ZT4P8Q.")
        self.assertEqual(self.assess(said, sender=None, sign=coded), "already_known")
        self.assertEqual(self.assess(said, sender=domain, sign=coded), "already_known")
        self.assertIsNone(self.assess(said, sender=domain))
        self.assertIsNone(self.assess(said, sender=f"news.{domain}"))

    def test_a_shared_mail_service_never_vouches_for_its_users(self):
        self.refuses_users_of("gmail.com")

    def test_a_regional_shared_mail_service_never_vouches_for_its_users(self):
        self.refuses_users_of("hotmail.fr")

    def test_an_isp_mail_domain_never_vouches_for_its_users(self):
        self.refuses_users_of("orange.fr")

    def test_a_made_up_non_travel_domain_never_vouches_for_its_users(self):
        self.refuses_users_of("mail.made-up-isp.example")

    def test_a_reminder_from_a_non_travel_domain_kept_with_the_booking_stays_in_review(self):
        self.only_kept_from("hotmail.fr", self.known)
        self.read_mail(REMINDER, SAME, sender="Someone <someone@hotmail.fr>")
        self.assertEqual((len(self.kept()), self.counted()), (1, (0, 0)))
        self.assertNotIn("reminder", [a["message_id"] for a in self.attached()])

    def test_a_reminder_with_the_code_from_a_non_travel_domain_kept_with_the_booking_still_attaches(self):
        self.only_kept_from("hotmail.fr", self.known)
        self.read_mail(f"{REMINDER} Booking reference QX7M2K.", SAME, sender="Someone <someone@hotmail.fr>")
        self.assertEqual((self.kept(), self.scanned()["reminder"]), ([], "follow-up"))

    def test_a_known_travel_sender_kept_with_the_booking_vouches_at_the_same_domain_and_below(self):
        with mock.patch.object(query, "SENDERS", (*query.SENDERS, "known-air.example")):
            self.only_kept_from("known-air.example")
            said = {**SAME, "flight_number": "EX 202"}
            self.assertEqual(self.assess(said, sender="known-air.example"), "already_known")
            self.assertEqual(self.assess(said, sender="news.known-air.example"), "already_known")
            self.assertIsNone(self.assess(said, sender="other-air.example"))

    def test_assess_needs_the_code_in_the_text_or_a_kept_sender(self):
        self.assertEqual(self.assess(SAME), "already_known")
        self.assertIsNone(self.assess(SAME, sender="example-air-alerts.example"))
        self.assertIsNone(self.assess(SAME, sender=None))
        self.assertEqual(self.assess(SAME, sender=None, sign=nothing_new.signals(f"{REMINDER} Booking reference QX7M2K.")), "already_known")
        self.assertIsNone(self.assess(SAME, sender=None, sign=nothing_new.signals(f"{REMINDER} Booking reference ZZ9Y8X.")))


class SendersDateTests(NothingNewCase):
    def attached(self) -> list[stored_mail.Attached]:
        return self.read(lambda conn: stored_mail.attached(conn, self.known["id"]))

    def test_a_future_dated_reminder_is_kept_as_of_the_day_it_arrived(self):
        self.read_mail(REMINDER, SAME, date=FAR_FUTURE, arrived=ARRIVED)
        self.assertEqual(self.counted(), (1, 0))
        self.assertEqual(max(a["received"] or "" for a in self.attached()), "2026-10-13")

    def test_a_future_dated_reminder_does_not_make_a_later_airline_change_older(self):
        self.read_mail(REMINDER, SAME, date=FAR_FUTURE, arrived=ARRIVED)
        raw = revised()
        self.assertIn(BODY_CANARY.encode(), raw)
        self.add_mail("newer", raw)
        with no_leaks(self, BODY_CANARY, database=self.path, sent_ok=True):
            self.scan(now=NOW + 600)
        [seg] = self.segments()
        self.assertEqual((seg["id"], seg["start_local"], seg["status"]), (self.known["id"], "2026-11-20T21:30", "changed"))
        self.assertIn("newer", [a["message_id"] for a in self.attached()])

    def test_the_sender_that_vouches_is_the_message_s_own_never_one_written_in_its_body(self):
        def own(body: str, subject: str = SUBJECT, sender: str = OUTSIDER) -> str | None:
            return extract.own_sender({"raw": base64.urlsafe_b64encode(mail(body, subject, sender=sender)).decode()})
        self.assertEqual(own(REMINDER), "example-air-alerts.example")
        self.assertEqual(own(REMINDER, sender="Example Air <reservations@example-air.example>"), "example-air.example")
        fwd = "---------- Forwarded message ---------\nFrom: Example Air <reservations@example-air.example>\nSubject: Hi\n\n" + REMINDER
        self.assertIsNone(own(fwd))
        self.assertIsNone(own(REMINDER, "Fwd: Your upcoming flight"))
        self.assertIsNone(extract.own_sender({"raw": "!!"}))

    def test_the_sender_s_date_is_kept_when_it_is_not_after_the_message_arrived(self):
        def read(date: str, arrived: str | None) -> str | None:
            message = {"raw": base64.urlsafe_b64encode(mail(REMINDER, date=date)).decode()}
            if arrived:
                message["internalDate"] = str(int(parsedate_to_datetime(arrived).timestamp() * 1000))
            return extract.read(message).received
        self.assertEqual(read(SAME_DAY, ARRIVED), "2026-10-12")
        self.assertEqual(read(FAR_FUTURE, ARRIVED), "2026-10-13")
        self.assertEqual(read(FAR_FUTURE, None), "2031-10-10")
        self.assertEqual(read("Mon, 12 Oct 2026 23:30:00 -0400", "Tue, 13 Oct 2026 03:31:00 +0000"), "2026-10-12")


class SignalTests(unittest.TestCase):
    def test_every_way_a_flight_number_is_written_is_recognised(self):
        written = {"EX102": "EX102", "EX 102": "EX102", "EX-102": "EX102", "ex102": "EX102", "ex-102": "EX102", "ex 102": "EX102",
                   "EX0102": "EX102", "U2 1234": "U21234", "3K 551": "3K551", "| EX102 |": "EX102", "<td>EX102</td>": "EX102",
                   "Flight: EX-102": "EX102", "Flight No. ex 102": "EX102", "flight number u2 1234": "U21234"}
        for text, key in written.items():
            with self.subTest(text=text):
                self.assertIn(key, {trips.flight_key(f) for f in nothing_new.signals(text).flights})
        self.assertFalse(nothing_new.covers(nothing_new.signals("EX 101 and EX-102"), [SAME]))

    def test_ordinary_words_before_numbers_and_codes_inside_words_are_not_flights(self):
        for text in ("Departs on 20 November", "Be there at 7", "It is 30 minutes away", "Ref CANARY-4T8Q", "Room 4401"):
            with self.subTest(text=text):
                self.assertEqual(nothing_new.signals(text).flights, frozenset())

    def test_times_and_names_are_seen_in_the_formats_the_readers_accept(self):
        for text, clock in (("Départ 19h00", (19, 0)), ("出発 19時30分", (19, 30)), ("Leaves 7:15pm", (19, 15))):
            with self.subTest(text=text):
                self.assertIn(clock, nothing_new.signals(text).clocks)
        for text, name in (("Passagier: Alex Stranger", "Alex Stranger"), ("Pasajero: Mia Rose Doe", "Mia Rose Doe"),
                           ("Passagers : Alex Stranger", "Alex Stranger")):
            with self.subTest(text=text):
                self.assertIn(name, nothing_new.signals(text).passengers)

    def test_change_and_travel_words_are_seen_without_regard_to_case(self):
        self.assertTrue(nothing_new.signals("FLIGHT CANCELLED").change)
        self.assertTrue(nothing_new.signals("Your boarding pass").change)
        self.assertEqual(nothing_new.signals("Save big this week on everything"), nothing_new.Signals(False))
        self.assertTrue(nothing_new.signals("Hello", "Your flight has been cancelled").change)
        self.assertTrue(nothing_new.signals("Hello", "", True).change)

    def test_named_passengers_are_picked_out_of_the_text(self):
        self.assertEqual(nothing_new.signals("Passenger: Jane Doe 21C\nTraveller Mia Rose Doe and Alex Stranger").passengers,
                         ("Jane Doe", "Mia Rose Doe", "Alex Stranger"))
        self.assertEqual(nothing_new.signals("No names here").passengers, ())

    def test_the_summary_keeps_its_counts_through_storage_and_old_summaries_read_as_zero(self):
        found = scan.Summary(3, 3, 0, 0, 0, False, dismissed_known=2, dismissed_older=1)
        self.assertEqual(scan.decode(scan.encode(found)), found)
        self.assertEqual(scan.decode(json.dumps({"found": 1, "read": 1, "bookings": 0, "review": 0, "skipped": 0, "capped": False})),
                         scan.Summary(1, 1, 0, 0, 0, False))
        self.assertTrue(all(isinstance(v, (int, bool)) for v in json.loads(scan.encode(found)).values()))


if __name__ == "__main__":
    unittest.main()
