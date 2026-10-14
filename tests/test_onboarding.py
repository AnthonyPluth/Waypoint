from unittest import mock

from tests.shared import ServerCase
from tests.test_trips import OUT
from waypoint.server import jobs


class LocalStartTests(ServerCase):
    unset = ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ALLOWED_EMAILS", "OIDC_ALLOWED_GROUPS", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "RAPIDAPI_KEY", "OPENROUTER_API_KEY")

    def test_a_new_household_can_add_and_read_a_booking_without_accounts_or_connections(self):
        with mock.patch("waypoint.tls.urlopen", side_effect=AssertionError("Local onboarding must not need the network")) as network:
            status, state = self.req("GET", "/api/state")
            self.assertEqual(status, 200)
            self.assertTrue(state["user"]["local"])
            status, mail = self.req("GET", "/api/mailboxes")
            self.assertEqual(status, 200)
            self.assertFalse(mail["configured"])
            self.assertEqual(mail["mailboxes"], [])
            status, booking = self.req("POST", "/api/segments", {**OUT, "provider": "United Airlines"})
            self.assertEqual(status, 200)
            self.assertEqual(self.req("GET", f"/api/trips/{booking['trip_id']}")[0], 200)
            self.assertIsNotNone(booking["logo"])
            jobs.scan_mailboxes()
            jobs.check_flights()
            jobs.send_reminders()
            network.assert_not_called()

    def test_local_mode_keeps_cross_site_and_missing_app_header_checks(self):
        self.assertEqual(self.req("POST", "/api/segments", OUT, {"Origin": "https://example.com"})[0], 403)
        from tests.shared import fetch
        self.assertEqual(fetch(self.base, "POST", "/api/segments", b"{}", {"Content-Type": "application/json"})[0], 403)
