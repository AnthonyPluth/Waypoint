"""POST /mcp over HTTP, the tools and the protocol (waypoint/server/mcp_server.py), and the Settings routes for the assistants
(switches, connections, Disconnect). Names, codes and numbers are made up."""
import base64
import hashlib
import json
import unittest
from unittest import mock

from sqlalchemy import select

from tests.shared import ServerCase, fetch, tag
from tests.test_mcp import ALL, CALLBACK, READ, VERIFIER, WRITE, Assistants, person
from waypoint.server import mcp_access, mcp_http, mcp_oauth, mcp_server
from waypoint.storage import db
from waypoint.storage.models import OAuthGrant, OAuthToken


class StreamableHttpTests(Assistants):
    """POST /mcp: the server, served by Waypoint itself."""

    def rpc(self, msg, key="", headers=None, method="POST", raw=None):
        h = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {}), **(headers or {})}
        return fetch(self.base, method, "/mcp", raw if raw is not None else (json.dumps(msg).encode() if method == "POST" else None), h)

    def call(self, key, name, args=None, mid=1):
        status, _, body = self.rpc({"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}, key)
        self.assertEqual(status, 200)
        return json.loads(body)["result"]

    def tools(self, key):
        return json.loads(self.rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, key)[2])["result"]["tools"]

    def test_auth_failures_are_401_with_a_challenge(self):
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        key = self.make_token()
        for k in ("", "wpa_wrong", key + "x", "wpr_" + key[4:]):
            with self.subTest(key=k):
                status, headers, _ = self.rpc(ping, k)
                self.assertEqual(status, 401)
                self.assertTrue(headers["WWW-Authenticate"].startswith('Bearer realm="Waypoint", resource_metadata="'))
        status, _, _ = self.rpc(ping, headers={"Authorization": key})              # not a bearer header
        self.assertEqual(status, 401)
        self.assertEqual(self.rpc(ping, key)[0], 200)

    def test_a_web_page_in_a_browser_is_refused(self):
        key = self.make_token()
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        for origin in ("https://evil.example", "null", "http://localhost:1"):
            with self.subTest(origin=origin):
                self.assertEqual(self.rpc(ping, key, {"Origin": origin})[0], 403)
        self.assertEqual(self.rpc(ping, key, {"Origin": self.base})[0], 200)       # its own address, and no Origin at all, are fine

    def test_get_is_not_allowed_and_bad_messages_are_answered(self):
        key = self.make_token()
        status, headers, _ = self.rpc(None, key, method="GET")
        self.assertEqual((status, headers["Allow"]), (405, "POST"))
        status, _, body = self.rpc(None, key, raw=b"{not json")
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, -32700))
        status, _, body = self.rpc(None, key, raw=b"[{}]")
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, -32600))
        status, _, body = self.rpc({"jsonrpc": "2.0", "id": 3, "method": "nope"}, key)
        self.assertEqual((status, json.loads(body)["error"]["code"]), (200, -32601))

    def test_a_notification_gets_202_and_no_body(self):
        status, _, body = self.rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.make_token())
        self.assertEqual((status, body), (202, b""))

    def test_initialize_tells_the_assistant_what_it_may_do(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
        read = json.loads(self.rpc(init, self.make_token())[2])["result"]
        self.assertEqual((read["protocolVersion"], read["serverInfo"]["name"]), ("2025-06-18", "waypoint"))
        self.assertIn("read-only", read["instructions"])
        self.switch(True)
        write = json.loads(self.rpc(init, self.make_token(*WRITE))[2])["result"]["instructions"]
        self.assertIn("wait for the person's explicit yes", write)
        self.assertIn("destructive", write)
        self.assertIn("separately", write)
        self.assertIn("read-only", json.loads(self.rpc(init, self.make_token(*READ))[2])["result"]["instructions"])   # (no scope)
        self.assertEqual(json.loads(self.rpc({**init, "params": {"protocolVersion": "1999"}}, self.make_token())[2])["result"]["protocolVersion"],
                         mcp_server.PROTOCOL_VERSIONS[0])

    def test_the_tools_offered_follow_the_scopes_and_switches(self):
        reads = [t["name"] for t in mcp_server.TOOLS]
        names = lambda key: [t["name"] for t in self.tools(key)]
        self.assertEqual(names(self.make_token(*ALL)), reads)                     # switches off: reads only
        self.switch(True)
        self.assertEqual(names(self.make_token(*READ)), reads)                    # (a connection that wasn't allowed it)
        with_write = names(self.make_token(*WRITE))
        self.assertIn("add_segment", with_write)
        self.assertIn("call_endpoint", with_write)
        self.assertEqual([n for n in with_write if "loyalty" in n], [])           # no tool touches a number, whatever it's allowed

    def test_write_tools_carry_mcp_s_annotations(self):
        self.switch(True)
        by_name = {t["name"]: t["annotations"] for t in self.tools(self.make_token(*ALL))}
        self.assertEqual(by_name["upcoming"], {"readOnlyHint": True, "openWorldHint": False})
        self.assertEqual(by_name["remove_segment"], {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False})
        self.assertEqual(by_name["merge_trips"]["destructiveHint"], True)
        self.assertEqual(by_name["update_segment"], {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
        self.assertEqual(by_name["add_segment"]["destructiveHint"], False)
        self.assertEqual(by_name["call_endpoint"]["destructiveHint"], True)
        self.assertEqual(by_name["list_endpoints"], {"readOnlyHint": True, "openWorldHint": False})
        self.assertEqual({n for n, a in by_name.items() if not a["readOnlyHint"]},
                         {t["name"] for t in mcp_server.WRITE_TOOLS} | {"call_endpoint"})

    def test_a_read_tool_runs_in_process_as_its_approver(self):
        key = self.make_token()
        result = self.call(key, "list_trips")
        self.assertNotIn("isError", result)
        self.assertEqual([t["name"] for t in json.loads(result["content"][0]["text"])["trips"]], ["London"])
        sam = json.loads(self.call(self.make_token(sub="u-sam"), "list_trips")["content"][0]["text"])
        self.assertEqual([t["name"] for t in sam["trips"]], ["Rome"])
        self.assertIn("isError", self.call(key, "no_such_tool"))

    def test_a_write_tool_needs_the_scope_and_the_switch_over_http(self):
        key, read_only = self.make_token(*WRITE), self.make_token(*READ)
        args = {"fields": person("Joan Doe")}
        result = self.call(key, "add_guest", args)
        self.assertTrue(result["isError"])
        self.assertIn("switched off", result["content"][0]["text"])
        self.switch(True)
        added = self.call(key, "add_guest", args)
        self.assertNotIn("isError", added)
        self.assertEqual(json.loads(added["content"][0]["text"])["display_name"], "Joan Doe")
        refused = self.call(read_only, "add_guest", args)
        self.assertIn("reconnect", refused["content"][0]["text"])

    def test_what_a_tool_gets_wrong_is_told_not_crashed(self):
        key = self.make_token()
        for name, args in (("get_trip", {}), ("get_trip", {"trip_id": "abc"}), ("get_trip", {"trip_id": True}), ("upcoming", {"from": "soon"}),
                           ("get_stats", {"person": "x"}), ("get_stats", {"year": "20x"})):
            with self.subTest(name=name, args=args):
                self.assertTrue(self.call(key, name, args)["isError"])
        self.switch(True)
        wide = self.make_token(*WRITE)
        for sent in (2.7, "2.7", "2e0x"):
            with self.subTest(sent=sent):
                self.assertTrue(self.call(wide, "remove_segment", {"segment_id": sent})["isError"])   # not segment 2
        _status, _, body = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": 5}}, key)
        self.assertEqual(json.loads(body)["error"]["code"], -32602)

    def test_upcoming_lists_the_next_segments_with_their_trip(self):
        got = json.loads(self.call(self.make_token(), "upcoming", {"days": 30})["content"][0]["text"])
        self.assertEqual((got["today"], got["from"]), ("2026-09-23", "2026-09-23"))
        self.assertEqual([(s["trip"], s["confirmation"], s["start_zone"]) for s in got["segments"]],
                         [("London", "ZQ4PXD", "America/New_York")])                       # wall-clock times, in the place's zone
        far = json.loads(self.call(self.make_token(), "upcoming", {"from": "2027-01-01", "days": 5})["content"][0]["text"])
        self.assertEqual(far["segments"], [])

    def test_a_reply_that_is_too_long_is_cut_with_a_hint(self):
        key = self.make_token()
        original = mcp_server.MAX_TEXT
        mcp_server.MAX_TEXT = 300
        try:
            text = self.call(key, "list_people")["content"][0]["text"]
        finally:
            mcp_server.MAX_TEXT = original
        self.assertIn("cut at 300 characters", text)

    def test_the_log_line_for_a_request_has_no_query_and_the_token_never_appears(self):
        key = self.make_token()
        with mock.patch("builtins.print") as printed:
            self.rpc({"jsonrpc": "2.0", "id": 1, "method": "ping"}, key)
        self.assertNotIn(key, " ".join(str(c.args[0]) for c in printed.call_args_list))


class SettingsRoutes(ServerCase):
    """Settings → AI assistants (MCP), on your own machine (no sign-in), the way Settings calls them."""
    unset = ("OIDC_ISSUER", "WAYPOINT_PUBLIC_URL")

    def setUp(self):
        self.tag = tag()
        self.addCleanup(self.reset)

    def reset(self):
        with db.session() as conn:
            for (grant,) in conn.execute(select(OAuthGrant.id)).fetchall():
                mcp_oauth.revoke_grant(conn, grant, "test")
            mcp_access.set_allow_writes(conn, False)

    def connect(self, *scopes, name=None) -> int:
        """An assistant `ana@example.com` approved for `scopes`, with its tokens (as if it had traded its code): its grant's id."""
        with db.session() as conn:
            c = mcp_oauth.register(conn, {"client_name": name or "Claude " + self.tag, "redirect_uris": [CALLBACK]})
            challenge = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
            code = mcp_oauth.approve(conn, {"client_id": c["client_id"], "redirect_uri": CALLBACK, "code_challenge": challenge,
                                            "resource": self.base + "/mcp"}, frozenset(scopes or READ), None, "ana@example.com")
            mcp_oauth.token(conn, mcp_oauth.get_client(conn, c["client_id"]),
                            {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK, "code_verifier": VERIFIER}, self.base)
            return conn.execute(select(OAuthGrant.id).where(OAuthGrant.client_id == c["client_id"])).scalar()

    def test_settings_say_where_to_connect_and_start_with_everything_off(self):
        status, got = self.req("GET", "/api/mcp-settings")
        self.assertEqual(status, 200)
        self.assertEqual((got["allow_writes"], got["oauth"], got["url"]), (False, True, self.base + "/mcp"))
        self.assertIsNone(got["reason"])

    def test_without_an_address_that_oauth_can_use_it_says_why(self):
        with mock.patch.dict("os.environ", {"WAYPOINT_PUBLIC_URL": "http://example.com"}):
            _status, got = self.req("GET", "/api/mcp-settings")
        self.assertEqual((got["oauth"], got["url"]), (False, None))
        self.assertIn("WAYPOINT_PUBLIC_URL", got["reason"])

    def test_the_switch_turns_on_and_off(self):
        self.assertEqual(self.req("POST", "/api/mcp-settings/writes", {"allow": True}), (200, {"allow": True}))
        self.assertEqual(self.req("GET", "/api/mcp-settings")[1]["allow_writes"], True)
        with db.session() as conn:
            self.assertTrue(mcp_access.allow_writes(conn))
        self.assertEqual(self.req("POST", "/api/mcp-settings/writes", {"allow": False}), (200, {"allow": False}))
        self.assertEqual(self.req("GET", "/api/mcp-settings")[1]["allow_writes"], False)
        self.assertEqual(self.req("POST", "/api/mcp-settings/ids", {"allow": True})[0], 404)   # (there is no switch for numbers)

    def test_connected_assistants_are_listed_with_who_approved_them_and_disconnect_ends_them_at_once(self):
        grant = self.connect("read", "write", name="Claude " + self.tag)
        ours = [c for c in self.req("GET", "/api/mcp-settings")[1]["connections"] if c["client"] == "Claude " + self.tag]
        self.assertEqual([(c["id"], c["who"], c["scope"], c["last_used"]) for c in ours],
                         [(grant, "ana@example.com", ["read", "write"], None)])
        self.assertTrue(ours[0]["created"])
        self.assertEqual(self.req("DELETE", f"/api/mcp-settings/connections/{grant}"), (200, {"ok": True}))
        self.assertEqual([c for c in self.req("GET", "/api/mcp-settings")[1]["connections"] if c["client"] == "Claude " + self.tag], [])
        self.assertEqual(self.req("DELETE", f"/api/mcp-settings/connections/{grant}")[0], 404)   # gone already
        with db.session() as conn:
            self.assertEqual(conn.execute(select(OAuthToken.token_hash).where(OAuthToken.grant_id == grant)).fetchall(), [])

    def test_the_settings_routes_are_not_reachable_from_mcp(self):
        full = mcp_access.Access(frozenset({"read", "write"}), None, None, None)
        for path, method in (("mcp-settings", "GET"), ("mcp-settings/writes", "POST"),
                             ("mcp-settings/connections/1", "DELETE")):
            with self.subTest(path=path), self.assertRaises(mcp_server.ToolError):
                with db.session() as conn:
                    mcp_access.set_allow_writes(conn, True)
                mcp_http.local_fetch(path, {}, {} if method != "GET" else None, full, method)


if __name__ == "__main__":
    unittest.main()
