import os
import unittest
from unittest import mock

from tests.shared import ServerCase
from waypoint import oidc
from waypoint.domain import demo
from waypoint.storage import db

LOCAL_USER = {"name": None, "email": None, "local": True}


def seed_demo_data(marker: bool = True) -> None:
    with db.session() as conn:
        demo.seed(conn)
    if marker:
        with open(os.path.join(db.data_dir(), oidc.VERIFY_MARKER), "w"):
            pass


class SignedInDemoTests(ServerCase):
    unset = ("OIDC_ISSUER", "DATABASE_URL", oidc.VERIFY_AS)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        seed_demo_data()

    def state(self):
        code, st = self.req("GET", "/api/state")
        self.assertEqual(code, 200)
        return st

    def test_a_normal_run_is_the_local_user_and_photos_stay_off(self):
        st = self.state()
        self.assertEqual((st["user"], st["person_id"]), (LOCAL_USER, None))
        self.assertEqual(self.req("GET", "/api/photos/review")[0], 404)

    def test_the_verify_environment_signs_in_as_the_named_demo_member(self):
        for who, name in (("jane", "Jane Doe"), ("sam", "Sam Doe")):
            with mock.patch.dict(os.environ, {oidc.VERIFY_AS: who}):
                st = self.state()
                self.assertEqual((st["user"]["name"], st["user"].get("local"), st["person_id"] is not None), (name, None, True))
                self.assertEqual(self.req("GET", "/api/photos/review")[0], 200)

    def test_an_unknown_name_is_the_local_user(self):
        for who in ("", "demo-jane", "root", "JANE", "jane "):
            with mock.patch.dict(os.environ, {oidc.VERIFY_AS: who}):
                self.assertEqual(self.state()["user"], LOCAL_USER, who)

    def test_with_sign_in_configured_the_setting_does_nothing(self):
        with mock.patch.dict(os.environ, {oidc.VERIFY_AS: "jane", "OIDC_ISSUER": "https://idp.example"}):
            self.assertIsNone(oidc.verify_user())
            self.assertTrue(oidc.enabled())

    def test_on_postgres_the_setting_does_nothing(self):
        with mock.patch.dict(os.environ, {oidc.VERIFY_AS: "jane"}), mock.patch.object(db, "using_postgres", return_value=True):
            self.assertIsNone(oidc.verify_user())

    def test_without_the_marker_only_verify_writes_the_setting_does_nothing(self):
        marker = os.path.join(db.data_dir(), oidc.VERIFY_MARKER)
        os.rename(marker, marker + ".off")
        self.addCleanup(os.rename, marker + ".off", marker)
        with mock.patch.dict(os.environ, {oidc.VERIFY_AS: "jane"}):
            self.assertEqual(self.state()["user"], LOCAL_USER)
            self.assertEqual(self.req("GET", "/api/photos/review")[0], 404)


class WithoutDemoMemberTests(unittest.TestCase):
    def test_a_marked_folder_without_the_member_is_the_local_user(self):
        from tests.shared import own_database
        own_database(self)
        with open(os.path.join(db.data_dir(), oidc.VERIFY_MARKER), "w"), mock.patch.dict(os.environ, {oidc.VERIFY_AS: "jane"}):
            self.assertIsNone(oidc.verify_user())
