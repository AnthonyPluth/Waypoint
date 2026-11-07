import contextlib
import http.client
import io
import socket
import socketserver
import ssl
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from waypoint import oidc, tls


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class TlsTests(unittest.TestCase):
    def test_one_context_that_checks_certificates(self):
        ctx = tls.ssl_context()
        self.assertIs(tls.ssl_context(), ctx)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_the_context_refuses_anything_older_than_tls_1_2(self):
        self.assertEqual(tls.ssl_context().minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_only_web_addresses_are_opened_before_anything_is_sent(self):
        opened = mock.Mock(side_effect=AssertionError("nothing may be opened"))
        refused = ["file:///etc/passwd", "ftp://example.com/x", "data:text/plain,hi", "http://example.com/", "gopher://x/",
                   "/etc/passwd"]
        with mock.patch.object(urllib.request.OpenerDirector, "open", opened), \
                mock.patch("socket.create_connection", opened), mock.patch("socket.getaddrinfo", opened):
            for url in refused:
                for req in (url, urllib.request.Request(url) if ":" in url else url):
                    with self.subTest(url=url), self.assertRaises(urllib.error.URLError):
                        tls.urlopen(req, timeout=1)
            for url in ("file:///etc/passwd", "ftp://example.com/x", "data:text/plain,hi"):
                with self.subTest(url=url, allow_http=True), self.assertRaises(urllib.error.URLError):
                    tls.urlopen(url, timeout=1, allow_http=True)
        opened.assert_not_called()

    def test_its_opener_has_no_handler_for_other_schemes(self):
        for allow_http in (False, True):
            o = tls.opener(allow_http=allow_http)
            kinds = {type(h) for h in o.handlers}
            for absent in (urllib.request.FileHandler, urllib.request.FTPHandler, urllib.request.DataHandler):
                self.assertNotIn(absent, kinds)
            self.assertEqual(urllib.request.HTTPHandler in kinds, allow_http)
            https = next(h for h in o.handlers if isinstance(h, urllib.request.HTTPSHandler))
            self.assertIs(https._context, tls.ssl_context())
            with self.assertRaises(urllib.error.URLError):
                next(h for h in o.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)).redirect_request(
                    urllib.request.Request("https://example.com/"), None, 302, "Found", {}, "ftp://example.com/x")
        o = tls.opener(_NoRedirects())
        self.assertEqual([type(h) for h in o.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)], [_NoRedirects])
        with self.assertRaises(urllib.error.URLError):
            o.open("file:///etc/passwd", timeout=1)

    def test_https_is_opened_with_the_shared_context(self):
        seen = []

        def open_(self, req, timeout=None):
            seen.append((req.full_url if isinstance(req, urllib.request.Request) else req,
                         next(h for h in self.handlers if isinstance(h, urllib.request.HTTPSHandler))._context))
            return io.BytesIO(b"{}")
        with mock.patch.object(urllib.request.OpenerDirector, "open", open_):
            oidc._get_json("https://idp.invalid/.well-known/openid-configuration")
            oidc._get_json("http://idp.lan/.well-known/openid-configuration")
            tls.urlopen("https://example.com/", timeout=1)
        self.assertEqual([u for u, _ in seen], ["https://idp.invalid/.well-known/openid-configuration",
                                                "http://idp.lan/.well-known/openid-configuration", "https://example.com/"])
        self.assertTrue(all(ctx is tls.ssl_context() for _, ctx in seen))


class _Scripted(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, parts: list[tuple[bytes, float]], wait_for_request: bool = True):
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.server.connections += 1   # type: ignore[attr-defined]
                seen = b""
                while self.server.wait_for_request and b"\r\n\r\n" not in seen:   # type: ignore[attr-defined]
                    got = self.request.recv(4096)
                    if not got:
                        return
                    seen += got
                for data, pause in self.server.parts:   # type: ignore[attr-defined]
                    if not data:
                        time.sleep(pause)
                        continue
                    for i in range(len(data)) if pause else [None]:
                        try:
                            self.request.sendall(data[i:i + 1] if i is not None else data)
                        except OSError:
                            return
                        time.sleep(pause)
        super().__init__(("127.0.0.1", 0), Handler)
        self.parts = parts
        self.wait_for_request = wait_for_request
        self.connections = 0

    def handle_error(self, request, client_address):
        pass


HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nX-Pad: " + b"y" * 120 + b"\r\n"


class DeadlineTests(unittest.TestCase):
    def serve(self, parts, wait_for_request=True) -> str:
        server = _Scripted(parts, wait_for_request)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.server = server
        return f"http://127.0.0.1:{server.server_address[1]}/"

    def open(self, url, seconds):
        return tls.urlopen(url, 10, allow_http=True, handlers=(urllib.request.ProxyHandler({}),),
                           deadline=time.monotonic() + seconds)

    def cut_off(self, url, read_body=False):
        began = time.monotonic()
        with self.assertRaises((TimeoutError, urllib.error.URLError)):
            with self.open(url, 0.5) as r:
                if read_body:
                    r.read()
        self.assertLess(time.monotonic() - began, 2.0)

    def test_a_status_line_and_header_block_that_trickle_are_cut_off_at_the_deadline(self):
        self.cut_off(self.serve([(HEAD + b"Content-Length: 2\r\n\r\nok", 0.03)]))

    def test_a_server_that_stalls_inside_the_headers_is_cut_off_at_the_deadline(self):
        self.cut_off(self.serve([(b"HTTP/1.1 200 OK\r\n", 0), (b"X", 4), (b"-A: b\r\n\r\n", 0)]))

    def test_a_body_after_quick_headers_is_held_to_the_same_deadline(self):
        self.cut_off(self.serve([(b"HTTP/1.1 200 OK\r\nContent-Length: 200\r\n\r\n", 0), (b"z" * 200, 0.03)]), read_body=True)

    def test_a_chunked_body_whose_size_lines_trickle_is_held_to_the_deadline(self):
        chunked = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
        self.cut_off(self.serve([(chunked, 0), (b"2;" + b"x" * 150 + b"\r\nok\r\n0\r\n\r\n", 0.03)]), read_body=True)

    def test_each_read_still_waits_no_longer_than_the_timeout(self):
        url = self.serve([(b"HTTP/1.1 200 OK\r\n", 0), (b"", 3), (b"Content-Length: 0\r\n\r\n", 0)])
        began = time.monotonic()
        with self.assertRaises((TimeoutError, urllib.error.URLError)):
            tls.urlopen(url, 0.3, allow_http=True, handlers=(urllib.request.ProxyHandler({}),), deadline=time.monotonic() + 60)
        self.assertLess(time.monotonic() - began, 2.0)

    def test_a_reply_inside_the_deadline_is_read_whole(self):
        for head, body, expected in ((b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n", b"hello", b"hello"),
                                     (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n", b"5\r\nhello\r\n0\r\n\r\n", b"hello")):
            url = self.serve([(head, 0), (b"", 0.2), (body, 0)])
            with self.subTest(head=head), self.open(url, 5) as r:
                self.assertEqual(r.read(), expected)

    def test_a_deadline_already_past_opens_nothing(self):
        url = self.serve([(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", 0)])
        with self.assertRaises((TimeoutError, urllib.error.URLError)):
            tls.urlopen(url, 10, allow_http=True, handlers=(urllib.request.ProxyHandler({}),), deadline=time.monotonic() - 1)
        self.assertEqual(self.server.connections, 0)

    def test_a_deadline_is_not_combined_with_public_only(self):
        opened = mock.Mock(side_effect=AssertionError("nothing may be opened"))
        with mock.patch.object(urllib.request.OpenerDirector, "open", opened), self.assertRaises(ValueError):
            tls.urlopen("https://example.com/", 5, public_only=True, deadline=time.monotonic() + 5)
        opened.assert_not_called()

    def test_a_proxy_that_trickles_its_connect_answer_is_cut_off_at_the_deadline(self):
        proxy = self.serve([(b"HTTP/1.1 200 Connection established\r\nX-Pad: " + b"y" * 150 + b"\r\n\r\n", 0.03)])
        began = time.monotonic()
        with self.assertRaises(OSError):
            tls.urlopen("https://photos.example.invalid/", 10, handlers=(urllib.request.ProxyHandler({"https": proxy}),),
                        deadline=time.monotonic() + 0.5)
        self.assertLess(time.monotonic() - began, 2.0)
        self.assertEqual(self.server.connections, 1)

    def test_the_tunnel_hands_the_plain_socket_back_for_the_handshake(self):
        proxy = self.serve([(b"HTTP/1.1 200 Connection established\r\n\r\n", 0)])
        context = tls.ssl_context()
        wrapped = mock.Mock()
        conn = tls._DeadlineHTTPSConnection("127.0.0.1", self.server.server_address[1], timeout=5, deadline=time.monotonic() + 5,
                                            context=context)
        conn.set_tunnel("photos.example.invalid", 443)
        with mock.patch.object(context, "wrap_socket", return_value=wrapped) as wrap:
            conn.connect()
        [(plain,), kwargs] = wrap.call_args
        self.assertIsInstance(plain, socket.socket)
        self.assertEqual(kwargs["server_hostname"], "photos.example.invalid")
        self.assertIsInstance(conn.sock, tls._DeadlineSocket)
        self.assertIs(conn.sock.sock, wrapped)
        plain.close()
        self.assertTrue(proxy)

    def test_a_proxy_that_refuses_the_tunnel_closes_the_connection(self):
        proxy = self.serve([(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n", 0)])
        conn = tls._DeadlineHTTPSConnection("127.0.0.1", self.server.server_address[1], timeout=5, deadline=time.monotonic() + 5,
                                            context=tls.ssl_context())
        conn.set_tunnel("photos.example.invalid", 443)
        with self.assertRaises(OSError):
            conn.connect()
        self.assertIsNone(conn.sock)
        self.assertTrue(proxy)

    def handshake_cut_off(self, parts, wait_for_request):
        port = self.serve(parts, wait_for_request).rsplit(":", 1)[1].rstrip("/")
        began = time.monotonic()
        with self.assertRaises(OSError):
            tls.urlopen(f"https://127.0.0.1:{port}/", 10, handlers=(urllib.request.ProxyHandler({}),), deadline=time.monotonic() + 0.5)
        self.assertLess(time.monotonic() - began, 2.0)

    def test_a_server_that_never_answers_the_handshake_is_cut_off_at_the_deadline(self):
        self.handshake_cut_off([(b"", 5)], wait_for_request=True)

    def test_a_server_that_trickles_its_handshake_is_cut_off_at_the_deadline(self):
        self.handshake_cut_off([(b"\x16\x03\x03\x40\x00" + b"\x02" * 300, 0.03)], wait_for_request=False)

    def test_https_opens_the_deadline_connection_with_the_shared_context(self):
        deadline = time.monotonic() + 5
        with mock.patch.object(urllib.request.AbstractHTTPHandler, "do_open", autospec=True) as do_open:
            tls._DeadlineHTTPSHandler(deadline).https_open(urllib.request.Request("https://example.com/"))
        [(_, connection, req), kwargs] = do_open.call_args
        self.assertIs(connection.func, tls._DeadlineHTTPSConnection)
        self.assertEqual(connection.keywords, {"deadline": deadline})
        self.assertIs(kwargs["context"], tls.ssl_context())
        self.assertEqual(req.full_url, "https://example.com/")

    def test_an_https_connection_is_bounded_by_the_deadline_and_keeps_its_idle_timeout(self):
        plain, secured = mock.Mock(), mock.Mock()

        def connected(conn):
            conn.sock = plain
        for timeout in (5, object()):
            context = tls.ssl_context()
            conn = tls._DeadlineHTTPSConnection("example.com", timeout=timeout, deadline=time.monotonic() + 1, context=context)
            with self.subTest(timeout=timeout), mock.patch.object(http.client.HTTPConnection, "connect", connected), \
                    mock.patch.object(context, "wrap_socket", return_value=secured) as wrap:
                conn.connect()
                self.assertLessEqual(conn.timeout, 1)
                self.assertIsInstance(conn.sock, tls._DeadlineSocket)
                self.assertIs(conn.sock.sock, secured)
                self.assertIs(conn.sock.timeout, timeout)
                self.assertLessEqual(conn.sock.wait(), 1)
                wrap.assert_called_once_with(plain, server_hostname="example.com")
                [(handshake_timeout,), _] = plain.settimeout.call_args
                self.assertLessEqual(handshake_timeout, 1)

    def test_a_connection_that_ends_up_with_no_socket_is_an_error(self):
        conn = tls._DeadlineHTTPSConnection("example.com", timeout=5, deadline=time.monotonic() + 1, context=tls.ssl_context())
        with mock.patch.object(http.client.HTTPConnection, "connect", lambda conn: None), self.assertRaises(OSError):
            conn.connect()

    def test_every_context_a_request_can_use_needs_tls_1_2_or_newer(self):
        weak = mock.Mock(spec=ssl.SSLContext)
        conn = tls._DeadlineHTTPSConnection("example.com", timeout=5, deadline=time.monotonic() + 5, context=weak)
        handlers = [*tls.opener(allow_http=True).handlers, tls._DeadlineHTTPSHandler(time.monotonic() + 5)]
        contexts = [conn.secure_with, *(h._context for h in handlers if isinstance(h, urllib.request.HTTPSHandler))]
        self.assertEqual(len(contexts), 3)
        for context in contexts:
            with self.subTest(context=context):
                self.assertIs(context, tls.ssl_context())
                self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_without_a_deadline_the_standard_handlers_are_used(self):
        kinds = {type(h) for h in tls.opener(allow_http=True).handlers}
        self.assertIn(urllib.request.HTTPSHandler, kinds)
        self.assertIn(urllib.request.HTTPHandler, kinds)


class _Unanswered:
    made: list[_Unanswered] = []
    answers_at: set[int] = set()
    refuse = False
    delay = 0.0

    def __init__(self, family, kind, proto):
        self.timeout = None
        self.address = None
        self.bound = None
        _Unanswered.made.append(self)

    def bind(self, address):
        self.bound = address

    def settimeout(self, timeout):
        self.timeout = timeout

    def setsockopt(self, *args):
        pass

    def connect(self, address):
        self.address = address
        if address[1] in _Unanswered.answers_at:
            time.sleep(_Unanswered.delay)
            return
        if _Unanswered.refuse:
            raise ConnectionRefusedError("refused")
        time.sleep(self.timeout)
        raise TimeoutError("timed out")

    def close(self):
        pass


class ConnectDeadlineTests(unittest.TestCase):
    ADDRESSES = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", port)) for port in range(8001, 8007)]

    def connect(self, cls, answers_at=(), refuse=False, delay=0.0, **kwargs):
        _Unanswered.made, _Unanswered.answers_at, _Unanswered.refuse, _Unanswered.delay = [], set(answers_at), refuse, delay
        conn = cls("photos.example.invalid", 8000, timeout=10, deadline=time.monotonic() + 0.5, **kwargs)
        with mock.patch.object(socket, "getaddrinfo", return_value=self.ADDRESSES), mock.patch.object(socket, "socket", _Unanswered):
            conn.connect()
        return conn

    def test_several_unanswered_addresses_together_stay_inside_the_deadline(self):
        began = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.connect(tls._DeadlineHTTPConnection)
        self.assertLess(time.monotonic() - began, 1.5)
        self.assertTrue(all(s.timeout <= 0.5 for s in _Unanswered.made))

    def test_the_first_address_that_answers_inside_the_deadline_is_used(self):
        conn = self.connect(tls._DeadlineHTTPConnection, answers_at={8003}, refuse=True)
        self.assertIsInstance(conn.sock, tls._DeadlineSocket)
        self.assertEqual(conn.sock.sock.address, ("192.0.2.1", 8003))
        self.assertEqual(len(_Unanswered.made), 3)

    def test_when_every_address_refuses_the_last_failure_is_raised(self):
        with self.assertRaises(ConnectionRefusedError):
            self.connect(tls._DeadlineHTTPConnection, refuse=True)
        self.assertEqual(len(_Unanswered.made), 6)

    def handshake_after_a_slow_connect(self, delay):
        context = tls.ssl_context()
        seen = []

        def wrap(sock, **kwargs):
            seen.append((sock.timeout, self.deadline - time.monotonic()))
            return sock
        self.deadline = time.monotonic() + 0.5
        conn = tls._DeadlineHTTPSConnection("photos.example.invalid", 8000, timeout=10, deadline=self.deadline, context=context)
        _Unanswered.made, _Unanswered.answers_at, _Unanswered.refuse, _Unanswered.delay = [], {8001}, False, delay
        with mock.patch.object(socket, "getaddrinfo", return_value=self.ADDRESSES), mock.patch.object(socket, "socket", _Unanswered), \
                mock.patch.object(context, "wrap_socket", side_effect=wrap):
            conn.connect()
        return seen

    def test_the_handshake_gets_only_the_time_left_after_a_slow_connect(self):
        [(timeout, left)] = self.handshake_after_a_slow_connect(0.3)
        self.assertLessEqual(timeout, left + 0.01)
        self.assertLess(timeout, 0.3)

    def test_no_handshake_starts_once_a_slow_connect_has_spent_the_deadline(self):
        with self.assertRaises(TimeoutError):
            self.handshake_after_a_slow_connect(0.6)

    def test_a_source_address_is_bound_before_connecting(self):
        conn = self.connect(tls._DeadlineHTTPConnection, answers_at={8001}, source_address=("127.0.0.1", 0))
        self.assertEqual(conn.sock.sock.bound, ("127.0.0.1", 0))

    def test_no_address_at_all_is_an_error(self):
        conn = tls._DeadlineHTTPConnection("photos.example.invalid", 8000, timeout=10, deadline=time.monotonic() + 5)
        with mock.patch.object(socket, "getaddrinfo", return_value=[]), self.assertRaises(OSError):
            conn.connect()

    def test_an_https_connection_tries_its_addresses_inside_the_deadline_too(self):
        context = tls.ssl_context()
        with mock.patch.object(context, "wrap_socket", side_effect=lambda sock, **kwargs: sock):
            conn = self.connect(tls._DeadlineHTTPSConnection, answers_at={8002}, refuse=True, context=context)
        self.assertEqual(conn.sock.sock.address, ("192.0.2.1", 8002))
        self.assertEqual(len(_Unanswered.made), 2)


class DnsDeadlineTests(unittest.TestCase):
    URL = "http://slow-resolver.invalid/"

    def open(self, deadline, timeout=10):
        return tls.urlopen(self.URL, timeout, allow_http=True, handlers=(urllib.request.ProxyHandler({}),), deadline=deadline)

    def blocked_resolver(self):
        release = threading.Event()
        self.addCleanup(release.set)
        started = threading.Event()

        def resolver(*args, **kwargs):
            started.set()
            release.wait(10)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9))]
        return resolver, started, release

    def test_a_resolver_that_never_answers_ends_the_request_at_the_deadline(self):
        resolver, _, _ = self.blocked_resolver()
        began = time.monotonic()
        with mock.patch.object(socket, "getaddrinfo", resolver), self.assertRaises(urllib.error.URLError) as caught:
            self.open(time.monotonic() + 0.3)
        self.assertIsInstance(caught.exception.reason, TimeoutError)
        self.assertLess(time.monotonic() - began, 2.0)

    def serving(self, body, accepted):
        def handle(request):
            accepted.append(body)
            request.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
        server = socketserver.TCPServer(("127.0.0.1", 0), type("Answering", (socketserver.BaseRequestHandler,), {"handle": handle}))
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", server.server_address)]

    def wait_for_lookup_slots(self):
        held = 0
        try:
            while held < tls.MAX_LOOKUPS:
                self.assertTrue(tls._LOOKUPS.acquire(timeout=5))
                held += 1
        finally:
            for _ in range(held):
                tls._LOOKUPS.release()

    def test_a_late_answer_never_reaches_a_later_request(self):
        accepted: list = []
        late = self.serving(b"late", accepted)
        own = self.serving(b"own", accepted)
        release = threading.Event()
        self.addCleanup(release.set)
        finished = threading.Event()

        def slow(*args, **kwargs):
            release.wait(10)
            finished.set()
            return late

        with mock.patch.object(socket, "getaddrinfo", slow):
            with self.assertRaises(urllib.error.URLError) as caught:
                self.open(time.monotonic() + 0.2)
            self.assertIsInstance(caught.exception.reason, TimeoutError)
            release.set()
            self.assertTrue(finished.wait(2))
            self.wait_for_lookup_slots()
        with mock.patch.object(socket, "getaddrinfo", return_value=own), self.open(time.monotonic() + 5) as reply:
            self.assertEqual(reply.read(), b"own")
        self.assertEqual(accepted, [b"own"])

    def test_an_answer_inside_the_deadline_is_used(self):
        server = socketserver.TCPServer(("127.0.0.1", 0), type("Quiet", (socketserver.BaseRequestHandler,), {"handle": lambda self: self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")}))
        self.addCleanup(server.server_close)
        threading.Thread(target=server.handle_request, daemon=True).start()
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", server.server_address)]
        with mock.patch.object(socket, "getaddrinfo", return_value=answer), self.open(time.monotonic() + 5) as reply:
            self.assertEqual(reply.read(), b"ok")

    def test_a_resolver_error_inside_the_deadline_is_raised_as_it_was(self):
        with mock.patch.object(socket, "getaddrinfo", side_effect=socket.gaierror(socket.EAI_NONAME, "no such host")), \
                self.assertRaises(urllib.error.URLError) as caught:
            self.open(time.monotonic() + 5)
        self.assertIsInstance(caught.exception.reason, socket.gaierror)

    def test_lookups_at_the_cap_fail_at_once_with_a_message_of_their_own(self):
        resolver, started, release = self.blocked_resolver()
        with mock.patch.object(socket, "getaddrinfo", resolver), mock.patch.object(tls, "_LOOKUPS", threading.BoundedSemaphore(1)):
            first = threading.Thread(target=lambda: self.open_quietly(time.monotonic() + 3), daemon=True)
            first.start()
            self.assertTrue(started.wait(2))
            began = time.monotonic()
            with self.assertRaises(urllib.error.URLError) as caught:
                self.open(time.monotonic() + 30)
            self.assertLess(time.monotonic() - began, 1.0)
            self.assertIsInstance(caught.exception.reason, TimeoutError)
            self.assertEqual(str(caught.exception.reason), "too many name lookups are waiting")
        release.set()
        first.join(5)
        self.assertFalse(first.is_alive())

    def open_quietly(self, deadline):
        with contextlib.suppress(OSError):
            self.open(deadline)

    def test_a_finished_lookup_frees_its_place(self):
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9))]
        cap = threading.BoundedSemaphore(1)
        with mock.patch.object(socket, "getaddrinfo", return_value=answer), mock.patch.object(tls, "_LOOKUPS", cap):
            for _ in range(3):
                with self.assertRaises(urllib.error.URLError) as caught:
                    self.open(time.monotonic() + 5)
                self.assertNotIsInstance(caught.exception.reason, TimeoutError)
        self.assertTrue(cap.acquire(blocking=False))

    def test_a_request_without_a_deadline_resolves_directly_on_its_own_thread(self):
        seen = []

        def resolver(*args, **kwargs):
            seen.append(threading.current_thread())
            raise socket.gaierror(socket.EAI_NONAME, "no such host")
        with mock.patch.object(socket, "getaddrinfo", resolver), self.assertRaises(urllib.error.URLError):
            tls.urlopen(self.URL, 5, allow_http=True, handlers=(urllib.request.ProxyHandler({}),))
        self.assertEqual(seen, [threading.current_thread()])
