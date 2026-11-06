import os
import time
import unittest
from unittest import mock

from sqlalchemy import select, update

from tests import test_mcp_oauth_http as base
from waypoint.server import mcp_oauth
from waypoint.storage import db
from waypoint.storage.models import OAuthClient, OAuthGrant, User

APP = {"client_id": mcp_oauth.APP_CLIENT, "redirect_uris": [mcp_oauth.APP_REDIRECT]}
APP_HEADERS = {"X-Waypoint": "1"}


class AppSignIn(base.SignedInServer):

    def setUp(self):
        super().setUp()
        self.clients.append(mcp_oauth.APP_CLIENT)
        self.session = self.sign_in_as("me@example.com")
        self.app_resource = self.base + "/app"

    def app_page(self, **over):
        return self.authorize(APP, cookies=self.session, resource=self.app_resource, scope="app", **over)

    def app_tokens(self):
        page = self.app_page()
        self.assertEqual(page.status, 200, page.body)
        back = self.answer(page)
        self.assertEqual(back.status, 302, back.body)
        self.assertTrue(back.location.startswith(mcp_oauth.APP_REDIRECT + "?"), back.location)
        r = self.exchange(APP, back.query()["code"], redirect_uri=mcp_oauth.APP_REDIRECT)
        self.assertEqual(r.status, 200, r.body)
        return r.json

    def api(self, token, method="GET", path="/api/trips", body=None, headers=None):
        return self.http(method, path, body, {"Authorization": f"Bearer {token}", **(headers or {})})


class SignInFlowTests(AppSignIn):

    def test_the_app_signs_in_with_pkce_and_gets_a_token_for_the_app_resource(self):
        page = self.app_page()
        self.assertEqual(page.status, 200)
        self.assertIn(b"Waypoint for iPhone", page.body)
        self.assertIn(b"signed in as <b>me@example.com</b>", page.body)
        self.assertIn("form-action 'self' waypoint:", page.headers["Content-Security-Policy"])
        t = self.app_tokens()
        self.assertEqual(t["scope"], "app")
        self.assertTrue(t["access_token"].startswith("wpa_"))
        refreshed = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                                               "client_id": mcp_oauth.APP_CLIENT})
        self.assertEqual(refreshed.status, 200, refreshed.body)
        self.assertEqual(refreshed.json["scope"], "app")

    def test_the_scope_is_always_app(self):
        r = self.authorize(APP, cookies=self.session, resource=self.app_resource, scope="read write")
        self.assertEqual(r.status, 302)
        self.assertEqual(r.query()["error"], "invalid_scope")
        self.assertTrue(r.location.startswith(mcp_oauth.APP_REDIRECT))
        self.assertEqual(self.authorize(APP, cookies=self.session, resource=self.app_resource, scope=None).status, 200)

    def test_a_deny_goes_back_to_the_app(self):
        back = self.answer(self.app_page(), decision="deny")
        self.assertEqual(back.status, 302)
        self.assertEqual(back.query()["error"], "access_denied")
        self.assertTrue(back.location.startswith(mcp_oauth.APP_REDIRECT + "?"))

    def test_the_mcp_resource_is_refused_for_the_app(self):
        r = self.authorize(APP, cookies=self.session, resource=self.resource, scope="app")
        self.assertEqual(r.status, 302)
        self.assertEqual(r.query()["error"], "invalid_target")

    def test_no_other_client_can_use_the_app_redirect(self):
        other = self.client()
        r = self.authorize({**other, "redirect_uris": [mcp_oauth.APP_REDIRECT]}, cookies=self.session)
        self.assertEqual(r.status, 400)
        self.assertEqual(self.register(redirect_uris=[mcp_oauth.APP_REDIRECT]).status, 400)

    def test_the_app_client_is_not_dropped_by_housekeeping_and_is_not_an_assistant_connection(self):
        t = self.app_tokens()
        with db.session() as conn:
            conn.execute(update(OAuthClient).where(OAuthClient.id == mcp_oauth.APP_CLIENT).values(created=time.time() - 9 * 86400))
            conn.execute(update(OAuthGrant).where(OAuthGrant.client_id == mcp_oauth.APP_CLIENT).values(created=time.time() - 9 * 86400))
            mcp_oauth.housekeeping(conn)
        self.assertEqual(self.mine(select(OAuthClient.id).where(OAuthClient.id == mcp_oauth.APP_CLIENT)), mcp_oauth.APP_CLIENT)
        self.assertEqual(self.api(t["access_token"], path="/api/trips").status, 200)
        listed = self.api(t["access_token"], path="/api/mcp-settings").json
        self.assertEqual([c for c in listed["connections"] if c["client"] == mcp_oauth.APP_NAME], [])


