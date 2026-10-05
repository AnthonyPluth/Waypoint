"""The MCP server's promises, against a real Waypoint with sign-in on and two members: an assistant sees exactly what its
approver sees (visibility, by every tool and by call_endpoint), full ID numbers come only with "ids:read" and its switch
(masking, with canary numbers over every read tool's output), changes need "write" and its switch, and nothing BLOCKED is
reachable. OAuth itself is tested in tests/test_mcp_oauth.py and tests/test_mcp_oauth_http.py, the protocol in
tests/test_mcp_protocol.py and the route list in tests/test_mcp_routes.py. Names, codes and numbers are made up."""
import base64
import hashlib
import json
import os
import unittest
from unittest import mock

from sqlalchemy import delete, func, select

from tests.privacy import no_leaks
from tests.shared import ServerCase, freeze_today
from waypoint import oidc
from waypoint.domain import loyalty, people, trips
from waypoint.domain.visibility import Viewer
from waypoint.server import mcp_access, mcp_http, mcp_oauth, mcp_server
from waypoint.storage import db
from waypoint.storage.models import OAuthGrant, Segment, Trip

VERIFIER = "v" * 50
CALLBACK = "http://127.0.0.1:1/cb"
JANE_NUMBER = "CANARY-JANE-48271936"     # made-up numbers, long enough that they can't match by chance
SAM_NUMBER = "CANARY-SAM-90417253"
READ = ("read",)
IDS = ("read", "ids:read")
WRITE = ("read", "write")
ALL = ("read", "ids:read", "write")
OUT = {"kind": "flight", "origin": "JFK", "destination": "LHR", "start_local": "2026-10-01T19:00",
       "end_local": "2026-10-02T07:10", "confirmation": "ZQ4PXD", "details": {"flight_number": "BA112"}}
HOTEL = {"kind": "hotel", "origin": "Harbour Hotel", "start_local": "2026-10-02T15:00", "end_local": "2026-10-08T10:00",
         "start_zone": "Europe/London", "end_zone": "Europe/London"}


def person(name: str) -> dict:
    return {"display_name": name, "first_name": None, "legal_name": None, "aliases": []}


