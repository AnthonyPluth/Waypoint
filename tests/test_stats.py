"""Travel stats: each number, over the trips the viewer can see (AGENTS.md, "You see the trips you're on"), with times
at their own zones ("Times are where they happen"). Names, codes and itineraries are made up; airports and airlines are real."""
import gzip
import unittest
from pathlib import Path
from datetime import UTC, datetime

from sqlalchemy import select

from waypoint.domain import stats, trips
from waypoint.domain.visibility import Viewer
from waypoint.server.api import stats as api
from waypoint.server.common import ApiError
from waypoint.storage import db
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import Airline
from tests.shared import DbCase
from tests import test_trips
from tests.test_trips import Household

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
AKL_LAX = {"kind": "flight", "origin": "AKL", "destination": "LAX", "start_local": "2026-03-01T22:15",
           "end_local": "2026-03-01T15:10", "provider": "Air New Zealand",
           "details": {"flight_number": "NZ6", "seat": "34K", "cabin": "economy"}}   # across the date line: 13 h 55 min
JFK_LHR = {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-06-01T19:00",
           "end_local": "2026-06-02T07:10", "details": {"flight_number": "BA 112", "seat": "12A", "cabin": "Business"}}   # overnight: 7 h 10 min
LHR_JFK = {"kind": "flight", "origin": "LHR", "destination": "JFK", "start_local": "2026-06-08T11:00",
           "end_local": "2026-06-08T14:05", "details": {"flight_number": "BA 117", "seat": "12A", "cabin": "business"}}
HOTEL = {"kind": "hotel", "origin": "Harbour Hotel", "destination": "London", "provider": "Example Hotels",
         "start_local": "2026-06-02T15:00", "end_local": "2026-06-08T10:00", "start_zone": "Europe/London",
         "end_zone": "Europe/London"}
CAR = {"kind": "car", "origin": "Heathrow depot", "destination": "Heathrow depot", "provider": "Example Rentals",
       "start_local": "2026-06-03T09:00", "end_local": "2026-06-05T09:00", "start_zone": "Europe/London",
       "end_zone": "Europe/London"}


class StatsCase(Household):
    def stats(self, who, person=None, year=None, now=NOW):
        got = stats.compute(self.c, who, person, year, now)
        assert got is not None
        return got

    def mine(self, *fields, who=None, **extra):
        who = who or self.jane
        for f in fields:
            self.add(who, f, travelers=self.on(who.person_id), **extra)


