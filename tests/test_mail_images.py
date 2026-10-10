import io
import ssl
import unittest
from unittest import mock

from tests.privacy import no_leaks
from waypoint import tls
from waypoint.providers import mailimages

PNG = b"\x89PNG\r\n\x1a\n" + b"CANARY-IMAGE-BYTES-4H8J" + bytes(64)
JPEG = b"\xff\xd8\xff\xe0" + bytes(32)
GIF = b"GIF89a" + bytes(32)
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + bytes(32)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
HOSTS = {"images.example": "93.184.216.34", "other.example": "93.184.216.35", "internal.example": "10.1.2.3", "loop.example": "127.0.0.1",
         "link.example": "169.254.169.254", "v6.example": "::1", "mapped.example": "::ffff:10.0.0.1", "rebind.example": "93.184.216.34,10.1.2.3"}


def reply(status: int, headers: dict[str, str], body: bytes) -> bytes:
    head = "".join(f"{k}: {v}\r\n" for k, v in {"Content-Length": str(len(body)), **headers}.items())
    return f"HTTP/1.1 {status} X\r\n{head}\r\n".encode() + body


class FakeSocket:
    def __init__(self, routes: dict[str, bytes], address: str, log: list[bytes]):
        self.routes, self.address, self.log, self.sent = routes, address, log, b""

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def makefile(self, *_args, **_kwargs) -> io.BytesIO:
        self.log.append(self.sent)
        head = self.sent.decode("latin-1")
        host = next(line.split(":", 1)[1].strip() for line in head.split("\r\n") if line.lower().startswith("host:"))
        path = head.split(" ", 2)[1]
        return io.BytesIO(self.routes.get(host + path, reply(404, {}, b"")))

    def close(self) -> None:
        pass

    def settimeout(self, _t) -> None:
        pass


class FakeInternet:
    def __init__(self, routes: dict[str, bytes]):
        self.routes, self.requests, self.connected = routes, [], []

    def getaddrinfo(self, host, port, **_kwargs):
        return [(0, 0, 0, "", (a, port)) for a in HOSTS[host].split(",")]

    def create_connection(self, address, _timeout=None):
        self.connected.append(address[0])
        return FakeSocket(self.routes, address[0], self.requests)

    def __enter__(self):
        context = mock.Mock(verify_mode=ssl.CERT_REQUIRED, check_hostname=True)
        context.wrap_socket = lambda sock, server_hostname=None: sock
        self.patches = [mock.patch("socket.getaddrinfo", self.getaddrinfo), mock.patch("socket.create_connection", self.create_connection),
                        mock.patch.object(tls, "ssl_context", return_value=context)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *_exc):
        for p in self.patches:
            p.stop()


class Sniffing(unittest.TestCase):
    def test_only_png_jpeg_gif_and_webp_are_images_and_the_bytes_decide(self):
        self.assertEqual([mailimages.sniff(d) for d in (PNG, JPEG, GIF, WEBP)], ["image/png", "image/jpeg", "image/gif", "image/webp"])
        for data in (SVG, b"<html>", b"", b"RIFF\x00\x00\x00\x00WAVEfmt ", b"GIF"):
            self.assertIsNone(mailimages.sniff(data), data)

    def test_an_address_has_to_be_plain_https(self):
        good = ["https://images.example/a.png", "https://images.example:8443/a.png?x=1"]
        bad = ["http://images.example/a.png", "ftp://images.example/a.png", "cid:logo", "data:image/png;base64,AAAA", "//images.example/a.png",
               "https://user:pass@images.example/a.png", "https:///a.png", "", "https://images.example/a b.png", "https://" + "a" * 2100,
               "https://[::1/a.png"]
        self.assertEqual([mailimages.allowed_url(u) for u in good], [True, True])
        for url in bad:
            self.assertFalse(mailimages.allowed_url(url), url)