class Assistants(ServerCase):
    """A real Waypoint with sign-in on and two members: Jane (with a London trip and a loyalty number) and Sam (with a Rome
    trip and a number). Nothing else writes to this database, but each test removes the grants it made and turns the switches
    off, so the tests don't depend on each other's order."""
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint",
           "OIDC_ALLOWED_EMAILS": "jane@example.com,sam@example.com"}
    unset = ("WAYPOINT_PUBLIC_URL",)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        freeze_today(cls)
        with db.session() as conn:
            for sub, name in (("u-jane", "Jane Doe"), ("u-sam", "Sam Doe")):
                oidc.remember_user(conn, sub, f"{sub[2:]}@example.com", name, None)
            cls.jane = Viewer(people.person_for_sub(conn, "u-jane"))
            cls.sam = Viewer(people.person_for_sub(conn, "u-sam"))
            cls.guest = people.add_guest(conn, person("Mia Doe"))["id"]
            cls.jane_trip = cls.book(conn, cls.jane, OUT, "London", cls.jane.person_id)
            cls.sam_trip = cls.book(conn, cls.sam, {**OUT, "origin": "JFK", "destination": "FCO", "confirmation": "SAMROM"},
                                    "Rome", cls.sam.person_id)
            for who, number in ((cls.jane, JANE_NUMBER), (cls.sam, SAM_NUMBER)):
                loyalty.add(conn, {"person_id": who.person_id, "kind": "airline", "program": "Delta SkyMiles", "number": number,
                                   "tier": None, "expiry": None, "notes": None})
            cls.jane_loyalty = conn.execute(select(loyalty.LoyaltyId.id).where(loyalty.LoyaltyId.person_id == cls.jane.person_id)).scalar()
            cls.sam_loyalty = conn.execute(select(loyalty.LoyaltyId.id).where(loyalty.LoyaltyId.person_id == cls.sam.person_id)).scalar()

    @staticmethod
    def book(conn, who: Viewer, segment: dict, name: str, traveller: int | None) -> dict:
        seg = trips.add_segment(conn, who, {**segment, "travelers": [{"person_id": traveller, "name": None}]}, None)
        assert seg is not None
        got = trips.edit_trip(conn, who, seg["trip_id"], {"name": name})
        assert got is not None
        return {"id": seg["trip_id"], "segment": seg["id"]}

    def setUp(self):
        self.path = os.path.join(os.environ["WAYPOINT_DATA"], "waypoint.db")   # (own_database's)
        self.addCleanup(self.forget)

    def forget(self):
        with db.session() as conn:
            conn.execute(delete(OAuthGrant))   # (cascades to their codes and tokens)
            mcp_access.set_allow_ids(conn, False)
            mcp_access.set_allow_writes(conn, False)

    def switch(self, ids: bool | None = None, writes: bool | None = None):
        with db.session() as conn:
            if ids is not None:
                mcp_access.set_allow_ids(conn, ids)
            if writes is not None:
                mcp_access.set_allow_writes(conn, writes)

    def access(self, scopes=READ, sub="u-jane") -> mcp_access.Access:
        """What a connection approved by `sub` for `scopes` may do, as mcp_http.local_fetch is given it."""
        return mcp_access.Access(frozenset(scopes), None, sub, f"{sub[2:]}@example.com")

    def make_token(self, *scopes, sub="u-jane", name="Claude") -> str:
        """An access token for this Waypoint's /mcp, as if an assistant had connected and `sub` had approved `scopes`."""
        with db.session() as conn:
            c = mcp_oauth.register(conn, {"client_name": name, "redirect_uris": [CALLBACK]})
            challenge = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
            params = {"client_id": c["client_id"], "redirect_uri": CALLBACK, "code_challenge": challenge, "resource": self.base + "/mcp"}
            code = mcp_oauth.approve(conn, params, frozenset(scopes or READ), sub, f"{sub[2:]}@example.com")
            out = mcp_oauth.token(conn, mcp_oauth.get_client(conn, c["client_id"]),
                                  {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK, "code_verifier": VERIFIER},
                                  self.base)
        return out["access_token"]

    def tool(self, scopes, name, args=None, sub="u-jane"):
        """A tool's result (parsed), or the ToolError's text, as the assistant sees it."""
        fetch = mcp_http.fetch_for(self.access(scopes, sub))
        try:
            return json.loads(mcp_server.call_tool(name, args or {}, fetch))
        except mcp_server.ToolError as e:
            return str(e)

    def refused(self, scopes, name, args=None, sub="u-jane") -> str:
        got = self.tool(scopes, name, args, sub)
        self.assertIsInstance(got, str, f"{name} wasn't refused")
        return got


class PagesTests(Assistants):
    """What mcp_http.local_fetch (the tools' way into Waypoint) reaches, as an assistant."""

    def test_reads_the_listed_pages_as_the_approver(self):
        for path in ("trips", "people", "loyalty", "stats", "distance-unit", "flight-status"):
            with self.subTest(page=path):
                mcp_http.local_fetch(path, {}, None, self.access())
        got = mcp_http.local_fetch("trips", {}, None, self.access())
        self.assertEqual([t["id"] for t in got["trips"]], [self.jane_trip["id"]])

    def test_no_read_scope_no_reading(self):
        with self.assertRaises(mcp_server.ToolError):
            mcp_http.local_fetch("trips", {}, None, self.access(()))

    def test_a_page_s_own_refusal_comes_through(self):
        with self.assertRaisesRegex(mcp_server.ToolError, "No such trip"):
            mcp_http.local_fetch(f"trips/{self.sam_trip['id']}", {}, None, self.access())

    def test_a_route_that_isnt_listed_isnt_there(self):
        for path in ("airports/JFK/x", "nothing", "access/../backup"):
            with self.subTest(path=path), self.assertRaises(mcp_server.ToolError):
                mcp_http.local_fetch(path, {}, None, self.access(ALL))

    def test_the_acting_person_is_forgotten_after_a_call(self):
        from waypoint.server.common import _current
        mcp_http.local_fetch("trips", {}, None, self.access())
        self.assertIsNone(_current.user)

    def test_without_sign_in_the_assistant_is_the_local_household(self):
        with mock.patch.object(oidc, "enabled", return_value=False):
            got = mcp_http.local_fetch("trips", {}, None, mcp_access.Access(frozenset(READ), None, None, None))
        self.assertEqual({t["id"] for t in got["trips"]}, {self.jane_trip["id"], self.sam_trip["id"]})

    def test_a_grant_with_no_member_sees_nothing_when_sign_in_is_on(self):
        got = mcp_http.local_fetch("trips", {}, None, mcp_access.Access(frozenset(READ), None, None, None))
        self.assertEqual(got["trips"], [])


