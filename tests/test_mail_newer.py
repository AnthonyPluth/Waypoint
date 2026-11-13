import json
import time
from datetime import UTC, datetime

from sqlalchemy import func, select

from tests.privacy import no_leaks
from tests.test_mail_followup import mail
from tests.test_mail_scan import NOW, ScanCase, eml
from tests.test_reminders import subscription
from waypoint.domain import reminders, trips
from waypoint.storage import db, stored_mail
from waypoint.storage.models import ReminderSent, ReviewItem, Segment, SegmentMessage, StoredMessage

FIRST_DAY = b"Mon, 12 Oct 2026 09:30:00 -0400"
LATER_DAY = "Wed, 14 Oct 2026 09:30:00 -0400"
EARLIER_DAY = "Sat, 10 Oct 2026 09:30:00 -0400"
OLD_DEPARTURE = b"2026-11-20T19:00:00-05:00"
NEW_DEPARTURE = "2026-11-20T21:30:00-05:00"
SUBJECT_CANARY = "CANARY-SUBJECT-NEWER-6H3K"
BODY_CANARY = "CANARY-BODY-NEWER-9D2P"


def revised(day: str = LATER_DAY, departure: str | None = NEW_DEPARTURE, name: str = "newer") -> bytes:
    out = eml("flight_jsonld").replace(FIRST_DAY, day.encode()).replace(b"fx-flight-jsonld", name.encode())
    return out.replace(OLD_DEPARTURE, departure.encode()) if departure else out


class NewerCase(ScanCase):
    def first(self) -> int:
        self.put("flight_jsonld")
        self.scan()
        [segment] = self.segments()
        return int(segment["id"])

    def held(self, segment_id: int) -> set[str]:
        return {a["message_id"] for a in self.read(lambda conn: stored_mail.attached(conn, segment_id))}

    def counts(self) -> tuple[int, int, int]:
        return self.read(lambda conn: tuple(int(conn.execute(select(func.count()).select_from(t)).scalar()) for t in (Segment, StoredMessage, SegmentMessage)))

    def lock_start(self, segment_id: int) -> None:
        self.read(lambda conn: trips.edit_segment(conn, self.jane, segment_id, {"start_local": "2026-11-20T18:00"}))


