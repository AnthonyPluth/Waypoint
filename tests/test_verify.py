import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from waypoint import verify

REAL_POPEN = subprocess.Popen


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

    def test_the_demo_server_gets_only_the_variables_it_needs_never_a_provider_credential(self):
        secrets = {"GOOGLE_CLIENT_ID": "real-id", "GOOGLE_CLIENT_SECRET": "real-secret", "OPENROUTER_API_KEY": "sk-real", "GITHUB_TOKEN": "ghp_real",
                   "AWS_SECRET_ACCESS_KEY": "aws", "NODE_AUTH_TOKEN": "npm", "ANTHROPIC_API_KEY": "sk-ant", "VAPID_PRIVATE_KEY": "vapid",
                   "WAYPOINT_SECRET_KEY": "k", "SOMETHING_NEW_TOKEN": "t"}
        needed = {"PATH": "/bin", "HOME": "/root", "LANG": "C.UTF-8", "LC_ALL": "C", "PYTHONPATH": "/x", "PLAYWRIGHT_BROWSERS_PATH": "/opt/pw", "VIRTUAL_ENV": "/venv"}
        env = verify.clean_env("/tmp/demo", {**secrets, **needed})
        self.assertFalse(set(secrets) & set(env))
        self.assertEqual({k: env[k] for k in needed}, needed)
        with mock.patch.dict("os.environ", secrets, clear=False):
            self.assertFalse(set(secrets) & set(verify.frozen_env(verify.clean_env("/tmp/demo"), "/lib/f.so")))

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


class JobsTests(unittest.TestCase):
    def test_the_default_is_the_cpu_count_capped_at_four(self):
        self.assertEqual([verify.default_jobs(n) for n in (0, 1, 2, 4, 16)], [1, 1, 2, 4, 4])
        with mock.patch("os.cpu_count", return_value=3):
            self.assertEqual(verify.default_jobs(), 3)
        with mock.patch("os.cpu_count", return_value=None):
            self.assertEqual(verify.default_jobs(), 1)

    def test_the_flag_beats_the_environment_which_beats_the_default(self):
        self.assertEqual(verify.resolve_jobs(2, {"VERIFY_JOBS": "3"}, cpus=8), 2)
        self.assertEqual(verify.resolve_jobs(None, {"VERIFY_JOBS": "3"}, cpus=8), 3)
        self.assertEqual(verify.resolve_jobs(None, {"VERIFY_JOBS": " "}, cpus=8), 4)
        self.assertEqual(verify.resolve_jobs(None, {}, cpus=2), 2)
        self.assertEqual(verify.resolve_jobs(1, {}, cpus=8), 1)

    def test_a_count_that_is_not_a_positive_whole_number_names_where_it_came_from(self):
        for flag, env, source in ((0, {}, "--jobs"), (-1, {}, "--jobs"), (None, {"VERIFY_JOBS": "many"}, "VERIFY_JOBS"), (None, {"VERIFY_JOBS": "0"}, "VERIFY_JOBS")):
            with self.assertRaisesRegex(ValueError, source):
                verify.resolve_jobs(flag, env)

    def test_run_refuses_a_bad_count_before_starting_anything(self):
        with mock.patch("os.path.isdir", return_value=True), mock.patch("os.path.isfile", return_value=True), \
                mock.patch("shutil.which", return_value="/usr/bin/node"), mock.patch.object(verify, "find_faketime", return_value="/lib/f.so"), \
                mock.patch.object(verify, "start_instances") as started, mock.patch("builtins.print") as out:
            self.assertEqual(verify.run([], 0), 2)
        self.assertIn("--jobs", out.call_args.args[0])
        started.assert_not_called()

    def test_the_browser_gets_every_server_address_the_flows_and_the_pages(self):
        command = verify.node_command("node", "/app/frontend", ["http://127.0.0.1:1", "http://127.0.0.1:2"], ["trips"], ["add-trip"])
        self.assertEqual([command[i + 1] for i, a in enumerate(command) if a == "--url"], ["http://127.0.0.1:1", "http://127.0.0.1:2"])
        self.assertEqual(command[command.index("--flow") + 1], "add-trip")
        self.assertEqual(command[-1], "trips")
        self.assertEqual(command[command.index("--now") + 1], verify.FROZEN_NOW_ISO)


