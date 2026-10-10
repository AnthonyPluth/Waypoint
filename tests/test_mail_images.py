import base64
import json
import socket
from email.message import EmailMessage
from unittest import mock

from sqlalchemy import select

from tests.fakenet import IMAGE_CANARIES, JPEG, PNG, PUBLIC, SENDER_HOSTS, SENDER_PAGES, SVG, internet
from tests.privacy import no_leaks
from tests.shared import DbCase, own_database
from tests.test_mail_scan import FIXTURES, ScanCase, b64, eml
from waypoint import imagetype
from waypoint.domain import trips
from waypoint.domain.mail import extract, review, scan
from waypoint.providers import images
from waypoint.storage import backup, db, secretbox, stored_mail
from waypoint.storage.models import StoredMessage

URL = "CANARY-IMGURL-9D4T"
HOSTS, PAGES, CANARIES = SENDER_HOSTS, SENDER_PAGES, IMAGE_CANARIES
IMAGE_BYTES = IMAGE_CANARIES[:3]
REFUSED = ("Insecure picture", "Internal picture", "Redirected picture", "Huge picture", "Page picture", "Vector picture")


def raw(html: str, *inline: tuple[str, bytes, str]) -> dict:
    mail = EmailMessage()
    mail["From"] = "Example Air <reservations@example-air.example>"
    mail["Subject"] = "Your itinerary"
    mail["Date"] = "Mon, 12 Oct 2026 09:30:00 -0400"
    mail.set_content("Plain text.")
    mail.add_alternative(html, subtype="html")
    body = mail.get_body(("html",))
    assert isinstance(body, EmailMessage)
    for cid, data, kind in inline:
        main, _, sub = kind.partition("/")
        body.add_related(data, main, sub, cid=f"<{cid}>")
    return {"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode()}


class Fetcher:
    def __init__(self, found: dict[str, tuple[str, bytes]] | None = None) -> None:
        self.found = found or {}
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, urls, budget):
        self.calls.append((list(urls), budget))
        return {u: self.found[u] for u in urls if u in self.found}