class ANewerEmailReplacesTheAttachedOne(NewerCase):
    def test_a_newer_message_with_changed_times_becomes_the_attached_email_and_updates_the_booking(self):
        segment = self.first()
        self.add_mail("newer", revised())
        result = self.scan(now=NOW + 60)
        self.assertEqual((result.state, result.review), ("done", 0))
        [seg] = self.segments()
        self.assertEqual((seg["id"], seg["start_local"], seg["status"]), (segment, "2026-11-20T21:30", "changed"))
        self.assertEqual(seg["email_update"], {"at": NOW + 60, "updated": ["start_local"], "disagreed": []})
        self.assertEqual(self.held(segment), {"newer"})
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(self.scanned(), {"msg-flight_jsonld": "booking", "newer": "booking"})
        shown = self.read(lambda conn: trips.emails_of(conn, self.jane, segment))
        assert shown is not None
        self.assertEqual(len(shown), 1)

    def test_the_old_message_is_not_attached_again_when_it_is_read_again(self):
        segment = self.first()
        self.add_mail("newer", revised())
        self.scan(now=NOW + 60)
        self.scan(now=NOW + 120, again=True)
        [seg] = self.segments()
        self.assertEqual(seg["start_local"], "2026-11-20T21:30")
        self.assertEqual(self.held(segment), {"newer"})

    def test_a_message_that_is_older_changes_nothing(self):
        segment = self.first()
        self.add_mail("newer", revised())
        self.scan(now=NOW + 60)
        before = self.segments()[0]
        self.add_mail("older", revised(EARLIER_DAY, "2026-11-20T23:00:00-05:00", "older"))
        result = self.scan(now=NOW + 120)
        self.assertEqual((result.state, result.review), ("done", 0))
        self.assertEqual(self.segments()[0], before)
        self.assertEqual(self.held(segment), {"newer"})
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_an_older_message_scanned_after_a_newer_one_in_the_same_scan_changes_nothing(self):
        self.first()
        self.add_mail("newer", revised())
        self.add_mail("older", revised(EARLIER_DAY, "2026-11-20T23:00:00-05:00", "older"))
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual(seg["start_local"], "2026-11-20T21:30")
        self.assertEqual(self.held(seg["id"]), {"newer"})

    def test_a_message_from_the_same_day_is_not_newer_and_is_handled_as_before(self):
        segment = self.first()
        self.add_mail("sameday", revised(FIRST_DAY.decode(), NEW_DEPARTURE, "sameday"))
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual((seg["start_local"], seg["status"], seg["email_update"]), ("2026-11-20T21:30", "changed", None))
        self.assertEqual(self.held(segment), {"msg-flight_jsonld", "sameday"})

    def test_a_message_with_no_date_cannot_be_shown_newer_so_it_only_fills_gaps(self):
        segment = self.first()
        undated = revised(name="undated").replace(f"Date: {LATER_DAY}\n".encode(), b"")
        self.assertNotIn(b"Date:", undated)
        self.add_mail("undated", undated)
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual((seg["start_local"], seg["status"], seg["email_update"]), ("2026-11-20T19:00", "confirmed", None))
        self.assertEqual(self.held(segment), {"msg-flight_jsonld", "undated"})

    def test_an_identical_newer_message_changes_no_field_and_records_no_update(self):
        segment = self.first()
        self.add_mail("same", revised(departure=None, name="same"))
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual((seg["start_local"], seg["status"], seg["email_update"]), ("2026-11-20T19:00", "confirmed", None))
        self.assertEqual(self.held(segment), {"msg-flight_jsonld", "same"})

    def test_a_field_a_person_edited_is_kept_and_the_booking_says_a_newer_email_disagreed(self):
        segment = self.first()
        self.lock_start(segment)
        self.add_mail("newer", revised())
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual(seg["start_local"], "2026-11-20T18:00")
        self.assertIn("start_local", seg["locked_fields"])
        self.assertEqual(seg["email_update"], {"at": NOW + 60, "updated": [], "disagreed": ["start_local"]})
        self.assertEqual(self.held(segment), {"newer"})

    def test_a_cancellation_does_not_replace_the_attached_email_and_records_no_update(self):
        segment = self.first()
        self.add_mail("cancelled", revised(name="cancelled").replace(b"ReservationConfirmed", b"ReservationCancelled"))
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual((seg["status"], seg["email_update"]), ("cancelled", None))
        self.assertEqual(self.held(segment), {"msg-flight_jsonld", "cancelled"})

    def test_a_message_that_says_it_changed_but_cannot_be_read_goes_to_review_and_changes_nothing(self):
        segment = self.first()
        before = self.segments()[0]
        self.add_mail("vague", mail("example-air.example", "Your trip: flight itinerary has been modified", "Your flight reservation number: QX7M2K has been rescheduled. Please check the new times for your flight.",
                                    LATER_DAY, "Example Air"))
        self.scan(now=NOW + 60)
        self.assertEqual(self.segments()[0], before)
        self.assertEqual(self.held(segment), {"msg-flight_jsonld"})
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(ReviewItem)).scalar()), 1)

    def test_a_message_for_another_booking_is_added_and_leaves_this_one_alone(self):
        segment = self.first()
        before = self.segments()[0]
        other = revised(name="other").replace(b"QX7M2K", b"ZZ9Y8X").replace(b"2026-11-20", b"2026-12-20").replace(b"2026-11-21", b"2026-12-21")
        self.add_mail("other", other)
        self.scan(now=NOW + 60)
        found = {s["confirmation"]: s for s in self.segments()}
        self.assertEqual(set(found), {"QX7M2K", "ZZ9Y8X"})
        self.assertEqual(found["QX7M2K"], before)
        self.assertEqual(self.held(segment), {"msg-flight_jsonld"})

    def test_a_booking_the_mailbox_owner_cannot_see_keeps_its_attached_email_and_records_no_update(self):
        segment = self.first()
        sam_box = self.connect("u-sam", "sam@gmail.example", "refresh-sam-1")
        self.google.mail["sam-newer"] = revised(name="sam-newer")
        self.google.matches[:] = ["sam-newer"]
        self.google.added[:] = ["sam-newer"]
        self.scan(sam_box, now=NOW + 60)
        self.assertEqual(self.held(segment), {"msg-flight_jsonld", "sam-newer"})
        [seg] = self.segments()
        self.assertIsNone(seg["email_update"])
        self.assertEqual(self.read(lambda conn: conn.execute(select(Segment.email_updated)).scalar()), None)

    def test_a_backfill_never_replaces_anything(self):
        segment = self.first()
        self.add_mail("newer", revised())
        self.scan(now=NOW + 60, backfill=True)
        [seg] = self.segments()
        self.assertIsNone(seg["email_update"])
        self.assertIn("msg-flight_jsonld", self.held(segment))


