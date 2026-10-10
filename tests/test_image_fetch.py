import unittest
import urllib.error
from unittest import mock

from tests import fakenet
from tests.fakenet import GIF, JPEG, PNG, SVG, WEBP, internet, moved, ok
from waypoint import imagetype, tls
from waypoint.providers import images

PUBLIC = "93.184.216.34"
HOSTS = {"img.example-air.example": [PUBLIC], "cdn.example-air.example": ["93.184.216.35"], "inside.example-air.example": ["10.0.0.5"],
         "mixed.example-air.example": [PUBLIC, "192.168.1.9"], "loop.example-air.example": ["127.0.0.1"],
         "v6.example-air.example": ["2606:2800:220:1:248:1893:25c8:1946"], "mapped.example-air.example": ["::ffff:127.0.0.1"]}
LOGO = "https://img.example-air.example/logo.png"


class AddressTests(unittest.TestCase):
    def test_only_addresses_on_the_public_internet_are_public(self):
        for address in (PUBLIC, "2606:2800:220:1:248:1893:25c8:1946", "8.8.8.8"):
            with self.subTest(address=address):
                self.assertTrue(tls.public_address(address))
        for address in ("127.0.0.1", "127.1.2.3", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
                        "224.0.0.1", "255.255.255.255", "::1", "::", "fe80::1", "fc00::1", "fd12::1", "ff02::1", "::ffff:127.0.0.1",
                        "::ffff:10.0.0.5", "64:ff9b::7f00:1", "2002:7f00:1::", "192.0.2.1", "not an address", "", "fe80::1%eth0"):
            with self.subTest(address=address):
                self.assertFalse(tls.public_address(address))


class ConnectTests(unittest.TestCase):
    def get(self, url, wire_pages=None, **hosts):
        with internet({**HOSTS, **hosts}, wire_pages or {}) as wire:
            try:
                tls.urlopen(url, timeout=2, handlers=tls.public_handlers())
            except urllib.error.URLError as e:
                if isinstance(e, urllib.error.HTTPError):
                    e.close()
                return wire, e
        return wire, None

    def test_a_name_that_resolves_to_a_private_address_is_never_connected_to(self):
        for host in ("inside", "mixed", "loop", "mapped"):
            with self.subTest(host=host):
                wire, error = self.get(f"https://{host}.example-air.example/x.png", {f"{host}.example-air.example/x.png": ok(PNG)})
                self.assertIsInstance(error, urllib.error.URLError)
                self.assertEqual(wire.connected, [])

    def test_an_address_given_as_numbers_is_checked_the_same_way(self):
        for url in ("https://127.0.0.1/x.png", "https://10.0.0.5/x.png", "https://169.254.169.254/latest/meta-data", "https://[::1]/x.png",
                    "https://192.168.1.1/x.png", "https://[::ffff:127.0.0.1]/x.png", "https://2130706433/x.png", "https://0x7f.1/x.png"):
            with self.subTest(url=url):
                wire, error = self.get(url)
                self.assertIsInstance(error, (urllib.error.URLError, OSError))
                self.assertEqual(wire.connected, [])

    def test_a_public_name_is_connected_to_by_the_address_that_was_checked(self):
        wire, error = self.get(LOGO, {"img.example-air.example/logo.png": ok(PNG)})
        self.assertIsNone(error)
        self.assertEqual(wire.connected, [(PUBLIC, 443)])
        self.assertEqual(wire.resolved, ["img.example-air.example"])
        wire, error = self.get("https://v6.example-air.example/logo.png", {"v6.example-air.example/logo.png": ok(PNG)})
        self.assertIsNone(error)
        self.assertEqual(wire.connected, [("2606:2800:220:1:248:1893:25c8:1946", 443)])

    def test_a_redirect_to_a_private_address_is_refused_before_connecting(self):
        pages = {"img.example-air.example/logo.png": moved("https://inside.example-air.example/secret.png"),
                 "inside.example-air.example/secret.png": ok(PNG)}
        wire, error = self.get(LOGO, pages)
        self.assertIsInstance(error, urllib.error.URLError)
        self.assertEqual(wire.connected, [(PUBLIC, 443)])
        pages["img.example-air.example/logo.png"] = moved("https://127.0.0.1/secret.png")
        wire, error = self.get(LOGO, pages)
        self.assertIsInstance(error, urllib.error.URLError)
        self.assertEqual(wire.connected, [(PUBLIC, 443)])

    def test_a_redirect_to_http_or_another_scheme_is_refused(self):
        for target in ("http://cdn.example-air.example/logo.png", "ftp://cdn.example-air.example/logo.png", "file:///etc/passwd",
                       "data:image/png;base64,AAAA"):
            with self.subTest(target=target):
                wire, error = self.get(LOGO, {"img.example-air.example/logo.png": moved(target), "cdn.example-air.example/logo.png": ok(PNG)})
                self.assertIsInstance(error, urllib.error.URLError)
                self.assertEqual(wire.connected, [(PUBLIC, 443)])

    def test_a_redirect_to_a_public_https_address_is_followed_but_not_forever(self):
        wire, error = self.get(LOGO, {"img.example-air.example/logo.png": moved("https://cdn.example-air.example/logo.png"),
                                      "cdn.example-air.example/logo.png": ok(PNG)})
        self.assertIsNone(error)
        self.assertEqual(wire.connected, [(PUBLIC, 443), ("93.184.216.35", 443)])
        wire, error = self.get(LOGO, {"img.example-air.example/logo.png": moved("https://img.example-air.example/logo.png")})
        self.assertIsInstance(error, urllib.error.HTTPError)

    def test_no_proxy_is_used_even_when_the_environment_names_one(self):
        with mock.patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy.example:3128", "https_proxy": "http://proxy.example:3128"}):
            wire, error = self.get(LOGO, {"img.example-air.example/logo.png": ok(PNG)})
        self.assertIsNone(error)
        self.assertEqual(wire.connected, [(PUBLIC, 443)])