class VisibilityTests(Assistants):
    """"You see the trips you're on": an assistant approved by Jane can't read or change a trip only Sam is on, by any tool or
    by call_endpoint, with every scope and switch on."""

    def setUp(self):
        super().setUp()
        self.switch(ids=True, writes=True)

    def sams(self):
        with db.session() as conn:
            return (conn.execute(select(func.count()).select_from(Trip)).scalar(),
                    conn.execute(select(Trip.name).where(Trip.id == self.sam_trip["id"])).scalar(),
                    conn.execute(select(Segment.confirmation).where(Segment.id == self.sam_trip["segment"])).scalar())

    def test_no_read_tool_shows_sams_trip(self):
        for name, args in (("list_trips", {}), ("upcoming", {"days": 365}), ("get_stats", {}), ("flight_status", {}),
                           ("get_trip", {"trip_id": self.jane_trip["id"]})):
            with self.subTest(tool=name):
                text = json.dumps(self.tool(ALL, name, args))
                self.assertNotIn("SAMROM", text)
                self.assertNotIn("Rome", text)
                self.assertNotIn("FCO", text)
        self.assertIn("ZQ4PXD", json.dumps(self.tool(ALL, "upcoming", {"days": 365})))   # (her own does show)

    def test_get_trip_for_sams_trip_is_not_found(self):
        self.assertEqual(self.refused(ALL, "get_trip", {"trip_id": self.sam_trip["id"]}), "No such trip")
        absent = self.refused(ALL, "get_trip", {"trip_id": 987654})
        self.assertEqual(absent, "No such trip")           # the same as one that doesn't exist

    def test_call_endpoint_cant_read_sams_trip_or_segment(self):
        for path in (f"/api/trips/{self.sam_trip['id']}", f"/api/segments/{self.sam_trip['segment']}"):
            with self.subTest(path=path):
                self.assertRegex(self.refused(ALL, "call_endpoint", {"method": "GET", "path": path}), "No such")

    def test_no_changing_tool_reaches_sams_trip(self):
        before = self.sams()
        t, s = self.sam_trip["id"], self.sam_trip["segment"]
        mine = self.jane_trip["id"]
        for name, args in (("update_trip", {"trip_id": t, "fields": {"name": "Hijacked"}}),
                           ("update_segment", {"segment_id": s, "fields": {"confirmation": "HIJACK"}}),
                           ("remove_segment", {"segment_id": s}),
                           ("add_segment", {"trip_id": t, "fields": HOTEL}),
                           ("merge_trips", {"trip_id": mine, "merge": t}),
                           ("merge_trips", {"trip_id": t, "merge": mine}),
                           ("call_endpoint", {"method": "POST", "path": f"/api/trips/{t}", "body": {"name": "Hijacked"}}),
                           ("call_endpoint", {"method": "POST", "path": f"/api/trips/{t}/split", "body": {"segment_ids": [s]}}),
                           ("call_endpoint", {"method": "POST", "path": f"/api/segments/{s}", "body": {"confirmation": "HIJACK"}}),
                           ("call_endpoint", {"method": "DELETE", "path": f"/api/trips/{t}"}),
                           ("call_endpoint", {"method": "DELETE", "path": f"/api/segments/{s}"})):
            with self.subTest(tool=name, args=args):
                self.assertRegex(self.refused(ALL, name, args), "No such|Choose")
        self.assertEqual(self.sams(), before)

    def test_the_same_tools_work_on_her_own_trip(self):
        got = self.tool(ALL, "update_trip", {"trip_id": self.jane_trip["id"], "fields": {"notes": "Window seat"}})
        self.assertEqual(got["notes"], "Window seat")

    def test_what_a_trip_shows_is_per_approver(self):
        self.assertIn("SAMROM", json.dumps(self.tool(ALL, "upcoming", {"days": 365}, sub="u-sam")))
        self.assertNotIn("ZQ4PXD", json.dumps(self.tool(ALL, "upcoming", {"days": 365}, sub="u-sam")))

    def test_a_guest_added_by_an_assistant_has_no_trips_until_someone_puts_them_on_one(self):
        mia = self.tool(ALL, "add_guest", {"fields": person("Grandma Joan")})
        self.assertEqual(mia["display_name"], "Grandma Joan")
        self.assertEqual(self.sams()[1], "Rome")


