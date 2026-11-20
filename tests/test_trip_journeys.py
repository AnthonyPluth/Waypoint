import unittest

from tests.test_trips import Household
from waypoint.domain import trips
from waypoint.domain.visibility import Viewer

CODE = "QZXW74"


def leg(origin, destination, start, end, number, code=CODE, **more):
    return {"kind": "flight", "origin": origin, "destination": destination, "start_local": start, "end_local": end,
            "provider": "Aurora Air", "confirmation": code, "details": {"flight_number": number}, **more}


FIRST = leg("BOS", "JFK", "2026-03-09T06:10", "2026-03-09T07:28", "AU1402")
SECOND = leg("JFK", "LIS", "2026-03-09T09:40", "2026-03-09T21:15", "AU212")


class Journeys(Household):
    def setUp(self):
        super().setUp()
        self.who = [{"person_id": self.jane.person_id, "name": None}]

    def book(self, fields, trip_id=None, travelers=None):
        return self.add(self.jane, fields, trip_id, self.who if travelers is None else travelers)

    def trip(self, *legs):
        first = self.book(legs[0])
        return [first, *(self.book(f, first["trip_id"]) for f in legs[1:])]

    def journeys(self, trip_id):
        got = trips.get(self.c, self.jane, trip_id)
        assert got is not None
        return {s["id"]: s["journey"] for s in got["segments"]}

    def test_two_legs_on_one_code_in_one_trip_are_one_journey(self):
        a, b = self.trip(FIRST, SECOND)
        self.assertEqual(self.journeys(a["trip_id"]), {
            a["id"]: {"lead": a["id"], "leg": 1, "legs": 2, "previous": None, "next": b["id"]},
            b["id"]: {"lead": a["id"], "leg": 2, "legs": 2, "previous": a["id"], "next": None}})

    def test_the_code_itself_is_never_in_the_journey(self):
        a, _ = self.trip(FIRST, SECOND)
        self.assertNotIn(CODE, str(self.journeys(a["trip_id"])))

    def test_three_legs_are_one_journey_in_order(self):
        third = leg("LIS", "MAD", "2026-03-09T23:30", "2026-03-10T01:30", "AU77")
        a, b, c = self.trip(FIRST, SECOND, third)
        got = self.journeys(a["trip_id"])
        self.assertEqual([got[i]["leg"] for i in (a["id"], b["id"], c["id"])], [1, 2, 3])
        self.assertEqual({got[i]["legs"] for i in got}, {3})
        self.assertEqual(got[b["id"]]["previous"], a["id"])
        self.assertEqual(got[b["id"]]["next"], c["id"])

    def test_a_gap_of_24_hours_or_more_is_two_journeys(self):
        a, b = self.trip(FIRST, {**SECOND, "start_local": "2026-03-10T07:28", "end_local": "2026-03-10T19:00"})
        self.assertEqual(self.journeys(a["trip_id"]), {a["id"]: None, b["id"]: None})

    def test_a_gap_just_under_24_hours_is_a_connection(self):
        a, b = self.trip(FIRST, {**SECOND, "start_local": "2026-03-10T07:27", "end_local": "2026-03-10T19:00"})
        self.assertEqual(self.journeys(a["trip_id"])[b["id"]]["leg"], 2)

    def test_the_gap_is_between_real_instants_not_wall_clock_values(self):
        back = leg("BOS", "JFK", "2026-10-31T22:00", "2026-11-01T00:30", "AU1402")
        onward = leg("JFK", "LIS", "2026-11-01T23:45", "2026-11-02T12:00", "AU212")
        a, b = self.trip(back, onward)
        self.assertEqual(self.journeys(a["trip_id"]), {a["id"]: None, b["id"]: None})

    def test_the_same_clock_gap_is_a_connection_when_the_clocks_go_forward(self):
        back = leg("BOS", "JFK", "2026-03-07T20:00", "2026-03-07T22:00", "AU1402")
        onward = leg("JFK", "LIS", "2026-03-08T21:30", "2026-03-09T09:00", "AU212")
        a, b = self.trip(back, onward)
        self.assertEqual(self.journeys(a["trip_id"])[b["id"]]["previous"], a["id"])

    def test_a_round_trip_on_one_code_is_two_journeys_not_one(self):
        back = leg("LIS", "JFK", "2026-03-16T10:00", "2026-03-16T13:00", "AU213")
        home = leg("JFK", "BOS", "2026-03-16T15:00", "2026-03-16T16:20", "AU1403")
        a, b, c, d = self.trip(FIRST, SECOND, back, home)
        got = self.journeys(a["trip_id"])
        self.assertEqual((got[a["id"]]["next"], got[b["id"]]["next"]), (b["id"], None))
        self.assertEqual((got[c["id"]]["previous"], got[c["id"]]["lead"], got[d["id"]]["leg"]), (None, c["id"], 2))
        self.assertEqual({got[i]["legs"] for i in got}, {2})

    def test_a_cancelled_leg_never_links(self):
        a, b = self.trip(FIRST, {**SECOND, "status": "cancelled"})
        self.assertEqual(self.journeys(a["trip_id"]), {a["id"]: None, b["id"]: None})

    def test_a_cancelled_leg_does_not_stand_between_the_live_ones(self):
        stray = leg("JFK", "LIS", "2026-03-09T08:00", "2026-03-09T20:00", "AU99", status="cancelled")
        a, _, c = self.trip(FIRST, stray, SECOND)
        self.assertEqual(self.journeys(a["trip_id"])[c["id"]]["previous"], a["id"])

    def test_a_leg_with_no_time_never_links(self):
        a, b = self.trip(FIRST, {**SECOND, "details": {"flight_number": "AU212", "time_unknown": "yes"}})
        self.assertEqual(self.journeys(a["trip_id"]), {a["id"]: None, b["id"]: None})

    def test_separate_reservations_are_not_linked(self):
        a, b = self.trip(FIRST, {**SECOND, "confirmation": "LMNOP9"})
        self.assertEqual(self.journeys(a["trip_id"]), {a["id"]: None, b["id"]: None})

    def test_legs_with_no_code_are_not_linked(self):
        a, b = self.trip({**FIRST, "confirmation": None}, {**SECOND, "confirmation": None})
        self.assertEqual(self.journeys(a["trip_id"]), {a["id"]: None, b["id"]: None})

    def test_the_second_leg_must_leave_from_where_the_first_landed(self):
        a, b = self.trip(FIRST, leg("EWR", "LIS", "2026-03-09T09:40", "2026-03-09T21:15", "AU212"))
        self.assertEqual(self.journeys(a["trip_id"]), {a["id"]: None, b["id"]: None})

    def test_another_flight_on_another_code_between_them_breaks_the_chain(self):
        other = leg("JFK", "MIA", "2026-03-09T08:00", "2026-03-09T10:30", "AU5", code="OTHER1")
        a, _, c = self.trip(FIRST, other, SECOND)
        self.assertIsNone(self.journeys(a["trip_id"])[c["id"]])

    def test_legs_on_one_code_in_two_trips_are_not_linked(self):
        a = self.book(FIRST)
        other = trips.create_trip(self.c, self.jane, {"name": "Elsewhere", "people": [self.jane.person_id]})
        b = self.book(SECOND, other["id"])
        self.assertNotEqual(a["trip_id"], b["trip_id"])
        self.assertEqual(self.journeys(a["trip_id"]), {a["id"]: None})

    def test_a_card_links_when_every_one_of_its_bookings_has_the_next_leg(self):
        a1, b1 = self.trip(FIRST, SECOND)
        a2 = self.book({**FIRST, "confirmation": "ZZ9999"}, a1["trip_id"], self.on(self.mia))
        b2 = self.book({**SECOND, "confirmation": "ZZ9999"}, a1["trip_id"], self.on(self.mia))
        got = self.journeys(a1["trip_id"])
        self.assertEqual([got[i]["leg"] for i in (a1["id"], a2["id"], b1["id"], b2["id"])], [1, 1, 2, 2])
        self.assertEqual(got[a2["id"]]["next"], b1["id"])

    def test_a_card_does_not_link_when_only_some_of_its_bookings_have_the_next_leg(self):
        a1, b1 = self.trip(FIRST, SECOND)
        a2 = self.book({**FIRST, "confirmation": "ZZ9999"}, a1["trip_id"], self.on(self.mia))
        b2 = self.book({**SECOND, "confirmation": "YY8888"}, a1["trip_id"], self.on(self.mia))
        got = self.journeys(a1["trip_id"])
        self.assertEqual([got[i] for i in (a1["id"], a2["id"], b1["id"], b2["id"])], [None] * 4)

    def test_a_next_card_with_a_booking_the_first_lacks_does_not_link(self):
        a1, b1 = self.trip(FIRST, SECOND)
        self.book({**SECOND, "confirmation": "YY8888"}, a1["trip_id"], self.on(self.mia))
        got = self.journeys(a1["trip_id"])
        self.assertEqual((got[a1["id"]], got[b1["id"]]), (None, None))

    def test_a_viewer_who_cannot_see_the_trip_gets_nothing(self):
        a, b = self.trip(FIRST, SECOND)
        stranger = Viewer(self.mia)
        self.assertIsNone(trips.get(self.c, stranger, a["trip_id"]))
        self.assertIsNone(trips.get_segment(self.c, stranger, b["id"]))

    def test_a_segment_reply_carries_its_journey(self):
        a, b = self.trip(FIRST, SECOND)
        got = trips.get_segment(self.c, self.jane, b["id"])
        assert got is not None
        self.assertEqual(got["journey"], {"lead": a["id"], "leg": 2, "legs": 2, "previous": a["id"], "next": None})

    def test_a_stay_has_no_journey(self):
        stay = self.book({"kind": "hotel", "origin": "Harbour Hotel", "start_local": "2026-03-09T15:00", "end_local": "2026-03-10T10:00",
                          "start_zone": "Europe/Lisbon", "end_zone": "Europe/Lisbon"})
        self.assertIsNone(stay["journey"])


if __name__ == "__main__":
    unittest.main()