class FetchTests(unittest.TestCase):
    def fetch(self, answer, url=LOGO, limit=images.MAX_IMAGE, **hosts):
        with internet({**HOSTS, **hosts}, {"img.example-air.example/logo.png": answer}) as wire:
            return images.fetch_one(url, limit), wire

    def test_the_four_image_types_that_can_be_shown_come_back_with_their_real_type(self):
        for body, kind in ((PNG, "image/png"), (JPEG, "image/jpeg"), (GIF, "image/gif"), (WEBP, "image/webp")):
            with self.subTest(kind=kind):
                got, _ = self.fetch(ok(body, "application/octet-stream"))
                self.assertEqual(got, (kind, body))

    def test_the_declared_type_does_not_decide_what_it_is(self):
        self.assertIsNone(self.fetch(ok(b"<html><body>Not an image</body></html>", "image/png"))[0])
        self.assertEqual(self.fetch(ok(PNG, "text/html"))[0], ("image/png", PNG))

    def test_svg_is_refused_however_it_is_declared(self):
        for kind in ("image/svg+xml", "image/png", "text/xml"):
            with self.subTest(kind=kind):
                self.assertIsNone(self.fetch(ok(SVG, kind))[0])

    def test_something_that_is_not_an_image_is_refused(self):
        for body in (b"", b"GIF", b"%PDF-1.7", b"{}", b"MZ\x90\x00", b"RIFF\x00\x00\x00\x00WAVEfmt "):
            with self.subTest(body=body):
                self.assertIsNone(self.fetch(ok(body))[0])

    def test_an_image_over_the_limit_is_refused_whether_or_not_it_says_how_big_it_is(self):
        big = PNG + bytes(2000)
        self.assertIsNone(self.fetch(ok(big), limit=1000)[0])
        self.assertIsNone(self.fetch((200, {"Content-Type": "image/png"}, big), limit=1000)[0])
        self.assertEqual(self.fetch(ok(big), limit=len(big))[0], ("image/png", big))

    def test_a_slow_image_is_given_up_on(self):
        ticks = iter(range(0, 1000, 3))
        with mock.patch.object(images.time, "monotonic", lambda: next(ticks)):
            self.assertIsNone(self.fetch(ok(PNG + bytes(100_000)))[0])

    def test_an_error_answer_or_a_dead_server_leaves_the_image_out(self):
        for status in (403, 404, 500):
            with self.subTest(status=status):
                self.assertIsNone(self.fetch((status, {"Content-Length": "0"}, b""))[0])
        self.assertIsNone(self.fetch(ok(PNG), url="https://nowhere.example-air.example/logo.png")[0])
        with mock.patch.object(tls, "urlopen", side_effect=OSError("reset")):
            self.assertIsNone(images.fetch_one(LOGO, 1000))

    def test_only_https_web_addresses_are_tried_and_nothing_is_connected_to_otherwise(self):
        for url in ("http://img.example-air.example/logo.png", "ftp://img.example-air.example/logo.png", "file:///etc/passwd",
                    "data:image/png;base64,AAAA", "cid:logo", "//img.example-air.example/logo.png", "https://user:pw@img.example-air.example/logo.png",
                    "https://img.example-air.example:8443/logo.png", "https:///logo.png", "https://img.example-air.example/a b.png",
                    "https://img.example-air.example/" + "a" * 3000, "javascript:alert(1)", "", "https://[bad"):
            with self.subTest(url=url):
                got, wire = self.fetch(ok(PNG), url=url)
                self.assertIsNone(got)
                self.assertEqual(wire.connected, [])

    def test_nothing_identifying_is_sent(self):
        _, wire = self.fetch(ok(PNG))
        [request] = wire.requests
        names = {line.split(":")[0].lower() for line in request.split("\r\n")[1:] if ":" in line}
        self.assertEqual(names, {"host", "user-agent", "accept", "accept-encoding", "connection"})
        self.assertIn("User-Agent: Mozilla/5.0\r\n", request)
        self.assertTrue(request.startswith("GET /logo.png HTTP/1.1\r\n"))

    def test_cookies_and_credentials_set_by_a_redirect_are_never_sent_on(self):
        pages = {"img.example-air.example/logo.png": (302, {"Location": "https://cdn.example-air.example/logo.png", "Set-Cookie": "id=1",
                                                            "Content-Length": "0"}, b""),
                 "cdn.example-air.example/logo.png": ok(PNG)}
        with internet(HOSTS, pages) as wire:
            self.assertEqual(images.fetch_one(LOGO, 1000), ("image/png", PNG))
        for request in wire.requests:
            self.assertNotIn("cookie", request.lower())
            self.assertNotIn("authorization", request.lower())
            self.assertNotIn("referer", request.lower())