class MaskingTests(Assistants):
    """"IDs are for the household": full numbers only with "ids:read" and its switch, and never in a log; checked with canary
    numbers over every read tool's output."""

    def read_everything(self, scopes):
        """Every read tool, with the arguments that reach a membership, and call_endpoint's GET /api/loyalty: their texts."""
        out = {}
        for tool in mcp_server.TOOLS:
            for args in ({}, {"person_id": self.jane.person_id}, {"loyalty_id": self.jane_loyalty}, {"trip_id": self.jane_trip["id"]}):
                out[(tool["name"], json.dumps(args))] = json.dumps(self.tool(scopes, tool["name"], args))
        out["endpoint"] = json.dumps(self.tool((*scopes, "write"), "call_endpoint", {"method": "GET", "path": "/api/loyalty"}))
        return out

    def test_without_ids_read_no_read_tool_has_a_full_number(self):
        for scopes in (READ, WRITE):
            self.switch(ids=True, writes=True)          # (the switches alone don't reveal anything)
            for where, text in self.read_everything(scopes).items():
                with self.subTest(scopes=scopes, where=where):
                    self.assertNotIn(JANE_NUMBER, text)
                    self.assertNotIn(SAM_NUMBER, text)
                    self.assertNotIn(JANE_NUMBER[-8:], text)
        masked = json.dumps(self.tool(READ, "get_loyalty_ids"), ensure_ascii=False)
        self.assertIn(loyalty.mask(JANE_NUMBER), masked)       # the last four are what it gets

    def test_revealing_needs_the_scope_and_then_the_switch(self):
        args = {"person_id": self.jane.person_id, "reveal": True}
        self.assertIn("reconnect", self.refused(READ, "get_loyalty_ids", args))   # not allowed when it connected
        self.assertIn("reconnect", self.refused(WRITE, "get_loyalty_ids", args))
        self.switch(ids=False)
        self.assertIn("switched off", self.refused(IDS, "get_loyalty_ids", args))   # allowed, but the household's switch is off
        self.switch(ids=True)
        got = self.tool(IDS, "get_loyalty_ids", args)
        self.assertEqual([r["number"] for r in got["loyalty"]], [JANE_NUMBER])
        self.switch(ids=False)                                                        # off: the very next call
        self.assertIn("switched off", self.refused(IDS, "get_loyalty_ids", args))

    def test_the_reveal_request_itself_is_gated_too(self):
        path = f"loyalty/{self.jane_loyalty}/reveal"
        for scopes in (READ, WRITE):
            self.switch(ids=True)
            with self.assertRaises(mcp_server.ToolError):
                mcp_http.local_fetch(path, {}, {}, self.access(scopes))
        self.switch(ids=False)
        with self.assertRaisesRegex(mcp_server.ToolError, "switched off"):
            mcp_http.local_fetch(path, {}, {}, self.access(IDS))
        self.switch(ids=True)
        self.assertEqual(mcp_http.local_fetch(path, {}, {}, self.access(IDS)), {"number": JANE_NUMBER})

    def test_a_reveal_wants_to_know_whose(self):
        self.switch(ids=True)
        self.assertIn("whose", self.refused(IDS, "get_loyalty_ids", {"reveal": True}))

    def test_a_reveal_is_logged_by_membership_and_connection_never_the_number(self):
        self.switch(ids=True)
        with no_leaks(self, JANE_NUMBER, SAM_NUMBER, database=self.path), mock.patch("builtins.print") as printed:
            mcp_http.local_fetch(f"loyalty/{self.jane_loyalty}/reveal", {}, {}, mcp_access.Access(frozenset(IDS), 7, "u-jane", "jane@example.com"))
        lines = " ".join(str(c.args[0]) for c in printed.call_args_list)
        self.assertIn(f"membership {self.jane_loyalty}", lines)
        self.assertIn("connection 7", lines)
        self.assertNotIn(JANE_NUMBER, lines)

    def test_the_household_s_numbers_are_everyone_s_but_only_through_the_gate(self):
        self.switch(ids=True)
        got = self.tool(IDS, "get_loyalty_ids", {"person_id": self.sam.person_id, "reveal": True})
        self.assertEqual([r["number"] for r in got["loyalty"]], [SAM_NUMBER])   # (the household's: anyone can book for anyone)

    def test_adding_a_membership_takes_ids_read_as_well_as_write(self):
        self.switch(ids=True, writes=True)
        fields = {"person_id": self.jane.person_id, "kind": "hotel", "program": "Hilton Honors", "number": "CANARY-HHONORS-5550"}
        self.assertIn("reconnect", self.refused(WRITE, "add_loyalty_id", {"fields": fields}))    # write isn't enough
        with no_leaks(self, "CANARY-HHONORS-5550", database=self.path):
            got = self.tool(ALL, "add_loyalty_id", {"fields": fields})
        self.assertEqual(got["masked"], loyalty.mask("CANARY-HHONORS-5550"))                     # the reply is masked
        self.assertIn("reconnect", self.refused(WRITE, "update_loyalty_id", {"loyalty_id": got["id"], "fields": {**fields, "tier": "Gold"}}))
        self.assertEqual(self.tool(ALL, "update_loyalty_id", {"loyalty_id": got["id"], "fields": {**fields, "number": None, "tier": "Gold"}})["tier"], "Gold")
        self.assertEqual(self.tool(WRITE, "remove_loyalty_id", {"loyalty_id": got["id"]}), {"ok": True})   # (removing takes no number)


