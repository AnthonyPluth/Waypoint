import json
from unittest import mock
from sqlalchemy import func, select

from tests.privacy import no_leaks
from tests.test_mail_scan import NOW, ScanCase, b64, eml
from waypoint.domain import trips
from waypoint.domain.mail import extract, references, review, scan
from waypoint.storage import secretbox, stored_mail
from waypoint.storage.models import Mailbox, ReviewItem, ScannedMessage, Segment, SegmentMessage, StoredMessage

STAYS = "example-stays.example"
HOTEL = "harbourhotel.example"
CODE = "H88231"
STAY = {"kind": "hotel", "origin": "Harbour Hotel", "destination": None, "provider": "Harbour Hotel", "start_local": "2026-11-21T15:00",
        "end_local": "2026-11-27T10:00", "start_zone": "Europe/London", "end_zone": "Europe/London", "confirmation": CODE}


def mail(domain: str, subject: str, body: str, day: str = "Fri, 16 Oct 2026 09:00:00 +0100", name: str = "Example") -> bytes:
    return (f"From: {name} <noreply@{domain}>\nTo: traveller@gmail.example\nSubject: {subject}\nDate: {day}\nMIME-Version: 1.0\n"
            f"Content-Type: text/plain; charset=utf-8\n\n{body}\n").encode()


def follow(subject: str, body: str, domain: str = STAYS, day: str = "Fri, 16 Oct 2026 09:00:00 +0100") -> bytes:
    return mail(domain, subject, body, day)


class FollowUpCase(ScanCase):
    def add(self, mid: str, raw: bytes) -> None:
        self.add_mail(mid, raw)

    def outcomes(self) -> dict[str, str]:
        return self.scanned()

    def stored(self) -> int:
        return int(self.read(lambda conn: conn.execute(select(func.count()).select_from(StoredMessage)).scalar()))

    def by_hand(self, viewer=None, **swaps) -> int:
        seg = self.read(lambda conn: trips.add_segment(conn, viewer or self.jane, {**STAY, **swaps}))
        assert seg is not None
        return int(seg["id"])

    def confirmed(self) -> int:
        self.put("hotel_jsonld")
        self.scan()
        [segment] = self.segments()
        return int(segment["id"])