class Fetching(unittest.TestCase):
    def fetch(self, routes: dict[str, bytes], *urls: str):
        with FakeInternet(routes) as net:
            fetcher = mailimages.Fetcher()
            return [fetcher(u) for u in urls], net

    def test_an_image_is_fetched_once_with_nothing_that_identifies_anyone(self):
        found, net = self.fetch({"images.example/logo.png?id=CANARY-URL-TOKEN-7C2P": reply(200, {"Content-Type": "image/png"}, PNG)},
                                "https://images.example/logo.png?id=CANARY-URL-TOKEN-7C2P")
        self.assertEqual(found, [("image/png", PNG)])
        self.assertEqual(net.connected, ["93.184.216.34"])
        [sent] = net.requests
        headers = sent.decode("latin-1").lower()
        for name in ("cookie", "authorization", "referer", "x-waypoint", "origin"):
            self.assertNotIn(f"\r\n{name}:", headers)
        self.assertIn("user-agent: mozilla/5.0", headers)

    def test_each_image_type_is_accepted_whatever_the_server_calls_it(self):
        routes = {f"images.example/{n}": reply(200, {"Content-Type": "text/plain"}, d) for n, d in (("a", PNG), ("b", JPEG), ("c", GIF), ("d", WEBP))}
        found, _ = self.fetch(routes, *(f"https://images.example/{n}" for n in "abcd"))
        self.assertEqual([f[0] for f in found if f], ["image/png", "image/jpeg", "image/gif", "image/webp"])

    def test_svg_and_other_non_images_are_refused_even_when_called_an_image(self):
        routes = {"images.example/a.svg": reply(200, {"Content-Type": "image/svg+xml"}, SVG),
                  "images.example/b.png": reply(200, {"Content-Type": "image/png"}, b"<html>not an image</html>"),
                  "images.example/c.png": reply(200, {"Content-Type": "image/png"}, b"")}
        found, _ = self.fetch(routes, *(f"https://images.example/{n}" for n in ("a.svg", "b.png", "c.png")))
        self.assertEqual(found, [None, None, None])

    def test_private_loopback_link_local_and_mixed_answers_are_never_connected_to(self):
        urls = [f"https://{h}/x.png" for h in ("internal.example", "loop.example", "link.example", "v6.example", "mapped.example", "rebind.example")]
        found, net = self.fetch({}, *urls)
        self.assertEqual(found, [None] * len(urls))
        self.assertEqual(net.connected, [])

    def test_a_redirect_to_a_private_address_or_to_http_is_refused_and_a_public_one_followed(self):
        routes = {"images.example/to-private": reply(302, {"Location": "https://internal.example/x.png"}, b""),
                  "images.example/to-http": reply(302, {"Location": "http://other.example/x.png"}, b""),
                  "images.example/to-public": reply(302, {"Location": "https://other.example/x.png"}, b""),
                  "other.example/x.png": reply(200, {}, PNG),
                  "internal.example/x.png": reply(200, {}, PNG)}
        found, net = self.fetch(routes, "https://images.example/to-private", "https://images.example/to-http", "https://images.example/to-public")
        self.assertEqual(found, [None, None, ("image/png", PNG)])
        self.assertNotIn("10.1.2.3", net.connected)

    def test_errors_and_other_statuses_leave_the_image_out(self):
        routes = {"images.example/missing.png": reply(404, {}, b"no"), "images.example/error.png": reply(500, {}, b"no"),
                  "images.example/empty.png": reply(204, {}, b"")}
        found, _ = self.fetch(routes, *(f"https://images.example/{n}" for n in ("missing.png", "error.png", "empty.png", "unknown.png")))
        self.assertEqual(found, [None] * 4)

    def test_an_image_over_the_size_limit_is_refused_by_its_header_or_by_counting(self):
        big = PNG + bytes(mailimages.MAX_IMAGE_BYTES)
        routes = {"images.example/declared.png": reply(200, {}, big),
                  "images.example/hidden.png": reply(200, {"Content-Length": "5"}, big).replace(b"Content-Length: 5", b"X-Pad: 1")}
        found, _ = self.fetch(routes, "https://images.example/declared.png", "https://images.example/hidden.png")
        self.assertEqual(found, [None, None])

    def test_a_message_has_a_total_size_and_a_count_limit(self):
        with mock.patch.object(mailimages, "MAX_TOTAL_BYTES", len(PNG) * 2 + 1):
            found, _ = self.fetch({f"images.example/{i}": reply(200, {}, PNG) for i in range(3)}, *(f"https://images.example/{i}" for i in range(3)))
        self.assertEqual([f is not None for f in found], [True, True, False])
        with mock.patch.object(mailimages, "MAX_ATTEMPTS", 1):
            found, _ = self.fetch({f"images.example/{i}": reply(200, {}, PNG) for i in range(2)}, *(f"https://images.example/{i}" for i in range(2)))
        self.assertEqual([f is not None for f in found], [True, False])

    def test_a_slow_image_and_a_slow_message_are_given_up_on(self):
        clock = iter([0.0, 0.0, 0.0, 0.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0])
        with FakeInternet({"images.example/slow.png": reply(200, {}, PNG)}), mock.patch.object(mailimages.time, "monotonic", lambda: next(clock, 99.0)):
            fetcher = mailimages.Fetcher()
            self.assertIsNone(fetcher("https://images.example/slow.png"))
        with FakeInternet({"images.example/late.png": reply(200, {}, PNG)}):
            fetcher = mailimages.Fetcher()
            fetcher.started -= mailimages.TOTAL_SECONDS + 1
            self.assertIsNone(fetcher("https://images.example/late.png"))

    def test_a_connection_that_fails_leaves_the_image_out(self):
        with FakeInternet({}) as net, mock.patch("socket.create_connection", side_effect=OSError("refused")):
            self.assertIsNone(mailimages.Fetcher()("https://images.example/a.png"))
        self.assertEqual(net.requests, [])

    def test_the_address_the_url_and_the_bytes_are_not_logged_or_printed(self):
        url = "https://images.example/CANARY-URL-PATH-9Q3L.png"
        with FakeInternet({"images.example/CANARY-URL-PATH-9Q3L.png": reply(200, {}, PNG)}), \
                no_leaks(self, "CANARY-URL-PATH-9Q3L", "CANARY-IMAGE-BYTES-4H8J", sent_ok=True):
            self.assertIsNotNone(mailimages.Fetcher()(url))
            self.assertIsNone(mailimages.Fetcher()("https://internal.example/CANARY-URL-PATH-9Q3L.png"))


