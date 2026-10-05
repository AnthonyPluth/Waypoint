"""Reminders and the calendar feed: ICS events that keep each segment's own zone and wall-clock time (across a zone change and
the date line), a feed that holds only the trips its owner can see under a key kept only as a hash, notifications that
come once and carry no loyalty number, and devices and feeds that end with their owner's access. Names, codes and
itineraries are made up; the airports are real."""
import os
import secrets
import time
import unittest
from datetime import UTC, date, datetime
from unittest import mock

from sqlalchemy import delete, insert, select, update

from waypoint import monitoring, oidc
from waypoint.domain import calendar, loyalty, people, reminders, trips
from waypoint.domain.visibility import Viewer
from waypoint.providers import webpush
from waypoint.server import feed, jobs
from waypoint.storage import db
from waypoint.storage.models import AuthSession, CalendarFeed, Person, PushDevice, ReminderPrefs, ReminderSent, Trip, User
from tests.privacy import found_in_database, no_leaks
from tests.shared import ServerCase, fetch
from tests.test_trips import Household
from tests.test_webpush import receiver

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 21, 0, 30, tzinfo=UTC)   # the flights have left: only the day's summary is due
LOYALTY_CANARY = "CANARY-LOYALTY-5550123"
ENDPOINT = "https://push.example.com/send/abc123"

# Made up: Jane and Mia fly to London from New York and stay in a hotel across the clocks going back; Sam has a trip of his own.
FLIGHT_OUT = {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-11-20T19:00",
              "end_local": "2026-11-21T07:10", "confirmation": "JANE42", "provider": "Example Air",
              "details": {"flight_number": "EX 101", "seat": "34K"}}
HOTEL = {"kind": "hotel", "origin": "Harbour Hotel", "start_local": "2026-10-30T15:00", "end_local": "2026-11-03T10:00",
         "start_zone": "America/New_York", "end_zone": "America/New_York", "confirmation": "HOTEL9"}
SAM_FLIGHT = {"kind": "flight", "origin": "SFO", "destination": "SEA", "start_local": "2026-11-20T09:00",
              "end_local": "2026-11-20T11:05", "confirmation": "SAMONLY", "details": {"flight_number": "EX 7"}}


def segment(**over):
    base = {"id": 1, "trip_id": 1, "kind": "flight", "status": "confirmed", "confirmation": None, "provider": None,
            "start_local": "2026-03-01T22:15:00", "start_zone": "Pacific/Auckland", "end_local": "2026-03-01T15:10:00",
            "end_zone": "America/Los_Angeles", "origin": "AKL", "destination": "LAX", "details": {"flight_number": "NZ 6"},
            "manage_url": None, "source": "manual", "booked_by": None, "locked_fields": [], "travelers": []}
    return {**base, **over}


def trip_of(*segs, name="Made-up trip"):
    return {"id": 1, "name": name, "start_date": None, "end_date": None, "destination": None, "notes": None, "auto": False,
            "booked_by": None, "segments": list(segs)}