class FollowUpTests(FollowUpCase):
    def test_a_receipt_a_check_in_notice_a_reminder_and_a_hotel_reply_quietly_attach_to_the_booking_their_code_names(self):
        segment = self.confirmed()
        self.add("m-receipt", follow("Your receipt for your stay", f"Thanks. Your stay at the hotel is paid.\nReservation number: {CODE}"))
        self.add("m-checkin", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}."))
        self.add("m-reminder", follow("A week until your stay", f"Your hotel booking {CODE} is a week away."))
        self.add("m-reply", follow("Your room request for your stay", f"Hello, about your hotel room: reference {CODE} is noted.", "harbourhotel.example"))
        result = self.scan(now=NOW + 60)
        self.assertEqual((result.state, result.bookings, result.review), ("done", 0, 0))
        self.assertEqual(self.items(), [])
        self.assertEqual({v for k, v in self.outcomes().items() if k != "msg-hotel_jsonld"}, {"follow-up"})
        self.assertEqual(len([k for k, v in self.outcomes().items() if v == "follow-up"]), 4)
        linked = self.read(lambda conn: set(conn.execute(select(ScannedMessage.segment_id).where(ScannedMessage.outcome == "follow-up")).scalars()))
        self.assertEqual(linked, {segment})
        summary = scan.summary(self.mailbox)
        assert summary is not None
        self.assertEqual((summary.followups, summary.with_facts, summary.review), (4, 0, 0))
        self.assertEqual(self.stored(), 1)
        self.assertEqual(len(self.segments()), 1)

    def test_the_earlier_message_stays_the_bookings_source_and_a_follow_up_is_not_stored(self):
        segment = self.confirmed()
        self.add("m-checkin", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}."))
        self.scan(now=NOW + 60)
        sources = self.read(lambda conn: stored_mail.with_messages(conn, [segment]))
        self.assertEqual(sources, {segment})
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(SegmentMessage)).scalar()), 1)
        self.assertIsNone(self.read(lambda conn: stored_mail.get(conn, self.mailbox, "m-checkin")))

    def test_the_log_counts_follow_ups_and_says_nothing_else_about_them(self):
        self.confirmed()
        self.add("m-gate", follow("Your stay: online check-in is open", f"Your hotel reservation {CODE}: use Gate 12 after 3 pm. CANARY-BODY-LOG-8W2Q"))
        said: list[str] = []
        real = scan.monitoring.log
        with mock.patch.object(scan.monitoring, "log", side_effect=lambda text, *a, **k: (said.append(text), real(text, *a, **k))[1]), \
                no_leaks(self, "CANARY-BODY-LOG-8W2Q", database=self.path):
            self.scan(now=NOW + 60)
        self.assertIn("Scanned a mailbox: 1 message(s) found, 1 read, 0 booking(s) added or changed, 0 to review, 1 follow-up(s) attached (1 with details not applied), 0 skipped (0 as not travel).", said)

    def test_a_follow_up_is_not_read_again_by_the_next_scan(self):
        self.confirmed()
        self.add("m-checkin", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}."))
        self.scan(now=NOW + 60)
        self.google.fetched.clear()
        self.assertEqual(self.scan(now=NOW + 120).messages, 0)
        self.assertEqual(self.google.fetched, [])

    def test_a_modification_and_a_cancellation_still_update_the_booking_and_are_not_follow_ups(self):
        self.confirmed()
        moved = eml("hotel_jsonld").replace(b"2026-11-27T10:00:00+00:00", b"2026-11-28T10:00:00+00:00")
        self.add("m-moved", moved)
        self.scan(now=NOW + 60)
        [segment] = self.segments()
        self.assertEqual(segment["end_local"][:10], "2026-11-28")
        self.add("m-cancelled", moved.replace(b"ReservationConfirmed", b"ReservationCancelled"))
        self.scan(now=NOW + 120)
        [segment] = self.segments()
        self.assertEqual(segment["status"], "cancelled")
        self.assertEqual(self.items(), [])
        self.assertNotIn("follow-up", self.outcomes().values())

    def test_mail_that_says_it_changes_or_cancels_is_queued_for_a_person_not_attached(self):
        self.confirmed()
        self.add("m-cancel", follow("Your stay: reservation cancelled", f"Your hotel reservation number: {CODE} has been cancelled."))
        self.add("m-change", follow("Your stay has been modified", f"Your hotel reservation number: {CODE} now has new dates."))
        self.scan(now=NOW + 60)
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(ReviewItem)).scalar()), 2)
        self.assertNotIn("follow-up", self.outcomes().values())

    def test_a_neutral_subject_over_a_body_that_says_it_cancelled_or_changed_is_queued_for_a_person(self):
        self.by_hand()
        self.add("m-cancel", follow("Your stay: an update", f"Your hotel reservation {CODE} has been cancelled.", HOTEL))
        self.add("m-change", follow("Your stay: a note", f"We have rescheduled your hotel booking {CODE}.", HOTEL, "Sat, 17 Oct 2026 09:00:00 +0100"))
        self.scan()
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(ReviewItem)).scalar()), 2)
        self.assertNotIn("follow-up", self.outcomes().values())

    def test_a_cancellation_policy_in_the_body_does_not_stop_a_follow_up(self):
        self.by_hand()
        self.add("m-policy", follow("Your stay: check-in is open", f"Your hotel reservation {CODE}. Free cancellation until 48 hours before.", HOTEL))
        self.assertEqual(self.scan().review, 0)

    def test_a_generic_provider_name_or_part_of_a_label_is_not_the_same_sender(self):
        self.by_hand(provider="Stays")
        self.by_hand(provider="Harbour Hotel", confirmation="K55667", start_local="2026-12-21T15:00", end_local="2026-12-27T10:00")
        self.add("m-generic", follow("Your stay: check-in is open", f"Your hotel reservation {CODE}.", "stays.example"))
        self.add("m-part", follow("Your stay: check-in is open", "Your hotel reservation K55667.", "harbourhotel-deals.example"))
        self.add("m-whole", follow("Your stay: check-in is open", "Your hotel reservation K55667.", "mail.harbourhotel.example"))
        self.scan()
        self.assertEqual(self.outcomes(), {"m-generic": "unreadable", "m-part": "unreadable", "m-whole": "follow-up"})

    def test_a_code_that_matches_two_bookings_queues_as_before(self):
        self.by_hand()
        self.by_hand(start_local="2026-12-21T15:00", end_local="2026-12-27T10:00")
        self.add("m-checkin", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}.", HOTEL))
        result = self.scan()
        self.assertEqual(result.review, 1)
        self.assertEqual(len(self.items()), 1)
        self.assertNotIn("follow-up", self.outcomes().values())

    def test_a_code_that_matches_no_booking_queues_as_before(self):
        self.by_hand(confirmation="Z99999")
        self.add("m-checkin", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}.", HOTEL))
        self.assertEqual(self.scan().review, 1)
        self.assertEqual(len(self.items()), 1)

    def test_a_code_that_only_matches_a_booking_the_viewer_cannot_see_is_no_match_and_says_nothing_of_it(self):
        sam_only = self.by_hand(self.sam)
        self.assertEqual(self.segments(), [])
        self.add("m-checkin", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}.", HOTEL))
        result = self.scan()
        self.assertEqual(result.review, 1)
        [item] = self.items()
        self.assertEqual(set(item), {"id", "address", "owner", "mine", "sender_domain", "known_sender", "holds_bookings", "subject",
                                     "has_email", "received", "reason", "suggestions", "suggestion_error", "count", "others"})
        self.assertEqual(self.read(lambda conn: conn.execute(select(ScannedMessage.segment_id)).scalars()), [None])
        self.assertEqual(self.segments(self.sam)[0]["id"], sam_only)

    def test_a_visible_booking_is_attached_even_when_another_with_the_code_is_hidden(self):
        mine = self.by_hand()
        self.by_hand(self.sam, start_local="2027-03-01T15:00", end_local="2027-03-04T10:00")
        self.add("m-checkin", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}.", HOTEL))
        self.assertEqual(self.scan().review, 0)
        self.assertEqual(self.read(lambda conn: conn.execute(select(ScannedMessage.segment_id)).scalar()), mine)

    def test_a_follow_up_with_another_providers_code_is_not_attached(self):
        self.confirmed()
        self.add("m-other", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}.", "unrelated-lodging.example"))
        self.assertEqual(self.scan(now=NOW + 60).review, 1)
        self.assertEqual(len(self.items()), 1)

    def test_a_booking_added_by_hand_is_matched_by_its_provider_name_in_the_senders_domain(self):
        self.by_hand()
        self.add("m-reply", follow("Your room request for your stay", f"About your hotel room: reference {CODE} is noted.", HOTEL))
        self.add("m-stranger", follow("Your room request for your stay", f"About your hotel room: reference {CODE} is noted.", "stranger.example"))
        self.scan()
        self.assertEqual(self.outcomes(), {"m-reply": "follow-up", "m-stranger": "unreadable"})

    def test_nothing_is_attached_on_a_date_or_a_name_alone(self):
        self.by_hand()
        self.add("m-dates", follow("Your stay: online check-in is open", "Your stay at Harbour Hotel from 21 November to 27 November: check-in is open.", HOTEL))
        self.assertEqual(self.scan().review, 1)

    def test_a_lowercase_or_spaced_written_code_still_matches(self):
        self.by_hand()
        self.add("m-checkin", follow("Your stay: online check-in is open", "Check-in opens soon for reservation h88-231.", HOTEL))
        self.assertEqual(self.scan().review, 0)

    def test_new_facts_are_counted_and_not_applied(self):
        segment = self.confirmed()
        before = self.read(lambda conn: trips.decode_details(conn.execute(select(Segment.details).where(Segment.id == segment)).scalar()))
        self.add("m-gate", follow("Your stay: online check-in is open", f"Your hotel reservation {CODE}: arrivals use Gate 12 after 3 pm."))
        self.add("m-plain", follow("Your stay: a week to go", f"Your hotel reservation number: {CODE} is booked."))
        self.scan(now=NOW + 60)
        summary = scan.summary(self.mailbox)
        assert summary is not None
        self.assertEqual((summary.followups, summary.with_facts), (2, 1))
        after = self.read(lambda conn: trips.decode_details(conn.execute(select(Segment.details).where(Segment.id == segment)).scalar()))
        self.assertEqual(after, before)

    def test_a_forwarded_follow_up_is_matched_by_the_original_sender(self):
        self.confirmed()
        body = (f"See below.\n\n---------- Forwarded message ---------\nFrom: Example <noreply@{STAYS}>\nSubject: Your stay: online check-in is open\n"
                f"Date: Fri, 16 Oct 2026\n\nCheck-in opens soon for reservation {CODE}.")
        self.add("m-fwd", mail("gmail.example", "Fwd: Your stay: online check-in is open", body))
        self.assertEqual(self.scan(now=NOW + 60).review, 0)
        self.assertEqual(self.outcomes()["m-fwd"], "follow-up")

    def test_the_summary_figures_survive_a_round_trip_and_older_summaries_read_as_none(self):
        found = scan.Summary(5, 4, 1, 0, 0, False, followups=3, with_facts=2)
        self.assertEqual(scan.decode(scan.encode(found)), found)
        older = json.dumps({"found": 1, "read": 1, "bookings": 0, "review": 0, "skipped": 0, "capped": False})
        decoded = scan.decode(older)
        assert decoded is not None
        self.assertEqual((decoded.followups, decoded.with_facts), (0, 0))

    def test_a_follow_up_with_a_hidden_booking_does_not_leak_through_a_second_attempt(self):
        self.by_hand(self.sam)
        self.add("m-checkin", follow("Your stay: online check-in is open", f"Check-in opens soon for reservation {CODE}.", HOTEL))
        self.scan()
        self.assertEqual(len(self.items()), 1)
        self.assertEqual(self.items("u-sam"), [])