class FlightTests(StatsCase):
    def test_a_flight_across_the_date_line_and_an_overnight_one_are_timed_at_their_own_zones(self):
        self.mine(AKL_LAX, JFK_LHR)
        flights = self.stats(self.jane)["flights"]
        self.assertEqual(flights["count"], 2)
        self.assertEqual(flights["air_seconds"], (13 * 60 + 55 + 7 * 60 + 10) * 60)

    def test_distance_routes_airports_and_records(self):
        self.mine(JFK_LHR, LHR_JFK, AKL_LAX)
        f = self.stats(self.jane)["flights"]
        self.assertAlmostEqual(f["routes"][0]["distance_km"], 5540, delta=15)   # JFK–LHR, once each way
        self.assertEqual((f["routes"][0]["a"], f["routes"][0]["b"], f["routes"][0]["flights"]), ("JFK", "LHR", 2))
        self.assertEqual(len(f["routes"]), 2)   # A–B and B–A are one route
        self.assertEqual(f["longest"]["origin"], "AKL")
        self.assertAlmostEqual(f["longest"]["distance_km"], 10500, delta=100)
        self.assertEqual((f["shortest"]["origin"], f["shortest"]["flight_number"]), ("JFK", "BA112"))
        self.assertAlmostEqual(f["distance_km"], 2 * f["routes"][0]["distance_km"] + f["longest"]["distance_km"], delta=0.5)
        self.assertEqual({a["code"]: a["visits"] for a in f["airports"]}, {"JFK": 2, "LHR": 2, "AKL": 1, "LAX": 1})
        self.assertEqual(f["most_visited_airport"], "JFK")
        self.assertEqual(f["airports"][0]["latitude"] is not None, True)
        self.assertEqual({c["name"]: c["count"] for c in f["countries"]}, {"US": 3, "GB": 2, "NZ": 1})
        self.assertAlmostEqual(f["times_around_earth"], f["distance_km"] / 40075, places=3)
        self.assertAlmostEqual(f["moon_fraction"], f["distance_km"] / 384400, places=4)

    def test_the_busiest_month(self):
        self.mine(JFK_LHR, LHR_JFK, AKL_LAX)
        self.assertEqual(self.stats(self.jane)["flights"]["busiest_month"], "2026-06")

    def test_airlines_are_named_from_the_flight_number_and_unknown_codes_show_the_code(self):
        self.mine(AKL_LAX, JFK_LHR, LHR_JFK, OUT_UNKNOWN, NO_NUMBER)
        airlines = {(a["code"], a["name"]): a["flights"] for a in self.stats(self.jane)["flights"]["airlines"]}
        self.assertEqual(airlines, {("BA", "British Airways"): 2, ("NZ", "Air New Zealand"): 1, ("6X", "6X"): 1,
                                    (None, "Example Air"): 1})

    def test_cabins_and_seats(self):
        self.mine(AKL_LAX, JFK_LHR, LHR_JFK)
        f = self.stats(self.jane)["flights"]
        self.assertEqual({c["name"]: c["count"] for c in f["cabins"]}, {"Business": 2, "Economy": 1})
        self.assertEqual(f["top_seat"], "12A")
        self.assertEqual(f["seat_positions"], {"window": 3, "aisle": 0, "middle": 0, "unknown": 0})

    def test_seat_positions_and_a_seat_letter_the_rule_cannot_place(self):
        for seat, position in (("34K", "window"), ("12a", "window"), ("5F", "window"), ("7C", "aisle"), ("7D", "aisle"),
                               ("9B", "middle"), ("9E", "middle"), ("21I", "unknown"), ("40L", "unknown"), ("12", "unknown"),
                               ("", "unknown"), (None, "unknown"), ("WAIT", "unknown")):
            with self.subTest(seat=seat):
                self.assertEqual(stats.seat_position(seat), position)
        self.mine({**JFK_LHR, "details": {"seat": "21L"}}, {**LHR_JFK, "details": {"seat": "9B"}}, {**AKL_LAX, "details": {}})
        shares = self.stats(self.jane)["flights"]["seat_positions"]
        self.assertEqual(shares, {"window": 0, "aisle": 0, "middle": 1, "unknown": 2})

    def test_an_airport_missing_from_the_table_still_counts_but_adds_no_distance(self):
        self.mine({**AKL_LAX, "origin": "ZZZ", "start_zone": "Pacific/Auckland"}, JFK_LHR)
        f = self.stats(self.jane)["flights"]
        self.assertEqual(f["count"], 2)
        by_code = {a["code"]: a for a in f["airports"]}
        self.assertEqual((by_code["ZZZ"]["name"], by_code["ZZZ"]["latitude"], by_code["ZZZ"]["country"]), ("ZZZ", None, None))
        self.assertEqual(f["shortest"]["origin"], "JFK")   # only the flight with both airports has a distance
        self.assertEqual(f["longest"], f["shortest"])
        self.assertIsNone(next(r for r in f["routes"] if r["a"] == "LAX")["distance_km"])
        self.assertEqual({c["name"] for c in f["countries"]}, {"US", "GB"})

    def test_a_future_leg_and_a_cancelled_one_do_not_count_and_one_in_the_air_waits_for_its_arrival(self):
        self.mine(JFK_LHR, {**LHR_JFK, "status": "cancelled"}, {**AKL_LAX, "start_local": "2026-12-01T22:15",
                                                                 "end_local": "2026-12-01T15:10"})
        self.assertEqual(self.stats(self.jane)["flights"]["count"], 1)
        before = datetime(2026, 6, 2, 6, 9, tzinfo=UTC)   # 07:10 BST is 06:10 UTC
        self.assertEqual(self.stats(self.jane, now=before)["flights"]["count"], 0)
        self.assertEqual(self.stats(self.jane, now=datetime(2026, 6, 2, 6, 10, tzinfo=UTC))["flights"]["count"], 1)

    def test_a_year_is_the_departures_local_year(self):
        # 23:30 on New Year's Eve in Auckland is still the 31st in Auckland and the same moment as 10:30 UTC.
        self.mine({**AKL_LAX, "start_local": "2025-12-31T23:30", "end_local": "2025-12-31T17:00"}, JFK_LHR)
        self.assertEqual(self.stats(self.jane, year=2025)["flights"]["count"], 1)
        self.assertEqual(self.stats(self.jane, year=2026)["flights"]["count"], 1)
        self.assertEqual(self.stats(self.jane)["flights"]["count"], 2)
        self.assertEqual(self.stats(self.jane, year=2024)["flights"]["count"], 0)

    def test_nothing_at_all(self):
        s = self.stats(self.jane)
        self.assertEqual((s["flights"]["count"], s["flights"]["distance_km"], s["flights"]["longest"], s["flights"]["top_seat"],
                          s["flights"]["busiest_month"], s["flights"]["most_visited_airport"]), (0, 0.0, None, None, None, None))
        self.assertEqual((s["stays"]["nights"], s["cars"]["days"], s["places"]), (0, 0, {"countries": [], "cities": []}))

    def test_a_route_is_one_route_either_way_round(self):
        self.mine(JFK_LHR, LHR_JFK)
        self.assertEqual([(r["a"], r["b"], r["flights"]) for r in self.stats(self.jane)["flights"]["routes"]], [("JFK", "LHR", 2)])