class InstanceTests(unittest.TestCase):
    def fakes(self, root, ready=None):
        seeded = []

        def seed(command, env, **_):
            seeded.append(env["WAYPOINT_DATA"])
            with open(os.path.join(env["WAYPOINT_DATA"], "waypoint.db"), "w") as f:
                f.write("seed")
            return mock.Mock(returncode=0, stdout="", stderr="")

        self.servers = []

        def start(*args, **kwargs):
            self.servers.append(mock.Mock(spec=REAL_POPEN, returncode=None))
            return self.servers[-1]

        popen = mock.Mock(side_effect=start)
        ports = iter(range(9101, 9110))
        return seeded, mock.patch("subprocess.run", side_effect=seed), mock.patch("subprocess.Popen", popen), \
            mock.patch.object(verify, "free_port", side_effect=lambda: next(ports)), mock.patch.object(verify, "wait_ready", side_effect=ready), popen

    def test_every_server_gets_its_own_copy_of_one_seed_and_its_own_port(self):
        with tempfile.TemporaryDirectory() as root:
            seeded, run, popen_patch, port, ready, popen = self.fakes(root)
            with run, popen_patch, port, ready:
                instances = verify.start_instances(root, 3, "/lib/f.so")
            self.assertEqual(len(seeded), 1)
            self.assertEqual([i.url for i in instances], ["http://127.0.0.1:9101", "http://127.0.0.1:9102", "http://127.0.0.1:9103"])
            self.assertEqual(len({i.data for i in instances}), 3)
            for instance in instances:
                with open(os.path.join(instance.data, "waypoint.db")) as f:
                    self.assertEqual(f.read(), "seed")
            datas = [call.kwargs["env"]["WAYPOINT_DATA"] for call in popen.call_args_list]
            self.assertEqual(datas, [i.data for i in instances])
            self.assertTrue(all(call.kwargs["env"]["FAKETIME"] == verify.FROZEN_NOW for call in popen.call_args_list))

    def test_one_server_is_served_from_the_seeded_folder_itself(self):
        with tempfile.TemporaryDirectory() as root:
            seeded, run, popen_patch, port, ready, _ = self.fakes(root)
            with run, popen_patch, port, ready:
                (only,) = verify.start_instances(root, 1, "/lib/f.so")
            self.assertEqual(seeded, [only.data])

    def test_a_server_that_does_not_come_up_stops_the_others_and_says_which(self):
        with tempfile.TemporaryDirectory() as root:
            def ready(url, server, timeout=60):
                if url.endswith("9102"):
                    raise RuntimeError("the server exited with code 3 before it was ready")

            _, run, popen_patch, port, patched, _ = self.fakes(root, ready)
            with run, popen_patch, port, patched:
                with self.assertRaisesRegex(RuntimeError, "exited with code 3"):
                    verify.start_instances(root, 2, "/lib/f.so")
            self.assertEqual(len(self.servers), 2)
            for server in self.servers:
                server.terminate.assert_called_once()

    def test_a_failed_seed_is_reported_with_its_output(self):
        with tempfile.TemporaryDirectory() as root, mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout="out", stderr="err")), \
                mock.patch("subprocess.Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "couldn't fill the demo database:\nouterr"):
                verify.start_instances(root, 2, "/lib/f.so")
        popen.assert_not_called()


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


class ControlSessionTests(unittest.TestCase):
    def test_seed_runs_run_py_demo_frozen_in_a_new_folder(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(verify, "find_faketime", return_value="/lib/f.so"), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as ran:
            self.assertEqual(verify.seed(["--data", os.path.join(tmp, "seed")]), 0)
            argv, env = ran.call_args.args[0], ran.call_args.kwargs["env"]
            self.assertEqual(argv[-1], "demo")
            self.assertEqual((env["FAKETIME"], env["WAYPOINT_DATA"], env["LD_PRELOAD"]), (verify.FROZEN_NOW, os.path.join(tmp, "seed"), "/lib/f.so"))
            self.assertTrue(os.path.isdir(os.path.join(tmp, "seed")))

    def test_seed_never_goes_on_top_of_data_that_is_there_and_needs_the_clock(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("subprocess.run") as ran, mock.patch("sys.stderr"):
            with mock.patch.object(verify, "find_faketime", return_value="/lib/f.so"):
                self.assertEqual(verify.seed(["--data", tmp]), 2)
            with mock.patch.object(verify, "find_faketime", return_value=None):
                self.assertEqual(verify.seed(["--data", os.path.join(tmp, "new")]), 2)
            ran.assert_not_called()

    def test_a_seed_that_fails_leaves_no_folder(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(verify, "find_faketime", return_value="/lib/f.so"), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout="", stderr="boom")), mock.patch("sys.stderr"):
            self.assertEqual(verify.seed(["--data", os.path.join(tmp, "seed")]), 2)
            self.assertFalse(os.path.exists(os.path.join(tmp, "seed")))

    def test_serve_copies_the_seed_and_becomes_the_server_on_demo_data_only(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(verify, "find_faketime", return_value="/lib/f.so"), \
                mock.patch.object(verify, "die_with_parent") as dies, mock.patch("os.execve") as execve, mock.patch("os.chdir"), \
                mock.patch("os.dup2"), mock.patch("signal.signal"), mock.patch.dict("os.environ", {"DATABASE_URL": "postgresql://real", "OIDC_ISSUER": "https://idp"}):
            seed = os.path.join(tmp, "seed")
            os.mkdir(seed)
            with open(os.path.join(seed, "waypoint.db"), "w") as f:
                f.write("seeded")
            data = os.path.join(tmp, "data")
            verify.serve(["--parent", "42", "--seed", seed, "--data", data, "--port", "9200"])
            dies.assert_called_once_with(42)
            with open(os.path.join(data, "waypoint.db")) as f:
                self.assertEqual(f.read(), "seeded")
            command, env = execve.call_args.args[1], execve.call_args.args[2]
            self.assertEqual(command[-4:], ["--host", "127.0.0.1", "--port", "9200"])
            self.assertEqual((env["WAYPOINT_DATA"], env["FAKETIME"], env["HTTPS_PROXY"]), (data, verify.FROZEN_NOW, verify.NO_OUTSIDE))
            self.assertFalse({"DATABASE_URL", "OIDC_ISSUER"} & set(env))

    def test_serve_refuses_a_folder_that_exists_and_does_not_remove_it(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(verify, "find_faketime", return_value="/lib/f.so"), \
                mock.patch.object(verify, "die_with_parent"), mock.patch("os.execve") as execve, mock.patch("signal.signal"), mock.patch("sys.stderr"):
            seed = os.path.join(tmp, "seed")
            os.mkdir(seed)
            self.assertEqual(verify.serve(["--parent", "42", "--seed", seed, "--data", tmp, "--port", "9200"]), 2)
            self.assertTrue(os.path.isdir(tmp))
            execve.assert_not_called()

    def test_a_child_whose_parent_is_already_gone_is_sent_the_signal(self):
        with mock.patch("os.getppid", return_value=1), mock.patch("os.kill") as kill:
            verify.die_with_parent(parent=4242)
        kill.assert_called_once_with(os.getpid(), verify.signal.SIGTERM)
        with mock.patch("os.getppid", return_value=4242), mock.patch("os.kill") as kill:
            verify.die_with_parent(parent=4242)
        kill.assert_not_called()

    def test_a_running_verify_is_found_by_its_command_line(self):
        self.assertTrue(verify.is_verify(["node", "/r/frontend/verify/verify.mjs", "--url", "x"]))
        self.assertTrue(verify.is_verify(["python", "/r/run.py", "verify", "trips"]))
        self.assertFalse(verify.is_verify(["python", "/r/run.py", "--port", "1"]))
        self.assertFalse(verify.is_verify(["node", "/r/frontend/verify/control-daemon.mjs", "--dir", "d"]))
        with tempfile.TemporaryDirectory() as proc:
            for pid, argv in ((11, ["python", "run.py", "--port", "1"]), (12, ["node", "/r/frontend/verify/verify.mjs"])):
                os.makedirs(os.path.join(proc, str(pid)))
                with open(os.path.join(proc, str(pid), "cmdline"), "wb") as f:
                    f.write("\0".join(argv).encode())
            self.assertIn("pid 12", verify.verify_running(proc) or "")
            os.remove(os.path.join(proc, "12", "cmdline"))
            self.assertIsNone(verify.verify_running(proc))
        self.assertIsNone(verify.verify_running("/no/such/proc"))

    def test_status_reports_the_clock_the_load_and_a_running_verify(self):
        with mock.patch.object(verify, "busy_now", return_value=2.0), mock.patch.object(verify, "verify_running", return_value=None), \
                mock.patch.object(verify, "find_faketime", return_value="/lib/f.so"):
            got = verify.status()
        self.assertEqual((got["frozen_now"], got["frozen_now_iso"], got["busy"], got["busy_limit"], got["verify_running"]),
                         (verify.FROZEN_NOW, verify.FROZEN_NOW_ISO, True, verify.BUSY, None))
        json.dumps(got)
        with mock.patch.object(verify, "busy_now", return_value=0.5), mock.patch.object(verify, "verify_running", return_value=None):
            self.assertFalse(verify.status()["busy"])

    def test_the_control_commands_run_from_the_command_line(self):
        out = subprocess.run([sys.executable, "-m", "waypoint.verify", "status"], cwd=verify.ROOT, capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out)["frozen_now"], verify.FROZEN_NOW)
        usage = subprocess.run([sys.executable, "-m", "waypoint.verify"], cwd=verify.ROOT, capture_output=True, text=True)
        self.assertEqual(usage.returncode, 1)
        self.assertIn("usage: python -m waypoint.verify serve", usage.stderr)


if __name__ == "__main__":
    unittest.main()