class PublicAddresses(unittest.TestCase):
    def test_only_global_unicast_addresses_are_public(self):
        public = ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946", "8.8.8.8"]
        private = ["10.0.0.1", "172.16.5.4", "192.168.1.1", "127.0.0.1", "169.254.169.254", "0.0.0.0", "100.64.0.1", "224.0.0.1", "::1", "fe80::1%eth0",
                   "fc00::1", "::ffff:10.0.0.1", "::ffff:127.0.0.1", "255.255.255.255", "not an address", ""]
        self.assertTrue(all(tls.is_public(a) for a in public))
        for address in private:
            self.assertFalse(tls.is_public(address), address)

    def test_a_name_is_refused_when_any_of_its_answers_is_not_public(self):
        with mock.patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("93.184.216.34", 443)), (0, 0, 0, "", ("10.0.0.2", 443))]):
            with self.assertRaises(OSError):
                tls.public_addresses("rebind.example", 443)
        with mock.patch("socket.getaddrinfo", return_value=[]), self.assertRaises(OSError):
            tls.public_addresses("nothing.example", 443)
        with mock.patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("93.184.216.34", 443))]):
            self.assertEqual(tls.public_addresses("images.example", 443), ["93.184.216.34"])

    def test_public_only_never_uses_a_proxy_or_http(self):
        with mock.patch.dict("os.environ", {"HTTPS_PROXY": "http://10.9.9.9:3128"}), FakeInternet({"images.example/a.png": reply(200, {}, PNG)}) as net:
            self.assertIsNotNone(mailimages.Fetcher()("https://images.example/a.png"))
        self.assertEqual(net.connected, ["93.184.216.34"])
        with self.assertRaises(OSError):
            tls.urlopen("http://images.example/a.png", 1, allow_http=True, public_only=True)


if __name__ == "__main__":
    unittest.main()
