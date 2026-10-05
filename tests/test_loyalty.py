"""Loyalty and Known Traveler numbers: kept encrypted, listed masked, revealed one at a time, and never in a log, an error
reply or a table in the clear."""
import os
from unittest import mock

from sqlalchemy import select

from waypoint import oidc
from waypoint.domain import demo, loyalty, people
from waypoint.server.api import loyalty as api
from waypoint.server.common import ApiError
from waypoint.storage import db, secretbox
from waypoint.storage.models import LoyaltyId
from tests.privacy import no_leaks
from tests.shared import DbCase, ServerCase

CANARY = "CANARY-AAD-4417029X"   # a made-up membership number, one nothing else uses


def membership(person_id, **kw):
    return {"person_id": person_id, "kind": "airline", "program": "American AAdvantage", "number": "DEMO1234567",
            "tier": "Gold", "expiry": "2029-01-31", "notes": None, **kw}


def guest(c, name="Mia Doe"):
    return people.add_guest(c, {"display_name": name, "first_name": None, "legal_name": None, "aliases": []})["id"]


class StorageTests(DbCase):
    def test_the_number_is_encrypted_in_the_column(self):
        who = guest(self.c)
        added = loyalty.add(self.c, membership(who, number=CANARY))
        raw = self.c.execute(select(LoyaltyId.number).where(LoyaltyId.id == added["id"])).scalar()
        self.assertTrue(raw.startswith(secretbox.PREFIX))
        self.assertNotIn(CANARY, raw)
        self.assertEqual(secretbox.decrypt(raw), CANARY)

    def test_the_list_carries_the_last_four_only(self):
        who = guest(self.c)
        loyalty.add(self.c, membership(who, number=CANARY))
        loyalty.add(self.c, membership(who, kind="redress", program="DHS TRIP", number="12"))
        [a, b] = loyalty.everyone(self.c)
        self.assertEqual((a["masked"], a["readable"]), ("••••029X", True))
        self.assertEqual(b["masked"], "••••")   # too short to show any of it
        self.assertNotIn(CANARY, str(loyalty.everyone(self.c)))

    def test_the_list_is_by_person_then_kind_then_program(self):
        a, b = guest(self.c, "Ann"), guest(self.c, "Bo")
        loyalty.add(self.c, membership(b, kind="hotel", program="Marriott Bonvoy"))
        loyalty.add(self.c, membership(a, kind="known_traveler", program="TSA PreCheck"))
        loyalty.add(self.c, membership(a, program="United MileagePlus"))
        loyalty.add(self.c, membership(a, program="American AAdvantage"))
        self.assertEqual([(m["person_id"], m["program"]) for m in loyalty.everyone(self.c)],
                         [(a, "American AAdvantage"), (a, "United MileagePlus"), (a, "TSA PreCheck"), (b, "Marriott Bonvoy")])

    def test_reveal_gives_one_number_and_edit_keeps_it_unless_a_new_one_comes(self):
        who = guest(self.c)
        added = loyalty.add(self.c, membership(who, number="DEMO1234567"))
        kept = loyalty.edit(self.c, added["id"], membership(who, number=None, tier="Platinum"))
        assert kept
        self.assertEqual((kept["tier"], loyalty.reveal(self.c, added["id"])), ("Platinum", "DEMO1234567"))
        loyalty.edit(self.c, added["id"], membership(who, number="DEMO7654321"))
        self.assertEqual(loyalty.reveal(self.c, added["id"]), "DEMO7654321")

    def test_a_membership_without_a_number_is_refused(self):
        with self.assertRaises(ValueError):
            loyalty.add(self.c, membership(guest(self.c), number=None))

    def test_nothing_by_that_id_and_nobody_by_that_person(self):
        who = guest(self.c)
        self.assertIsNone(loyalty.reveal(self.c, 999))
        self.assertIsNone(loyalty.edit(self.c, 999, membership(who)))
        self.assertFalse(loyalty.remove(self.c, 999))
        with self.assertRaises(loyalty.NoSuchPerson):
            loyalty.add(self.c, membership(999))
        added = loyalty.add(self.c, membership(who))
        with self.assertRaises(loyalty.NoSuchPerson):
            loyalty.edit(self.c, added["id"], membership(999))

    def test_removing_a_guest_takes_their_memberships(self):
        who, other = guest(self.c), guest(self.c, "Bo")
        loyalty.add(self.c, membership(who))
        keep = loyalty.add(self.c, membership(other))
        people.remove_guest(self.c, who)
        self.assertEqual([m["id"] for m in loyalty.everyone(self.c)], [keep["id"]])

    def test_a_number_the_key_cannot_unlock_says_so(self):
        who = guest(self.c)
        added = loyalty.add(self.c, membership(who))
        other = secretbox.PREFIX + "gAAAAA-not-a-token-of-this-key"
        self.c.execute(LoyaltyId.__table__.update().where(LoyaltyId.id == added["id"]).values(number=other))
        self.c.orm.expire_all()
        [m] = loyalty.everyone(self.c)
        self.assertEqual((m["masked"], m["readable"]), ("••••", False))
        with self.assertRaises(loyalty.Unreadable):
            loyalty.reveal(self.c, added["id"])

    def test_the_demo_household_has_memberships(self):
        demo.seed(self.c)
        found = loyalty.everyone(self.c)
        self.assertEqual(len(found), len(demo.MEMBERSHIPS))
        self.assertTrue(all(m["readable"] for m in found))