class WriteTests(Assistants):
    """Changes need the "write" scope and its switch, each checked on every call; a connection approved without it is told
    to reconnect."""

    SEGMENT = {"kind": "hotel", "origin": "Harbour Hotel", "start_local": "2026-12-02T15:00", "end_local": "2026-12-08T10:00",
               "start_zone": "Europe/London", "end_zone": "Europe/London"}

    def count(self):
        with db.session() as conn:
            return conn.execute(select(func.count()).select_from(Segment)).scalar()

    def test_refused_without_the_scope_with_a_reconnect_message(self):
        self.switch(writes=True)
        before = self.count()
        for name, args in (("add_segment", {"fields": self.SEGMENT}), ("create_trip", {"fields": {"name": "Nope"}}),
                           ("add_guest", {"fields": person("Nobody")}), ("remove_segment", {"segment_id": self.jane_trip["segment"]}),
                           ("call_endpoint", {"method": "POST", "path": "/api/trips", "body": {"name": "Nope"}})):
            with self.subTest(tool=name):
                self.assertIn("reconnect", self.refused((*READ, "ids:read"), name, args))
        self.assertEqual(self.count(), before)

    def test_refused_while_the_switch_is_off_and_allowed_the_moment_it_is_on(self):
        before = self.count()
        self.assertIn("switched off", self.refused(WRITE, "add_segment", {"fields": self.SEGMENT}))
        self.assertEqual(self.count(), before)
        self.switch(writes=True)
        got = self.tool(WRITE, "add_segment", {"fields": self.SEGMENT})
        self.assertEqual(got["kind"], "hotel")
        self.assertEqual(self.count(), before + 1)
        self.switch(writes=False)
        self.assertIn("switched off", self.refused(WRITE, "remove_segment", {"segment_id": got["id"]}))
        self.assertEqual(self.count(), before + 1)
        self.switch(writes=True)
        self.assertEqual(self.tool(WRITE, "remove_segment", {"segment_id": got["id"]}), {"ok": True})

    def test_every_changing_tool_works_with_both(self):
        self.switch(writes=True)
        trip = self.tool(WRITE, "create_trip", {"fields": {"name": "Lisbon", "start_date": "2026-11-01", "end_date": "2026-11-05"}})
        self.assertEqual(trip["name"], "Lisbon")
        renamed = self.tool(WRITE, "update_trip", {"trip_id": trip["id"], "fields": {"name": "Lisbon long weekend"}})
        self.assertEqual(renamed["name"], "Lisbon long weekend")
        seg = self.tool(WRITE, "add_segment", {"trip_id": trip["id"], "fields": {**self.SEGMENT, "start_local": "2026-11-01T15:00",
                                                                                   "end_local": "2026-11-05T10:00"}})
        self.assertEqual(seg["trip_id"], trip["id"])
        self.assertEqual(self.tool(WRITE, "update_segment", {"segment_id": seg["id"], "fields": {"provider": "Harbour"}})["provider"], "Harbour")
        other = self.tool(WRITE, "create_trip", {"fields": {"name": "Porto", "start_date": "2026-11-06", "end_date": "2026-11-08"}})
        merged = self.tool(WRITE, "merge_trips", {"trip_id": trip["id"], "merge": other["id"]})
        self.assertEqual(merged["id"], trip["id"])
        mia = self.tool(WRITE, "add_guest", {"fields": person("Joan Doe")})
        self.assertEqual(self.tool(WRITE, "update_person", {"person_id": mia["id"], "fields": person("Joan Smith")})["display_name"], "Joan Smith")
        self.assertEqual(self.tool(WRITE, "remove_segment", {"segment_id": seg["id"]}), {"ok": True})

    def test_call_endpoint_reaches_the_rest_of_what_write_allows(self):
        self.switch(writes=True)
        listed = self.tool(WRITE, "list_endpoints")
        self.assertIn("POST /api/trips/{id}/split (destructive)", listed["trips"])
        self.assertIn("DELETE /api/trips/{id} (destructive)", listed["trips"])
        self.assertEqual(self.tool(WRITE, "call_endpoint", {"method": "POST", "path": "/api/distance-unit", "body": {"distance_unit": "km"}}),
                         {"distance_unit": "km"})
        self.assertEqual(self.tool(WRITE, "call_endpoint", {"method": "POST", "path": "/api/distance-unit", "body": {"distance_unit": "mi"}}),
                         {"distance_unit": "mi"})

    def test_list_endpoints_names_nothing_blocked(self):
        self.switch(writes=True)
        areas = set(self.tool(WRITE, "list_endpoints"))
        self.assertEqual(areas & {"mailboxes", "review", "backup", "restore", "reminders", "feed", "mcp-settings", "ai", "state", "import"}, set())
        self.assertNotIn("/api/flight-status/{id}", json.dumps(self.tool(WRITE, "list_endpoints")))

    def test_a_blocked_route_is_refused_whatever_the_scope_or_switch(self):
        self.switch(ids=True, writes=True)
        for method, pattern in self.blocked_routes():
            path = pattern.replace("{id}", "1")
            with self.subTest(route=f"{method} {pattern}"):
                got = self.refused(ALL, "call_endpoint", {"method": method, "path": path})
                self.assertIn("can't reach", got)
                with self.assertRaises(mcp_server.ToolError):
                    mcp_http.local_fetch(path[len("/api/"):], {}, {} if method != "GET" else None, self.access(ALL), method)

    @staticmethod
    def blocked_routes():
        from waypoint.server import ROUTES
        found = [(m, p) for m, p, *_ in ROUTES if mcp_access.blocked(p)]
        assert len(found) > 10
        return found

    def test_changes_that_fold_or_remove_are_marked_destructive_and_the_rest_are_not(self):
        marked = {t["name"]: t for t in mcp_server.WRITE_TOOLS}
        for name in ("remove_segment", "remove_loyalty_id", "merge_trips"):
            self.assertTrue(marked[name]["destructive"], name)
            self.assertIn("Destructive", marked[name]["description"])
        for name in ("add_segment", "update_segment", "create_trip", "update_trip", "add_guest", "update_person", "add_loyalty_id",
                     "update_loyalty_id"):
            self.assertFalse(marked[name]["destructive"], name)
        for t in marked.values():
            self.assertIn("Ask the person", t["description"])


class LapseTests(Assistants):
    """"Access that outlives the person": a connection ends the moment its approver can no longer sign in."""

    def test_the_connection_stops_working_when_the_approver_is_taken_off_the_list(self):
        token = self.make_token("read", sub="u-sam")
        with db.session() as conn:
            self.assertIsNotNone(mcp_http.authorized(conn, f"Bearer {token}", self.base + "/mcp"))
        with mock.patch.dict("os.environ", {"OIDC_ALLOWED_EMAILS": "jane@example.com"}):
            with db.session() as conn:
                self.assertIsNone(mcp_http.authorized(conn, f"Bearer {token}", self.base + "/mcp"))
            with db.session() as conn:
                reason = conn.execute(select(OAuthGrant.revoked_reason)).scalar()
        self.assertEqual(reason, "user_removed")
        with db.session() as conn:                                  # (and it stays ended when they're let back in)
            self.assertIsNone(mcp_http.authorized(conn, f"Bearer {token}", self.base + "/mcp"))


if __name__ == "__main__":
    unittest.main()
