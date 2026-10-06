import os
import unittest
from unittest import mock

from waypoint.storage import db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class StoragePathTests(unittest.TestCase):
    def test_the_default_data_folder_is_data_in_the_repository(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("WAYPOINT_DATA", None)
            with mock.patch("os.makedirs") as made:
                self.assertEqual(db.data_dir(), os.path.join(REPO, "data"))
        made.assert_called_once()

    def test_waypoint_data_still_wins(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_DATA": "/somewhere/else"}), mock.patch("os.makedirs"):
            self.assertEqual(db.data_dir(), "/somewhere/else")

    def test_the_migrations_use_the_repositorys_alembic_ini(self):
        self.assertTrue(os.path.isfile(os.path.join(REPO, "alembic.ini")))
        self.assertEqual(db.alembic_config().config_file_name, os.path.join(REPO, "alembic.ini"))


if __name__ == "__main__":
    unittest.main()