def unfolded(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")[:-1]


class CalendarTests(unittest.TestCase):
    def lines(self, *segs, now=NOW):
        return unfolded(calendar.feed([trip_of(*segs)], now))

    def test_a_flight_across_the_date_line_keeps_its_own_zones_and_wall_clock_times(self):
        lines = self.lines(segment())
        self.assertIn("DTSTART;TZID=Pacific/Auckland:20260301T221500", lines)
        self.assertIn("DTEND;TZID=America/Los_Angeles:20260301T151000", lines)   # it lands "before" it left, on the same date
        self.assertIn("SUMMARY:Flight NZ 6 AKL → LAX", lines)

    def test_no_event_time_is_converted_to_utc(self):
        for line in self.lines(segment(), segment(id=2, start_zone="Europe/London", end_zone="America/New_York")):
            if line.startswith(("DTSTART", "DTEND")):
                self.assertFalse(line.endswith("Z"), line)
        self.assertIn("DTSTAMP:20261119T120000Z", self.lines(segment()))   # the one UTC time RFC 5545 asks for

    def test_a_stay_across_the_clocks_going_back_says_when_they_changed(self):
        stay = segment(id=3, kind="hotel", origin="Harbour Hotel", destination=None, start_local="2026-10-30T15:00",
                       end_local="2026-11-03T10:00", start_zone="America/New_York", end_zone="America/New_York",
                       details={})
        lines = self.lines(stay)
        self.assertIn("DTSTART;TZID=America/New_York:20261030T150000", lines)
        self.assertIn("DTEND;TZID=America/New_York:20261103T100000", lines)
        zone = lines[lines.index("TZID:America/New_York"):]
        i = zone.index("DTSTART:20261101T020000")   # 02:00 on the wall, as the clocks said
        self.assertEqual(zone[i - 1:i + 3], ["BEGIN:STANDARD", "DTSTART:20261101T020000", "TZOFFSETFROM:-0400", "TZOFFSETTO:-0500"])

    def test_a_flight_changes_zone_between_its_ends_and_each_zone_is_described(self):
        lines = self.lines(segment(origin="JFK", destination="LHR", start_local="2026-11-20T19:00:00",
                                   end_local="2026-11-21T07:10:00", start_zone="America/New_York", end_zone="Europe/London"))
        self.assertIn("DTSTART;TZID=America/New_York:20261120T190000", lines)
        self.assertIn("DTEND;TZID=Europe/London:20261121T071000", lines)
        self.assertIn("TZID:America/New_York", lines)
        self.assertIn("TZID:Europe/London", lines)
        self.assertIn("TZOFFSETTO:+0000", lines)

    def test_a_zone_that_changes_across_the_date_line_in_summer_time(self):
        lines = self.lines(segment(start_local="2026-09-25T08:00:00", end_local="2026-09-28T09:30:00", start_zone="Pacific/Auckland",
                                   end_zone="Pacific/Auckland", origin="AKL", destination="AKL"))
        zone = lines[lines.index("TZID:Pacific/Auckland"):]
        i = zone.index("DTSTART:20260927T020000")
        self.assertEqual(zone[i - 1:i + 3], ["BEGIN:DAYLIGHT", "DTSTART:20260927T020000", "TZOFFSETFROM:+1200", "TZOFFSETTO:+1300"])

    def test_a_cancelled_booking_stays_in_the_feed_as_cancelled(self):
        self.assertIn("STATUS:CANCELLED", self.lines(segment(status="cancelled")))

    def test_text_is_escaped_and_long_lines_are_folded_at_75_octets(self):
        lines = calendar.feed([trip_of(segment(provider="Example, Air; Ltd", confirmation="AB12CD", origin="Zürich" * 12,
                                               manage_url="https://air.example/manage?id=AB12CD"))], NOW)
        for raw in lines.split("\r\n"):
            self.assertLessEqual(len(raw.encode()), 75, raw)
        text = "\r\n".join(unfolded(lines))
        self.assertIn("Example\\, Air\\; Ltd", text)
        self.assertIn("Confirmation: AB12CD", text.replace("\\n", "\n"))
        self.assertTrue(lines.endswith("END:VCALENDAR\r\n"))

    def test_an_empty_calendar_is_still_one(self):
        self.assertEqual(unfolded(calendar.feed([], NOW))[0], "BEGIN:VCALENDAR")
        self.assertNotIn("BEGIN:VEVENT", calendar.feed([], NOW))


def subscription(endpoint=ENDPOINT):
    _key, p256dh, auth = receiver()
    return endpoint, p256dh, webpush.b64u(auth)


class Reminders(Household):
    """Jane and Sam (members) and Mia (a guest): Jane and Mia travel, Sam has a trip of his own."""

    def setUp(self):
        super().setUp()
        self.out = self.add(self.jane, FLIGHT_OUT, travelers=self.on(self.jane.person_id, self.mia))
        self.sam_trip = self.add(self.sam, SAM_FLIGHT, travelers=self.on(self.sam.person_id))
        self.sent: list[tuple[int, dict]] = []

    def send(self, device, message):
        self.sent.append((device.id, message))

    def device(self, owner="u-jane", endpoint=ENDPOINT):
        return reminders.add_device(self.c, owner, *subscription(endpoint), time.time())

    def due(self, now, today=date(2026, 11, 20), hour=8, send=None):
        return reminders.run_due(self.c, now, today, hour, send or self.send)


class FeedTests(Reminders):
    def test_the_feed_holds_only_the_trips_its_owner_can_see(self):
        jane = "".join(unfolded(reminders.feed_text(self.c, "u-jane", NOW)))
        sam = "".join(unfolded(reminders.feed_text(self.c, "u-sam", NOW)))
        self.assertIn("JANE42", jane)
        self.assertNotIn("SAMONLY", jane)
        self.assertIn("SAMONLY", sam)
        self.assertNotIn("JANE42", sam)
        self.assertEqual(reminders.feed_text(self.c, "u-nobody", NOW).count("BEGIN:VEVENT"), 0)   # no person: nothing is theirs

    def test_without_sign_in_the_local_household_sees_every_trip(self):
        text = "".join(unfolded(reminders.feed_text(self.c, reminders.LOCAL_OWNER, NOW)))
        self.assertIn("JANE42", text)
        self.assertIn("SAMONLY", text)

    def test_a_guest_who_travels_is_not_a_viewer_of_the_feed_but_their_trips_are_their_members(self):
        jane = reminders.feed_text(self.c, "u-jane", NOW)
        self.assertEqual(jane.count("BEGIN:VEVENT"), 1)

    def test_the_key_is_kept_only_as_a_hash(self):
        key = reminders.new_feed_key(self.c, "u-jane", 1.0)
        self.c.commit()
        self.assertEqual(found_in_database(self.path, (key,)), [])
        self.assertEqual(self.c.orm.get(CalendarFeed, "u-jane").key_hash, reminders.key_hash(key))
        self.assertNotEqual(reminders.key_hash(key), key)
        self.assertEqual(reminders.feed_owner(self.c, key, 2.0), "u-jane")

    def test_a_new_key_ends_the_old_one_and_turning_it_off_ends_the_feed(self):
        old = reminders.new_feed_key(self.c, "u-jane", 1.0)
        new = reminders.new_feed_key(self.c, "u-jane", 2.0)
        self.assertNotEqual(old, new)
        self.assertIsNone(reminders.feed_owner(self.c, old, 3.0))
        self.assertEqual(reminders.feed_owner(self.c, new, 3.0), "u-jane")
        self.assertTrue(reminders.feed_off(self.c, "u-jane"))
        self.assertFalse(reminders.feed_off(self.c, "u-jane"))
        self.assertIsNone(reminders.feed_owner(self.c, new, 3.0))
        self.assertFalse(reminders.feed_on(self.c, "u-jane"))

    def test_the_feed_and_notifications_never_carry_a_loyalty_number(self):
        program = loyalty.PROGRAMS["airline"][0]
        loyalty.add(self.c, {"person_id": self.jane.person_id, "kind": "airline", "program": program, "number": LOYALTY_CANARY,
                             "tier": None, "expiry": None, "notes": None})
        self.device()
        with no_leaks(self, LOYALTY_CANARY, database=self.path):
            text = reminders.feed_text(self.c, "u-jane", NOW)
            self.due(datetime(2026, 11, 20, 8, 0, tzinfo=UTC))
        self.assertNotIn(LOYALTY_CANARY, text)
        self.assertTrue(self.sent)
        self.assertNotIn(LOYALTY_CANARY, repr(self.sent))


class LapseTests(Reminders):
    ALLOWED = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "u-jane@example.com"}

    def test_a_device_and_a_feed_end_when_their_owner_can_no_longer_sign_in(self):
        self.device("u-jane", ENDPOINT)
        self.device("u-sam", "https://push.example.com/send/sam")
        reminders.set_prefs(self.c, "u-sam", {"check_in": True, "day_of": False})
        jane_key = reminders.new_feed_key(self.c, "u-jane", 1.0)
        sam_key = reminders.new_feed_key(self.c, "u-sam", 1.0)
        with mock.patch.dict(os.environ, self.ALLOWED):   # Sam's email isn't on the list any more
            self.assertEqual(reminders.end_lapsed(self.c), 1)
            self.assertEqual(reminders.end_lapsed(self.c), 0)
            self.assertEqual(reminders.feed_owner(self.c, jane_key, time.time()), "u-jane")
            self.assertIsNone(reminders.feed_owner(self.c, sam_key, time.time()))
        self.assertEqual([d["id"] for d in reminders.devices(self.c, "u-sam")], [])
        self.assertEqual(len(reminders.devices(self.c, "u-jane")), 1)
        self.assertFalse(reminders.feed_on(self.c, "u-sam"))
        self.assertEqual(reminders.prefs(self.c, "u-sam"), {"check_in": True, "day_of": True})   # their choices went too

    def test_a_feed_is_gone_the_moment_it_is_asked_for_after_the_owner_lapses_and_not_before(self):
        key = reminders.new_feed_key(self.c, "u-sam", 1.0)
        self.assertEqual(reminders.feed_owner(self.c, key, 2.0), "u-sam")   # (no sign-in: nothing lapses)
        with mock.patch.dict(os.environ, self.ALLOWED):
            self.assertIsNone(reminders.feed_owner(self.c, key, 2.0))
            self.assertFalse(reminders.feed_on(self.c, "u-sam"))

    def test_no_reminder_goes_to_a_lapsed_owner(self):
        self.device("u-sam", "https://push.example.com/send/sam")
        with mock.patch.dict(os.environ, self.ALLOWED):
            self.assertEqual(reminders.run_due(self.c, datetime(2026, 11, 20, 8, 0, tzinfo=UTC), date(2026, 11, 20), 8, self.send), 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(reminders.devices(self.c, "u-sam"), [])

    def test_with_groups_a_sign_in_that_is_too_old_lapses_it(self):
        groups = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_GROUPS": "household"}
        self.device("u-sam", "https://push.example.com/send/sam")
        with mock.patch.dict(os.environ, groups):
            self.c.execute(update(User).where(User.sub == "u-sam").values(last_seen=time.time() - 365 * 86400))
            self.assertEqual(reminders.end_lapsed(self.c), 1)

    def test_the_hourly_sweep_ends_them_and_survives_a_failure(self):
        self.device("u-sam", "https://push.example.com/send/sam")
        self.c.commit()
        with mock.patch.dict(os.environ, self.ALLOWED):
            jobs.sweep_lapsed()
        self.assertEqual(reminders.devices(self.c, "u-sam"), [])
        with mock.patch.object(reminders, "end_lapsed", side_effect=RuntimeError("boom")):
            jobs.sweep_lapsed()   # reported without its text, not raised


class SendingTests(Reminders):
    def test_check_in_goes_out_once_in_the_day_before_the_flight_leaves(self):
        self.device()
        # Leaves 19:00 in New York on the 20th = 00:00 UTC on the 21st; check-in opens 00:00 UTC on the 20th.
        self.assertEqual(self.due(datetime(2026, 11, 19, 23, 59, tzinfo=UTC), hour=3), 0)   # a minute early
        self.assertEqual(self.due(datetime(2026, 11, 20, 0, 1, tzinfo=UTC), hour=3), 1)
        (_id, message), = self.sent
        self.assertEqual(message["title"], "Check-in opens")
        self.assertEqual(message["body"], "Flight EX 101 JFK → LHR leaves Fri 20 Nov at 19:00.")   # the airport's own wall clock
        self.assertEqual(message["url"], f"/#trip/{self.out['trip_id']}")
        self.assertEqual(self.due(datetime(2026, 11, 20, 0, 6, tzinfo=UTC), hour=3), 0)   # once
        self.assertEqual(len(self.sent), 1)

    def test_nothing_after_the_flight_has_left(self):
        self.device()
        self.assertEqual(self.due(datetime(2026, 11, 21, 0, 0, tzinfo=UTC), hour=3), 0)
        self.assertEqual(self.sent, [])

    def test_a_flight_moved_to_another_time_gets_its_own_reminder(self):
        self.device()
        self.due(datetime(2026, 11, 20, 1, 0, tzinfo=UTC), hour=3)
        trips.edit_segment(self.c, self.jane, self.out["id"], {"start_local": "2026-11-20T21:00", "end_local": "2026-11-21T09:10"})
        self.assertEqual(self.due(datetime(2026, 11, 20, 2, 0, tzinfo=UTC), hour=3), 1)

    def test_a_cancelled_flight_and_a_hotel_have_no_check_in(self):
        self.device()
        trips.edit_segment(self.c, self.jane, self.out["id"], {"status": "cancelled"})
        self.add(self.jane, {**HOTEL, "start_local": "2026-11-20T15:00", "end_local": "2026-11-22T10:00"}, self.out["trip_id"])
        self.assertEqual(self.due(datetime(2026, 11, 20, 12, 0, tzinfo=UTC), hour=3), 0)

    def test_the_day_of_summary_goes_out_once_from_seven_with_each_bookings_own_clock(self):
        self.device()
        self.add(self.jane, {**HOTEL, "start_local": "2026-11-20T15:00", "end_local": "2026-11-22T10:00"}, self.out["trip_id"])
        later = LATER
        self.assertEqual(self.due(later, hour=6), 0)   # before 7:00
        self.assertEqual(self.due(later, hour=7), 1)
        (_id, message), = self.sent
        self.assertEqual(message["title"], "Today")
        self.assertEqual(message["body"].split("\n"), ["15:00 Hotel check-in Harbour Hotel", "19:00 Flight EX 101 JFK → LHR"])
        self.assertEqual(self.due(later, hour=12), 0)
        self.assertEqual(self.due(later, hour=12, today=date(2026, 11, 21)), 0)   # nothing starts the next day

    def test_a_long_day_names_five_bookings_and_counts_the_rest(self):
        self.device()
        for i in range(7):
            self.add(self.jane, {**SAM_FLIGHT, "start_local": f"2026-11-20T0{i}:30", "end_local": f"2026-11-20T0{i}:50",
                                 "confirmation": f"X{i}", "details": {"flight_number": f"EX {70 + i}"}}, self.out["trip_id"], travelers=self.on(self.jane.person_id))
        self.due(LATER, hour=8)
        lines = next(m["body"] for _i, m in self.sent if m["title"] == "Today").split("\n")
        self.assertEqual((len(lines), lines[-1]), (6, "and 3 more"))

    def test_people_choose_which_reminders_they_get(self):
        self.device()
        reminders.set_prefs(self.c, "u-jane", {"check_in": False, "day_of": True})
        self.due(datetime(2026, 11, 20, 1, 0, tzinfo=UTC), hour=8)
        self.assertEqual([m["title"] for _i, m in self.sent], ["Today"])
        self.sent.clear()
        self.c.execute(delete(ReminderSent))
        reminders.set_prefs(self.c, "u-jane", {"check_in": True, "day_of": False})
        self.due(datetime(2026, 11, 20, 1, 0, tzinfo=UTC), hour=8)
        self.assertEqual([m["title"] for _i, m in self.sent], ["Check-in opens"])
        self.sent.clear()
        self.c.execute(delete(ReminderSent))
        reminders.set_prefs(self.c, "u-jane", {"check_in": False, "day_of": False})
        self.assertEqual(self.due(datetime(2026, 11, 20, 1, 0, tzinfo=UTC), hour=8), 0)

    def test_everyone_is_told_about_their_own_trips_only(self):
        self.device("u-jane", ENDPOINT)
        self.device("u-sam", "https://push.example.com/send/sam")
        self.due(LATER, hour=8)
        by_device = {d["id"]: owner for owner in ("u-jane", "u-sam") for d in reminders.devices(self.c, owner)}
        for device_id, message in self.sent:
            if by_device[device_id] == "u-jane":
                self.assertIn("EX 101", message["body"])
                self.assertNotIn("EX 7", message["body"].replace("EX 101", ""))
            else:
                self.assertIn("EX 7", message["body"])
                self.assertNotIn("EX 101", message["body"])
        self.assertEqual(len(self.sent), 2)   # one summary each

    def test_every_device_of_a_member_gets_it(self):
        self.device("u-jane", ENDPOINT)
        self.device("u-jane", "https://push.example.com/send/second")
        self.assertEqual(self.due(datetime(2026, 11, 20, 1, 0, tzinfo=UTC), hour=3), 1)
        self.assertEqual(len(self.sent), 2)

    def test_a_device_that_is_gone_is_forgotten_and_the_rest_still_get_it(self):
        self.device("u-jane", ENDPOINT)
        self.device("u-jane", "https://push.example.com/send/second")
        first = reminders.devices(self.c, "u-jane")[0]["id"]

        def send(device, message):
            if device.id == first:
                raise webpush.Gone(device.endpoint)
            self.send(device, message)
        self.assertEqual(self.due(datetime(2026, 11, 20, 1, 0, tzinfo=UTC), hour=3, send=send), 1)
        self.assertEqual(len(reminders.devices(self.c, "u-jane")), 1)

    def test_a_push_service_that_cant_be_reached_is_tried_again_not_counted_as_sent(self):
        self.device()
        calls = []

        def down(device, message):
            calls.append(1)
            raise RuntimeError("push service said 503")
        with mock.patch.object(monitoring, "report") as report:
            self.assertEqual(self.due(datetime(2026, 11, 20, 1, 0, tzinfo=UTC), hour=3, send=down), 0)
        report.assert_called()
        self.assertEqual(report.call_args.kwargs, {"values": False})
        self.assertEqual(self.c.execute(select(ReminderSent.id)).fetchall(), [])
        self.assertEqual(self.due(datetime(2026, 11, 20, 1, 5, tzinfo=UTC), hour=3), 1)   # the next round gets through
        self.assertEqual(len(calls), 1)

    def test_a_member_with_no_device_is_told_nothing_and_nothing_is_recorded(self):
        self.assertEqual(self.due(datetime(2026, 11, 20, 1, 0, tzinfo=UTC), hour=8), 0)
        self.assertEqual(self.c.execute(select(ReminderSent.id)).fetchall(), [])

    def test_the_job_sends_with_the_servers_key_and_survives_a_failure(self):
        self.device()
        self.c.commit()
        real = []
        with mock.patch.object(webpush, "send", side_effect=lambda *a, **k: real.append(a) or 201):
            jobs.send_reminders()   # (whatever day it is: it must not raise)
        with mock.patch.object(reminders, "run_due", side_effect=RuntimeError("boom")):
            jobs.send_reminders()


class DeviceTests(Reminders):
    def test_a_subscription_is_checked_before_anything_is_stored(self):
        endpoint, p256dh, auth = subscription()
        bad = [("http://push.example.com/x", p256dh, auth), ("https://127.0.0.1/x", p256dh, auth),
               ("https://10.0.0.5/x", p256dh, auth), ("https://nas/x", p256dh, auth), ("https://nas.local/x", p256dh, auth),
               ("https://user:pw@push.example.com/x", p256dh, auth), ("", p256dh, auth), (endpoint, "AAAA", auth),
               (endpoint, p256dh, "AAAA"), (endpoint, p256dh, "!!!"), ("https://push.example.com/" + "x" * 3000, p256dh, auth)]
        for args in bad:
            with self.subTest(endpoint=args[0][:30]), self.assertRaises(reminders.Invalid):
                reminders.add_device(self.c, "u-jane", *args, 1.0)
        self.assertEqual(reminders.devices(self.c, "u-jane"), [])

    def test_a_device_is_listed_by_its_service_and_belongs_to_one_member(self):
        made = self.device("u-jane")
        self.assertEqual(reminders.devices(self.c, "u-jane"), [{"id": made["id"], "service": "push.example.com", "created": made["created"]}])
        self.assertEqual(reminders.devices(self.c, "u-sam"), [])
        self.assertFalse(reminders.remove_device(self.c, "u-sam", made["id"]))   # not Sam's to remove
        self.assertTrue(reminders.remove_device(self.c, "u-jane", made["id"]))
        self.assertFalse(reminders.remove_device(self.c, "u-jane", made["id"]))

    def test_subscribing_again_keeps_one_row_and_a_browser_that_changes_hands_changes_owner(self):
        self.device("u-jane")
        self.device("u-jane")
        self.assertEqual(len(reminders.devices(self.c, "u-jane")), 1)
        self.device("u-sam")
        self.assertEqual((len(reminders.devices(self.c, "u-jane")), len(reminders.devices(self.c, "u-sam"))), (0, 1))

    def test_a_member_has_at_most_ten(self):
        for i in range(reminders.MAX_DEVICES):
            self.device("u-jane", f"https://push.example.com/send/{i}")
        with self.assertRaises(reminders.Invalid):
            self.device("u-jane", "https://push.example.com/send/one-too-many")
        self.device("u-jane", "https://push.example.com/send/3")   # one they have already is fine


class RouteCase(ServerCase):
    """Waypoint with sign-in on, two members (Ana and Ben) with sessions, and a public address."""
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint",
           "OIDC_ALLOWED_EMAILS": "ana@example.com,ben@example.com"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ["WAYPOINT_PUBLIC_URL"] = cls.base

    def setUp(self):
        with db.session() as conn:
            for table in (CalendarFeed, PushDevice, ReminderSent, AuthSession, User, Person):
                conn.execute(delete(table))
            conn.execute(delete(ReminderPrefs))
            conn.execute(delete(Trip))
        self.who = {n: self.sign_in(f"sub-{n}", f"{n}@example.com", n.title()) for n in ("ana", "ben")}

    def sign_in(self, sub, email, name) -> dict:
        token = secrets.token_urlsafe(24)
        now = time.time()
        with db.session() as conn:
            conn.execute(insert(AuthSession).values(token_hash=oidc._hash(token), sub=sub, email=email, name=name,
                                                    created=now, expires=now + 86400))
            oidc.remember_user(conn, sub, email, name, None, now)
        return {"Cookie": f"waypoint_session={token}"}

    def call(self, who, method, path, body=None):
        return self.req(method, path, body if method != "GET" else None, self.who[who])


class ApiTests(RouteCase):
    def test_reminders_start_with_both_on_and_no_device_or_feed(self):
        status, got = self.call("ana", "GET", "/api/reminders")
        self.assertEqual(status, 200)
        self.assertTrue(webpush.valid_public_key(got.pop("public_key")))
        self.assertEqual(got, {"check_in": True, "day_of": True, "devices": [], "feed": False})

    def test_a_member_chooses_their_reminders_and_only_their_own(self):
        self.assertEqual(self.call("ana", "POST", "/api/reminders", {"check_in": False, "day_of": True})[0], 200)
        self.assertEqual(self.call("ana", "GET", "/api/reminders")[1]["check_in"], False)
        self.assertEqual(self.call("ben", "GET", "/api/reminders")[1]["check_in"], True)
        for body in ({}, {"check_in": "yes", "day_of": True}, {"check_in": True, "day_of": 1}):
            self.assertEqual(self.call("ana", "POST", "/api/reminders", body)[0], 400)

    def test_devices_are_added_checked_and_removed_by_their_owner_alone(self):
        endpoint, p256dh, auth = subscription()
        body = {"endpoint": endpoint, "p256dh": p256dh, "auth": auth}
        status, added = self.call("ana", "POST", "/api/reminders/devices", body)
        self.assertEqual((status, added["service"]), (200, "push.example.com"))
        self.assertEqual(len(self.call("ana", "GET", "/api/reminders")[1]["devices"]), 1)
        self.assertEqual(self.call("ben", "GET", "/api/reminders")[1]["devices"], [])
        self.assertEqual(self.call("ben", "DELETE", f"/api/reminders/devices/{added['id']}")[0], 404)   # as one that isn't there
        self.assertEqual(self.call("ana", "DELETE", "/api/reminders/devices/x")[0], 404)
        self.assertEqual(self.call("ana", "DELETE", f"/api/reminders/devices/{added['id']}"), (200, {"ok": True}))
        self.assertEqual(self.call("ana", "POST", "/api/reminders/devices", {**body, "endpoint": "http://push.example.com/x"})[0], 400)
        self.assertEqual(self.call("ana", "POST", "/api/reminders/devices", {"endpoint": 5, "p256dh": p256dh, "auth": auth})[0], 400)
        self.assertEqual(self.call("ana", "POST", "/api/reminders/devices", {"endpoint": endpoint})[0], 400)

    def test_a_refusal_never_quotes_what_was_sent(self):
        status, got = self.call("ana", "POST", "/api/reminders/devices",
                                {"endpoint": "https://10.9.8.7/CANARY-ENDPOINT", "p256dh": "x", "auth": "y"})
        self.assertEqual(status, 400)
        self.assertNotIn("CANARY-ENDPOINT", got["error"])

    def test_the_feed_address_is_made_once_with_its_key_and_replaced_by_the_next(self):
        status, first = self.call("ana", "POST", "/api/feed")
        self.assertEqual(status, 200)
        self.assertRegex(first["url"], r"^" + self.base + r"/feed/[A-Za-z0-9_-]{43}\.ics$")
        self.assertTrue(self.call("ana", "GET", "/api/reminders")[1]["feed"])
        self.assertFalse(self.call("ben", "GET", "/api/reminders")[1]["feed"])
        second = self.call("ana", "POST", "/api/feed")[1]
        self.assertNotEqual(first["url"], second["url"])
        self.assertEqual(self.call("ana", "DELETE", "/api/feed"), (200, {"ok": True}))
        self.assertFalse(self.call("ana", "GET", "/api/reminders")[1]["feed"])
        self.assertEqual(self.call("ana", "DELETE", "/api/feed"), (200, {"ok": True}))   # already off

    def test_a_lapsed_members_things_end_even_when_someone_else_opens_settings(self):
        self.call("ben", "POST", "/api/feed")
        with db.session() as conn:
            reminders.add_device(conn, "sub-ben", *subscription("https://push.example.com/send/ben"), time.time())
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com"}):
            self.assertEqual(self.call("ana", "GET", "/api/reminders")[0], 200)
        with db.session() as conn:
            self.assertEqual(conn.execute(select(CalendarFeed.owner_sub)).fetchall(), [])
            self.assertEqual(conn.execute(select(PushDevice.id)).fetchall(), [])


class FeedRouteTests(RouteCase):
    """/feed/<key>.ics: a calendar app can't sign in, so the key in the address does it."""

    def setUp(self):
        super().setUp()
        with db.session() as conn:
            ana, ben = (Viewer(people.person_for_sub(conn, f"sub-{n}")) for n in ("ana", "ben"))
            trips.add_segment(conn, ana, {**FLIGHT_OUT, "confirmation": "ANAONLY"})
            trips.add_segment(conn, ben, {**SAM_FLIGHT, "confirmation": "BENONLY"})

    def key(self, who="ana"):
        url = self.call(who, "POST", "/api/feed")[1]["url"]
        return url.removeprefix(self.base)

    def test_the_address_opens_the_calendar_without_signing_in(self):
        status, headers, body = fetch(self.base, "GET", self.key())
        text = "".join(unfolded(body.decode()))
        self.assertEqual((status, headers["Content-Type"], headers["Cache-Control"]), (200, "text/calendar; charset=utf-8", "no-store"))
        self.assertIn("DTSTART;TZID=America/New_York:20261120T190000", text)
        self.assertIn("ANAONLY", text)
        self.assertNotIn("BENONLY", text)   # Ben's own trip isn't in Ana's feed
        self.assertIn("BENONLY", "".join(unfolded(fetch(self.base, "GET", self.key("ben"))[2].decode())))
        self.assertEqual(fetch(self.base, "HEAD", self.key())[0], 200)

    def test_a_key_that_isnt_one_is_a_404_the_same_as_one_that_was_replaced(self):
        old = self.key()
        self.key()
        for path in (old, "/feed/" + "a" * 43 + ".ics", "/feed/short.ics", "/feed/", "/feed/x/y.ics", "/feed/" + "a" * 43,
                     "/feed/..%2Fapi%2Fstate.ics"):
            with self.subTest(path=path[:30]):
                status, _, body = fetch(self.base, "GET", path)
                self.assertEqual((status, body), (404, b"Not found"))

    def test_only_a_get_reads_it(self):
        path = self.key()
        for method in ("POST", "DELETE"):
            self.assertEqual(fetch(self.base, method, path, b"{}", {"X-Waypoint": "1"})[0], 405)

    def test_the_feed_stops_when_it_is_turned_off_or_its_owner_lapses(self):
        path = self.key()
        self.call("ana", "DELETE", "/api/feed")
        self.assertEqual(fetch(self.base, "GET", path)[0], 404)
        path = self.key()
        self.assertEqual(fetch(self.base, "GET", path)[0], 200)
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ben@example.com"}):
            self.assertEqual(fetch(self.base, "GET", path)[0], 404)
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com,ben@example.com"}):
            self.assertEqual(fetch(self.base, "GET", path)[0], 404)   # and it doesn't come back with the access

    def test_the_key_is_not_in_the_log_nor_in_an_error(self):
        path = self.key()
        key = path.removeprefix("/feed/").removesuffix(".ics")
        lines = []
        with mock.patch.object(monitoring, "log", side_effect=lambda m, *a, **k: lines.append(m)):
            fetch(self.base, "GET", path)
            fetch(self.base, "GET", "/feed/" + "b" * 43 + ".ics")
        self.assertTrue(any("/feed/" in line for line in lines))
        self.assertFalse([line for line in lines if key in line or "b" * 43 in line], lines)
        with mock.patch.object(feed.reminders, "feed_text", side_effect=RuntimeError(key)), \
                mock.patch.object(monitoring, "report") as report, mock.patch.object(monitoring, "log", side_effect=lambda m, *a, **k: lines.append(m)):
            status, _, body = fetch(self.base, "GET", path)
        self.assertEqual(status, 500)
        self.assertNotIn(key.encode(), body)
        self.assertEqual(report.call_args.kwargs, {"values": False})
        self.assertFalse([line for line in lines if key in line])


class LocalTests(ServerCase):
    """Without sign-in, on your own machine: the one local household has a feed and sees every trip."""
    unset = ("OIDC_ISSUER", "WAYPOINT_PUBLIC_URL")

    def test_the_feed_is_made_at_this_machines_own_address_and_holds_every_trip(self):
        self.assertEqual(self.req("POST", "/api/segments", {**FLIGHT_OUT, "confirmation": "LOCAL1"})[0], 200)
        status, made = self.req("POST", "/api/feed")
        self.assertEqual(status, 200)
        self.assertTrue(made["url"].startswith("http://127.0.0.1:"))
        status, _, body = fetch(self.base, "GET", "/feed/" + made["url"].rsplit("/", 1)[1])
        self.assertEqual(status, 200)
        self.assertIn("LOCAL1", "".join(unfolded(body.decode())))


class SignInWithoutAddressTests(ServerCase):
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "ana@example.com"}
    unset = ("WAYPOINT_PUBLIC_URL",)

    def test_a_feed_address_needs_the_public_url_when_signing_in_is_on(self):
        token = secrets.token_urlsafe(24)
        now = time.time()
        with db.session() as conn:
            conn.execute(insert(AuthSession).values(token_hash=oidc._hash(token), sub="s", email="ana@example.com", name="Ana",
                                                    created=now, expires=now + 86400))
            oidc.remember_user(conn, "s", "ana@example.com", "Ana", None, now)
        status, got = self.req("POST", "/api/feed", None, {"Cookie": f"waypoint_session={token}"})
        self.assertEqual(status, 400)
        self.assertIn("WAYPOINT_PUBLIC_URL", got["error"])
        with db.session() as conn:
            self.assertEqual(conn.execute(select(CalendarFeed.owner_sub)).fetchall(), [])   # nothing was made that couldn't be shown


if __name__ == "__main__":
    unittest.main()
