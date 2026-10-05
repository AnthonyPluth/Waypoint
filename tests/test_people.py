"""People: members made at sign-in, guests added, edited and removed by any member, and the routes that do it."""
from sqlalchemy import func, select

from waypoint import oidc
from waypoint.domain import demo, people
from waypoint.server.api import people as api
from waypoint.server.common import ApiError
from waypoint.storage.models import Person, Segment, SegmentTraveler, Trip, User
from tests.shared import DbCase, ServerCase


def guest(**kw):
    return {"display_name": "Mia Doe", "first_name": "Mia", "legal_name": "Mia Rose Doe", "aliases": ["DOE/MIA MISS"], **kw}


class SignInTests(DbCase):
    def count(self):
        return self.c.orm.scalar(select(func.count()).select_from(Person))

    def test_signing_in_makes_the_member_once(self):
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe", "Jane", 100.0)
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe", "Jane", 200.0)
        self.assertEqual(self.count(), 1)
        [jane] = people.everyone(self.c)
        self.assertEqual((jane["display_name"], jane["first_name"], jane["member"]), ("Jane Doe", "Jane", True))

    def test_a_member_without_a_name_is_called_by_their_email_then_their_id(self):
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", None)
        oidc.remember_user(self.c, "u2", None, None)
        self.assertEqual([p["display_name"] for p in people.everyone(self.c)], ["jane.doe@example.com", "u2"])

    def test_a_later_sign_in_keeps_what_was_edited_since(self):
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe", "Jane", 100.0)
        [jane] = people.everyone(self.c)
        people.edit(self.c, jane["id"], {"display_name": "Janie", "first_name": None, "legal_name": "Jane Q Doe", "aliases": ["DOE/JANE MS"]})
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe", "Jane", 200.0)
        [after] = people.everyone(self.c)
        self.assertEqual((after["display_name"], after["legal_name"], after["aliases"]), ("Janie", "Jane Q Doe", ["DOE/JANE MS"]))

    def test_no_sub_makes_no_one(self):
        oidc.remember_user(self.c, None, "x@example.com", "X")
        self.assertEqual(self.count(), 0)


class PeopleTests(DbCase):
    def test_the_list_has_members_first_then_guests_by_name(self):
        people.add_guest(self.c, guest(display_name="zed"))
        people.add_guest(self.c, guest(display_name="Alma"))
        oidc.remember_user(self.c, "u1", "b@example.com", "Bo Example", "Bo")
        self.assertEqual([(p["display_name"], p["member"]) for p in people.everyone(self.c)],
                         [("Bo Example", True), ("Alma", False), ("zed", False)])

    def test_a_guest_is_added_edited_and_removed(self):
        added = people.add_guest(self.c, guest())
        self.assertEqual((added["member"], added["aliases"]), (False, ["DOE/MIA MISS"]))
        changed = people.edit(self.c, added["id"], guest(display_name="Mia D.", aliases=[]))
        assert changed
        self.assertEqual((changed["display_name"], changed["aliases"]), ("Mia D.", []))
        self.assertTrue(people.remove_guest(self.c, added["id"]))
        self.assertEqual(people.everyone(self.c), [])

    def test_editing_a_member_keeps_their_login(self):
        oidc.remember_user(self.c, "u1", "b@example.com", "Bo Example", "Bo")
        [bo] = people.everyone(self.c)
        people.edit(self.c, bo["id"], guest(display_name="Bobby"))
        row = self.c.orm.scalars(select(Person)).one()
        self.assertEqual((row.display_name, row.user_sub), ("Bobby", "u1"))

    def test_a_member_is_not_removed(self):
        oidc.remember_user(self.c, "u1", "b@example.com", "Bo Example", "Bo")
        [bo] = people.everyone(self.c)
        with self.assertRaises(people.MemberRemoval):
            people.remove_guest(self.c, bo["id"])
        self.assertEqual(len(people.everyone(self.c)), 1)

    def test_nobody_by_that_id(self):
        self.assertIsNone(people.edit(self.c, 999, guest()))
        self.assertFalse(people.remove_guest(self.c, 999))
        self.assertIsNone(people.get(self.c, 999))

    def test_aliases_that_are_not_a_list_of_texts_read_as_none(self):
        for raw in (None, "", "not json", '{"a": 1}', "7"):
            self.assertEqual(people.decode_aliases(raw), [])
        self.assertEqual(people.decode_aliases('["A", 3, "B"]'), ["A", "B"])

    def test_the_demo_household(self):
        added = demo.seed(self.c)
        shown = people.everyone(self.c)
        self.assertEqual(added, 2 + len(shown) + sum(self.c.orm.scalar(select(func.count()).select_from(m)) or 0
                                                       for m in (Trip, Segment, SegmentTraveler)))
        self.assertEqual([p["member"] for p in shown], [True, True, False, False])
        self.assertEqual(self.c.orm.scalar(select(func.count()).select_from(User)), 2)


