"""What a scan matches a booking to: people by the name printed on it or by loyalty number, a time zone for a place with no
airport code, and what is kept encrypted about mail it couldn't read (names, codes and numbers here are made up)."""
import os
import unittest
from unittest import mock

from sqlalchemy import insert, select, update

from tests.shared import DbCase, add_database
from waypoint import oidc
from waypoint.domain import airports, loyalty, people
from waypoint.domain.mail import review
from waypoint.storage import backup, db, secretbox
from waypoint.storage.models import LoyaltyId, Mailbox, ReviewItem


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


class SubjectTests(DbCase):
    """The subject of mail that couldn't be read is kept encrypted, with the rest of a backup, and moves with the key."""
    SUBJECT = "Your itinerary CANARY-SUBJECT-KEEP-5J2M"

    def setUp(self):
        super().setUp()
        oidc.remember_user(self.c, "u-jane", "jane@example.com", "Jane Doe", None)
        self.box = self.c.execute(insert(Mailbox).values(owner_sub="u-jane", address="jane@gmail.example", token=secretbox.encrypt("t"),
                                                         status="connected", created=1.0)).lastrowid
        review.add(self.c, self.box, "m1", "example-air.example", self.SUBJECT, "2026-10-17", "no_markup", 1.0)
        review.add(self.c, self.box, "m2", "example-air.example", "", "2026-10-18", "broken", 1.0)   # no subject at all
        self.c.commit()

    def stored(self, c=None):
        return [r["subject"] for r in (c or self.c).execute(select(ReviewItem.subject).order_by(ReviewItem.message_id)).fetchall()]

    def test_it_is_stored_encrypted_and_a_missing_one_is_not(self):
        first, second = self.stored()
        self.assertTrue(secretbox.is_encrypted(first))
        self.assertNotIn("CANARY", first)
        self.assertIsNone(second)

    def test_asking_again_for_the_same_message_changes_nothing(self):
        review.add(self.c, self.box, "m1", "other.example", "A different subject", "2026-01-01", "incomplete", 2.0)
        self.assertEqual(len(self.stored()), 2)
        self.assertEqual({i["subject"] for i in review.listing(self.c, "u-jane")}, {self.SUBJECT, ""})

    def test_a_backup_holds_it_encrypted_and_restores_it(self):
        raw = backup.dump(self.c)
        self.assertNotIn(b"CANARY-SUBJECT-KEEP", raw)
        import gzip
        self.assertNotIn(b"CANARY-SUBJECT-KEEP", gzip.decompress(raw))
        other = add_database(self, os.path.join(os.path.dirname(self.path), "restored.db"))
        with db.session(other) as c2:
            backup.restore(c2, backup.load(raw))
        with db.session(other) as c2:
            self.assertEqual({i["subject"] for i in review.listing(c2, "u-jane")}, {self.SUBJECT, ""})

    def test_it_moves_to_a_new_key_with_the_rest_of_the_secrets(self):
        old = os.environ.get("WAYPOINT_SECRET_KEY", "")
        new = "a-brand-new-key-abcdefghijklmnopqrstuvwxyz"
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": new, **({"WAYPOINT_SECRET_KEY_OLD": old} if old else {})}):
            self.assertGreaterEqual(secretbox.encrypt_stored(self.c), 1)
            self.assertEqual(secretbox.encrypt_stored(self.c), 0)
        self.c.commit()
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": new}):
            self.assertEqual({i["subject"] for i in review.listing(self.c, "u-jane")}, {self.SUBJECT, ""})

    def test_one_it_cannot_unlock_is_left_alone_at_start(self):
        self.c.execute(update(ReviewItem).where(ReviewItem.message_id == "m1").values(subject=secretbox.PREFIX + "bad"))
        secretbox.encrypt_stored(self.c)
        self.assertEqual(self.stored()[0], secretbox.PREFIX + "bad")
        self.assertIsNone(next(i for i in review.listing(self.c, "u-jane") if i["gmail_url"].endswith("m1"))["subject"])


if __name__ == "__main__":
    unittest.main()
