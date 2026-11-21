import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from waypoint.server import handler
from tests.shared import ServerCase


class ServerTests(ServerCase):
    def test_state_and_static(self):
        code, st = self.req("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(st["user"], {"name": None, "email": None, "local": True})
        with urllib.request.urlopen(self.base + "/manifest.webmanifest") as resp:
            self.assertIn(b"Waypoint", resp.read())
            self.assertEqual(resp.headers["Content-Type"].split(";")[0], "application/manifest+json")
        with urllib.request.urlopen(self.base + "/sw.js") as resp:
            self.assertEqual(resp.headers["Content-Type"].split(";")[0], "text/javascript")

    def test_csrf_header_required(self):
        code, _ = self.req("POST", "/api/restore", {}, headers={"X-Waypoint": "0"})
        self.assertEqual(code, 403)

    def test_foreign_host_rejected(self):
        r = urllib.request.Request(self.base + "/api/state", headers={"Host": "evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r)
        self.assertEqual(cm.exception.code, 403)

    def test_an_address_no_route_answers_is_a_404(self):
        self.assertEqual(self.req("GET", "/api/transactions"), (404, {"error": "Not found"}))
        self.assertEqual(self.req("POST", "/api/state", {}), (404, {"error": "Not found"}))


class HangUpLateTests(unittest.TestCase):
    def serve(self):
        httpd = handler.Server(("127.0.0.1", 0), handler.Handler)
        self.addCleanup(httpd.server_close)
        return httpd

    def hang_ups(self):
        return {t for t in threading.enumerate() if t.name == "hang-up-late"}

    def test_it_never_waits_on_an_event_with_a_timeout_which_returns_at_once_under_the_frozen_clock(self):
        timed_waits = []
        real_wait = threading.Event.wait

        def fast_wait(event, timeout=None):
            if threading.current_thread() is not threading.main_thread() and timeout is not None:
                timed_waits.append(timeout)
                return False
            return real_wait(event, timeout)

        with mock.patch.object(threading.Event, "wait", fast_wait):
            httpd = self.serve()
            cpu_before = time.process_time()
            time.sleep(0.3)
            httpd.server_close()
        self.assertEqual(timed_waits, [])
        self.assertLess(time.process_time() - cpu_before, 0.15)

    def test_a_connection_past_its_deadline_is_hung_up_and_one_that_is_not_yet_late_is_left(self):
        httpd = self.serve()
        late_client, late = socket.socketpair()
        fresh_client, fresh = socket.socketpair()
        self.addCleanup(lambda: [s.close() for s in (late_client, late, fresh_client, fresh)])
        httpd.set_deadline(late, -1)
        httpd.set_deadline(fresh, 60)
        late_client.settimeout(5)
        self.assertEqual(late_client.recv(1), b"")
        fresh_client.settimeout(0.1)
        with self.assertRaises(TimeoutError):
            fresh_client.recv(1)
        httpd.set_deadline(late, None)

    def test_a_failed_bind_raises_the_bind_error_and_leaves_no_thread_behind(self):
        before = self.hang_ups()
        taken = self.serve()
        ours = self.hang_ups() - before
        self.assertEqual(len(ours), 1)
        with self.assertRaises(OSError) as raised:
            handler.Server(taken.server_address, handler.Handler)
        self.assertNotIsInstance(raised.exception, AttributeError)
        self.assertEqual(self.hang_ups() - before, ours)

    def test_closing_the_server_stops_the_thread_at_once_and_closing_twice_is_fine(self):
        before = self.hang_ups()
        httpd = self.serve()
        [thread] = self.hang_ups() - before
        httpd.server_close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        httpd.server_close()


if __name__ == "__main__":
    unittest.main()
