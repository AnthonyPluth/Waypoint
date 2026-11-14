import json

from tests.privacy import no_leaks
from tests.test_mail_nothing_new import BODY, CANARIES, EARLIER, FULL, LATER, OLD_TEXT, NothingNewCase, mail
from tests.test_mail_scan import NOW
from waypoint.domain import trips
from waypoint.storage import stored_mail

CHANGE_TEXT = "Flight EX 101 from JFK to LHR, booking QX7M2K, has a schedule change."
NEWEST = "2026-11-20T21:30"
STALE = "2026-11-20T23:00"
ORIGINAL = "2026-11-20T19:00"
AFTER_NEWEST = "Fri, 16 Oct 2026 09:30:00 -0400"


class OrderCase(NothingNewCase):
    def say(self, name: str, start: str, text: str = CHANGE_TEXT, date: str = LATER, **more):
        return self.read_mail(text, {**FULL, "start_local": start, **more}, name=name, date=date, sender=f"Travel <desk@{name}.example>")

    def booking(self) -> dict:
        [seg] = self.segments()
        return seg

    def waiting(self) -> list[str]:
        return [i["sender_domain"] for i in self.kept()]

    def attached(self) -> list[stored_mail.Attached]:
        return self.read(lambda conn: stored_mail.attached(conn, self.known["id"]))

    def held(self) -> list[str]:
        return [a["message_id"] for a in self.attached()]

    def settle_on_newest(self) -> None:
        self.say("newest", NEWEST)
        self.assertEqual(self.booking()["start_local"], NEWEST)


class OlderMessageAfterNewerTests(OrderCase):
    def test_an_older_complete_reading_with_a_change_word_leaves_the_current_times_and_stays_in_review(self):
        self.settle_on_newest()
        before = self.booking()
        self.assertEqual(self.say("stale", STALE, date=EARLIER).state, "done")
        self.assertEqual(self.booking(), before)
        self.assertEqual(self.waiting(), ["stale.example"])
        self.assertEqual(self.held(), ["msg-flight_jsonld", "newest"])

    def test_the_same_older_message_read_again_still_changes_nothing(self):
        self.settle_on_newest()
        self.say("stale", STALE, date=EARLIER)
        before = self.booking()
        self.scan(now=NOW + 5000, again=True)
        self.assertEqual((self.booking(), self.booking()["start_local"]), (before, NEWEST))

    def test_an_older_message_read_when_it_is_the_first_one_for_a_changed_booking_keeps_the_stored_times(self):
        self.say("stale", STALE, date=EARLIER)
        self.assertEqual(self.booking()["start_local"], ORIGINAL)
        self.assertEqual(self.waiting(), ["stale.example"])

    def test_a_newer_message_still_updates_the_times(self):
        self.say("first", NEWEST)
        self.say("second", STALE, date=AFTER_NEWEST)
        self.assertEqual(self.booking()["start_local"], STALE)
        self.assertEqual(self.waiting(), [])

    def test_a_message_dated_the_same_day_as_the_newest_one_still_updates_the_times(self):
        self.settle_on_newest()
        self.say("same-day", STALE, date=LATER)
        self.assertEqual(self.booking()["start_local"], STALE)

    def test_an_older_complete_reading_that_agrees_with_the_booking_is_attached_and_leaves_review(self):
        self.settle_on_newest()
        before = self.booking()
        self.say("agrees", NEWEST, date=EARLIER)
        self.assertEqual((self.booking(), self.waiting()), (before, []))
        self.assertEqual(self.held(), ["msg-flight_jsonld", "newest", "agrees"])
        self.assertEqual(max(a["received"] or "" for a in self.attached()), "2026-10-14")

    def test_an_older_complete_reading_that_states_a_total_the_booking_lacks_is_not_merged_and_stays_in_review(self):
        self.settle_on_newest()
        before = self.booking()
        self.say("total", NEWEST, f"{CHANGE_TEXT} Total USD 120.00", EARLIER, total="120.00", currency="USD")
        self.assertEqual(self.booking(), before)
        self.assertEqual(self.waiting(), ["total.example"])

    def test_an_older_message_for_a_cancelled_booking_does_not_change_it(self):
        self.read(lambda conn: trips.edit_segment(conn, self.jane, self.known["id"], {"status": "cancelled"}))
        before = self.booking()
        self.say("stale", STALE, date=EARLIER)
        self.assertEqual((self.booking(), before["status"]), (before, "cancelled"))
        self.assertEqual(self.waiting(), ["stale.example"])

    def test_a_message_with_no_date_fills_gaps_but_never_overwrites_times(self):
        self.settle_on_newest()
        self.tick += 60
        self.add_mail("undated", mail(CHANGE_TEXT, date="", ident="undated", sender="Travel <desk@undated.example>"))
        self.fake.content = json.dumps({**FULL, "start_local": STALE})
        with no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
            self.scan(now=NOW + self.tick)
        self.assertEqual(self.booking()["start_local"], NEWEST)


class PrivacyTests(OrderCase):
    def test_an_older_message_held_back_from_the_booking_keeps_its_text_out_of_the_clear(self):
        self.settle_on_newest()
        self.say("stale", STALE, f"{OLD_TEXT} Schedule change. {BODY}", EARLIER)
        self.assertEqual(self.booking()["start_local"], NEWEST)
