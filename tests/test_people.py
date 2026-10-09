from sqlalchemy import func, select

from waypoint import oidc
from waypoint.domain import demo, loyalty, people
from waypoint.server.api import people as api
from waypoint.server.common import ApiError, _current
from waypoint.storage.models import (FlightStatus, Person, Segment, SegmentMessage, SegmentPort, SegmentRecipient, SegmentTraveler, StoredMessage,
                                     Trip, User)
from tests.privacy import no_leaks
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
        self.assertEqual(added, 2 + len(shown) + len(demo.MEMBERSHIPS) + 2 + len(demo.UNREAD) + len(demo.SHARED_UNREAD) + 1
                         + sum(self.c.orm.scalar(select(func.count()).select_from(m)) or 0 for m in (Trip, Segment, SegmentPort, SegmentTraveler, FlightStatus,
                                                                                              StoredMessage, SegmentMessage)))
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

    def test_add_edit_list_and_remove_a_guest(self):
        status, added = self.req("POST", "/api/people", {"display_name": "Joan O’Hare 🐶", "aliases": ["OHARE/JOAN MRS"]})
        self.assertEqual(status, 200)
        self.assertEqual((added["member"], added["legal_name"], added["aliases"]), (False, None, ["OHARE/JOAN MRS"]))
        status, edited = self.req("POST", f"/api/people/{added['id']}", {"display_name": "Joan", "legal_name": "Joan Marie O’Hare"})
        self.assertEqual((status, edited["display_name"], edited["legal_name"], edited["aliases"]), (200, "Joan", "Joan Marie O’Hare", []))
        status, listing = self.req("GET", "/api/people")
        self.assertEqual(status, 200)
        self.assertIn(added["id"], [p["id"] for p in listing["people"]])
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


