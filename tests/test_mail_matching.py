"""What a scan matches a booking to: people by the name printed on it or by loyalty number, a time zone for a place with no
airport code, (names, codes and numbers here are made up)."""
import unittest

from sqlalchemy import update

from tests.shared import DbCase
from waypoint.domain import airports, loyalty, people
from waypoint.domain.mail import extract, ingest
from waypoint.storage import secretbox
from waypoint.storage.models import LoyaltyId


def person(c, name, *aliases, legal=None):
    return people.add_guest(c, {"display_name": name, "first_name": None, "legal_name": legal, "aliases": list(aliases)})["id"]


class NameTests(DbCase):
    def test_a_printed_name_is_compared_without_case_titles_or_punctuation_and_first_name_first(self):
        for printed in ("DOE/JANE MS", "Jane Doe", "doe/jane", "Ms. Jane Doe", "JANE  DOE MRS", "Doe, Jane"):
            with self.subTest(printed=printed):
                self.assertEqual(people.normalize(printed), "jane doe" if "," not in printed else "doe jane")
        self.assertEqual(people.normalize("O’HARE/JOAN MRS"), "joan o hare")
        self.assertEqual(people.normalize("MR"), "")

    def test_a_name_matches_the_display_name_legal_name_or_an_alias(self):
        jane = person(self.c, "Jane Doe")
        mia = person(self.c, "Mia", "DOE/MIAROSE MISS", legal="Mia Rose Doe")
        self.assertEqual(people.match_name(self.c, "DOE/JANE MS"), jane)
        self.assertEqual(people.match_name(self.c, "Rose Mia Doe"), None)   # (the words must be the same, in the same order)
        self.assertEqual(people.match_name(self.c, "MIA ROSE DOE MISS"), mia)   # the legal name
        self.assertEqual(people.match_name(self.c, "DOE/MIAROSE MISS"), mia)    # an alias
        self.assertIsNone(people.match_name(self.c, "DOE/SAM MR"))
        self.assertIsNone(people.match_name(self.c, ""))
        self.assertIsNone(people.match_name(self.c, "MR"))

    def test_a_name_two_people_share_matches_neither(self):
        person(self.c, "Alex Rivera")
        person(self.c, "Alexandra", "RIVERA/ALEX MR")
        self.assertIsNone(people.match_name(self.c, "RIVERA/ALEX MR"))

    def test_adding_an_alias_keeps_what_was_there_and_skips_one_that_already_matches(self):
        mia = person(self.c, "Mia Rose Doe", "DOE/MIA MISS")
        people.add_alias(self.c, mia, "DOE/MIAROSE MISS")
        people.add_alias(self.c, mia, "DOE/MIA MISS")          # already matches: nothing to add
        people.add_alias(self.c, mia, "Mia Rose Doe")          # so does the display name
        people.add_alias(self.c, mia, "   ")                   # nothing to add
        people.add_alias(self.c, 9999, "DOE/NOBODY MR")        # no such person
        self.assertEqual(people.get(self.c, mia)["aliases"], ["DOE/MIA MISS", "DOE/MIAROSE MISS"])


class LoyaltyMatchTests(DbCase):
    def add(self, who, number):
        loyalty.add(self.c, {"person_id": who, "kind": "airline", "program": "Other", "number": number, "tier": None, "expiry": None,
                             "notes": None})

    def test_a_number_finds_its_person_however_it_is_printed(self):
        jane = person(self.c, "Jane Doe")
        self.add(jane, "FXLOY-4400123")
        for printed in ("FXLOY-4400123", "fxloy 4400123", " FXLOY4400123 "):
            with self.subTest(printed=printed):
                self.assertEqual(loyalty.person_for_number(self.c, printed), jane)
        self.assertIsNone(loyalty.person_for_number(self.c, "FXLOY-4400124"))
        self.assertIsNone(loyalty.person_for_number(self.c, "  "))

    def test_a_number_on_two_people_matches_neither_and_one_on_two_programs_of_one_person_still_matches(self):
        jane, sam = person(self.c, "Jane Doe"), person(self.c, "Sam Doe")
        self.add(jane, "SHARED-1")
        self.add(sam, "SHARED-1")
        self.assertIsNone(loyalty.person_for_number(self.c, "SHARED-1"))
        self.add(jane, "OWN-9")
        self.add(jane, "own-9")
        self.assertEqual(loyalty.person_for_number(self.c, "OWN-9"), jane)

    def test_a_number_this_key_cannot_unlock_matches_no_one(self):
        jane = person(self.c, "Jane Doe")
        self.add(jane, "FXLOY-4400123")
        self.c.execute(update(LoyaltyId).values(number=secretbox.PREFIX + "bad"))
        self.assertIsNone(loyalty.person_for_number(self.c, "FXLOY-4400123"))


