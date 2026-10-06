"""Every route is either reachable by an assistant (and with which scopes) or blocked, listed here, so a route added to
waypoint/server/routes.py fails these tests until someone has decided which (AGENTS.md: a new route is held to the
promises the moment it's added). Nothing under mailboxes, the review queue, AI, backup, the feed or push is reachable,
whatever the scope or switch."""
import re
import unittest

from waypoint.server import ROUTES, mcp_access, mcp_http

READ = ("read",)
WRITE = ("write",)

# What an assistant may read with "read".
READS = [
    "GET /api/airports/{id}", "GET /api/distance-unit", "GET /api/flight-status", "GET /api/people",
    "GET /api/segments/{id}", "GET /api/stats", "GET /api/trips", "GET /api/trips/{id}",
]
# What "write" opens to read: it finds who a change is for. No numbers, no mail.
WRITE_READS = ["GET /api/people/claim-suggestions"]
# The changes "write" allows (and its switch): everything the web app changes outside BLOCKED.
CHANGES = [
    "DELETE /api/people/{id}", "DELETE /api/segments/{id}", "DELETE /api/trips/{id}",
    "POST /api/distance-unit", "POST /api/people", "POST /api/people/claim-suggestions/dismiss", "POST /api/people/{id}",
    "POST /api/people/{id}/claim", "POST /api/segments", "POST /api/segments/{id}", "POST /api/trips", "POST /api/trips/{id}",
    "POST /api/trips/{id}/merge", "POST /api/trips/{id}/split",
]
# Never reachable, whatever the scope or switch (loyalty and Known Traveler numbers: not even the masked listing).
BLOCKED = [
    "DELETE /api/loyalty/{id}", "GET /api/loyalty", "POST /api/loyalty", "POST /api/loyalty/{id}", "POST /api/loyalty/{id}/reveal",
    "DELETE /api/feed", "DELETE /api/mailboxes/{id}", "DELETE /api/mcp-settings/connections/{id}", "DELETE /api/reminders/devices/{id}",
    "DELETE /api/review/{id}", "GET /api/ai", "GET /api/backup", "GET /api/mailboxes", "GET /api/mailboxes/callback",
    "GET /api/mcp-settings", "GET /api/reminders", "GET /api/review", "GET /api/review/{id}/preview", "GET /api/state",
    "POST /api/ai", "POST /api/backup/inspect", "POST /api/feed", "POST /api/flight-status/{id}", "POST /api/import",
    "POST /api/import/preview", "POST /api/mailboxes/connect", "POST /api/mailboxes/{id}/reread", "POST /api/mailboxes/{id}/scan", "POST /api/mailboxes/{id}/share",
    "POST /api/mcp-settings/writes", "POST /api/reminders", "POST /api/reminders/devices",
    "GET /api/logodev", "POST /api/logodev", "POST /api/logodev/fetch", "GET /api/segments/{id}/logo",
    "POST /api/restore", "POST /api/review/who/{id}", "POST /api/review/{id}/ignore", "POST /api/review/{id}/suggest",
]
# Where a route in one of these areas must never be reachable: the promises' sources (mail, the AI, backups, sign-in and
# sessions, the feed's key, push devices, the flight-status budget and key, these settings).
NEVER = re.compile(r"^/api/(mailboxes|review|ai|backup|restore|state|feed|reminders|mcp-settings|import|loyalty|logodev)(/|$)|^/api/flight-status/")


class RouteTests(unittest.TestCase):
    def reachable(self):
        return {f"{m} {p}": mcp_http.needs(m, p) for m, p, *_ in ROUTES}

    def test_every_route_is_listed_as_reachable_or_blocked(self):
        listed = set(READS + WRITE_READS + CHANGES + BLOCKED)
        every = {f"{m} {p}" for m, p, *_ in ROUTES}
        self.assertEqual(sorted(every - listed), [], "decide for these routes: reachable (which scopes), or BLOCKED in "
                                                    "waypoint/server/mcp_access.py, then list them here")
        self.assertEqual(sorted(listed - every), [], "this list names a route that's gone")

    def test_each_route_needs_what_the_list_says(self):
        got = self.reachable()
        for route in READS:
            self.assertEqual(got[route], READ, route)
        for route in WRITE_READS + CHANGES:
            self.assertEqual(got[route], WRITE, route)
        for route in BLOCKED:
            self.assertIsNone(got[route], route)

    def test_nothing_in_a_never_area_is_reachable(self):
        for (m, p, *_) in ROUTES:
            if NEVER.match(p):
                with self.subTest(route=f"{m} {p}"):
                    self.assertTrue(mcp_access.blocked(p))
                    self.assertIsNone(mcp_http.needs(m, p))

    def test_blocked_areas_block_what_is_added_under_them_too(self):
        for path in ("/api/mailboxes/{id}/anything", "/api/review/new/thing", "/api/ai/key", "/api/backup/x", "/api/feed/key",
                     "/api/reminders/devices/{id}/x", "/api/mcp-settings/x", "/api/flight-status/{id}/x", "/api/import/csv", "/api/loyalty", "/api/loyalty/{id}/reveal"):
            self.assertTrue(mcp_access.blocked(path), path)
        for path in ("/api/flight-status", "/api/trips", "/api/people"):
            self.assertFalse(mcp_access.blocked(path), path)

    def test_a_new_post_or_delete_is_allowed_unless_blocked_so_the_list_above_must_grow(self):
        fake = [("POST", "/api/newthing", None), ("DELETE", "/api/newthing/{id}", None), ("GET", "/api/newthing", None),
                ("POST", "/api/mailboxes/new", None)]
        self.assertEqual(mcp_access.writable_routes(fake), [("POST", "/api/newthing"), ("DELETE", "/api/newthing/{id}")])

    def test_destructive_changes_are_marked(self):
        for m, p in (("DELETE", "/api/trips/{id}"), ("DELETE", "/api/segments/{id}"), ("DELETE", "/api/people/{id}"),
                     ("POST", "/api/trips/{id}/merge"), ("POST", "/api/trips/{id}/split"),
                     ("POST", "/api/people/{id}/claim")):
            self.assertTrue(mcp_access.destructive(m, p), f"{m} {p}")
        for m, p in (("POST", "/api/segments"), ("POST", "/api/segments/{id}"), ("POST", "/api/trips"),
                     ("POST", "/api/distance-unit")):
            self.assertFalse(mcp_access.destructive(m, p), f"{m} {p}")

    def test_oauth_and_mcp_are_not_api_routes(self):
        for _m, p, *_ in ROUTES:
            self.assertFalse(p.startswith(("/mcp", "/oauth", "/.well-known")), p)   # (the handler answers those, not the table)


if __name__ == "__main__":
    unittest.main()
