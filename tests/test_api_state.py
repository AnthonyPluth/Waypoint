"""GET /api/state: who's signed in, the version, the database and the last backup."""
import os
from datetime import datetime
from unittest import mock

from waypoint.storage import db
from waypoint.storage import settings_keys as sk
from waypoint.server.api import state
from waypoint.server.common import _current
from tests.shared import DbCase, ServerCase

class StateTests(DbCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, _current, "user", getattr(_current, "user", None))

    def test_version(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_VERSION": "v1.2.3"}):
            self.assertEqual(state.api_state(self.c, {}, {})["version"], "v1.2.3")
        with mock.patch.dict(os.environ, {"WAYPOINT_VERSION": ""}):
            self.assertEqual(state.api_state(self.c, {}, {})["version"], "dev")

    def test_database(self):
        self.assertEqual(state.api_state(self.c, {}, {})["database"], "postgres" if db.using_postgres() else "sqlite")
        with mock.patch.object(db, "using_postgres", return_value=True):
            self.assertEqual(state.api_state(self.c, {}, {})["database"], "postgres")

    def test_the_signed_in_person(self):
        _current.user = {"sub": "u1", "name": "Rosa Example", "email": "rosa@example.com"}
        self.assertEqual(state.api_state(self.c, {}, {})["user"], _current.user)
        _current.user = None
        self.assertIsNone(state.api_state(self.c, {}, {})["user"])

    def test_the_last_backup_carries_its_offset(self):
        self.assertIsNone(state.api_state(self.c, {}, {})["last_backup"])
        db.set_setting(self.c, sk.LAST_BACKUP, "2026-09-30T07:02:00")
        st = state.api_state(self.c, {}, {})
        self.assertEqual(datetime.fromisoformat(st["last_backup"]), datetime(2026, 9, 30, 7, 2).astimezone())
        self.assertIsNotNone(datetime.fromisoformat(st["last_backup"]).tzinfo)
        self.assertEqual(state.with_offset("2026-09-30T12:02:00+00:00"), "2026-09-30T12:02:00+00:00")
        self.assertEqual(state.with_offset("2026-09-30T12:02:00-05:00", utc=True), "2026-09-30T12:02:00-05:00")
        self.assertEqual(state.with_offset("2026-09-30 12:02:00", utc=True), "2026-09-30T12:02:00+00:00")
        self.assertIsNone(state.with_offset(None))
        self.assertEqual(state.with_offset(""), "")
        self.assertEqual(state.with_offset("garbled"), "garbled")


class LocalStateTests(ServerCase):
    env = {"WAYPOINT_VERSION": "v9.8.7"}
    unset = ("OIDC_ISSUER",)

    def test_without_sign_in_everyone_is_local(self):
        code, st = self.req("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(st, {"version": "v9.8.7", "database": "postgres" if db.using_postgres() else "sqlite",
                              "user": {"name": None, "email": None, "local": True}, "last_backup": None,
                              "review_count": 0})