class NothingOfTheMessageIsKept(NewerCase):
    def test_the_replaced_message_is_deleted_and_the_new_one_leaves_no_text_in_the_clear(self):
        self.first()
        text = revised().replace(b"Thanks for booking with Example Air. CANARY-BODY-FLIGHT-JSONLD-7Q2X", BODY_CANARY.encode())
        text = text.replace(b"Your e-ticket receipt and itinerary QX7M2K", f"Itinerary changed {SUBJECT_CANARY}".encode())
        self.add_mail("newer", text)
        with no_leaks(self, SUBJECT_CANARY, BODY_CANARY, database=self.path):
            self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual(self.held(seg["id"]), {"newer"})
        kept = self.read(lambda conn: stored_mail.for_segment(conn, seg["id"]))
        self.assertEqual(len(kept), 1)
        self.assertIn(BODY_CANARY, kept[0]["text"])
        dump = json.dumps(self.read(lambda conn: db.rows(conn.execute(select(Segment)))), default=str)
        self.assertNotIn(BODY_CANARY, dump)
        self.assertNotIn(SUBJECT_CANARY, dump)
        self.assertNotIn("msg-flight_jsonld", dump)

    def test_the_booking_records_field_names_only(self):
        self.first()
        self.add_mail("newer", revised())
        self.scan(now=NOW + 60)
        raw = self.read(lambda conn: conn.execute(select(Segment.email_update)).scalar())
        self.assertEqual(json.loads(raw), {"updated": ["start_local"], "disagreed": []})
        self.assertNotIn("21:30", raw)


class AChangedFlightWithinTheDayIsPushed(NewerCase):
    def setUp(self):
        super().setUp()
        self.sent: list[dict] = []
        self.read(lambda conn: reminders.add_device(conn, "u-jane", *subscription(), time.time()))

    def send(self, _device, message):
        self.sent.append(message)

    def due(self, now: datetime, since: float = NOW) -> int:
        return self.read(lambda conn: reminders.times_due(conn, since, now, lambda: self.send))

    def changed(self) -> None:
        self.first()
        self.add_mail("newer", revised())
        self.scan(now=NOW + 60)

    def test_a_flight_leaving_within_a_day_is_pushed_once_with_no_email_text(self):
        self.changed()
        with no_leaks(self, SUBJECT_CANARY, BODY_CANARY):
            self.assertEqual(self.due(datetime(2026, 11, 20, 12, 0, tzinfo=UTC)), 1)
            self.assertEqual(self.due(datetime(2026, 11, 20, 13, 0, tzinfo=UTC)), 0)
        [message] = self.sent
        self.assertEqual(message["title"], "Flight times changed")
        self.assertIn("21:30", message["body"])
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(ReminderSent).where(ReminderSent.kind == "times")).scalar()), 1)

    def test_a_flight_more_than_a_day_away_or_already_gone_is_not_pushed(self):
        self.changed()
        self.assertEqual(self.due(datetime(2026, 11, 18, 12, 0, tzinfo=UTC)), 0)
        self.assertEqual(self.due(datetime(2026, 11, 21, 12, 0, tzinfo=UTC)), 0)
        self.assertEqual(self.sent, [])

    def test_an_update_from_before_this_scan_is_not_pushed_again(self):
        self.changed()
        self.assertEqual(self.due(datetime(2026, 11, 20, 12, 0, tzinfo=UTC), since=NOW + 3600), 0)

    def test_nothing_is_pushed_for_a_booking_no_email_changed(self):
        self.first()
        self.assertEqual(self.due(datetime(2026, 11, 20, 12, 0, tzinfo=UTC)), 0)

    def test_someone_who_cannot_see_the_flight_is_not_told(self):
        self.changed()
        self.read(lambda conn: reminders.add_device(conn, "u-sam", *subscription("https://push.example.com/send/other"), time.time()))
        self.assertEqual(self.due(datetime(2026, 11, 20, 12, 0, tzinfo=UTC)), 1)
        self.assertEqual(len(self.sent), 1)

    def test_a_person_who_turned_check_in_reminders_off_is_not_told(self):
        self.changed()
        self.read(lambda conn: reminders.set_prefs(conn, "u-jane", {"check_in": False, "day_of": True, "review": True}))
        self.assertEqual(self.due(datetime(2026, 11, 20, 12, 0, tzinfo=UTC)), 0)
