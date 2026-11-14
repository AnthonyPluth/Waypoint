import json
import unittest
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.test_mail_ai import ScanAiCase
from tests.test_mail_scan import NOW
from waypoint import tls
from waypoint.domain import trips
from waypoint.domain.mail import newer, nothing_new, review, scan
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
        self.put("flight_jsonld")
        self.assertEqual(self.scan().bookings, 1)
        [self.known] = self.segments()
        self.turn_on()
        self.tick = 0

    def counted(self) -> tuple[int, int]:
        found = scan.summary(self.mailbox)
        return found.dismissed_known, found.dismissed_older

    def read_mail(self, body: str, reply: dict, name: str = "reminder", subject: str = SUBJECT, date: str = SAME_DAY,
                  sender: str = "Example Air <reservations@example-air.example>") -> scan.Result:
        self.tick += 60
        self.add_mail(name, mail(body, subject, date, name, sender))
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

    def assess(self, said, received=None, convert=False, sign=None):
        def run(conn):
            fields = scan._ai_fields(conn, said) if convert else None
            return nothing_new.assess(conn, self.jane, said, fields, received, sign or nothing_new.Signals(False, False))
        return self.read(run)

    def edit_known(self, **changes):
        self.read(lambda conn: trips.edit_segment(conn, self.jane, self.known["id"], changes))


class AlreadyKnownTests(NothingNewCase):
    def test_a_reminder_that_repeats_the_booking_is_dismissed_and_counted_by_reason(self):
        result = self.read_mail(REMINDER, SAME)
        self.assertEqual((result.state, result.review, self.kept()), ("done", 0, []))
        self.assertEqual(self.counted(), (1, 0))
        self.assertEqual(scan.summary(self.mailbox).dismissed, 0)
        self.assertEqual(self.scanned()["reminder"], "unreadable")
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(len(self.read(lambda conn: stored_mail.attached(conn, self.known["id"]))), 1)

    def test_the_trip_is_untouched_by_the_dismissed_reminder(self):
        before = self.segments()
        self.read_mail(REMINDER, SAME)
        self.assertEqual(self.segments(), before)

    def test_it_is_logged_as_counts_and_codes_only(self):
        said = []
        real = scan.monitoring.log
        with mock.patch.object(scan.monitoring, "log", side_effect=lambda text, *a, **k: (said.append(text), real(text, *a, **k))[1]):
            self.read_mail(REMINDER, SAME)
        self.assertTrue(any("1 dismissed as nothing new (1 × already known, 0 × older copy)" in t for t in said))
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

    def test_hosted_mode_never_reads_the_email_so_nothing_is_dismissed(self):
        self.turn_on("openrouter")
        self.add_mail("hosted", mail(REMINDER, ident="hosted"))
        with no_leaks(self, *CANARIES, database=self.path):
            result = self.scan(now=NOW + 60)
        self.assertEqual((result.review, self.fake.requests, self.counted()), (1, [], (0, 0)))

    def test_asking_by_hand_does_not_dismiss_a_known_booking(self):
        self.turn_on(auto=False)
        self.add_mail("hand", mail(REMINDER, ident="hand"))
        self.scan(now=NOW + 60)
        [item] = self.kept()
        self.fake.content = json.dumps(SAME)
        with no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
            self.assertIsNone(scan.suggest_now("u-jane", item["id"], NOW + 90))
        self.assertEqual(len(self.kept()), 1)

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
    def test_an_older_message_than_the_attached_one_is_dismissed_even_when_its_times_differ(self):
        reply = {**FULL, "start_local": "2026-11-20T18:00"}
        self.read_mail(OLD_TEXT, reply, date=EARLIER, sender=AGENT)
        self.assertEqual((self.kept(), self.counted()), ([], (0, 1)))
        self.assertEqual(self.segments()[0]["start_local"], "2026-11-20T19:00")
        self.assertEqual(self.scanned()["reminder"], "unreadable")

    def test_an_older_cancellation_or_change_is_never_counted_as_nothing_new(self):
        for what, line in (("cancel", "Flight EX 101 from JFK to LHR, booking QX7M2K, was cancelled."),
                           ("change", "Flight EX 101 from JFK to LHR, booking QX7M2K, has a schedule change.")):
            with self.subTest(what=what):
                self.read_mail(line, {**FULL, "start_local": "2026-11-20T18:00"}, name=f"o-{what}", date=EARLIER, sender=AGENT)
                self.assertEqual(self.counted(), (0, 0))
                self.assertNotEqual(self.scanned()[f"o-{what}"], "unreadable")

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