OUT_UNKNOWN = {"kind": "flight", "origin": "SYD", "destination": "MEL", "start_local": "2026-07-01T08:00",
               "end_local": "2026-07-01T09:35", "provider": "Example Air", "details": {"flight_number": "6X 12"}}
NO_NUMBER = {**OUT_UNKNOWN, "details": {}}


class HotelAndCarTests(StatsCase):
    def test_nights_count_overlapping_stays_once(self):
        self.mine(HOTEL, {**HOTEL, "provider": "Other Stays", "start_local": "2026-06-06T15:00", "end_local": "2026-06-10T10:00"})
        s = self.stats(self.jane)["stays"]
        self.assertEqual(s["nights"], 8)   # June 2–9 (the second stay's nights June 6–9 overlap the first's)
        self.assertEqual(s["chains"], [{"name": "Example Hotels", "count": 1}, {"name": "Other Stays", "count": 1}])
        self.assertEqual(s["cities"], [{"name": "London", "count": 2}])
        self.assertEqual(s["countries"], [{"name": "GB", "count": 2}])

    def test_a_same_day_stay_has_no_nights_and_an_unfinished_one_does_not_count(self):
        self.mine({**HOTEL, "end_local": "2026-06-02T21:00"}, {**HOTEL, "start_local": "2026-09-22T15:00", "end_local": "2026-09-25T10:00"})
        s = self.stats(self.jane)["stays"]
        self.assertEqual((s["nights"], s["chains"]), (0, [{"name": "Example Hotels", "count": 1}]))

    def test_a_year_takes_the_nights_in_it(self):
        self.mine({**HOTEL, "start_local": "2025-12-30T15:00", "end_local": "2026-01-03T10:00"})   # 2 nights in 2025, 2 in 2026
        self.assertEqual(self.stats(self.jane, year=2025)["stays"]["nights"], 2)
        self.assertEqual(self.stats(self.jane, year=2026)["stays"]["nights"], 2)
        self.assertEqual(self.stats(self.jane, year=2027)["stays"]["nights"], 0)
        self.assertEqual(self.stats(self.jane, year=2027)["stays"]["chains"], [])

    def test_a_stay_without_a_place_has_a_chain_but_no_city(self):
        self.mine({**HOTEL, "destination": None}, {**HOTEL, "destination": "Nowhereville"})
        s = self.stats(self.jane)["stays"]
        self.assertEqual((s["cities"], s["countries"]), ([{"name": "Nowhereville", "count": 1}], []))

    def test_rental_days_count_each_day_once(self):
        self.mine(CAR, {**CAR, "provider": "Other Rentals", "start_local": "2026-06-04T09:00", "end_local": "2026-06-06T09:00"})
        c = self.stats(self.jane)["cars"]
        self.assertEqual(c["days"], 4)   # June 3, 4, 5, 6
        self.assertEqual(c["companies"], [{"name": "Example Rentals", "count": 1}, {"name": "Other Rentals", "count": 1}])
        self.assertEqual(self.stats(self.jane, year=2027)["cars"], {"days": 0, "companies": []})

    def test_places_are_the_union_of_flights_and_hotels_with_their_first_visit(self):
        self.mine(JFK_LHR, {**HOTEL, "destination": "Paris", "start_local": "2026-06-10T15:00", "end_local": "2026-06-12T10:00"},
                  HOTEL)
        p = self.stats(self.jane)["places"]
        self.assertEqual([(c["name"], c["first_visit"]) for c in p["countries"]], [("US", "2026-06-01"), ("GB", "2026-06-02"),
                                                                                 ("FR", "2026-06-10")])
        self.assertEqual({c["name"]: c["first_visit"] for c in p["cities"]},
                         {"New York": "2026-06-01", "London": "2026-06-02", "Paris": "2026-06-10"})


