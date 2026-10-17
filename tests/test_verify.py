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
                "WAYPOINT_SECRET_KEY": "real", "WAYPOINT_PUBLIC_URL": "https://r"}
        env = verify.clean_env("/tmp/demo", base)
        self.assertEqual(env, {"PATH": "/bin", "WAYPOINT_DATA": "/tmp/demo", "PYTHONUNBUFFERED": "1",
                               "RAPIDAPI_KEY": verify.DEMO_KEY, "HTTPS_PROXY": verify.NO_OUTSIDE, "https_proxy": verify.NO_OUTSIDE})

    def test_the_demo_server_has_a_made_up_flight_status_key_and_reaches_nobody(self):
        base = {"RAPIDAPI_KEY": "real-key-12345678", "HTTPS_PROXY": "http://proxy:3128", "HTTP_PROXY": "http://proxy:3128",
                "all_proxy": "socks5://proxy"}
        env = verify.clean_env("/tmp/demo", base)
        self.assertEqual((env["RAPIDAPI_KEY"], env["HTTPS_PROXY"]), (verify.DEMO_KEY, verify.NO_OUTSIDE))
        self.assertFalse({"HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"} & set(env))


class RunPyFileArgumentTests(unittest.TestCase):

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

    def test_without_libfaketime_it_stops_and_says_how_to_install_it(self):
        with mock.patch("os.path.isdir", return_value=True), mock.patch("os.path.isfile", return_value=True), \
                mock.patch("shutil.which", return_value="/usr/bin/node"), mock.patch.object(verify, "find_faketime", return_value=None), \
                mock.patch("builtins.print") as out, mock.patch("subprocess.run") as ran:
            self.assertEqual(verify.run([]), 2)
        self.assertIn("sudo apt-get install libfaketime", out.call_args.args[0])
        self.assertIn("macOS", out.call_args.args[0])
        ran.assert_not_called()


class FrozenClockTests(unittest.TestCase):
    def test_the_library_is_found_where_debian_puts_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = os.path.join(tmp, "libfaketime.so.1")
            self.assertIsNone(verify.find_faketime((library,)))
            open(library, "w").close()
            self.assertEqual(verify.find_faketime(("/nowhere/x.so", library)), library)

    def test_the_server_and_the_seed_run_on_one_fixed_date_in_one_zone(self):
        env = verify.frozen_env({"PATH": "/bin", "TZ": "America/Denver"}, "/lib/libfaketime.so.1")
        self.assertEqual((env["LD_PRELOAD"], env["FAKETIME"], env["TZ"]), ("/lib/libfaketime.so.1", verify.FROZEN_NOW, "UTC"))
        self.assertEqual(env["PATH"], "/bin")

    def test_the_browser_gets_the_same_date_as_the_server(self):
        self.assertEqual(verify.FROZEN_NOW_ISO, verify.FROZEN_NOW.replace(" ", "T") + "Z")

    def test_images_go_to_the_docs_assets_and_the_report_stays_in_artifacts(self):
        self.assertTrue(verify.IMAGES.endswith(os.path.join("docs", "src", "assets", "screenshots")))
        self.assertTrue(verify.OUT.endswith(os.path.join("artifacts", "verify")))


if __name__ == "__main__":
    unittest.main()