class FollowUpPrivacyTests(FollowUpCase):
    def test_canaries_in_follow_up_bodies_subjects_and_codes_reach_no_summary_no_log_and_no_row(self):
        code = "CNRY-7Q2X-TRIP"
        self.by_hand(confirmation=code)
        self.add("m-1", follow("Your stay: CANARY-SUBJECT-FOLLOW-4D8K", f"CANARY-BODY-FOLLOW-9B3M Your hotel reservation number: {code}", HOTEL))
        self.add("m-2", follow("Your stay: check-in is open CANARY-SUBJECT-FOLLOW-6T1R", f"CANARY-BODY-FOLLOW-2H7C Gate 9. Your hotel reservation number: {code}", HOTEL))
        with no_leaks(self, "CANARY-SUBJECT-FOLLOW-4D8K", "CANARY-SUBJECT-FOLLOW-6T1R", "CANARY-BODY-FOLLOW-9B3M", "CANARY-BODY-FOLLOW-2H7C"):
            self.scan()
        text = json.dumps(self.row(), default=str)
        for canary in ("CANARY", code):
            self.assertNotIn(canary, text)
        self.assertEqual(self.stored(), 0)

    def test_a_queued_code_is_kept_only_as_a_keyed_hash_and_never_in_the_database_in_the_clear(self):
        code = "CNRY-5W8Z-RSVN"
        for n in (1, 2):
            self.add(f"m-{n}", mail("example-air.example", f"Your flight itinerary CANARY-SUBJECT-GROUP-{n}A9X", f"Your flight itinerary CANARY-BODY-GROUP-{n}K4P Confirmation code: {code}"))
        with no_leaks(self, code, "CNRY5W8ZRSVN", "CANARY-SUBJECT-GROUP-1A9X", "CANARY-SUBJECT-GROUP-2A9X", "CANARY-BODY-GROUP-1K4P",
                      "CANARY-BODY-GROUP-2K4P", database=self.path):
            self.scan()
        [item] = self.items()
        self.assertEqual(item["count"], 2)
        kept = self.read(lambda conn: conn.execute(select(ReviewItem.reference)).scalars())
        self.assertEqual(kept[0], kept[1])
        self.assertEqual(len(kept[0]), 32)
        self.assertEqual(kept[0], stored_mail.reference_key("CNRY5W8ZRSVN"))
        self.assertNotIn("CANARY", json.dumps(item["others"]).replace("CANARY-SUBJECT-GROUP-1A9X", "").replace("CANARY-SUBJECT-GROUP-2A9X", ""))


