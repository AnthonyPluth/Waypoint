import json
from unittest import mock

from sqlalchemy import func, select

from tests.privacy import no_leaks
from tests.test_mail_scan import NOW, ScanCase, eml
from waypoint.domain import trips, visibility
from waypoint.domain.mail import scan
from waypoint.storage import stored_mail
from waypoint.storage.models import Segment, SegmentMessage, SegmentRecipient, SegmentTraveler, StoredMessage, Trip

SUBJECT_CANARY = "CANARY-SUBJECT-SAME-5K2M"
BODY_CANARY = "CANARY-BODY-SAME-8T4W"
NAME_CANARY = "CANARY-NAME-SAME-3V7Q"


def for_traveller(raw: bytes, name: str, seat: str, subject: str | None = None) -> bytes:
    out = raw.replace(b'"Jane Doe"', f'"{name}"'.encode()).replace(b'"21C"', f'"{seat}"'.encode()).replace(b"FXLOY-4400123", b"FXLOY-9100042")
    out = out.replace(b"fx-flight-jsonld", b"fx-" + seat.encode().lower())
    if subject:
        out = out.replace(b"Your e-ticket receipt and itinerary QX7M2K", subject.encode())
    return out


class SameBookingCase(ScanCase):
    def counts(self) -> tuple[int, int, int, int]:
        def read(conn):
            return tuple(int(conn.execute(select(func.count()).select_from(t)).scalar()) for t in (Trip, Segment, StoredMessage, SegmentMessage))
        return self.read(read)

    def summary(self) -> scan.Summary:
        found = scan.summary(self.mailbox)
        assert found is not None
        return found

    def first(self) -> int:
        self.put("flight_jsonld")
        self.scan()
        [segment] = self.segments()
        return int(segment["id"])


