from datetime import UTC, datetime

from sqlalchemy import func, select

from waypoint.domain import calendar, stats, trips
from waypoint.storage.models import Segment, Trip
from tests.test_trips import Household

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def visit(country, first, last):
    return {"kind": "visit", "destination": country, "start_local": f"{first}T00:00", "end_local": f"{last}T00:00"}


class Rows(Household):
    def add_all(self, *rows, who=None):
        who = who or self.jane
        first = self.add(who, rows[0], travelers=self.on(who.person_id))
        for row in rows[1:]:
            self.add(who, row, trip_id=first["trip_id"], travelers=self.on(who.person_id))
        return trips.get(self.c, who, first["trip_id"])


class MultiCountryTripTests(Rows):
    def test_three_countries_make_one_trip_with_three_visits_and_their_own_dates(self):
        trip = self.add_all(visit("es", "2008-06-01", "2008-06-05"), visit("fr", "2008-06-06", "2008-06-09"), visit("it", "2008-06-10", "2008-06-14"))
        self.assertEqual([(s["kind"], s["destination"], s["start_local"][:10], s["end_local"][:10]) for s in trip["segments"]],
                         [("visit", "ES", "2008-06-01", "2008-06-05"), ("visit", "FR", "2008-06-06", "2008-06-09"), ("visit", "IT", "2008-06-10", "2008-06-14")])
        self.assertEqual((trip["start_date"], trip["end_date"]), ("2008-06-01", "2008-06-14"))
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(Trip)), 1)

    def test_the_same_country_twice_and_overlapping_days_are_allowed(self):
        trip = self.add_all(visit("ec", "2005-03-01", "2005-03-10"), visit("pe", "2005-03-10", "2005-03-15"), visit("ec", "2005-03-14", "2005-03-20"))
        self.assertEqual([s["destination"] for s in trip["segments"]], ["EC", "PE", "EC"])
        self.assertEqual(trip["destination"], "Ecuador and Peru")

    def test_a_bad_row_is_refused_with_the_existing_wording_and_adds_nothing(self):
        first = self.add(self.jane, visit("ec", "2005-03-01", "2005-03-10"), travelers=self.on(self.jane.person_id))
        with self.assertRaisesRegex(trips.Invalid, "two-letter country code"):
            self.add(self.jane, visit("zz", "2005-03-11", "2005-03-12"), trip_id=first["trip_id"])
        with self.assertRaisesRegex(trips.Invalid, "ends before it starts"):
            self.add(self.jane, visit("pe", "2005-03-12", "2005-03-11"), trip_id=first["trip_id"])
        with self.assertRaises(trips.Invalid):
            self.add(self.jane, visit("zz", "2005-03-11", "2005-03-12"))
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(Segment)), 1)
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(Trip)), 1)

    def test_visits_are_named_for_their_countries_in_date_order(self):
        two = self.add_all(visit("pe", "2005-04-01", "2005-04-05"), visit("ec", "2005-03-20", "2005-03-31"))
        self.assertEqual((two["name"], two["destination"]), ("Trip to Ecuador and Peru (Mar 2005)", "Ecuador and Peru"))
        three = self.add_all(visit("es", "2008-06-01", "2008-06-05"), visit("fr", "2008-06-06", "2008-06-09"), visit("it", "2008-06-10", "2008-06-14"))
        self.assertEqual((three["name"], three["destination"]), ("Trip to Spain, France and Italy (Jun 2008)", "Spain, France and Italy"))
        five = self.add_all(visit("es", "2009-06-01", "2009-06-05"), visit("fr", "2009-06-06", "2009-06-09"), visit("it", "2009-06-10", "2009-06-14"),
                            visit("de", "2009-06-15", "2009-06-17"), visit("at", "2009-06-18", "2009-06-20"))
        self.assertEqual((five["name"], five["destination"]),
                         ("Trip to Spain, France, Italy and 2 more (Jun 2009)", "Spain, France, Italy and 2 more"))

    def test_the_same_country_twice_is_named_once(self):
        trip = self.add_all(visit("ec", "2005-03-01", "2005-03-05"), visit("ec", "2005-03-10", "2005-03-15"))
        self.assertEqual((trip["name"], trip["destination"]), ("Trip to Ecuador (Mar 2005)", "Ecuador"))

    def test_a_name_the_person_set_is_kept_when_a_country_is_added(self):
        first = self.add(self.jane, visit("ec", "2005-03-01", "2005-03-10"), travelers=self.on(self.jane.person_id))
        trips.edit_trip(self.c, self.jane, first["trip_id"], {"name": "Gap year"})
        self.add(self.jane, visit("pe", "2005-03-11", "2005-03-20"), trip_id=first["trip_id"], travelers=self.on(self.jane.person_id))
        got = trips.get(self.c, self.jane, first["trip_id"])
        self.assertEqual((got["name"], got["destination"]), ("Gap year", "Ecuador and Peru"))

    def test_a_destination_the_person_set_is_kept_when_a_country_is_added(self):
        first = self.add(self.jane, visit("ec", "2005-03-01", "2005-03-10"), travelers=self.on(self.jane.person_id))
        trips.edit_trip(self.c, self.jane, first["trip_id"], {"destination": "South America"})
        self.add(self.jane, visit("pe", "2005-03-11", "2005-03-20"), trip_id=first["trip_id"], travelers=self.on(self.jane.person_id))
        self.assertEqual(trips.get(self.c, self.jane, first["trip_id"])["destination"], "South America")

    def test_an_automatic_name_follows_the_countries_added_to_the_trip(self):
        first = self.add(self.jane, visit("ec", "2005-03-01", "2005-03-10"), travelers=self.on(self.jane.person_id))
        self.add(self.jane, visit("pe", "2005-03-11", "2005-03-20"), trip_id=first["trip_id"], travelers=self.on(self.jane.person_id))
        self.assertEqual(trips.get(self.c, self.jane, first["trip_id"])["name"], "Trip to Ecuador and Peru (Mar 2005)")
        self.add(self.jane, visit("bo", "2005-02-20", "2005-02-28"), trip_id=first["trip_id"], travelers=self.on(self.jane.person_id))
        self.assertEqual(trips.get(self.c, self.jane, first["trip_id"])["name"], "Trip to Bolivia, Ecuador and Peru (Feb 2005)")

    def test_a_flight_in_the_trip_keeps_the_trips_own_wording(self):
        first = self.add(self.jane, visit("ec", "2005-03-01", "2005-03-10"), travelers=self.on(self.jane.person_id))
        self.add(self.jane, {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2005-03-11T19:00", "end_local": "2005-03-12T07:10"},
                 trip_id=first["trip_id"], travelers=self.on(self.jane.person_id))
        self.assertEqual(trips.get(self.c, self.jane, first["trip_id"])["name"], "Trip to Ecuador (Mar 2005)")


class MultiCountryStatsTests(Rows):
    def stats(self, year=None):
        got = stats.compute(self.c, self.jane, None, year, NOW)
        assert got is not None
        return got

    def test_each_country_counts_once_per_trip_and_each_has_a_map_point(self):
        self.add_all(visit("ec", "2005-03-01", "2005-03-05"), visit("pe", "2005-03-06", "2005-03-09"), visit("ec", "2005-03-20", "2005-03-25"))
        places = self.stats()["places"]
        self.assertEqual([(c["name"], c["first_visit"], c["visits"]) for c in places["countries"]], [("EC", "2005-03-01", 1), ("PE", "2005-03-06", 1)])
        self.assertEqual([v["country"] for v in places["visits"]], ["EC", "PE"])

    def test_the_same_country_in_two_trips_is_two_visits(self):
        self.add_all(visit("ec", "2005-03-01", "2005-03-05"), visit("pe", "2005-03-06", "2005-03-09"))
        self.add_all(visit("ec", "2007-01-01", "2007-01-05"))
        self.assertEqual({c["name"]: c["visits"] for c in self.stats()["places"]["countries"]}, {"EC": 2, "PE": 1})

    def test_every_visit_adds_its_years_and_the_year_filter_keeps_the_matching_ones(self):
        self.add_all(visit("ec", "2004-12-28", "2005-01-03"), visit("pe", "2006-02-01", "2006-02-05"))
        self.assertEqual(self.stats()["years"], [2006, 2005, 2004])
        self.assertEqual([c["name"] for c in self.stats(year=2006)["places"]["countries"]], ["PE"])
        self.assertEqual([c["name"] for c in self.stats(year=2005)["places"]["countries"]], ["EC"])

    def test_a_cancelled_visit_never_counts(self):
        first = self.add(self.jane, visit("ec", "2005-03-01", "2005-03-05"), travelers=self.on(self.jane.person_id))
        gone = self.add(self.jane, visit("pe", "2007-03-06", "2007-03-09"), trip_id=first["trip_id"], travelers=self.on(self.jane.person_id))
        trips.edit_segment(self.c, self.jane, gone["id"], {"status": "cancelled"})
        got = self.stats()
        self.assertEqual([c["name"] for c in got["places"]["countries"]], ["EC"])
        self.assertEqual(got["years"], [2005])

    def test_each_visit_is_its_own_calendar_event(self):
        self.add_all(visit("ec", "2005-03-01", "2005-03-05"), visit("pe", "2005-03-06", "2005-03-09"))
        feed = calendar.feed(trips.listing(self.c, self.jane), NOW)
        self.assertEqual(feed.count("BEGIN:VEVENT"), 2)
        self.assertIn("SUMMARY:Visit: Ecuador", feed)
        self.assertIn("SUMMARY:Visit: Peru", feed)
