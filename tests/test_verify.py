import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from waypoint import verify


class ServerCommandTests(unittest.TestCase):
    def test_the_demo_server_listens_on_loopback_whatever_waypoint_host_says(self):
        with mock.patch.dict("os.environ", {"WAYPOINT_HOST": "0.0.0.0"}):
            command = verify.server_command(8123)
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--port") + 1], "8123")


class CleanEnvTests(unittest.TestCase):
    def test_the_demo_server_never_sees_real_data_settings(self):
        base = {"PATH": "/bin", "DATABASE_URL": "postgresql://real", "WAYPOINT_DATA": "/real", "OIDC_ISSUER": "https://idp",
                "SENTRY_DSN": "https://k@sentry", "WAYPOINT_SECRET_KEY": "real", "WAYPOINT_PUBLIC_URL": "https://r"}
        env = verify.clean_env("/tmp/demo", base)
        self.assertEqual(env, {"PATH": "/bin", "WAYPOINT_DATA": "/tmp/demo", "PYTHONUNBUFFERED": "1"})


class RunPyFileArgumentTests(unittest.TestCase):
    """run.py's file argument takes several words now (verify's pages); backup and restore still take one file."""

    def run_py(self, tmp, *args):
        return subprocess.run([sys.executable, os.path.join(verify.ROOT, "run.py"), *args], cwd=tmp,
                              env=verify.clean_env(tmp), capture_output=True, text=True, timeout=120)

    def test_backup_still_saves_to_the_one_file_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_py(tmp, "backup", "out.json.gz")
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(os.path.join(tmp, "out.json.gz"), "rb") as f:
                self.assertEqual(f.read(2), b"\x1f\x8b")

    def test_backup_and_restore_refuse_a_second_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            for command in ("backup", "restore"):
                done = self.run_py(tmp, command, "a.json.gz", "b.json.gz")
                self.assertEqual(done.returncode, 2, command)
                self.assertIn("only one file, please", done.stderr)
            self.assertEqual(os.listdir(tmp), [])

    def test_restore_without_a_file_still_asks_which(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_py(tmp, "restore")
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("Which backup file?", done.stderr)


class RunTests(unittest.TestCase):
    def test_a_server_that_dies_is_reported_not_waited_for(self):
        server = mock.Mock(spec=subprocess.Popen)
        server.poll.return_value = 3
        server.returncode = 3
        with self.assertRaisesRegex(RuntimeError, "exited with code 3"):
            verify.wait_ready("http://127.0.0.1:1", server, timeout=5)

    def test_the_readiness_check_skips_the_system_proxy(self):
        server = mock.Mock(spec=subprocess.Popen)
        server.poll.return_value = None
        with mock.patch.dict("os.environ", {"HTTP_PROXY": "http://proxy:3128", "http_proxy": "http://proxy:3128"}), \
                mock.patch("waypoint.tls.urlopen") as opened:
            verify.wait_ready("http://127.0.0.1:8123", server, timeout=5)
        (handler,) = opened.call_args.kwargs["handlers"]
        self.assertEqual(handler.proxies, {})

    def test_a_server_that_never_answers_times_out_with_the_address(self):
        server = mock.Mock(spec=subprocess.Popen)
        server.poll.return_value = None
        with self.assertRaisesRegex(RuntimeError, r"http://127\.0\.0\.1:1 after 0 seconds"):
            verify.wait_ready("http://127.0.0.1:1", server, timeout=0)

    def test_missing_packages_say_what_to_run(self):
        with mock.patch("os.path.isdir", return_value=False), mock.patch("builtins.print") as out:
            self.assertEqual(verify.run([]), 2)
        self.assertIn("npm ci", out.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