class GroupingTests(FollowUpCase):
    def flight(self, n: int, code: str | None = "ZZ9Y8X", domain: str = "example-air.example", day: int = 16) -> tuple[str, bytes]:
        tail = f" Confirmation code: {code}" if code else ""
        return f"m-{domain}-{n}", mail(domain, f"Your flight itinerary, update {n}", f"Your flight itinerary, update {n}.{tail}",
                                       f"Fri, {day} Oct 2026 09:00:00 +0100")

    def waiting(self) -> list[int]:
        return self.read(lambda conn: sorted(conn.execute(select(ReviewItem.id)).scalars()))

    def test_three_waiting_items_with_one_code_are_one_row_with_a_count_the_newest_first(self):
        for n, day in ((1, 14), (2, 18), (3, 16)):
            self.add(*self.flight(n, day=day))
        self.scan()
        [row] = self.items()
        self.assertEqual((row["count"], row["received"], len(row["others"])), (3, "2026-10-18", 2))
        self.assertEqual([o["received"] for o in row["others"]], ["2026-10-16", "2026-10-14"])
        self.assertEqual(row["subject"], "Your flight itinerary, update 2")
        self.assertEqual(self.read(lambda conn: review.count(conn, "u-jane")), 1)
        self.assertEqual(len(self.waiting()), 3)

    def test_a_group_whose_newest_item_holds_several_suggestions_lists_them_all_and_counts_the_others(self):
        for n, day in ((1, 14), (2, 18)):
            self.add(*self.flight(n, day=day))
        self.scan()
        newest = max(self.items(), key=lambda r: r["received"])
        picks = [{"kind": "flight", "origin": "BOS", "destination": "DEN", "start_local": "2026-12-02T07:15", "end_local": "2026-12-02T10:05"},
                 {"kind": "flight", "origin": "DEN", "destination": "BOS", "start_local": "2026-12-08T16:20", "end_local": "2026-12-08T21:50"}]
        box, message = self.read(lambda conn: conn.execute(select(ReviewItem.mailbox_id, ReviewItem.message_id).where(ReviewItem.id == newest["id"])).fetchone())
        self.read(lambda conn: review.set_suggestions(conn, box, message, picks, None))
        [row] = self.items()
        self.assertEqual((row["count"], len(row["suggestions"]), [s["origin"] for s in row["suggestions"]]), (2, 2, ["BOS", "DEN"]))
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", row["id"])))
        self.assertEqual(self.waiting(), [])

    def test_items_with_no_code_stay_separate(self):
        for n in (1, 2):
            self.add(*self.flight(n, code=None))
        self.scan()
        rows = self.items()
        self.assertEqual([(r["count"], r["others"]) for r in rows], [(1, []), (1, [])])
        self.assertEqual(self.read(lambda conn: review.count(conn, "u-jane")), 2)

    def test_a_message_naming_two_codes_is_never_grouped(self):
        self.add("m-two", mail("example-air.example", "Your flight itinerary, two", "Your flight itinerary. Confirmation code: ZZ9Y8X. Reservation number: QQ7W6V."))
        self.add(*self.flight(1))
        self.scan()
        self.assertEqual([r["count"] for r in self.items()], [1, 1])

    def test_items_from_different_sender_domains_are_not_grouped(self):
        self.add(*self.flight(1))
        self.add(*self.flight(2, domain="other-air.example"))
        self.scan()
        self.assertEqual([r["count"] for r in self.items()], [1, 1])

    def test_items_in_different_mailboxes_are_not_grouped(self):
        sam_box = self.connect("u-sam", "sam@gmail.example", "refresh-sam-1")
        self.add(*self.flight(1))
        self.scan()
        self.google.matches.clear()
        self.google.added.clear()
        self.add(*self.flight(2))
        self.scan(sam_box)
        self.assertEqual([r["count"] for r in self.items()], [1])
        self.assertEqual([r["count"] for r in self.items("u-sam")], [1])

    def test_a_shared_mailbox_groups_for_everyone_who_sees_it(self):
        self.read(lambda conn: conn.execute(Mailbox.__table__.update().where(Mailbox.id == self.mailbox).values(share_review=True)))
        for n in (1, 2):
            self.add(*self.flight(n))
        self.scan()
        self.assertEqual([r["count"] for r in self.items("u-sam")], [2])
        self.assertEqual(self.read(lambda conn: review.count(conn, "u-sam")), 1)

    def test_dismissing_the_row_dismisses_all_of_them_and_deletes_their_stored_copies(self):
        for n in (1, 2, 3):
            self.add(*self.flight(n))
        self.add(*self.flight(4, code="OTHER55"))
        self.scan()
        self.assertEqual(self.stored(), 4)
        [row] = [r for r in self.items() if r["count"] == 3]
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", row["id"])))
        self.assertEqual(len(self.waiting()), 1)
        self.assertEqual(self.stored(), 1)
        self.assertEqual([r["count"] for r in self.items()], [1])

    def test_dismissing_a_single_item_leaves_the_others_with_another_code_alone(self):
        self.add(*self.flight(1))
        self.add(*self.flight(2, code="OTHER55"))
        self.scan()
        [first, _] = self.items()
        self.read(lambda conn: review.dismiss(conn, "u-jane", first["id"]))
        self.assertEqual(len(self.waiting()), 1)
        self.assertEqual(self.stored(), 1)

    def test_adding_from_the_row_keeps_the_rows_message_as_the_bookings_source_and_removes_the_rest(self):
        for n, day in ((1, 14), (2, 18), (3, 16)):
            self.add(*self.flight(n, day=day))
        self.scan()
        [row] = self.items()
        segment = self.by_hand()
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", row["id"], (self.jane, [segment]))))
        self.assertEqual(self.waiting(), [])
        self.assertEqual(self.stored(), 1)
        [kept] = self.read(lambda conn: stored_mail.for_segment(conn, segment))
        self.assertEqual(kept["subject"], "Your flight itinerary, update 2")

    def test_the_stored_copy_of_a_group_is_encrypted_and_the_row_names_no_code(self):
        for n in (1, 2):
            self.add(*self.flight(n))
        self.scan()
        [row] = self.items()
        self.assertNotIn("ZZ9Y8X", json.dumps(row))
        sealed = self.read(lambda conn: conn.execute(select(StoredMessage.content)).scalars())
        self.assertTrue(all(secretbox.is_encrypted(s) for s in sealed))

    def test_a_group_a_person_cannot_see_is_not_theirs_to_dismiss(self):
        for n in (1, 2):
            self.add(*self.flight(n))
        self.scan()
        [row] = self.items()
        self.assertFalse(self.read(lambda conn: review.dismiss(conn, "u-sam", row["id"])))
        self.assertEqual(len(self.waiting()), 2)