class NotTravelTests(NothingNewCase):
    def plain(self, body: str, reply: dict, name: str, subject: str = "Your trip: save on flights and hotels"):
        return self.read_mail(body, reply, name=name, subject=subject)

    def test_a_verdict_on_an_email_whose_subject_states_a_change_stays(self):
        for n, subject in enumerate(CHANGED_TRIP_SUBJECTS):
            for category in ("promotion", "receipt"):
                with self.subTest(subject=subject, category=category):
                    with db.session() as conn:
                        conn.execute(ReviewItem.__table__.delete())
                    self.plain("Thank you for being a customer.", {"bookings": [], "not_a_booking": category}, f"vs-{n}-{category}", subject)
                    self.assertEqual((len(self.kept()), scan.summary(self.mailbox).dismissed), (1, 0))

    def test_the_revision_signal_alone_keeps_a_verdict_in_review(self):
        with mock.patch.object(scan.extract, "guard", return_value=("", True)):
            self.plain("Thank you for being a customer.", VERDICT, "rv")
        self.assertEqual((len(self.kept()), scan.summary(self.mailbox).dismissed), (1, 0))

    def test_marketing_a_receipt_and_a_notice_with_no_travel_details_are_dismissed_by_the_existing_count(self):
        for category in ("promotion", "statement", "newsletter", "receipt", "notification"):
            with self.subTest(category=category):
                self.plain("Thank you for being a customer. Save on your next purchase this week.", {"bookings": [], "not_a_booking": category}, f"n-{category}")
                self.assertEqual((self.kept(), scan.summary(self.mailbox).dismissed, self.counted()), ([], 1, (0, 0)))

    def test_the_same_verdict_on_an_email_with_a_time_a_place_or_a_confirmation_stays(self):
        cases = {"time": "Sale ends at 11:59 pm tonight.", "airports": "Fly from Boston (BOS) to Denver (DEN) this winter.",
                 "confirmation": "Your confirmation code is ZZ9Y8X.", "flight": "Take flight EX 101 for less.",
                 "passenger": "Passenger Jane Doe, thank you.", "check in": "Online check-in is open for your trip."}
        for what, line in cases.items():
            for category in ("promotion", "receipt"):
                with self.subTest(what=what, category=category):
                    with db.session() as conn:
                        conn.execute(ReviewItem.__table__.delete())
                    self.plain(line, {"bookings": [], "not_a_booking": category}, f"t-{what}-{category}".replace(" ", "-"))
                    self.assertEqual((len(self.kept()), scan.summary(self.mailbox).dismissed), (1, 0))

    def test_a_verdict_on_an_email_naming_a_booking_code_or_flight_stays(self):
        for n, line in enumerate(("Booking reference: ZQ4P8W", "Booking reference: QXMKZB", "Reservation number 88231", "Your PNR is ZZ9Y8X",
                                  "Thanks for flying ex-102.")):
            for category in ("receipt", "notification", "promotion"):
                with self.subTest(line=line, category=category):
                    with db.session() as conn:
                        conn.execute(ReviewItem.__table__.delete())
                    self.plain(f"Thank you for your payment. {line}", {"bookings": [], "not_a_booking": category}, f"code-{n}-{category}")
                    self.assertEqual((len(self.kept()), scan.summary(self.mailbox).dismissed), (1, 0))

    def test_a_cancellation_or_change_wearing_a_promotion_verdict_stays(self):
        for line in ("Your booking was cancelled. Save 10 percent on your next trip.", "Fare change: save on your next trip."):
            with self.subTest(line=line):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                self.plain(line, VERDICT, f"w-{len(line)}")
                self.assertEqual(len(self.kept()), 1)


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

    def test_an_older_copy_with_a_total_the_booking_already_holds_is_dismissed(self):
        self.read(lambda conn: trips.edit_segment(conn, self.jane, self.known["id"], {"price": {"amount_minor": 12000, "currency": "USD"}}))
        self.assertEqual(self.older(price_minor=12000, price_currency="USD"), "older_copy")
        self.assertIsNone(self.older(price_minor=13000, price_currency="USD"))

    def test_an_older_confirmation_with_a_total_is_filed_by_the_merge_path_and_the_cost_is_saved(self):
        self.read_mail(f"{OLD_TEXT} Total USD 120.00", {**self.EARLIER_TIMES, "total": "120.00", "currency": "USD"}, date=EARLIER, sender=AGENT)
        self.assertEqual(self.counted(), (0, 0))
        self.assertNotEqual(self.scanned()["reminder"], "unreadable")
        self.assertEqual(self.segments()[0]["price"], {"amount_minor": 12000, "currency": "USD", "source": "email"})

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
        for text in ("Départ 19h00", "出発 19時30分", "Leaves 7:15pm"):
            with self.subTest(text=text):
                self.assertTrue(nothing_new.signals(text).travel)
        for text, name in (("Passagier: Alex Stranger", "Alex Stranger"), ("Pasajero: Mia Rose Doe", "Mia Rose Doe"),
                           ("Passagers : Alex Stranger", "Alex Stranger")):
            with self.subTest(text=text):
                self.assertIn(name, nothing_new.signals(text).passengers)

    def test_change_and_travel_words_are_seen_without_regard_to_case(self):
        self.assertTrue(nothing_new.signals("FLIGHT CANCELLED").change)
        self.assertTrue(nothing_new.signals("Your boarding pass").change)
        self.assertTrue(nothing_new.signals("Departs at 7:15 am").travel)
        self.assertTrue(nothing_new.signals("Leaves JFK (JFK)").travel)
        self.assertTrue(nothing_new.signals("Flight EX 101").travel)
        self.assertEqual(nothing_new.signals("Save big this week on everything"), nothing_new.Signals(False, False))
        self.assertTrue(nothing_new.signals("Hello", "Your flight has been cancelled").change)
        self.assertTrue(nothing_new.signals("Hello", "", True).change)

    def test_named_passengers_are_picked_out_of_the_text(self):
        self.assertEqual(nothing_new.signals("Passenger: Jane Doe 21C\nTraveller Mia Rose Doe and Alex Stranger").passengers,
                         ("Jane Doe", "Mia Rose Doe", "Alex Stranger"))
        self.assertEqual(nothing_new.signals("No names here").passengers, ())

    def test_the_summary_keeps_its_counts_through_storage_and_old_summaries_read_as_zero(self):
        found = scan.Summary(3, 3, 0, 0, 0, False, dismissed=1, dismissed_known=2, dismissed_older=1)
        self.assertEqual(scan.decode(scan.encode(found)), found)
        self.assertEqual(scan.decode(json.dumps({"found": 1, "read": 1, "bookings": 0, "review": 0, "skipped": 0, "capped": False})),
                         scan.Summary(1, 1, 0, 0, 0, False))
        self.assertTrue(all(isinstance(v, (int, bool)) for v in json.loads(scan.encode(found)).values()))


if __name__ == "__main__":
    unittest.main()