class SameBookingScanTests(SameBookingCase):
    def test_the_same_flight_in_a_second_email_is_one_segment_with_both_emails_and_both_travellers(self):
        segment = self.first()
        self.add_mail("second", for_traveller(eml("flight_jsonld"), "Mia Rose Doe", "21D"))
        result = self.scan(now=NOW + 60)
        self.assertEqual((result.state, result.bookings, result.review), ("done", 0, 0))
        [seg] = self.segments()
        self.assertEqual(seg["id"], segment)
        self.assertEqual(seg["status"], "confirmed")
        self.assertEqual({t["name"] for t in seg["travelers"]}, {"Jane Doe", "Mia Rose Doe"})
        self.assertEqual(self.counts(), (1, 1, 2, 2))
        self.assertEqual(len(self.read(lambda conn: stored_mail.for_segment(conn, segment))), 2)
        self.assertEqual(self.scanned(), {"msg-flight_jsonld": "booking", "second": "booking"})

    def test_the_booking_shows_its_emails_newest_first_to_everyone_who_can_see_it(self):
        segment = self.first()
        self.add_mail("second", for_traveller(eml("flight_jsonld"), "Mia Rose Doe", "21D", "Your itinerary for Mia"))
        self.scan(now=NOW + 60)
        shown = self.read(lambda conn: trips.emails_of(conn, self.jane, segment))
        assert shown is not None
        self.assertEqual([e["subject"] for e in shown], ["Your itinerary for Mia", "Your e-ticket receipt and itinerary QX7M2K"])
        self.assertIsNone(self.read(lambda conn: trips.emails_of(conn, self.sam, segment)))

    def test_existing_fields_seats_and_travellers_are_kept_and_only_empty_ones_are_filled(self):
        segment = self.first()
        before = self.segments()[0]
        later = for_traveller(eml("flight_jsonld"), "Mia Rose Doe", "21D").replace(
            b'"modifyReservationUrl": "https://example-air.example/manage/QX7M2K"', b'"modifyReservationUrl": "https://example-air.example/other"')
        self.add_mail("second", later)
        self.scan(now=NOW + 60)
        [after] = self.segments()
        self.assertEqual(after["id"], segment)
        for key in ("start_local", "end_local", "origin", "destination", "provider", "confirmation", "manage_url", "status"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after["details"]["seat"], before["details"]["seat"])
        self.assertEqual(after["details"]["seat"], "21C")

    def test_a_field_the_booking_lacked_is_filled_from_the_second_email(self):
        self.first()
        [seg] = self.segments()
        self.read(lambda conn: conn.execute(Segment.__table__.update().where(Segment.id == seg["id"]).values(details='{"flight_number":"EX 101"}')))
        self.add_mail("second", eml("flight_jsonld").replace(b"fx-flight-jsonld", b"fx-second"))
        self.scan(now=NOW + 60)
        [after] = self.segments()
        self.assertEqual(after["details"]["flight_number"], "EX 101")
        self.assertEqual(after["details"].get("terminal"), "7")

    def test_locked_fields_and_what_a_person_edited_are_never_overwritten(self):
        segment = self.first()
        guest = {"person_id": None, "name": "Pat Guest"}
        edited = self.read(lambda conn: trips.edit_segment(conn, self.jane, segment, {
            "details": {"flight_number": "EX 101", "seat": "1A"}, "travelers": [{"person_id": self.jane.person_id, "name": None}, guest]}))
        assert edited is not None
        self.assertEqual(set(edited["locked_fields"]), {"details", "travelers"})
        self.add_mail("second", for_traveller(eml("flight_jsonld"), "Mia Rose Doe", "21D"))
        self.scan(now=NOW + 60)
        [after] = self.segments()
        self.assertEqual(after["details"], edited["details"])
        self.assertEqual([t["name"] for t in after["travelers"]], ["Jane Doe", "Pat Guest"])
        self.assertEqual(self.counts()[1:], (1, 2, 2))

    def test_the_same_traveller_again_adds_no_one(self):
        self.first()
        self.add_mail("second", eml("flight_jsonld").replace(b"fx-flight-jsonld", b"fx-again"))
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual(len(seg["travelers"]), 1)
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(SegmentTraveler)).scalar()), 1)
        self.assertEqual(self.summary().attached, 1)

    def test_the_summary_counts_attached_emails_and_the_log_says_only_the_number(self):
        self.first()
        said: list[str] = []
        real = scan.monitoring.log
        self.add_mail("second", for_traveller(eml("flight_jsonld"), NAME_CANARY, "21D", f"Your itinerary {SUBJECT_CANARY}").replace(
            b"Hello Jane. ", f"{BODY_CANARY} ".encode()))
        with mock.patch.object(scan.monitoring, "log", side_effect=lambda text, *a, **k: (said.append(text), real(text, *a, **k))[1]), \
                no_leaks(self, SUBJECT_CANARY, BODY_CANARY, database=self.path), no_leaks(self, NAME_CANARY):
            self.scan(now=NOW + 60)
        found = self.summary()
        self.assertEqual((found.attached, found.bookings, found.read, found.review), (1, 0, 1, 0))
        self.assertEqual(scan.decode(self.row()["scan_summary"]), found)
        self.assertIn("Scanned a mailbox: 1 message(s) found, 1 read, 0 booking(s) added or changed, 0 to review, 1 email(s) attached to an existing booking, 0 skipped (0 as not travel).", said)
        text = json.dumps(self.row(), default=str) + " ".join(said)
        for canary in (SUBJECT_CANARY, BODY_CANARY, NAME_CANARY):
            self.assertNotIn(canary, text)

    def test_the_kept_message_is_encrypted_and_not_readable_in_the_clear(self):
        self.first()
        self.add_mail("second", eml("flight_jsonld").replace(b"CANARY-BODY-FLIGHT-JSONLD-7Q2X is only in this made-up body.",
                                                           f"{BODY_CANARY} is only in this one.".encode()).replace(b"fx-flight-jsonld", b"fx-enc"))
        with no_leaks(self, BODY_CANARY, database=self.path):
            self.scan(now=NOW + 60)
        [kept] = [e for e in self.read(lambda conn: stored_mail.for_segment(conn, self.segments()[0]["id"])) if BODY_CANARY in e["text"]]
        self.assertTrue(kept["text"])

    def test_a_different_start_time_with_the_same_code_is_not_the_same_booking_and_is_handled_as_before(self):
        self.first()
        moved = eml("flight_jsonld").replace(b"2026-11-20T19:00:00-05:00", b"2026-11-20T21:30:00-05:00").replace(b"fx-flight-jsonld", b"fx-moved")
        self.add_mail("moved", moved)
        result = self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual((seg["start_local"], seg["status"]), ("2026-11-20T21:30", "changed"))
        self.assertEqual((result.bookings, self.summary().attached), (1, 0))

    def test_a_different_airport_with_the_same_code_is_another_segment(self):
        self.first()
        other = eml("flight_jsonld").replace(b'"iataCode": "LHR"', b'"iataCode": "LGW"').replace(b"fx-flight-jsonld", b"fx-airport")
        self.add_mail("other", other)
        self.scan(now=NOW + 60)
        self.assertEqual(sorted(s["destination"] for s in self.segments()), ["LGW", "LHR"])
        self.assertEqual(self.summary().attached, 0)

    def test_a_different_flight_number_at_the_same_minute_is_another_segment(self):
        self.first()
        other = eml("flight_jsonld").replace(b'"flightNumber": "101"', b'"flightNumber": "909"').replace(b"fx-flight-jsonld", b"fx-number")
        self.add_mail("other", other)
        self.scan(now=NOW + 60)
        self.assertEqual(len(self.segments()), 2)
        self.assertEqual(self.summary().attached, 0)

    def test_a_different_kind_with_the_same_code_is_never_merged(self):
        self.put("hotel_jsonld")
        self.scan()
        flight = eml("flight_jsonld").replace(b"QX7M2K", b"H88231")
        self.add_mail("flight", flight)
        self.scan(now=NOW + 60)
        self.assertEqual(sorted(s["kind"] for s in self.segments()), ["flight", "hotel"])
        self.assertEqual(self.summary().attached, 0)

    def test_a_different_provider_with_the_same_code_and_no_flight_number_in_common_is_not_merged(self):
        self.put("hotel_jsonld")
        self.scan()
        other = eml("hotel_jsonld").replace(b'"name": "Harbour Hotel"', b'"name": "Quayside Lodge"').replace(b"fx-hotel", b"fx-lodge")
        self.add_mail("other", other)
        self.scan(now=NOW + 60)
        self.assertEqual(self.summary().attached, 0)

    def test_a_hotel_with_the_same_code_place_and_dates_is_attached(self):
        self.put("hotel_jsonld")
        self.scan()
        again = eml("hotel_jsonld").replace(b"fx-hotel", b"fx-hotel-2").replace(b'"Jane Doe"', b'"Mia Rose Doe"')
        self.add_mail("again", again)
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual(len(seg["travelers"]), 2)
        self.assertEqual((self.summary().attached, self.counts()[1:]), (1, (1, 2, 2)))

    def test_a_hotel_with_other_dates_is_not_attached(self):
        self.put("hotel_jsonld")
        self.scan()
        later = eml("hotel_jsonld").replace(b"2026-11-27T10:00:00+00:00", b"2026-11-28T10:00:00+00:00").replace(b"fx-hotel", b"fx-hotel-3")
        self.add_mail("later", later)
        self.scan(now=NOW + 60)
        [seg] = self.segments()
        self.assertEqual(seg["end_local"][:10], "2026-11-28")
        self.assertEqual(self.summary().attached, 0)

    def test_a_cancelled_booking_is_not_matched_and_a_cancellation_is_not_an_attachment(self):
        self.first()
        cancel = eml("flight_jsonld").replace(b"ReservationConfirmed", b"ReservationCancelled").replace(b"fx-flight-jsonld", b"fx-cancel")
        self.add_mail("cancel", cancel)
        self.scan(now=NOW + 60)
        self.assertEqual(self.segments()[0]["status"], "cancelled")
        self.assertEqual(self.summary().attached, 0)
        self.add_mail("after", for_traveller(eml("flight_jsonld"), "Mia Rose Doe", "21D"))
        self.scan(now=NOW + 120)
        self.assertEqual(self.summary().attached, 0)
        self.assertEqual(len(self.segments()), 1)
        self.assertEqual(self.segments()[0]["status"], "cancelled")

    def test_a_booking_the_mailbox_owner_cannot_see_is_no_match_and_behaves_as_before(self):
        self.first()
        sam_box = self.connect("u-sam", "sam@gmail.example", "refresh-sam-1")
        self.assertEqual(self.segments(self.sam), [])
        self.google.mail["sam-copy"] = eml("flight_jsonld").replace(b"fx-flight-jsonld", b"fx-sam")
        self.google.matches[:] = ["sam-copy"]
        self.google.added[:] = ["sam-copy"]
        self.scan(sam_box, now=NOW + 60)
        found = scan.summary(sam_box)
        assert found is not None
        self.assertEqual(found.attached, 0)
        self.assertEqual(self.counts()[:2], (1, 1))
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(SegmentRecipient)).scalar()), 1)

    def test_nothing_can_be_attached_to_a_booking_the_viewer_cannot_see(self):
        self.first()
        fields: trips.SegmentIn = {"kind": "flight", "confirmation": "QX7M2K", "provider": "Example Air", "origin": "JFK", "destination": "LHR",
                                   "start_local": "2026-11-20T19:00", "end_local": "2026-11-21T07:10", "details": {"flight_number": "EX 101"}}
        self.assertIsNotNone(self.read(lambda conn: trips.find_same_booking(conn, self.jane, fields)))
        self.assertIsNone(self.read(lambda conn: trips.find_same_booking(conn, self.sam, fields)))
        self.assertIsNone(self.read(lambda conn: trips.find_same_booking(conn, visibility.Viewer(None), fields)))

    def test_reading_a_message_again_still_updates_its_booking(self):
        self.first()
        self.read(lambda conn: conn.execute(Segment.__table__.update().values(details='{"flight_number":"EX 101","seat":"9Z"}')))
        self.scan(again=True)
        self.assertEqual(self.segments()[0]["details"]["seat"], "21C")

    def test_a_backfill_attaches_too_and_does_not_overwrite(self):
        self.first()
        self.add_mail("second", for_traveller(eml("flight_jsonld"), "Mia Rose Doe", "21D"))
        self.scan(now=NOW + 60, backfill=True)
        [seg] = self.segments()
        self.assertEqual(seg["details"]["seat"], "21C")
        self.assertEqual(len(seg["travelers"]), 2)