class SeatStatsTests(StatsCase):
    def flight(self, who, *seats, **extra):
        people = [{"person_id": p, "name": None, "seat": s} for p, s in zip(who, seats, strict=True)]
        return self.add(self.jane, {**JFK_LHR, **extra}, travelers=people)

    def test_a_persons_stats_count_their_own_seat_and_the_households_count_everyones(self):
        self.flight([self.jane.person_id, self.sam.person_id], "12A", "12C")
        self.flight([self.jane.person_id, self.sam.person_id], "14A", "14B", start_local="2026-07-01T19:00", end_local="2026-07-02T07:10",
                    details={"flight_number": "BA 113", "seat": "99Z", "cabin": "Business"})
        everyone, jane, sam = (self.stats(self.jane, person)["flights"] for person in (None, self.jane.person_id, self.sam.person_id))
        self.assertEqual((everyone["count"], jane["count"], sam["count"]), (2, 2, 2))   # (a flight is counted once, whoever is asked)
        self.assertEqual(everyone["seat_positions"], {"window": 2, "aisle": 1, "middle": 1, "unknown": 0})   # 12A, 12C, 14A, 14B
        self.assertEqual(jane["seat_positions"], {"window": 2, "aisle": 0, "middle": 0, "unknown": 0})      # 12A, 14A
        self.assertEqual((sam["seat_positions"], sam["top_seat"]), ({"window": 0, "aisle": 1, "middle": 1, "unknown": 0}, "12C"))
        self.assertEqual(jane["top_seat"], "12A")

    def test_a_booking_with_no_traveller_seats_uses_its_booking_seat_once_and_one_with_nothing_is_unknown(self):
        self.mine({**JFK_LHR, "details": {"flight_number": "BA 112", "seat": "12A"}}, {**LHR_JFK, "details": {"flight_number": "BA 117"}})
        f = self.stats(self.jane)["flights"]
        self.assertEqual((f["seat_positions"], f["top_seat"]), ({"window": 1, "aisle": 0, "middle": 0, "unknown": 1}, "12A"))

    def test_a_traveller_without_a_seat_is_not_counted_unknown_when_another_has_one(self):
        self.flight([self.jane.person_id, self.sam.person_id], "12A", None)
        f = self.stats(self.jane)["flights"]
        self.assertEqual(f["seat_positions"], {"window": 1, "aisle": 0, "middle": 0, "unknown": 0})

    def test_a_partner_does_not_count_the_seats_of_a_solo_trip(self):
        self.add(self.sam, JFK_LHR, travelers=[{"person_id": self.sam.person_id, "name": None, "seat": "1A"}])
        self.assertEqual(self.stats(self.jane)["flights"]["count"], 0)
        self.assertEqual(self.stats(self.sam)["flights"]["top_seat"], "1A")