class KeepTests(DbCase):
    def test_an_inline_image_is_kept_without_any_fetch(self):
        fetch = Fetcher()
        kept = extract.keep(raw('<p>Hi <img src="cid:logo" alt="Logo" width="50"></p>', ("logo", PNG, "image/png")), fetch)
        self.assertEqual(kept["images"], [{"type": "image/png", "data": base64.b64encode(PNG).decode()}])
        self.assertEqual((kept["layout"] or "").strip(), '<p>Hi <img data-image="0" alt="Logo" width="50"></p>')
        self.assertTrue(kept["full"])
        self.assertEqual(fetch.calls, [])

    def test_a_remote_image_is_asked_for_once_and_only_over_https(self):
        fetch = Fetcher({"https://img.example-air.example/a.png": ("image/png", PNG)})
        html = ('<img src="https://img.example-air.example/a.png" alt="A"><img src="https://img.example-air.example/a.png" alt="A again">'
                '<img src="http://img.example-air.example/b.png" alt="B"><img src="data:image/png;base64,AAAA" alt="C">'
                '<img src="https://img.example-air.example/pixel.gif" width="1" height="1" alt="D"><img src="//img.example-air.example/e.png" alt="E">')
        kept = extract.keep(raw(html), fetch)
        self.assertEqual(fetch.calls, [(["https://img.example-air.example/a.png"], imagetype.MAX_TOTAL)])
        self.assertEqual(len(kept["images"]), 1)
        assert kept["layout"]
        self.assertEqual(kept["layout"].count('data-image="0"'), 2)
        self.assertNotIn("img.example-air.example", kept["layout"])
        for alt in ("B", "C", "E"):
            self.assertIn(f"{alt} ", kept["layout"])

    def test_without_a_fetcher_remote_images_are_left_out_and_inline_ones_stay(self):
        kept = extract.keep(raw('<img src="https://img.example-air.example/a.png" alt="Remote"><img src="cid:logo" alt="Logo">',
                                ("logo", PNG, "image/png")))
        self.assertEqual(len(kept["images"]), 1)
        assert kept["layout"]
        self.assertIn("Remote ", kept["layout"])
        self.assertIn('data-image="0"', kept["layout"])

    def test_a_failed_image_is_left_out_and_the_next_keeps_its_number(self):
        fetch = Fetcher({"https://img.example-air.example/b.png": ("image/jpeg", JPEG)})
        kept = extract.keep(raw('<img src="https://img.example-air.example/a.png" alt="First"><img src="https://img.example-air.example/b.png" alt="Second">'), fetch)
        self.assertEqual([i["type"] for i in kept["images"]], ["image/jpeg"])
        assert kept["layout"]
        self.assertIn('First <img data-image="0" alt="Second">', kept["layout"])

    def test_only_the_four_image_types_are_kept_whatever_the_part_or_the_fetch_says(self):
        fetch = Fetcher({"https://img.example-air.example/v.svg": ("image/svg+xml", SVG), "https://img.example-air.example/h.png": ("text/html", b"<p>")})
        html = ('<img src="cid:vector" alt="Vector"><img src="cid:fake" alt="Fake"><img src="https://img.example-air.example/v.svg" alt="Svg">'
                '<img src="https://img.example-air.example/h.png" alt="Html">')
        kept = extract.keep(raw(html, ("vector", SVG, "image/svg+xml"), ("fake", b"<html>not a png</html>", "image/png")), fetch)
        self.assertEqual(kept["images"], [])
        assert kept["layout"]
        self.assertNotIn("data-image", kept["layout"])

    def test_the_type_is_what_the_bytes_say_not_what_the_part_says(self):
        kept = extract.keep(raw('<img src="cid:logo" alt="Logo">', ("logo", JPEG, "image/png")))
        self.assertEqual([i["type"] for i in kept["images"]], ["image/jpeg"])

    def test_an_image_over_the_per_image_or_the_total_limit_is_left_out(self):
        big = PNG + bytes(imagetype.MAX_IMAGE)
        kept = extract.keep(raw('<img src="cid:big" alt="Big"><img src="cid:small" alt="Small">', ("big", big, "image/png"), ("small", PNG, "image/png")))
        self.assertEqual(len(kept["images"]), 1)
        with mock.patch.object(imagetype, "MAX_TOTAL", len(PNG) * 2 + 1):
            html = "".join(f'<img src="cid:i{n}" alt="I{n}">' for n in range(4))
            kept = extract.keep(raw(html, *[(f"i{n}", PNG, "image/png") for n in range(4)]))
            self.assertEqual(len(kept["images"]), 2)
            fetch = Fetcher()
            extract.keep(raw('<img src="cid:i0" alt="I"><img src="https://img.example-air.example/a.png" alt="R">', ("i0", PNG, "image/png")), fetch)
            self.assertEqual(fetch.calls[0][1], len(PNG) + 1)
        with mock.patch.object(imagetype, "MAX_COUNT", 2):
            kept = extract.keep(raw(html, *[(f"i{n}", PNG, "image/png") for n in range(4)]))
            self.assertEqual(len(kept["images"]), 2)

    def test_a_fetcher_that_returns_too_much_or_something_it_was_not_asked_for_is_not_trusted(self):
        fetch = Fetcher({"https://img.example-air.example/a.png": ("image/png", PNG + bytes(imagetype.MAX_TOTAL)),
                         "https://other.example/x.png": ("image/png", PNG)})
        kept = extract.keep(raw('<img src="https://img.example-air.example/a.png" alt="A">'), fetch)
        self.assertEqual(kept["images"], [])

    def test_a_message_without_html_has_no_layout_but_is_whole(self):
        mail = EmailMessage()
        mail["Subject"] = "Plain"
        mail.set_content("Just text.")
        kept = extract.keep({"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode()}, Fetcher())
        self.assertEqual((kept["layout"], kept["images"], kept["full"], kept["truncated"], kept["text"]), (None, [], True, False, "Just text.\n"))

    def test_a_long_message_is_whole_until_the_cap(self):
        self.assertGreaterEqual(extract.KEPT_LIMIT, 500_000)
        words = "<p>" + "word " * 20_000 + "</p>"
        kept = extract.keep(raw(words * 4))
        self.assertFalse(kept["truncated"])
        assert kept["layout"] and kept["html"]
        self.assertEqual(kept["layout"].count("word"), 80_000)
        self.assertEqual(kept["html"].count("word"), 80_000)
        with mock.patch.object(extract, "KEPT_LIMIT", 1000):
            cut = extract.keep(raw(words))
            self.assertTrue(cut["truncated"])
            assert cut["layout"]
            self.assertLessEqual(len(cut["layout"]), 1100)
        with mock.patch.object(extract, "MARKUP_LIMIT", 5000):
            self.assertTrue(extract.keep(raw(words))["truncated"])

    def test_the_markup_is_cut_when_only_the_layout_is_over(self):
        with mock.patch.object(extract, "MARKUP_LIMIT", 300):
            kept = extract.keep(raw("<p>one</p>" * 100))
        self.assertTrue(kept["truncated"])

    def test_a_message_that_cannot_be_decoded_keeps_no_layout(self):
        kept = extract.keep({"raw": None}, Fetcher())
        self.assertEqual((kept["layout"], kept["images"], kept["full"]), (None, [], True))


class StoredTests(ScanCase):
    def kept(self):
        return self.read(lambda conn: stored_mail.get(conn, self.mailbox, "msg-rich_note"))

    def scan_rich(self, *names, **kwargs):
        self.put(*names)
        with internet(HOSTS, PAGES) as wire:
            result = self.scan(**kwargs)
        return result, wire

    def test_a_kept_message_has_its_layout_and_its_images_in_the_one_encrypted_value(self):
        with no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
            self.scan_rich("rich_note")
        kept = self.kept()
        assert kept and kept["layout"]
        self.assertEqual([i["type"] for i in kept["images"]], ["image/png", "image/jpeg"])
        self.assertEqual([base64.b64decode(i["data"]) for i in kept["images"]], [PNG, JPEG])
        self.assertTrue(kept["full"])
        self.assertIn('<img data-image="0" alt="Example Air" width="200" style="display: block">', kept["layout"])
        self.assertIn('<img data-image="1" alt="Spring fares" width="560">', kept["layout"])
        self.assertIn("CANARY-BODY-RICH-NOTE-8K1Q", kept["layout"])
        self.assertIn("CANARY-BODY-RICH-NOTE-8K1Q", kept["text"])
        raw_value = self.read(lambda conn: conn.execute(select(StoredMessage.content)).scalar())
        self.assertTrue(secretbox.is_encrypted(raw_value))
        for canary in CANARIES:
            self.assertNotIn(canary, raw_value)

    def test_the_server_asks_only_for_the_images_it_needs_and_tells_the_sender_nothing_else(self):
        _, wire = self.scan_rich("rich_note")
        self.assertEqual(sorted(set(wire.asked)), ["img.example-air.example/banner.png", "img.example-air.example/huge.png",
                                                    "img.example-air.example/page.png", "img.example-air.example/redirect.png",
                                                    "img.example-air.example/vector.svg"])
        self.assertEqual({a for a, _ in wire.connected}, {PUBLIC})
        for request in wire.requests:
            self.assertNotRegex(request.lower(), r"cookie|authorization|referer|x-|waypoint|jane|traveller|canary-(body|subject)|msg-|rich_note")
        self.assertEqual(len([r for r in wire.requests if "banner.png" in r]), 1)
        self.assertNotIn("pixel", "".join(wire.asked))
        self.assertNotIn("insecure", "".join(wire.asked))
        self.assertNotIn("internal.png", "".join(a for a in wire.asked if a.startswith("inside")))

    def test_every_refused_image_is_left_out_and_the_message_still_opens(self):
        self.scan_rich("rich_note")
        kept = self.kept()
        assert kept and kept["layout"]
        for alt in REFUSED:
            self.assertIn(f"{alt} ", kept["layout"])
        self.assertEqual(kept["layout"].count("<img"), 2)
        self.assertNotRegex(kept["layout"], r"(?i)\bsrc=|img\.example-air|inside\.example|<script|<form|<style|onclick")
        self.assertEqual(len(self.items()), 1)
        self.assertTrue(self.items()[0]["has_email"])

    def test_an_image_that_is_too_slow_is_left_out_and_the_message_still_opens(self):
        ticks = iter(range(0, 100_000, 50))
        self.put("rich_note")
        with internet(HOSTS, PAGES), mock.patch.object(images.time, "monotonic", lambda: next(ticks)):
            self.scan()
        kept = self.kept()
        assert kept and kept["layout"]
        self.assertEqual([i["type"] for i in kept["images"]], ["image/png"])
        self.assertIn("Spring fares ", kept["layout"])
        self.assertIn("CANARY-BODY-RICH-NOTE-8K1Q", kept["layout"])

    def test_a_network_that_is_down_leaves_the_images_out_and_the_message_opens(self):
        self.put("rich_note")
        with internet(HOSTS, PAGES):
            wired = socket.create_connection

            def refuse(address, *args, **kwargs):
                if address[0] == PUBLIC:
                    raise ConnectionRefusedError
                return wired(address, *args, **kwargs)

            with mock.patch("socket.create_connection", refuse):
                self.scan()
        kept = self.kept()
        assert kept and kept["layout"]
        self.assertEqual(len(kept["images"]), 1)
        self.assertIn("CANARY-BODY-RICH-NOTE-8K1Q", kept["layout"])

    def test_a_booking_keeps_the_message_with_its_images_for_whoever_can_see_the_booking(self):
        with no_leaks(self, *CANARIES, database=self.path, sent_ok=True):
            self.scan_rich("rich_flight")
        [seg] = self.segments()
        emails = self.read(lambda conn: trips.emails_of(conn, self.jane, seg["id"]))
        assert emails
        [email] = emails
        self.assertEqual(len(email["images"]), 2)
        self.assertEqual(self.read(lambda conn: trips.email_images(conn, self.jane, seg["id"], email["id"])), email["images"])
        self.assertIsNone(self.read(lambda conn: trips.email_images(conn, self.sam, seg["id"], email["id"])))
        self.assertIsNone(self.read(lambda conn: trips.email_images(conn, self.jane, seg["id"] + 99, email["id"])))
        self.assertIsNone(self.read(lambda conn: trips.email_images(conn, self.jane, seg["id"], email["id"] + 99)))

    def test_an_ignored_sender_costs_no_download(self):
        self.put("rich_note")
        with internet(HOSTS, PAGES) as wire, mock.patch.object(scan, "_ignores", return_value=True):
            self.scan()
        self.assertEqual(wire.asked, [])

    def test_a_scan_that_cannot_file_a_message_still_keeps_it_with_its_images(self):
        self.put("rich_note")
        with internet(HOSTS, PAGES), mock.patch("waypoint.domain.mail.ingest.file_booking", side_effect=RuntimeError("CANARY-FILE-DETAILS-2Y8W")):
            self.scan()
        kept = self.kept()
        assert kept
        self.assertEqual(len(kept["images"]), 2)

    def test_a_message_kept_before_images_were_kept_is_shown_as_it_was(self):
        self.put("no_markup")
        self.scan()
        old = {"subject": "Old", "sender_domain": "x.example", "received": None, "text": "Old text", "html": "<p>Old</p>", "truncated": False}
        self.read(lambda conn: conn.execute(StoredMessage.__table__.update().values(content=secretbox.encrypt(json.dumps(old)))))
        found = self.read(lambda conn: stored_mail.get(conn, self.mailbox, "msg-no_markup"))
        self.assertEqual(found, {**old, "full": False, "layout": None, "images": []})
        item = self.items()[0]["id"]
        self.assertEqual(self.read(lambda conn: review.stored_email(conn, "u-jane", item))[1], found)


class GoneWithTheMessageTests(ScanCase):
    def kept(self):
        return self.read(lambda conn: conn.execute(select(StoredMessage.id)).fetchall())

    def scan_rich(self, *names):
        self.put(*names)
        with internet(HOSTS, PAGES):
            self.scan()

    def test_the_images_go_when_the_item_is_dismissed(self):
        self.scan_rich("rich_note")
        [item] = self.items()
        self.assertEqual(len(self.kept()), 1)
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", item["id"])))
        self.assertEqual(self.kept(), [])
        self.assertIsNone(self.read(lambda conn: stored_mail.get(conn, self.mailbox, "msg-rich_note")))

    def test_the_images_stay_while_a_booking_made_from_the_item_exists_and_go_with_the_last_one(self):
        self.scan_rich("rich_note")
        [item] = self.items()
        seg = self.read(lambda conn: trips.add_segment(conn, self.jane, {"kind": "flight", "origin": "JFK", "destination": "SFO",
                                                                         "start_local": "2026-12-08T08:00", "end_local": "2026-12-08T11:20"}))
        assert seg
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", item["id"], (self.jane, seg["id"]))))
        self.assertEqual(len(self.read(lambda conn: stored_mail.for_segment(conn, seg["id"]))[0]["images"]), 2)
        self.assertTrue(self.read(lambda conn: trips.delete_segment(conn, self.jane, seg["id"])))
        self.assertEqual(self.kept(), [])

    def test_the_images_go_with_the_last_booking_made_from_the_message(self):
        self.scan_rich("rich_flight")
        [seg] = self.segments()
        self.assertEqual(len(self.kept()), 1)
        self.assertTrue(self.read(lambda conn: trips.delete_segment(conn, self.jane, seg["id"])))
        self.assertEqual(self.kept(), [])

    def test_the_images_go_when_the_mailbox_is_disconnected(self):
        from waypoint.providers import gmail
        self.scan_rich("rich_note", "rich_flight")
        self.assertEqual(len(self.kept()), 2)
        with mock.patch.object(gmail, "_post", return_value={}):
            self.assertTrue(self.read(lambda conn: gmail.disconnect(conn, self.mailbox, "u-jane")))
        self.assertEqual(self.kept(), [])


class BackupTests(DbCase):
    def test_a_backup_carries_the_images_inside_the_encrypted_message_and_restores_them(self):
        self.put_message()
        with db.session() as conn:
            dumped = backup.dump(conn)
            data = backup.load(dumped)
        for canary in (*IMAGE_BYTES, "CANARY-BODY-RICH-FLIGHT-2J6V"):
            self.assertNotIn(canary.encode(), dumped)
        columns = data["tables"]["stored_messages"]["columns"]
        [row] = data["tables"]["stored_messages"]["rows"]
        self.assertTrue(secretbox.is_encrypted(row[columns.index("content")]))
        other = own_database(self)
        dst = db.connect(other)
        backup.restore(dst, data)
        dst.commit()
        [box] = [r[0] for r in dst.execute(select(StoredMessage.mailbox_id))]
        found = stored_mail.get(dst, box, "m1")
        assert found
        self.assertEqual([base64.b64decode(i["data"]) for i in found["images"]], [PNG, JPEG])
        self.assertEqual(found["layout"], self.content["layout"])
        dst.close()

    def put_message(self):
        from sqlalchemy import insert

        from waypoint.storage.models import Mailbox
        self.content = extract.keep({"raw": b64(eml("rich_flight"))}, Fetcher({"https://img.example-air.example/banner.png?t=CANARY-IMGURL-9D4T":
                                                                                 ("image/jpeg", JPEG)}))
        self.assertEqual(len(self.content["images"]), 2)
        db.init(self.path)
        with db.session() as conn:
            box = conn.execute(insert(Mailbox).values(owner_sub="u-jane", address="jane@gmail.example", token=secretbox.encrypt("t"),
                                                      status="connected", created=1.0)).lastrowid
            stored_mail.put(conn, int(box), "m1", self.content, 1.0)


class FixtureTests(DbCase):
    def test_the_fixtures_hold_their_canaries_and_hostile_markup(self):
        for name in ("rich_flight", "rich_note"):
            text = (FIXTURES / f"{name}.eml").read_bytes()
            self.assertIn(b"<script>", text.replace(b"=3D", b"="))
            self.assertIn(URL.encode(), text.replace(b"=\n", b""))
        self.assertIn(b"CANARY-BODY-RICH-FLIGHT-2J6V", (FIXTURES / "rich_flight.eml").read_bytes())
        self.assertIn(b"CANARY-BODY-RICH-NOTE-8K1Q", (FIXTURES / "rich_note.eml").read_bytes())
