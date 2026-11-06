import http.client
import io
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

    def __init__(self, parts: list[tuple[bytes, float]]):
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.server.connections += 1   # type: ignore[attr-defined]
                seen = b""
                while b"\r\n\r\n" not in seen:
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
        self.connections = 0

    def handle_error(self, request, client_address):
        pass


HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nX-Pad: " + b"y" * 120 + b"\r\n"


class DeadlineTests(unittest.TestCase):
    def serve(self, parts) -> str:
        server = _Scripted(parts)
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
        plain = mock.Mock()

        def connected(conn):
            conn.sock = plain
        for timeout in (5, object()):
            conn = tls._DeadlineHTTPSConnection("example.com", timeout=timeout, deadline=time.monotonic() + 1, context=tls.ssl_context())
            with self.subTest(timeout=timeout), mock.patch.object(http.client.HTTPSConnection, "connect", connected):
                conn.connect()
                self.assertLessEqual(conn.timeout, 1)
                self.assertIsInstance(conn.sock, tls._DeadlineSocket)
                self.assertIs(conn.sock.sock, plain)
                self.assertIs(conn.sock.timeout, timeout)
                self.assertLessEqual(conn.sock.wait(), 1)

    def test_without_a_deadline_the_standard_handlers_are_used(self):
        kinds = {type(h) for h in tls.opener(allow_http=True).handlers}
        self.assertIn(urllib.request.HTTPSHandler, kinds)
        self.assertIn(urllib.request.HTTPHandler, kinds)