class StayFigureTests(StatsCase):
    def stay(self, hotel, city, start, end, **extra):
        return {**HOTEL, "origin": hotel, "destination": city, "start_local": f"{start}T15:00", "end_local": f"{end}T10:00", **extra}

    def test_totals_lists_records_and_the_busiest_month(self):
        self.mine(self.stay("Harbour Hotel", "London", "2026-06-02", "2026-06-08"),            # 6 nights
                  self.stay("harbour  hotel", "London", "2026-07-01", "2026-07-03"),           # 2 nights, the same hotel written another way
                  self.stay("Quay Inn", "Paris", "2026-07-10", "2026-07-12"),                   # 2 nights
                  self.stay("Quay Inn", "Paris", "2026-08-01", "2026-08-03"))                   # 2 nights
        s = self.stats(self.jane)["stays"]
        self.assertEqual((s["count"], s["average_nights"], s["nights"]), (4, 3.0, 12))
        self.assertEqual(s["hotels"], [{"name": "Harbour Hotel", "stays": 2, "nights": 8}, {"name": "Quay Inn", "stays": 2, "nights": 4}])
        self.assertEqual(s["cities_by_nights"], [{"name": "London", "stays": 2, "nights": 8}, {"name": "Paris", "stays": 2, "nights": 4}])
        self.assertEqual(s["longest"], {"hotel": "Harbour Hotel", "city": "London", "nights": 6, "start_local": "2026-06-02T15:00"})
        self.assertEqual((s["most_visited_hotel"], s["most_visited_city"]),
                         ({"name": "Harbour Hotel", "stays": 2, "nights": 8}, {"name": "London", "stays": 2, "nights": 8}))   # (a tie on stays goes to nights)
        self.assertEqual(s["busiest_month"], "2026-06")   # 6 nights in June, 2 + 2 in July (4), 2 in August

    def test_a_year_counts_its_own_nights_of_a_stay_across_new_year(self):
        self.mine(self.stay("Harbour Hotel", "London", "2025-12-30", "2026-01-03"))
        a, b = (self.stats(self.jane, year=y)["stays"] for y in (2025, 2026))
        self.assertEqual((a["count"], a["longest"]["nights"], a["busiest_month"]), (1, 2, "2025-12"))
        self.assertEqual((b["count"], b["hotels"], b["busiest_month"]), (1, [{"name": "Harbour Hotel", "stays": 1, "nights": 2}], "2026-01"))
        none = self.stats(self.jane, year=2027)["stays"]
        self.assertEqual((none["count"], none["average_nights"], none["hotels"], none["longest"], none["busiest_month"]), (0, 0.0, [], None, None))

    def test_overlapping_stays_each_count_but_a_night_counts_once_toward_nights_away(self):
        self.mine(self.stay("Harbour Hotel", "London", "2026-06-02", "2026-06-06"), self.stay("Quay Inn", "London", "2026-06-04", "2026-06-08"))
        s = self.stats(self.jane)["stays"]
        self.assertEqual((s["nights"], s["count"], s["average_nights"]), (6, 2, 4.0))

    def test_a_same_day_a_cancelled_and_an_unfinished_stay_are_left_out_and_a_stay_without_names_is_in_the_totals_only(self):
        gone = self.add(self.jane, self.stay("Gone Inn", "Rome", "2026-05-01", "2026-05-03"), travelers=self.on(self.jane.person_id))
        trips.edit_segment(self.c, self.jane, gone["id"], {"status": "cancelled"})
        self.mine(self.stay("Same Day Inn", "Rome", "2026-05-10", "2026-05-10", end_local="2026-05-10T21:00"),
                  self.stay("Later Inn", "Rome", "2026-09-22", "2026-09-25"),
                  self.stay(None, None, "2026-06-02", "2026-06-04"))
        s = self.stats(self.jane)["stays"]
        self.assertEqual((s["count"], s["nights"], s["hotels"], s["cities_by_nights"]), (1, 2, [], []))
        self.assertEqual((s["longest"], s["most_visited_hotel"], s["most_visited_city"]),
                         ({"hotel": None, "city": None, "nights": 2, "start_local": "2026-06-02T15:00"}, None, None))

    def test_a_partner_does_not_see_the_stays_of_a_solo_trip(self):
        self.add(self.sam, self.stay("Harbour Hotel", "London", "2026-06-02", "2026-06-08"), travelers=self.on(self.sam.person_id))
        self.assertEqual(self.stats(self.jane)["stays"]["count"], 0)
        self.assertEqual(self.stats(self.sam)["stays"]["count"], 1)


