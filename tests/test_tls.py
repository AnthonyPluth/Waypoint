"""waypoint/tls.py: every outbound request is to a web address, and checks certificates the same way, with one shared
context."""
import io
import ssl
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