class PlaceZoneTests(DbCase):
    def test_a_city_the_airports_know_gives_its_zone_in_the_country_the_booking_names(self):
        self.assertEqual(airports.zone_for_place(self.c, "London", "GB"), "Europe/London")
        self.assertEqual(airports.zone_for_place(self.c, " paris ", "fr"), "Europe/Paris")
        self.assertEqual(airports.zone_for_place(self.c, "Auckland", None), "Pacific/Auckland")

    def test_a_city_in_two_zones_without_a_country_is_not_guessed(self):
        self.assertIsNone(airports.zone_for_place(self.c, "London", None))   # London, England or London, Kentucky

    def test_a_country_with_one_zone_does_when_the_city_is_unknown(self):
        self.assertEqual(airports.zone_for_place(self.c, "Nowhereville", "GB"), "Europe/London")
        self.assertEqual(airports.zone_for_place(self.c, None, "GB"), "Europe/London")

    def test_a_country_with_several_zones_or_no_place_at_all_is_not_guessed(self):
        self.assertIsNone(airports.zone_for_place(self.c, "Nowhereville", "NZ"))   # the Chatham Islands have their own
        self.assertIsNone(airports.zone_for_place(self.c, "Nowhereville", "US"))
        self.assertIsNone(airports.zone_for_place(self.c, None, None))
        self.assertIsNone(airports.zone_for_place(self.c, "  ", ""))


class ExplainTests(DbCase):
    """Why a booking can't be a segment, from a fixed list of phrases (for the log)."""

    def booking(self, **kw):
        base = dict(kind="flight", status="confirmed", confirmation="ABC123", provider="Example Air", start="2026-11-20T19:00:00-05:00",
                    end="2026-11-21T07:10:00+00:00", origin="JFK", destination="LHR")
        return extract.Booking(**{**base, **kw})

    def test_each_reason(self):
        self.assertEqual(ingest.explain(self.c, self.booking(origin="QQQ")), "unknown airport")
        self.assertEqual(ingest.explain(self.c, self.booking(kind="hotel", origin="Harbour Hotel", destination=None)),
                         "place's time zone unknown")
        self.assertEqual(ingest.explain(self.c, self.booking(start="tomorrow")), "time isn't a date and time")
        self.assertEqual(ingest.explain(self.c, self.booking(end="2026-11-20T10:00:00-05:00")), "rejected as a segment")


class TimesTests(DbCase):
    """A booking's times as wall-clock times at its places, whatever the sender's offsets: the clock as written, unless the
    sender evidently gave UTC (a flight that would otherwise take two hours across the Atlantic)."""

    booking = ExplainTests.booking

    def times(self, start, end, **kw):
        found = ingest.fields(self.c, self.booking(start=start, end=end, **kw))
        assert found is not None
        return found["start_local"], found["end_local"]

    def test_offsets_that_are_the_airports_own_change_nothing(self):
        self.assertEqual(self.times("2026-11-20T19:00:00-05:00", "2026-11-21T07:10:00+00:00"), ("2026-11-20T19:00:00", "2026-11-21T07:10:00"))

    def test_a_local_clock_marked_as_utc_is_kept_as_written(self):
        self.assertEqual(self.times("2026-11-20T19:00:00Z", "2026-11-21T07:10:00Z"), ("2026-11-20T19:00:00", "2026-11-21T07:10:00"))
        self.assertEqual(self.times("2026-11-20T19:00:00+00:00", "2026-11-21T07:10:00+00:00"), ("2026-11-20T19:00:00", "2026-11-21T07:10:00"))

    def test_times_that_are_really_utc_are_moved_to_the_airports_clocks(self):
        # Written as a departure at midnight and an arrival at 07:10: only as UTC is that a believable flight (7 hours 10).
        self.assertEqual(self.times("2026-11-21T00:00:00Z", "2026-11-21T07:10:00Z"), ("2026-11-20T19:00:00", "2026-11-21T07:10:00"))

    def test_times_with_no_offset_are_as_written_and_so_are_a_stays_whatever_its_offsets(self):
        self.assertEqual(self.times("2026-11-20T19:00:00", "2026-11-21T07:10:00"), ("2026-11-20T19:00:00", "2026-11-21T07:10:00"))
        stay = ingest.fields(self.c, self.booking(kind="hotel", origin="Harbour Hotel", destination=None, start="2026-11-21T15:00:00Z",
                                                  end="2026-11-27T10:00:00Z", start_place=extract.Place("London", "GB"),
                                                  end_place=extract.Place("London", "GB")))
        assert stay is not None
        self.assertEqual((stay["start_local"], stay["end_local"]), ("2026-11-21T15:00:00", "2026-11-27T10:00:00"))


if __name__ == "__main__":
    unittest.main()