CRUISE = {"kind": "cruise", "origin": "Miami", "destination": "Miami", "provider": "Example Cruise Line",
          "start_local": "2026-03-01T16:30", "start_zone": "America/New_York", "end_local": "2026-03-08T07:00", "end_zone": "America/New_York",
          "itinerary": [{"name": "Nassau", "zone": "America/Nassau", "arrive_local": "2026-03-02T08:00", "depart_local": "2026-03-02T17:00"},
                        {"name": "Cozumel", "zone": "America/Cancun", "arrive_local": "2026-03-05T08:00", "depart_local": "2026-03-05T17:00"},
                        {"name": "Nassau", "zone": "America/Nassau", "arrive_local": "2026-03-06T08:00", "depart_local": "2026-03-06T17:00"}]}


class CruiseTests(StatsCase):
    def test_nights_aboard_sea_days_and_ports_of_call(self):
        self.mine(CRUISE)
        c = self.stats(self.jane)["cruises"]
        # nights 1–7 March; days strictly between embarking (1st) and disembarking (8th) are the 2nd–7th; 2nd, 5th and 6th are in port
        self.assertEqual((c["count"], c["nights"], c["sea_days"], c["ports"]), (1, 7, 3, 2))   # (Nassau twice is one port)
        self.assertEqual(c["lines"], [{"name": "Example Cruise Line", "count": 1}])

    def test_a_night_in_port_is_not_a_sea_day_and_a_port_with_no_times_adds_a_port_but_no_day(self):
        overnight = {**CRUISE, "itinerary": [{"name": "Reykjavik", "zone": "Atlantic/Reykjavik", "arrive_local": "2026-03-02T08:00",
                                              "depart_local": "2026-03-03T17:00"}, {"name": "Akureyri", "zone": "Atlantic/Reykjavik",
                                                                                     "arrive_local": None, "depart_local": None}]}
        self.mine(overnight)
        c = self.stats(self.jane)["cruises"]
        self.assertEqual((c["nights"], c["sea_days"], c["ports"]), (7, 4, 2))   # 2nd and 3rd in port; 4th–7th at sea

    def test_a_year_takes_its_own_nights_and_sea_days_and_the_years_list_has_the_cruise(self):
        spanning = {**CRUISE, "start_local": "2025-12-29T16:30", "end_local": "2026-01-03T07:00", "itinerary": []}
        self.mine(spanning)
        self.assertEqual(self.stats(self.jane)["years"], [2026, 2025])
        c25, c26 = (self.stats(self.jane, year=y)["cruises"] for y in (2025, 2026))
        self.assertEqual((c25["nights"], c25["sea_days"], c26["nights"], c26["sea_days"]), (3, 2, 2, 2))
        self.assertEqual((c25["count"], c26["count"], self.stats(self.jane, year=2024)["cruises"]["count"]), (1, 1, 0))

    def test_a_cancelled_a_future_and_an_unfinished_cruise_do_not_count(self):
        self.mine(CRUISE, {**CRUISE, "confirmation": "X", "start_local": "2026-04-01T16:30", "end_local": "2026-04-08T07:00", "itinerary": []})
        cancelled = self.add(self.jane, {**CRUISE, "confirmation": "Y", "start_local": "2026-05-01T16:30", "end_local": "2026-05-08T07:00",
                                         "itinerary": []}, travelers=self.on(self.jane.person_id))
        trips.edit_segment(self.c, self.jane, cancelled["id"], {"status": "cancelled"})
        before_it_ends = stats.compute(self.c, self.jane, None, None, datetime(2026, 3, 8, 6, 0, tzinfo=UTC))
        assert before_it_ends
        self.assertEqual(before_it_ends["cruises"]["count"], 0)
        self.assertEqual(self.stats(self.jane, now=datetime(2026, 9, 23, 12, 0, tzinfo=UTC))["cruises"]["count"], 3 - 1)

    def test_a_cruise_only_another_member_is_on_stays_out_of_a_partners_stats(self):
        self.add(self.sam, CRUISE, travelers=self.on(self.sam.person_id))
        self.assertEqual(self.stats(self.jane)["cruises"]["count"], 0)
        self.assertEqual(self.stats(self.sam)["cruises"]["count"], 1)