class ClaimTests(DbCase):

    def setUp(self):
        super().setUp()
        from waypoint.domain import trips
        from waypoint.domain.visibility import Viewer, visible_trips
        self.visible_trips, self.Viewer = visible_trips, Viewer
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe", "Jane", 100.0)
        self.member = people.person_for_sub(self.c, "u1")
        self.guest = people.add_guest(self.c, guest(display_name="J. Doe", first_name="Jane", legal_name="Jane Q Doe", aliases=["DOE/JANE MS"]))["id"]
        self.trip = Trip(name="Lisbon", auto=False, booked_by=self.guest)
        self.c.orm.add(self.trip)
        self.c.orm.flush()
        seg = Segment(trip_id=self.trip.id, kind="flight", status="confirmed", start_local="2026-11-01T08:00", start_zone="Europe/London",
                      end_local="2026-11-01T11:00", end_zone="Europe/Lisbon", source="manual", booked_by=self.guest)
        self.c.orm.add(seg)
        self.c.orm.flush()
        self.c.orm.add(SegmentTraveler(segment_id=seg.id, person_id=self.guest))
        self.c.orm.flush()
        self.trips = trips

    def test_a_member_who_claims_a_guest_sees_the_guests_trip(self):
        me = self.Viewer(self.member)
        self.assertEqual(self.visible_trips(self.c, me), [])
        people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertEqual([t.name for t in self.visible_trips(self.c, me)], ["Lisbon"])

    def test_the_guests_loyalty_ids_names_and_bookings_move_over_and_the_guest_is_gone(self):
        loyalty.add(self.c, {"person_id": self.guest, "kind": "airline", "program": "Delta SkyMiles", "number": "CANARY-DL-3381",
                             "expiry": None, "notes": None})
        claimed = people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertEqual([m["person_id"] for m in loyalty.everyone(self.c)], [self.member])
        self.assertEqual((claimed["display_name"], claimed["first_name"], claimed["legal_name"]), ("Jane Doe", "Jane", "Jane Q Doe"))
        self.assertEqual(claimed["aliases"], ["J. Doe"])
        self.assertEqual(claimed["links"], [{"guest": "J. Doe", "by": "Jane Doe", "on": "2026-10-05"}])
        self.assertIsNone(people.get(self.c, self.guest))
        self.c.orm.expire_all()
        self.assertEqual(self.trip.booked_by, self.member)
        self.assertEqual([s.booked_by for s in self.c.orm.scalars(select(Segment)).all()], [self.member])
        self.assertEqual([t.person_id for t in self.c.orm.scalars(select(SegmentTraveler)).all()], [self.member])
        self.assertEqual(people.match_name(self.c, "DOE/JANE MS"), self.member)

    def test_the_member_keeps_their_own_names_and_a_second_legal_name_becomes_an_alias(self):
        people.edit(self.c, self.member, {"display_name": "Janie", "first_name": None, "legal_name": "Jane Doe", "aliases": ["doe/jane"]})
        claimed = people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertEqual((claimed["display_name"], claimed["legal_name"]), ("Janie", "Jane Doe"))
        self.assertEqual((claimed["first_name"]), "Jane")
        self.assertEqual(claimed["aliases"], ["doe/jane", "Jane Q Doe", "J. Doe"])

    def test_someone_on_the_same_segment_is_not_added_twice(self):
        seg = self.c.orm.scalars(select(Segment)).one()
        self.c.orm.add(SegmentTraveler(segment_id=seg.id, person_id=self.member))
        self.c.orm.flush()
        people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertEqual([t.person_id for t in self.c.orm.scalars(select(SegmentTraveler)).all()], [self.member])

    def test_a_booking_the_guest_received_stays_visible_to_the_member(self):
        seg = self.c.orm.scalars(select(Segment)).one()
        other = Segment(trip_id=self.trip.id, kind="hotel", status="confirmed", start_local="2026-11-01T15:00", start_zone="Europe/Lisbon",
                        end_local="2026-11-03T11:00", end_zone="Europe/Lisbon", source="email")
        self.c.orm.add(other)
        self.c.orm.flush()
        self.c.orm.add_all([SegmentRecipient(segment_id=seg.id, person_id=self.guest), SegmentRecipient(segment_id=seg.id, person_id=self.member),
                            SegmentRecipient(segment_id=other.id, person_id=self.guest)])
        self.c.orm.flush()
        people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        found = sorted((r.segment_id, r.person_id) for r in self.c.orm.scalars(select(SegmentRecipient)).all())
        self.assertEqual(found, [(seg.id, self.member), (other.id, self.member)])

    def test_a_member_cannot_be_claimed_and_a_guest_cannot_claim(self):
        oidc.remember_user(self.c, "u2", "bo@example.com", "Bo Example", "Bo")
        other = people.person_for_sub(self.c, "u2")
        assert other
        with self.assertRaises(people.NotAGuest):
            people.claim_guest(self.c, self.member, other, "2026-10-05")
        with self.assertRaises(people.NotAMember):
            people.claim_guest(self.c, self.guest, self.guest, "2026-10-05")
        with self.assertRaises(people.NoSuchGuest):
            people.claim_guest(self.c, self.member, 999, "2026-10-05")
        self.assertIsNotNone(people.get(self.c, self.guest))

    def test_two_numbers_for_one_program_are_both_kept_and_flagged(self):
        for who, number in ((self.member, "CANARY-AA-1111"), (self.guest, "CANARY-AA-2222")):
            loyalty.add(self.c, {"person_id": who, "kind": "airline", "program": "American AAdvantage", "number": number,
                                 "expiry": None, "notes": None})
        loyalty.add(self.c, {"person_id": self.guest, "kind": "hotel", "program": "Hilton Honors", "number": "CANARY-HH-3333",
                             "expiry": None, "notes": None})
        self.assertEqual(loyalty.conflicts(self.c), [])
        people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertEqual(len(loyalty.everyone(self.c)), 3)
        self.assertEqual(loyalty.conflicts(self.c), [{"person_id": self.member, "kind": "airline", "program": "American AAdvantage"}])

    def test_the_same_number_twice_is_not_a_conflict(self):
        for who in (self.member, self.guest):
            loyalty.add(self.c, {"person_id": who, "kind": "airline", "program": "Delta SkyMiles", "number": "CANARY-DL 4444",
                                 "expiry": None, "notes": None})
        people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
        self.assertEqual(loyalty.conflicts(self.c), [])

    def test_the_merge_writes_no_loyalty_number_anywhere(self):
        number = "CANARY-AAD-9034172"
        loyalty.add(self.c, {"person_id": self.guest, "kind": "airline", "program": "Delta SkyMiles", "number": number,
                             "expiry": None, "notes": None})
        self.c.commit()
        with no_leaks(self, number, database=self.path):
            people.claim_guest(self.c, self.member, self.guest, "2026-10-05")
            self.c.commit()
            loyalty.conflicts(self.c)