class PrivacyTests(DbCase):
    """Saving, listing, revealing and a failed save, with a made-up number as the canary."""

    def test_the_number_is_never_logged_replied_with_or_stored_in_the_clear(self):
        who = guest(self.c)
        replies = []
        with no_leaks(self, CANARY, database=self.path):
            added = api.api_loyalty_add(self.c, {}, membership(who, number=CANARY))
            self.c.commit()
            replies += [added, api.api_loyalty(self.c, {}, {})]
            api.api_loyalty_edit(self.c, {}, membership(who, number=None, tier="Silver"), str(added["id"]))
            self.assertEqual(api.api_loyalty_reveal(self.c, {}, {}, str(added["id"])), {"number": CANARY})
            for bad in (membership(who, number=CANARY, kind="boat"), membership(who, number=CANARY, program="Nope"),
                        membership(who, number=CANARY + "x" * 70), membership(who, number=CANARY, expiry="soon"),
                        membership(999, number=CANARY)):
                with self.assertRaises(ApiError) as caught:
                    api.api_loyalty_add(self.c, {}, bad)
                replies.append(str(caught.exception))
            self.c.commit()
        self.assertNotIn(CANARY, str(replies))


class RouteTests(ServerCase):
    def setUp(self):
        self.database = os.path.join(os.environ["WAYPOINT_DATA"], "waypoint.db")
        _, self.guest = self.req("POST", "/api/people", {"display_name": "Joan O’Hare"})

    def save(self, **kw):
        return self.req("POST", "/api/loyalty", {"person_id": self.guest["id"], "kind": "hotel", "program": "Marriott Bonvoy",
                                                 "number": "DEMO55501234", **kw})

    def test_save_list_reveal_edit_and_remove(self):
        status, added = self.save(tier="Gold")
        self.assertEqual((status, added["masked"], added["tier"]), (200, "••••1234", "Gold"))
        self.assertNotIn("number", added)
        status, listing = self.req("GET", "/api/loyalty")
        self.assertEqual(status, 200)
        self.assertNotIn("DEMO55501234", str(listing))   # a page load carries no number
        self.assertIn("Marriott Bonvoy", listing["programs"]["hotel"])
        self.assertEqual(self.req("POST", f"/api/loyalty/{added['id']}/reveal"), (200, {"number": "DEMO55501234"}))
        status, edited = self.req("POST", f"/api/loyalty/{added['id']}",
                                  {"person_id": self.guest["id"], "kind": "hotel", "program": "Hilton Honors"})
        self.assertEqual((status, edited["program"], edited["masked"]), (200, "Hilton Honors", "••••1234"))
        self.assertEqual(self.req("DELETE", f"/api/loyalty/{added['id']}"), (200, {"ok": True}))
        self.assertNotIn(added["id"], [m["id"] for m in self.req("GET", "/api/loyalty")[1]["loyalty"]])

    def test_an_id_that_is_not_there_is_a_404(self):
        for who in ("999", "abc"):
            for method, tail, body in (("POST", "/reveal", None), ("DELETE", "", None),
                                       ("POST", "", {"person_id": self.guest["id"], "kind": "car", "program": "Other"})):
                with self.subTest(method=method, tail=tail, who=who):
                    status, reply = self.req(method, f"/api/loyalty/{who}{tail}", body)
                    self.assertEqual((status, reply["error"]), (404, "No such membership"))
        self.assertEqual(self.req("POST", "/api/loyalty", {"person_id": 999, "kind": "car", "program": "Other", "number": "1"})[0], 404)

    def test_what_cannot_be_read_is_a_400_that_never_quotes_the_number(self):
        for body in ({"kind": "boat"}, {"program": "Nope"}, {"program": ""}, {"person_id": "x"}, {"person_id": True},
                     {"number": ""}, {"number": 5}, {"number": "x" * 65}, {"expiry": "31/01/2029"}, {"tier": ["a"]},
                     {"notes": "x" * 501}, {"tier": "x" * 101}):
            with self.subTest(body=str(body)):
                status, reply = self.save(**body)
                self.assertEqual(status, 400)
                self.assertNotIn("DEMO55501234", reply["error"])

    def test_numbers_stay_out_of_logs_replies_and_tables_when_a_save_fails(self):
        with no_leaks(self, CANARY, database=self.database):
            self.assertEqual(self.save(number=CANARY)[0], 200)
            self.assertEqual(self.save(number=CANARY, kind="boat")[0], 400)
            self.req("GET", "/api/loyalty")
            with mock.patch.object(loyalty, "add", side_effect=RuntimeError(f"database error near {CANARY}")):
                status, reply = self.save(number=CANARY)
            self.assertEqual(status, 500)
            self.assertNotIn(CANARY, reply["error"])

    def test_a_number_the_key_cannot_unlock_is_a_409_to_reveal(self):
        status, added = self.save()
        with db.session() as c:
            c.execute(LoyaltyId.__table__.update().where(LoyaltyId.id == added["id"]).values(number=secretbox.PREFIX + "bad"))
        status, _ = self.req("POST", f"/api/loyalty/{added['id']}/reveal")
        self.assertEqual(status, 409)
        listed = next(m for m in self.req("GET", "/api/loyalty")[1]["loyalty"] if m["id"] == added["id"])
        self.assertFalse(listed["readable"])