class ManyTests(unittest.TestCase):
    def pages(self, count, body=PNG):
        return {f"img.example-air.example/{i}.png": ok(body) for i in range(count)}

    def urls(self, count):
        return [f"https://img.example-air.example/{i}.png" for i in range(count)]

    def test_each_address_is_fetched_once_and_a_failure_is_just_left_out(self):
        pages = {**self.pages(2), "img.example-air.example/9.png": (404, {"Content-Length": "0"}, b"")}
        with internet(HOSTS, pages) as wire:
            got = images.fetch_many([*self.urls(2), self.urls(2)[0], "https://img.example-air.example/9.png", "http://img.example-air.example/0.png"])
        self.assertEqual(sorted(got), self.urls(2))
        self.assertEqual(len(wire.requests), 3)

    def test_the_whole_message_has_a_count_a_size_and_a_time_limit(self):
        with internet(HOSTS, self.pages(40)) as wire:
            self.assertEqual(len(images.fetch_many(self.urls(40))), imagetype.MAX_COUNT)
        self.assertEqual(len(wire.requests), imagetype.MAX_COUNT)
        size = len(PNG) * 2 + 1
        with internet(HOSTS, self.pages(5)):
            self.assertEqual(len(images.fetch_many(self.urls(5), budget=size)), 2)
            self.assertEqual(images.fetch_many(self.urls(5), budget=0), {})
        ticks = iter(range(0, 1000, 10))
        with internet(HOSTS, self.pages(5)) as wire, mock.patch.object(images.time, "monotonic", lambda: next(ticks)):
            self.assertLess(len(images.fetch_many(self.urls(5))), 5)

    def test_what_is_wrong_with_one_image_does_not_stop_the_next(self):
        pages = {"img.example-air.example/0.png": ok(SVG, "image/svg+xml"), "img.example-air.example/1.png": ok(PNG),
                 "img.example-air.example/2.png": moved("https://inside.example-air.example/x.png")}
        with internet(HOSTS, pages):
            self.assertEqual(images.fetch_many(self.urls(3)), {self.urls(3)[1]: ("image/png", PNG)})


class TypeTests(unittest.TestCase):
    def test_sniffing_names_the_four_types_and_nothing_else(self):
        self.assertEqual([imagetype.sniff(b) for b in (PNG, JPEG, GIF, WEBP, fakenet.SVG, b"", b"RIFF")],
                         ["image/png", "image/jpeg", "image/gif", "image/webp", None, None, None])
        self.assertEqual(imagetype.TYPES, ("image/png", "image/jpeg", "image/gif", "image/webp"))


if __name__ == "__main__":
    unittest.main()