class SuggestionTests(DbCase):

    def setUp(self):
        super().setUp()
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe", "Jane", 100.0)
        self.member = people.person_for_sub(self.c, "u1")
        assert self.member
        self.jane = people.add_guest(self.c, guest(display_name="Ms. J Doe", legal_name=None, aliases=["DOE/JANE MS"]))["id"]
        self.legal = people.add_guest(self.c, guest(display_name="Janie", legal_name="Jane Doe", aliases=[]))["id"]
        people.add_guest(self.c, guest(display_name="Mia Doe", aliases=[]))

    def ids(self, name="Jane Doe"):
        return [g["id"] for g in people.claim_suggestions(self.c, self.member, name)]

    def test_guests_whose_name_matches_the_sign_in_are_offered(self):
        self.assertEqual(self.ids(), [self.legal, self.jane])
        self.assertEqual(self.ids("DOE/JANE MRS"), [self.legal, self.jane])
        self.assertEqual(self.ids("Someone Else"), [])
        self.assertEqual(self.ids(""), [])
        self.assertEqual(people.claim_suggestions(self.c, self.member, None), [])

    def test_a_member_with_trips_is_not_offered_any(self):
        trip = Trip(name="Lisbon", auto=False, booked_by=self.member)
        self.c.orm.add(trip)
        self.c.orm.flush()
        self.assertEqual(self.ids(), [])

    def test_none_of_these_hides_it_for_that_member_only(self):
        oidc.remember_user(self.c, "u2", "jane2@example.com", "Jane Doe", "Jane", 100.0)
        other = people.person_for_sub(self.c, "u2")
        assert other
        people.dismiss_claims(self.c, self.member)
        self.assertEqual(self.ids(), [])
        self.assertEqual(len(people.claim_suggestions(self.c, other, "Jane Doe")), 2)

    def test_a_guest_is_never_offered_suggestions(self):
        self.assertEqual(people.claim_suggestions(self.c, self.jane, "Jane Doe"), [])
        people.dismiss_claims(self.c, self.jane)
        self.assertFalse(self.c.orm.get(Person, self.jane).claim_dismissed)   # type: ignore[union-attr]

    def test_a_member_is_preferred_over_a_guest_with_the_same_name(self):
        self.assertEqual(people.match_name(self.c, "DOE/JANE MS"), self.member)
        self.assertEqual(people.match_name(self.c, "Mia Doe"), self.c.orm.scalars(select(Person.id).where(Person.display_name == "Mia Doe")).one())

    def test_two_members_with_the_same_name_still_match_neither(self):
        oidc.remember_user(self.c, "u2", "jane2@example.com", "Jane Doe", "Jane", 100.0)
        self.assertIsNone(people.match_name(self.c, "DOE/JANE MS"))


class ClaimRouteTests(DbCase):

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, _current, "user", getattr(_current, "user", None))
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe", "Jane", 100.0)
        oidc.remember_user(self.c, "u2", "bo@example.com", "Bo Example", "Bo", 100.0)
        self.jane, self.bo = people.person_for_sub(self.c, "u1"), people.person_for_sub(self.c, "u2")
        self.guest = people.add_guest(self.c, guest(display_name="Jane D", legal_name=None, aliases=[]))["id"]

    def sign_in(self, sub="u1", name="Jane Doe"):
        _current.user = {"sub": sub, "name": name, "email": "x@example.com"}

    def test_a_member_claims_a_guest_for_themselves(self):
        self.sign_in()
        done = api.api_person_claim(self.c, {}, {}, str(self.guest))
        self.assertEqual((done["id"], done["links"][0]["guest"]), (self.jane, "Jane D"))
        self.assertIsNone(people.get(self.c, self.guest))

    def test_the_request_cannot_name_another_member_to_link_to(self):
        self.sign_in("u2", "Bo Example")
        api.api_person_claim(self.c, {}, {"person_id": self.jane, "member": self.jane}, str(self.guest))
        self.assertEqual(people.get(self.c, self.bo)["links"][0]["guest"], "Jane D")   # type: ignore[index]
        self.assertEqual(people.get(self.c, self.jane)["links"], [])   # type: ignore[index]

    def test_a_member_cannot_be_claimed_and_nobody_by_that_id_is_a_404(self):
        self.sign_in()
        for target, status in ((self.bo, 409), (999, 404), ("abc", 404)):
            with self.subTest(target=target), self.assertRaises(ApiError) as caught:
                api.api_person_claim(self.c, {}, {}, str(target))
            self.assertEqual(caught.exception.status, status)
        self.assertIsNotNone(people.get(self.c, self.guest))

    def test_without_a_person_of_their_own_nothing_is_claimed(self):
        for user in ({"name": None, "email": None, "local": True}, {"sub": "nobody", "name": "Jane Doe"}, None):
            _current.user = user
            with self.subTest(user=user), self.assertRaises(ApiError) as caught:
                api.api_person_claim(self.c, {}, {}, str(self.guest))
            self.assertEqual(caught.exception.status, 403)
            self.assertEqual(api.api_claim_suggestions(self.c, {}, {}), {"guests": []})
            self.assertEqual(api.api_claim_dismiss(self.c, {}, {}), {"ok": True})
        self.assertIsNotNone(people.get(self.c, self.guest))

    def test_the_suggestion_comes_from_the_sign_in_name_and_none_of_these_hides_it(self):
        self.sign_in()
        self.assertEqual([g["id"] for g in api.api_claim_suggestions(self.c, {}, {})["guests"]], [])
        people.add_guest(self.c, guest(display_name="Jane Doe", aliases=[]))
        self.assertEqual([g["display_name"] for g in api.api_claim_suggestions(self.c, {}, {})["guests"]], ["Jane Doe"])
        self.assertEqual(api.api_claim_dismiss(self.c, {}, {}), {"ok": True})
        self.assertEqual(api.api_claim_suggestions(self.c, {}, {})["guests"], [])
        self.sign_in("u2", "Bo Example")
        self.assertEqual(api.api_claim_suggestions(self.c, {}, {})["guests"], [])