class FieldTests(DbCase):
    def test_checks_and_trims_what_is_sent(self):
        got = api.fields({"display_name": "  Mia  ", "first_name": " ", "legal_name": None,
                          "aliases": [" DOE/MIA MISS ", "DOE/MIA MISS", "", "  "]})
        self.assertEqual(got, {"display_name": "Mia", "first_name": None, "legal_name": None, "aliases": ["DOE/MIA MISS"]})

    def test_refuses_what_cannot_be_read(self):
        for body, why in [({}, "Enter the name"), ({"display_name": " "}, "Enter the name"),
                          ({"display_name": "x" * 101}, "too long"),
                          ({"display_name": "A", "legal_name": "x" * 201}, "too long"),
                          ({"display_name": 5}, "as text"), ({"display_name": "A", "first_name": ["B"]}, "as text"),
                          ({"display_name": "A", "aliases": "DOE/A"}, "list of texts"),
                          ({"display_name": "A", "aliases": ["B", 3]}, "list of texts"),
                          ({"display_name": "A", "aliases": [f"A{i}" for i in range(21)]}, "at most 20"),
                          ({"display_name": "A", "aliases": ["x" * 101]}, "too long")]:
            with self.subTest(body=str(body)[:40]), self.assertRaisesRegex(ApiError, why):
                api.fields(body)


class PeopleRouteTests(ServerCase):
    """The routes, as the web app calls them (running without sign-in, so everyone is the local household)."""

    def test_add_edit_list_and_remove_a_guest(self):
        status, added = self.req("POST", "/api/people", {"display_name": "Joan O’Hare 🐶", "aliases": ["OHARE/JOAN MRS"]})
        self.assertEqual(status, 200)
        self.assertEqual((added["member"], added["legal_name"], added["aliases"]), (False, None, ["OHARE/JOAN MRS"]))
        status, edited = self.req("POST", f"/api/people/{added['id']}", {"display_name": "Joan", "legal_name": "Joan Marie O’Hare"})
        self.assertEqual((status, edited["display_name"], edited["legal_name"], edited["aliases"]), (200, "Joan", "Joan Marie O’Hare", []))
        status, listing = self.req("GET", "/api/people")
        self.assertEqual(status, 200)
        self.assertIn(added["id"], [p["id"] for p in listing["people"]])   # (the class shares one database)
        self.assertEqual(self.req("DELETE", f"/api/people/{added['id']}"), (200, {"ok": True}))
        self.assertNotIn(added["id"], [p["id"] for p in self.req("GET", "/api/people")[1]["people"]])

    def test_what_cannot_be_done_says_so(self):
        self.assertEqual(self.req("POST", "/api/people", {"display_name": ""})[0], 400)
        for method in ("POST", "DELETE"):
            for who in ("999", "abc"):
                with self.subTest(method=method, who=who):
                    status, body = self.req(method, f"/api/people/{who}", {"display_name": "A"} if method == "POST" else None)
                    self.assertEqual((status, body["error"]), (404, "No such person"))

    def test_a_member_is_edited_but_not_removed(self):
        from waypoint.storage import db
        with db.session() as conn:
            oidc.remember_user(conn, "u-route", "ro@example.com", "Ro Example", "Ro")
        member = next(p for p in self.req("GET", "/api/people")[1]["people"] if p["member"])
        status, edited = self.req("POST", f"/api/people/{member['id']}", {"display_name": "Ro E."})
        self.assertEqual((status, edited["display_name"], edited["member"]), (200, "Ro E.", True))
        status, body = self.req("DELETE", f"/api/people/{member['id']}")
        self.assertEqual(status, 409)
        self.assertIn("can’t be removed", body["error"])
        self.assertTrue(any(p["id"] == member["id"] for p in self.req("GET", "/api/people")[1]["people"]))