class FieldTests(DbCase):
    def test_trims_and_keeps_what_is_sent(self):
        got = api.fields({"person_id": 3, "kind": "known_traveler", "program": " TSA PreCheck ", "number": " TT1234 ",
                          "tier": " ", "expiry": "2029-03-31", "notes": " renewed "}, need_number=True)
        self.assertEqual(got, {"person_id": 3, "kind": "known_traveler", "program": "TSA PreCheck", "number": "TT1234",
                               "tier": None, "expiry": "2029-03-31", "notes": "renewed"})

    def test_a_number_is_needed_to_save_but_not_to_change(self):
        body = {"person_id": 1, "kind": "car", "program": "Other"}
        self.assertIsNone(api.fields(body, need_number=False)["number"])
        with self.assertRaises(ApiError):
            api.fields(body, need_number=True)

    def test_every_kind_has_programs_ending_in_other(self):
        self.assertEqual(set(loyalty.PROGRAMS), set(loyalty.KINDS))
        self.assertTrue(all(p[-1] == loyalty.OTHER for p in loyalty.PROGRAMS.values()))


class SignInTests(DbCase):
    def test_a_member_can_hold_memberships(self):
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe", "Jane", 1.0)
        [jane] = people.everyone(self.c)
        loyalty.add(self.c, membership(jane["id"]))
        self.assertEqual(len(self.c.orm.scalars(select(LoyaltyId)).all()), 1)