class VisibilityTests(StatsCase):
    def test_the_household_as_one_user_sees_leaves_out_a_trip_only_another_user_is_on(self):
        self.mine(JFK_LHR)                       # Jane's
        self.mine(AKL_LAX, who=self.sam)         # Sam's own: Jane isn't on it
        self.assertEqual(self.stats(self.jane)["flights"]["count"], 1)
        self.assertEqual(self.stats(self.sam)["flights"]["count"], 1)
        self.assertEqual(self.stats(Viewer(None, household=True))["flights"]["count"], 2)
        self.assertEqual(self.stats(Viewer(self.mia))["flights"]["count"], 0)

    def test_a_partner_sees_the_stats_of_a_person_without_their_solo_trips(self):
        self.add(self.jane, JFK_LHR, travelers=self.on(self.jane.person_id, self.sam.person_id))   # together
        self.add(self.jane, AKL_LAX, travelers=self.on(self.jane.person_id))                        # Jane alone
        self.assertEqual(self.stats(self.jane, self.jane.person_id)["flights"]["count"], 2)
        self.assertEqual(self.stats(self.sam, self.jane.person_id)["flights"]["count"], 1)

    def test_a_person_s_stats_include_a_trip_they_are_on_with_a_guest(self):
        self.add(self.jane, JFK_LHR, travelers=self.on(self.jane.person_id, self.mia))
        self.add(self.jane, AKL_LAX, travelers=self.on(self.jane.person_id))
        self.assertEqual(self.stats(self.jane, self.mia)["flights"]["count"], 1)
        self.assertEqual(self.stats(self.jane, self.jane.person_id)["flights"]["count"], 2)
        self.assertEqual(self.stats(self.jane, self.joan)["flights"]["count"], 0)
        self.assertEqual(self.stats(self.sam, self.mia)["flights"]["count"], 0)   # a trip Sam isn't on stays out of his view

    def test_the_household_counts_a_segment_once_however_many_are_on_it(self):
        self.add(self.jane, JFK_LHR, travelers=self.on(self.jane.person_id, self.mia, self.joan))
        self.assertEqual(self.stats(self.jane)["flights"]["count"], 1)

    def test_a_person_who_does_not_exist(self):
        self.assertIsNone(stats.compute(self.c, self.jane, 99999, None, NOW))


class AirlineDataTests(DbCase):
    def test_the_seeded_airlines(self):
        self.assertEqual(self.c.orm.get(Airline, "NZ").name, "Air New Zealand")
        self.assertEqual(self.c.orm.get(Airline, "BA").icao, "BAW")
        self.assertIsNone(self.c.orm.get(Airline, "6X"))
        self.assertGreater(len(self.c.orm.scalars(select(Airline)).all()), 900)

    def test_the_tool_keeps_the_active_airline_for_a_shared_code(self):
        import tempfile
        from tools import airlines
        dat = ('1,"Old Air",\\N,"XA","OLD","OLD","Nowhere","N"\n2,"Live Air",\\N,"XA","LIV","LIVE","Nowhere","Y"\n'
               '3,"No Code",\\N,"","NOC","NC","Nowhere","Y"\n4,"Unknown",\\N,"-","N/A",\\N,\\N,"Y"\n'
               '5,"Short",\\N,"XB","\\N",\\N,\\N,"Y"\n6,"Too\nShort",\\N\n')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "airlines.dat"
            path.write_text(dat, encoding="utf-8")
            self.assertEqual(airlines.rows(path), [("XA", "LIV", "Live Air", "Nowhere"), ("XB", "", "Short", "")])

    def test_the_shipped_file_is_what_the_tool_writes(self):
        with gzip.open(Path(__file__).resolve().parent.parent / "waypoint/storage/airlines.tsv.gz", "rt", encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines, sorted(lines))
        self.assertTrue(all(len(line.split("\t")) == 4 for line in lines))