class ReferenceTests(FollowUpCase):
    def test_labelled_codes_are_read_in_the_words_the_readers_use(self):
        for text, expected in (("Confirmation code: ZZ9Y8X", {"ZZ9Y8X"}), ("Booking reference is AB12CD", {"AB12CD"}), ("Reservation #: h88-231", {"H88231"}),
                               ("予約番号：AB12345", {"AB12345"}), ("Confirmation number: below", set()), ("Confirmation: ZZ9Y8X", set()),
                               ("Reservation number: AB1", set())):
            self.assertEqual(set(references.labelled(text)), expected, text)

    def test_one_labelled_code_is_the_reference_and_two_are_none(self):
        self.assertEqual(references.read("", "Confirmation code: ZZ9Y8X, again ZZ9Y8X").reference, "ZZ9Y8X")
        self.assertIsNone(references.read("", "Confirmation code: ZZ9Y8X. Booking number: QQ7W6V").reference)
        self.assertIsNone(references.read("a reply", "no code here").reference)

    def test_a_message_that_holds_a_booking_has_no_reference(self):
        message = extract.read({"raw": b64(eml("hotel_jsonld"))})
        self.assertEqual(message.found, references.Found())

    def test_facts_are_a_seat_a_terminal_a_gate_or_an_address(self):
        self.assertEqual(references.facts_in("Seat 12A, Terminal 2, Gate B12\nAddress: 1 Quay Street"), {"seat", "terminal", "gate", "address"})
        self.assertEqual(references.facts_in("Your seat: 14C (window)"), {"seat"})
        self.assertEqual(references.facts_in("the gate is open, terminal is busy"), set())

    def test_codes_are_capped(self):
        text = " ".join(f"AB{n:06d}" for n in range(references.MAX_TOKENS + 500))
        self.assertLessEqual(len(references.read("", text).codes), references.MAX_TOKENS)