class BearerTests(AppSignIn):

    def test_a_signed_out_request_is_still_refused(self):
        self.assertEqual(self.http("GET", "/api/trips").status, 401)
        self.assertEqual(self.api("wpa_nonsense").status, 401)

    def test_the_app_token_works_on_the_api_only(self):
        t = self.app_tokens()["access_token"]
        self.assertEqual(self.api(t).status, 200)
        self.assertEqual(self.api(t, "POST", "/api/people", b"{}", {"Content-Type": "application/json"}).status, 403)
        self.assertEqual(self.rpc(t, "ping").status, 401)
        self.assertEqual(self.http("GET", "/", headers={"Authorization": f"Bearer {t}"}).status, 302)

    def test_an_assistant_token_does_not_open_the_api(self):
        assistant = self.tokens(self.client())["access_token"]
        self.assertEqual(self.api(assistant).status, 401)

    def test_taken_off_the_sign_in_list_ends_the_app(self):
        t = self.app_tokens()
        self.assertEqual(self.api(t["access_token"]).status, 200)
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "someone-else@example.com"}):
            self.assertEqual(self.api(t["access_token"]).status, 401)
            r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                                           "client_id": mcp_oauth.APP_CLIENT})
            self.assertEqual((r.status, r.json["error"]), (400, "invalid_grant"))

    def test_a_revoked_grant_ends_the_app(self):
        t = self.app_tokens()
        r = self.form("/oauth/revoke", {"token": t["refresh_token"], "client_id": mcp_oauth.APP_CLIENT})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.api(t["access_token"]).status, 401)


    def test_a_refresh_may_repeat_the_app_scope(self):
        t = self.app_tokens()
        r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                                       "client_id": mcp_oauth.APP_CLIENT, "scope": "app",
                                       "resource": self.app_resource})
        self.assertEqual(r.status, 200, r.body)


class AppSessionTests(AppSignIn):

    def test_the_app_gets_a_web_session_for_its_web_view(self):
        t = self.app_tokens()["access_token"]
        r = self.api(t, "POST", "/auth/app-session", b"", APP_HEADERS)
        self.assertEqual(r.status, 200, r.body)
        cookie = r.json
        self.assertEqual(cookie["name"], "waypoint_session")
        self.assertEqual(cookie["max_age"], 86400)
        self.assertEqual(self.http("GET", "/api/trips", cookies={"waypoint_session": cookie["value"]}).status, 200)

    def test_with_groups_the_session_ends_with_the_last_sign_in_window(self):
        t = self.app_tokens()["access_token"]
        groups = {"OIDC_ALLOWED_GROUPS": "household", "WAYPOINT_SESSION_DAYS": "14"}
        with mock.patch.dict(os.environ, groups):
            with db.session() as conn:
                conn.execute(update(User).where(User.sub == "user-1").values(last_seen=time.time() - 13.5 * 86400))
            r = self.api(t, "POST", "/auth/app-session", b"", APP_HEADERS)
        self.assertEqual(r.status, 200, r.body)
        self.assertLessEqual(r.json["max_age"], 12 * 3600 + 5)

    def test_it_needs_the_app_header_and_a_valid_app_token(self):
        t = self.app_tokens()["access_token"]
        self.assertEqual(self.api(t, "POST", "/auth/app-session", b"").status, 403)
        self.assertEqual(self.http("POST", "/auth/app-session", b"", APP_HEADERS).status, 401)
        self.assertEqual(self.api("wpa_nonsense", "POST", "/auth/app-session", b"", APP_HEADERS).status, 401)
        assistant = self.tokens(self.client())["access_token"]
        self.assertEqual(self.api(assistant, "POST", "/auth/app-session", b"", APP_HEADERS).status, 401)
        self.assertEqual(self.api(t, "GET", "/auth/app-session").status, 405)


if __name__ == "__main__":
    unittest.main()
