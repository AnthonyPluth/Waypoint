from datetime import UTC, date, datetime

from waypoint.domain import calendar, flightstatus, reminders, trips
from tests.test_flightstatus import OUT
from tests.test_flightstatus import Household as FlightHousehold
from tests.test_reminders import FLIGHT_OUT, NOW, Reminders, segment, trip_of, unfolded


class Grouping(Reminders):
    def test_the_same_flight_on_two_bookings_is_one_group_other_flights_and_stays_are_not(self):
        a = segment(id=1, confirmation="AAAAAA", details={"flight_number": "AA 4001"})
        b = segment(id=2, confirmation="BBBBBB", details={"flight_number": "aa04001"})
        other_day = segment(id=3, details={"flight_number": "AA 4001"}, start_local="2026-03-02T22:15:00")
        other_flight = segment(id=4, details={"flight_number": "AA 4002"})
        other_route = segment(id=5, details={"flight_number": "AA 4001"}, destination="SFO")
        no_number = [segment(id=6, details={}), segment(id=7, details={})]
        stays = [segment(id=8, kind="hotel", details={}), segment(id=9, kind="hotel", details={})]
        groups = trips.flight_groups([a, b, other_day, other_flight, other_route, *no_number, *stays])
        self.assertEqual([[s["id"] for s in g] for g in groups], [[1, 2], [3], [4], [5], [6], [7], [8], [9]])


class CalendarGroups(Reminders):
    def lines(self, *segs):
        return unfolded(calendar.feed([trip_of(*segs)], NOW))

    def test_a_flight_on_two_bookings_is_one_event_listing_each_booking(self):
        lines = self.lines(segment(id=1, confirmation="AAAAAA", provider="Example Air"),
                           segment(id=2, confirmation="BBBBBB", provider="Example Air", details={"flight_number": "NZ0006"}))
        self.assertEqual(sum(line == "BEGIN:VEVENT" for line in lines), 1)
        text = "\n".join(lines).replace("\\n", "\n")
        self.assertIn("Confirmations: AAAAAA\\, BBBBBB", text)
        self.assertIn("UID:segment-1@waypoint", lines)

    def test_the_event_is_cancelled_only_when_every_booking_is(self):
        one = self.lines(segment(id=1, status="cancelled"), segment(id=2))
        self.assertIn("STATUS:CONFIRMED", one)
        both = self.lines(segment(id=1, status="cancelled"), segment(id=2, status="cancelled"))
        self.assertIn("STATUS:CANCELLED", both)

    def test_bookings_that_disagree_on_the_time_say_so_and_give_each_ones(self):
        text = "\n".join(self.lines(segment(id=1, confirmation="AAAAAA"),
                                    segment(id=2, confirmation="BBBBBB", start_local="2026-03-01T23:30:00"))).replace("\\n", "\n")
        self.assertIn("Times differ between bookings", text)
        self.assertIn("BBBBBB: departs 23:30", text)


    def test_a_cancelled_booking_with_other_times_is_not_a_disagreement(self):
        text = "\n".join(self.lines(segment(id=1, confirmation="AAAAAA"),
                                    segment(id=2, confirmation="BBBBBB", status="cancelled", start_local="2026-03-01T23:30:00"))).replace("\\n", "\n")
        self.assertNotIn("Times differ between bookings", text)


class ReminderGroups(Reminders):
    def test_a_flight_on_two_bookings_gets_one_check_in_reminder_and_one_line_in_the_day_summary(self):
        self.add(self.jane, {**FLIGHT_OUT, "confirmation": "MIA777"}, travelers=self.on(self.jane.person_id))
        self.device()
        when = datetime(2026, 11, 20, 0, 30, tzinfo=UTC)
        reminders.set_prefs(self.c, "u-jane", {"check_in": True, "day_of": True})
        self.assertEqual(self.due(when, today=date(2026, 11, 20), hour=8), 2)
        titles = [m["title"] for _d, m in self.sent]
        self.assertEqual(sorted(titles), ["Check-in opens", "Today"])
        [summary] = [m for _d, m in self.sent if m["title"] == "Today"]
        self.assertEqual(summary["body"].count("EX 101"), 1)


class StatusGroups(FlightHousehold):
    def test_a_flight_number_written_another_way_is_still_one_call(self):
        self.book(self.jane, OUT)
        self.book(self.sam, {**OUT, "confirmation": "ZZ9PLU", "details": {"flight_number": "EX0101"}})
        self.assertEqual([f.number for f in flightstatus.watching(self.c, self.when("3h"))], ["EX101"])
        self.assertEqual(flightstatus.run_due(self.c, self.when("3h")), 1)
        self.assertEqual(len(self.fake.calls), 1)