class RouteTests(Household):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, api, "viewer", api.viewer)
        api.viewer = lambda conn: self.jane

    def call(self, **q):
        return api.api_stats(self.c, {k: [v] for k, v in q.items()}, {})

    def test_defaults_are_everyone_and_always_and_miles(self):
        self.add(self.jane, JFK_LHR, travelers=self.on(self.jane.person_id))
        got = self.call()
        self.assertEqual((got["person"], got["year"], got["distance_unit"], got["flights"]["count"]), (None, None, "mi", 1))
        db.set_setting(self.c, sk.DISTANCE_UNIT, "km")
        self.assertEqual(self.call(person=str(self.jane.person_id), year="2026")["distance_unit"], "km")
        self.assertEqual(self.call(year="2025")["flights"]["count"], 0)

    def test_the_distance_unit_is_miles_until_the_household_chooses(self):
        self.assertEqual(api.api_distance_unit(self.c, {}, {}), {"distance_unit": "mi"})
        self.assertEqual(api.api_distance_unit_save(self.c, {}, {"distance_unit": "km"}), {"distance_unit": "km"})
        self.assertEqual(api.api_distance_unit(self.c, {}, {}), {"distance_unit": "km"})
        for body in ({}, {"distance_unit": "furlongs"}, {"distance_unit": 5}):
            with self.subTest(body=body), self.assertRaises(ApiError):
                api.api_distance_unit_save(self.c, {}, body)
        self.assertEqual(api.api_distance_unit(self.c, {}, {})["distance_unit"], "km")

    def test_the_years_are_those_with_something_finished_whichever_year_is_asked_about(self):
        on = self.on(self.jane.person_id)
        self.add(self.jane, JFK_LHR, travelers=on)
        self.add(self.jane, {**LHR_JFK, "start_local": "2025-06-08T11:00", "end_local": "2025-06-08T14:05"}, travelers=on)
        self.add(self.jane, {**HOTEL, "start_local": "2024-12-30T15:00", "end_local": "2025-01-02T10:00"}, travelers=on)
        for q in ({}, {"year": "2026"}, {"year": "2030"}):
            with self.subTest(q=q):
                self.assertEqual(self.call(**q)["years"], [2026, 2025, 2024])

    def test_what_isnt_a_person_or_a_year_is_refused(self):
        for q in ({"person": "jane"}, {"person": "-1"}, {"person": "1" * 12}, {"year": "last"}, {"year": "20"}, {"year": "99999"}):
            with self.subTest(q=q), self.assertRaises(ApiError) as e:
                self.call(**q)
            self.assertEqual(e.exception.status, 400)
        with self.assertRaises(ApiError) as e:
            self.call(person="99999")
        self.assertEqual(e.exception.status, 404)


class StatsRouteTests(test_trips.RouteCase):
    """GET /api/stats over HTTP, with sign-in: whose trips it adds up, and what it refuses."""

    def test_stats_count_only_the_trips_the_viewer_can_see(self):
        ana, ben = self.person["ana"], self.person["ben"]
        self.book("ana", JFK_LHR, travelers=[{"person_id": ana}, {"person_id": ben}])
        self.book("ana", AKL_LAX, travelers=[{"person_id": ana}])   # Ana alone
        self.book("cy", LHR_JFK, travelers=[{"person_id": self.person["cy"]}])
        self.assertEqual(self.ok("ana", "GET", f"/api/stats?person={ana}&year=2026")["flights"]["count"], 2)
        self.assertEqual(self.ok("ben", "GET", f"/api/stats?person={ana}&year=2026")["flights"]["count"], 1)   # not her solo trip
        self.assertEqual(self.ok("ben", "GET", "/api/stats?person=all")["flights"]["count"], 1)
        self.assertEqual(self.ok("cy", "GET", "/api/stats")["flights"]["count"], 1)
        mine = self.ok("ana", "GET", "/api/stats?year=2025")
        self.assertEqual((mine["person"], mine["year"], mine["distance_unit"], mine["flights"]["count"]), (None, 2025, "mi", 0))

    def test_what_it_refuses(self):
        self.assertEqual(self.call("ana", "GET", "/api/stats?person=99999")[0], 404)
        self.assertEqual(self.call("ana", "GET", "/api/stats?year=soon")[0], 400)
        self.assertEqual(self.call("ana", "GET", "/api/stats?person=ana")[0], 400)


if __name__ == "__main__":
    unittest.main()
