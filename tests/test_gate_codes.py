import base64
import email.message
import json
import secrets
import struct
import time
import unittest
import zlib
from datetime import datetime

from sqlalchemy import delete, func, insert, select

from tests.privacy import no_leaks
from tests.shared import ServerCase, fetch
from tests.test_mail_scan import NOW, ScanCase, b64
from waypoint import oidc
from waypoint.domain import calendar, offline, people, trips, visibility
from waypoint.domain.visibility import Viewer
from waypoint.domain.mail import review, scan
from waypoint.server import mcp_server
from waypoint.storage import backup, db, gate_codes, secretbox, stored_mail
from waypoint.storage.models import AuthSession, Mailbox, Person, Segment, SegmentCode, SegmentMessage, StoredMessage, Trip, User

CANARY_TEXT = "CANARY-GATE-TEXT-6K3P"
CANARY_PIXELS = b"CANARY-GATE-PIXELS-9D2R"
CANARY_OTHER = b"CANARY-GATE-OTHER-4M8T"
CANARIES = (CANARY_TEXT, CANARY_PIXELS.decode(), CANARY_OTHER.decode(), base64.b64encode(CANARY_PIXELS).decode()[:20])


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width: int, height: int, marker: bytes = b"") -> bytes:
    rows = b"".join(b"\x00" + bytes(width) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + (chunk(b"tEXt", b"Comment\x00" + marker) if marker else b"") + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def jpeg(width: int, height: int) -> bytes:
    frame = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + frame + b"\xff\xd9"


def mail(subject: str, images: dict[str, bytes], text: str = "Your reservation PK30417 is below.", domain: str = "mail.exampleparking.example",
         day: str = "Fri, 16 Oct 2026 09:00:00 +0100", name: str = "Example Parking Travel") -> bytes:
    msg = email.message.EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Date"] = f"{name} <noreply@{domain}>", "jane@gmail.example", subject, day
    pictures = "".join(f'<img src="cid:{cid}@example.example" alt="">' for cid in images)
    msg.set_content(f"<html><body><p>{text}</p>{pictures}</body></html>", subtype="html")
    for cid, data in images.items():
        kind = "png" if data.startswith(b"\x89PNG") else "jpeg"
        msg.add_related(data, "image", kind, cid=f"<{cid}@example.example>")
    return msg.as_bytes()


def raw_of(subject: str, images: dict[str, bytes], **more) -> dict:
    return {"raw": b64(mail(subject, images, **more))}


PARKING = {"kind": "parking", "origin": "Example Airport Long-Term Lot", "provider": "Example Parking", "confirmation": "PK30417",
           "start_local": "2026-12-01T05:15", "end_local": "2026-12-04T03:00", "start_zone": "America/New_York", "end_zone": "America/New_York"}
STAY = {"kind": "hotel", "origin": "Harbour Hotel", "provider": "Harbour Hotel", "confirmation": "H88231",
        "start_local": "2026-12-01T15:00", "end_local": "2026-12-04T10:00", "start_zone": "Europe/London", "end_zone": "Europe/London"}

QR = png(290, 290, CANARY_PIXELS)
OTHER_QR = png(300, 300, CANARY_OTHER)


class RuleTests(unittest.TestCase):
    def test_the_size_of_a_png_and_a_jpeg_is_read_from_their_headers_and_nothing_else_has_one(self):
        self.assertEqual(gate_codes.dimensions(png(120, 340)), (120, 340))
        self.assertEqual(gate_codes.dimensions(jpeg(200, 210)), (200, 210))
        for data in (b"", b"GIF89a" + bytes(40), b"\x89PNG\r\n\x1a\n", b"\xff\xd8", b"\xff\xd8\xff\xd9", b"\xff\xd8\xff\xc0\x00", bytes(30)):
            self.assertIsNone(gate_codes.dimensions(data))

    def test_a_small_near_square_picture_is_a_code_and_a_logo_a_banner_a_pixel_and_a_poster_are_not(self):
        yes = [(290, 290), (100, 100), (1000, 1000), (360, 400), (300, 310)]
        no = [(64, 64), (99, 99), (600, 160), (400, 380), (1, 1), (1200, 1200), (300, 360), (1001, 1001), (160, 600), (90, 400)]
        for size in yes:
            self.assertTrue(gate_codes.looks_like_a_code(png(*size)), size)
        for size in no:
            self.assertFalse(gate_codes.looks_like_a_code(png(*size)), size)
        self.assertTrue(gate_codes.looks_like_a_code(jpeg(250, 250)))

    def test_a_picture_that_comes_twice_in_one_message_is_a_header_and_never_a_code(self):
        header = {"type": "image/png", "data": png(200, 200)}
        qr = {"type": "image/png", "data": QR}
        self.assertEqual(gate_codes.qualifying([header, qr, header]), [1])
        self.assertEqual(gate_codes.qualifying([qr, {"type": "image/png", "data": OTHER_QR}]), [0, 1])
        self.assertEqual(gate_codes.qualifying([{"type": "image/png", "data": b""}]), [])


class Kept(ScanCase):
    def setUp(self):
        super().setUp()
        self.segment = self.park()

    def park(self, fields=PARKING, viewer=None) -> int:
        made = self.read(lambda conn: trips.add_segment(conn, viewer or self.jane, {**fields, "travelers": [{"person_id": self.jane.person_id, "name": None}]}))
        assert made
        return int(made["id"])

    def keep(self, mid: str, raw: dict, segments=None, now: float = NOW) -> None:
        scan.keep_message(self.mailbox, mid, raw, [self.segment] if segments is None else segments, now)

    def state(self, segment: int | None = None):
        return self.read(lambda conn: gate_codes.states(conn, [segment or self.segment]).get(segment or self.segment))

    def image(self, segment: int | None = None):
        return self.read(lambda conn: gate_codes.image_for(conn, segment or self.segment))

    def rows(self) -> int:
        return int(self.read(lambda conn: conn.execute(select(func.count()).select_from(SegmentCode)).scalar()))


class ConfirmationTests(Kept):
    def test_one_qualifying_picture_in_a_parking_message_is_kept_with_the_booking_sealed_and_shown_as_received(self):
        with no_leaks(self, *CANARIES, database=self.path):
            self.keep("m1", raw_of("Your parking reservation", {"qr": QR, "logo": png(64, 64)}, text=CANARY_TEXT + " PK30417"))
            self.assertEqual(self.state(), ("ready", "2026-10-16"))
            self.assertEqual(self.image(), {"type": "image/png", "data": QR})
            [out] = [s for s in self.segments() if s["id"] == self.segment]
            self.assertEqual(out["gate_code"], {"state": "ready", "day": "2026-10-16"})
        sealed = self.read(lambda conn: conn.execute(select(SegmentCode.content)).scalar())
        self.assertTrue(secretbox.is_encrypted(sealed))
        self.assertNotIn(CANARY_PIXELS.decode(), sealed)

    def test_a_message_read_later_and_linked_to_the_booking_gives_its_picture_too(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}), segments=[])
        self.assertIsNone(self.state())
        self.read(lambda conn: stored_mail.link(conn, self.segment, self.mailbox, "m1"))
        self.assertEqual(self.state(), ("ready", "2026-10-16"))

    def test_two_qualifying_pictures_keep_none_until_one_is_chosen(self):
        self.keep("m1", raw_of("Your parking reservation", {"a": QR, "b": OTHER_QR}))
        self.assertEqual(self.state(), ("choose", "2026-10-16"))
        self.assertIsNone(self.image())
        [out] = [s for s in self.segments() if s["id"] == self.segment]
        self.assertEqual(out["gate_code"], {"state": "choose", "day": "2026-10-16"})
        done = self.read(lambda conn: trips.choose_gate_code(conn, self.jane, self.segment, 0, 1, NOW))
        assert done
        self.assertEqual(done["gate_code"], {"state": "ready", "day": "2026-10-16"})
        self.assertEqual(self.image(), {"type": "image/png", "data": OTHER_QR})

    def test_a_logo_a_wide_banner_and_a_tracking_pixel_never_qualify(self):
        self.keep("m1", raw_of("Your parking reservation", {"logo": png(64, 64), "banner": png(600, 160), "pixel": png(1, 1)}))
        self.assertIsNone(self.state())
        self.assertEqual(self.rows(), 0)
        [out] = [s for s in self.segments() if s["id"] == self.segment]
        self.assertIsNone(out["gate_code"])

    def test_a_header_picture_repeated_in_the_message_is_not_taken_for_the_code(self):
        self.keep("m1", raw_of("Your parking reservation", {"top": png(200, 200), "bottom": png(200, 200)}))
        self.assertIsNone(self.state())

    def test_a_message_with_no_picture_keeps_none(self):
        self.keep("m1", raw_of("Your parking reservation", {}))
        self.assertIsNone(self.state())

    def test_a_booking_that_is_not_parking_never_keeps_a_code(self):
        stay = self.park(STAY)
        self.keep("m1", raw_of("Your reservation", {"qr": QR}), segments=[stay])
        self.assertIsNone(self.state(stay))
        self.assertEqual(self.rows(), 0)
        self.assertFalse(self.read(lambda conn: gate_codes.choose(conn, stay, 0, 0, NOW)))

    def test_a_newer_code_replaces_an_older_one_and_an_older_one_never_replaces_a_newer(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}, day="Fri, 16 Oct 2026 09:00:00 +0100"))
        self.keep("m2", raw_of("QR code reminder", {"qr": OTHER_QR}, day="Mon, 19 Oct 2026 09:00:00 +0100"))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-19"), {"type": "image/png", "data": OTHER_QR}))
        self.keep("m3", raw_of("Old reminder", {"qr": QR}, day="Sat, 17 Oct 2026 09:00:00 +0100"))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-19"), {"type": "image/png", "data": OTHER_QR}))

    def test_a_later_message_with_several_pictures_does_not_take_away_a_code_already_kept(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        self.keep("m2", raw_of("Reminder", {"a": QR, "b": OTHER_QR}, day="Mon, 19 Oct 2026 09:00:00 +0100"))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-16"), {"type": "image/png", "data": QR}))

    def test_a_single_code_after_a_choice_is_open_replaces_the_open_choice(self):
        self.keep("m1", raw_of("Your parking reservation", {"a": QR, "b": OTHER_QR}))
        self.assertEqual(self.state(), ("choose", "2026-10-16"))
        self.keep("m2", raw_of("Reminder", {"qr": OTHER_QR}, day="Mon, 19 Oct 2026 09:00:00 +0100"))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-19"), {"type": "image/png", "data": OTHER_QR}))

    def test_choosing_takes_only_a_picture_of_this_bookings_emails(self):
        self.keep("m1", raw_of("Your parking reservation", {"a": QR, "b": OTHER_QR}))
        for email_at, picture in ((1, 0), (-1, 0), (0, 2), (0, -1)):
            self.assertFalse(self.read(lambda conn, e=email_at, p=picture: gate_codes.choose(conn, self.segment, e, p, NOW)), (email_at, picture))
        with self.assertRaises(trips.Invalid):
            self.read(lambda conn: trips.choose_gate_code(conn, self.jane, self.segment, 3, 0, NOW))
        self.assertIsNone(self.read(lambda conn: trips.choose_gate_code(conn, self.sam, self.segment, 0, 0, NOW)))
        self.assertEqual(self.state(), ("choose", "2026-10-16"))

    def test_a_booking_edit_never_removes_the_code(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        edited = self.read(lambda conn: trips.edit_segment(conn, self.jane, self.segment, {"origin": "Example Airport Economy Lot", "end_local": "2026-12-05T03:00"}))
        assert edited
        self.assertEqual(edited["gate_code"], {"state": "ready", "day": "2026-10-16"})
        self.assertEqual(self.image(), {"type": "image/png", "data": QR})


class GoneWithTheMessageTests(Kept):
    def test_the_code_goes_with_the_last_booking_made_from_the_message(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        self.assertTrue(self.read(lambda conn: trips.delete_segment(conn, self.jane, self.segment)))
        self.assertEqual(self.rows(), 0)
        self.assertEqual(self.read(lambda conn: conn.execute(select(StoredMessage.id)).fetchall()), [])

    def test_the_code_goes_with_the_mailbox_it_came_from(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        self.assertEqual(self.rows(), 1)
        self.read(lambda conn: conn.execute(delete(Mailbox).where(Mailbox.id == self.mailbox)))
        self.assertEqual(self.rows(), 0)
        self.assertEqual(self.read(lambda conn: conn.execute(select(StoredMessage.id)).fetchall()), [])
        self.assertEqual(len(self.segments()), 1)

    def test_an_item_dismissed_with_no_booking_leaves_no_code_behind(self):
        self.read(lambda conn: review.add(conn, self.mailbox, "m1", "mail.exampleparking.example", "2026-10-16", "no_markup", NOW))
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}), segments=[])
        [item] = self.items()
        self.assertTrue(self.read(lambda conn: review.dismiss(conn, "u-jane", item["id"])))
        self.assertEqual(self.read(lambda conn: conn.execute(select(StoredMessage.id)).fetchall()), [])
        self.assertEqual(self.rows(), 0)

    def test_clearing_a_trips_saved_emails_clears_its_codes(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        trip_id = self.read(lambda conn: conn.execute(select(Segment.trip_id).where(Segment.id == self.segment)).scalar())
        today = datetime(2027, 3, 1).date()
        self.assertIsNotNone(self.read(lambda conn: trips.clear_emails(conn, self.jane, trip_id, today, NOW)))
        self.assertEqual(self.rows(), 0)

    def test_the_code_comes_back_from_a_backup_sealed_and_exact(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        self.read(lambda conn: conn.commit())
        dumped = self.read(backup.dump)
        for banned in (CANARY_PIXELS, base64.b64encode(QR)):
            self.assertNotIn(banned, dumped)
            self.assertNotIn(banned, __import__("gzip").decompress(dumped))
        data = backup.load(dumped)
        columns = data["tables"]["segment_codes"]["columns"]
        [row] = data["tables"]["segment_codes"]["rows"]
        self.assertTrue(secretbox.is_encrypted(row[columns.index("content")]))
        self.read(lambda conn: conn.execute(delete(SegmentCode)))
        self.read(lambda conn: backup.restore(conn, data))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-16"), {"type": "image/png", "data": QR}))

    def test_a_code_stays_sealed_when_the_key_is_rotated(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        self.read(lambda conn: conn.execute(SegmentCode.__table__.update().values(content=None)))
        self.assertEqual(self.state(), ("choose", "2026-10-16"))
        self.assertEqual(self.read(secretbox.encrypt_stored), 0)
        self.keep("m2", raw_of("Reminder", {"qr": QR}, day="Mon, 19 Oct 2026 09:00:00 +0100"))
        self.read(lambda conn: conn.execute(SegmentCode.__table__.update().values(content=json.dumps({"type": "image/png", "data": "AAAA"}))))
        self.assertEqual(self.read(secretbox.encrypt_stored), 1)
        self.assertTrue(secretbox.is_encrypted(self.read(lambda conn: conn.execute(select(SegmentCode.content)).scalar())))

    def test_a_code_that_cannot_be_opened_shows_as_none(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        for bad in (secretbox.PREFIX + "bad", secretbox.encrypt(json.dumps([1])), secretbox.encrypt(json.dumps({"type": "image/png", "data": "!!"})),
                    secretbox.encrypt(json.dumps({"data": base64.b64encode(QR).decode()}))):
            self.read(lambda conn, sealed=bad: conn.execute(SegmentCode.__table__.update().values(content=sealed)))
            self.assertIsNone(self.image())


class NeverElsewhereTests(Kept):
    def test_the_offline_copy_the_calendar_and_an_assistant_never_carry_the_code_or_say_there_is_one(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}, text=CANARY_TEXT))
        stamp = base64.b64encode(QR).decode()
        shown = trips.listing(self.c, self.jane)
        feed = calendar.feed(shown, datetime(2026, 10, 20))
        self.assertIn("Parking: Example Airport Long-Term Lot", feed)
        self.assertNotIn(stamp[:24], feed)
        self.assertNotIn("gate", feed.lower())
        saved = self.read(lambda conn: offline.projection(conn, self.jane, datetime(2026, 12, 2).date()))
        text = json.dumps(saved)
        self.assertEqual([s["gate_code"] for s in saved["trip"]["segments"]], [None])
        self.assertNotIn(stamp[:24], text)
        self.assertNotIn("gate_code", json.dumps(mcp_server._without_gate_codes({"trips": [{"segments": [{"id": 1, "gate_code": {"state": "ready"}}]}]})))
        self.assertEqual(mcp_server._without_gate_codes([{"gate_code": 1, "id": 2}, 3]), [{"id": 2}, 3])


class FollowUpTests(Kept):
    def reminder(self, mid: str, images: dict[str, bytes], text: str | None = None, subject: str = "Your parking reservation: QR code reminder",
                 domain: str = "mail.exampleparking.example", day: str = "Mon, 19 Oct 2026 09:00:00 +0100") -> None:
        self.add_mail(mid, mail(subject, images, text or f"Show this at the gate. Reservation PK30417. {CANARY_TEXT}", domain, day))

    def test_a_reminders_picture_is_kept_with_the_matched_booking_and_its_text_and_markup_are_not(self):
        self.reminder("m-reminder", {"qr": QR})
        with no_leaks(self, *CANARIES, database=self.path):
            result = self.scan()
        self.assertEqual((result.state, result.bookings, result.review), ("done", 0, 0))
        self.assertEqual(self.scanned()["m-reminder"], "follow-up")
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-19"), {"type": "image/png", "data": QR}))
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(StoredMessage)).scalar()), 0)
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(SegmentMessage)).scalar()), 0)
        self.assertEqual(self.items(), [])

    def test_a_newer_reminder_replaces_the_code_and_the_booking_says_only_which_day(self):
        self.keep("m1", raw_of("Your parking reservation", {"qr": QR}))
        self.reminder("m-reminder", {"qr": OTHER_QR})
        self.scan()
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-19"), {"type": "image/png", "data": OTHER_QR}))

    def test_a_reminder_with_several_pictures_leaves_the_choice_to_a_person_and_one_with_none_changes_nothing(self):
        self.reminder("m-two", {"a": QR, "b": OTHER_QR})
        self.reminder("m-none", {}, day="Tue, 20 Oct 2026 09:00:00 +0100")
        self.scan()
        self.assertEqual(self.state(), ("choose", "2026-10-19"))
        self.assertIsNone(self.image())

    def test_a_reminder_for_a_booking_that_is_not_parking_keeps_no_picture(self):
        stay = self.park(STAY)
        self.add_mail("m-stay", mail("Your stay: online check-in is open", {"qr": QR}, "Check-in opens soon for reservation H88231.", "mail.harbourhotel.example"))
        self.scan()
        self.assertEqual(self.scanned()["m-stay"], "follow-up")
        self.assertIsNone(self.state(stay))
        self.assertEqual(self.rows(), 0)

    def test_a_reminder_from_a_sender_the_booking_does_not_know_keeps_nothing(self):
        self.reminder("m-other", {"qr": QR}, domain="lots.unrelated.example")
        self.scan()
        self.assertEqual(self.rows(), 0)

    def test_a_reminder_that_cancels_is_queued_for_a_person_and_keeps_nothing(self):
        self.reminder("m-cancel", {"qr": QR}, subject="Your parking reservation was cancelled", text="Your parking reservation PK30417 has been cancelled.")
        self.scan()
        self.assertNotEqual(self.scanned()["m-cancel"], "follow-up")
        self.assertEqual(self.rows(), 0)

    def test_a_picture_that_cannot_be_read_does_not_stop_the_scan(self):
        self.reminder("m-reminder", {"qr": QR})
        from unittest import mock
        with mock.patch.object(gate_codes, "offer", side_effect=RuntimeError(CANARY_TEXT)), no_leaks(self, CANARY_TEXT):
            result = self.scan()
        self.assertEqual(result.state, "done")
        self.assertEqual(self.scanned()["m-reminder"], "follow-up")
        self.assertEqual(self.rows(), 0)


class CodeRouteTests(ServerCase):
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "ana@example.com,ben@example.com,cy@example.com"}

    def setUp(self):
        with db.session() as conn:
            for table in (Trip, Mailbox, AuthSession, User, Person):
                conn.execute(delete(table))
        self.who = {n: self.sign_in(f"sub-{n}", f"{n}@example.com", n.title()) for n in ("ana", "ben", "cy")}
        with db.session() as conn:
            self.person = {n: people.person_for_sub(conn, f"sub-{n}") for n in self.who}
            self.box = int(conn.execute(insert(Mailbox).values(owner_sub="sub-ana", address="ana@gmail.example", token=secretbox.encrypt("t"),
                                                               status="connected", created=1.0)).lastrowid)
        status, made = self.call("ana", "POST", "/api/segments", {**PARKING, "travelers": [{"person_id": self.person["ana"]}]})
        self.assertEqual(status, 200, made)
        self.segment = made["id"]

    def sign_in(self, sub, email_address, name) -> dict:
        token = secrets.token_urlsafe(24)
        now = time.time()
        with db.session() as conn:
            conn.execute(insert(AuthSession).values(token_hash=oidc._hash(token), sub=sub, email=email_address, name=name, created=now, expires=now + 86400))
            oidc.remember_user(conn, sub, email_address, name, None, now)
        return {"Cookie": f"waypoint_session={token}"}

    def call(self, who, method, path, body=None):
        return self.req(method, path, body if method != "GET" else None, self.who[who])

    def code(self, who, segment=None):
        return fetch(self.base, "GET", f"/api/segments/{segment or self.segment}/code", None, self.who[who] if who else {})

    def keep(self, *pictures: bytes) -> None:
        content = {"subject": "Your parking reservation", "sender_domain": "mail.exampleparking.example", "received": "2026-10-16",
                   "text": CANARY_TEXT, "html": f"<p>{CANARY_TEXT}</p>", "truncated": False, "original": True, "images": len(pictures)}
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", content, 1.0, [{"type": "image/png", "data": p} for p in pictures])   # type: ignore[arg-type]
            stored_mail.link(conn, self.segment, self.box, "m1")

    def test_the_picture_is_served_as_received_to_whoever_can_see_the_booking_and_to_nobody_else(self):
        self.keep(QR)
        with no_leaks(self, *CANARIES):
            status, headers, raw = self.code("ana")
            self.assertEqual((status, raw, headers["Content-Type"]), (200, QR, "image/png"))
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("default-src 'none'; sandbox", headers.get_all("Content-Security-Policy"))
            for who in ("ben", "cy"):
                status, _, raw = self.code(who)
                self.assertEqual((status, json.loads(raw)), (404, {"error": "No such code"}))
            self.assertEqual(self.code(None)[0], 401)
            for bad in ("99999", "x", "-1"):
                self.assertEqual(self.code("ana", bad)[0], 404, bad)

    def test_a_booking_without_a_code_and_one_still_to_be_chosen_serve_none(self):
        self.assertEqual(self.code("ana")[0], 404)
        self.keep(QR, OTHER_QR)
        self.assertEqual(self.code("ana")[0], 404)

    def test_whoever_sees_the_trip_through_a_traveller_a_booker_or_a_received_confirmation_sees_the_code_and_nobody_else(self):
        self.keep(QR)
        trip_id = self.call("ana", "GET", f"/api/segments/{self.segment}")[1]["trip_id"]
        self.assertEqual((self.code("ben")[0], self.code("cy")[0]), (404, 404))
        status, flight = self.call("ana", "POST", "/api/segments", {"kind": "flight", "origin": "JFK", "destination": "SFO", "trip_id": trip_id,
                                                                    "start_local": "2026-12-01T08:00", "end_local": "2026-12-01T11:20",
                                                                    "travelers": [{"person_id": self.person["ben"]}]})
        self.assertEqual(status, 200, flight)
        self.assertEqual(self.code("ben")[2], QR)
        self.assertEqual(self.code("cy")[0], 404)
        with db.session() as conn:
            seg = conn.orm.get(Segment, self.segment)
            self.assertTrue(visibility.note_recipient(conn, Viewer(self.person["cy"]), seg))
        self.assertEqual(self.code("cy")[2], QR)
        self.call("ana", "POST", f"/api/segments/{flight['id']}", {"travelers": [{"person_id": self.person["ana"]}]})
        self.assertEqual(self.code("ben")[0], 404)

    def test_the_trip_reply_says_whether_there_is_a_code_and_never_carries_it(self):
        self.keep(QR, OTHER_QR)
        [trip] = self.call("ana", "GET", "/api/trips")[1]["trips"]
        self.assertEqual(trip["segments"][0]["gate_code"], {"state": "choose", "day": "2026-10-16"})
        self.assertTrue(all(s["gate_code"] is None for t in self.call("ben", "GET", "/api/trips")[1]["trips"] for s in t["segments"]))
        self.assertNotIn(base64.b64encode(QR).decode()[:24], json.dumps(trip))

    def test_choosing_saves_the_picture_for_the_booking_and_answers_404_to_anyone_who_cannot_see_it(self):
        self.keep(QR, OTHER_QR)
        body = {"email": 0, "image": 1}
        self.assertEqual(self.call("ben", "POST", f"/api/segments/{self.segment}/code", body), (404, {"error": "No such segment"}))
        self.assertEqual(self.call("ana", "POST", "/api/segments/99999/code", body)[0], 404)
        status, chosen = self.call("ana", "POST", f"/api/segments/{self.segment}/code", body)
        self.assertEqual((status, chosen["gate_code"]), (200, {"state": "ready", "day": "2026-10-16"}))
        self.assertEqual(self.code("ana")[2], OTHER_QR)

    def test_a_choice_that_is_not_a_picture_of_the_bookings_emails_is_refused(self):
        self.keep(QR, OTHER_QR)
        for body in ({"email": 0, "image": 5}, {"email": 4, "image": 0}):
            status, got = self.call("ana", "POST", f"/api/segments/{self.segment}/code", body)
            self.assertEqual((status, got), (400, {"error": "Choose one of the pictures in this booking’s emails"}))
        for body in ({}, {"email": 0}, {"email": -1, "image": 0}, {"email": 0, "image": 1.5}, {"email": True, "image": 0}):
            self.assertEqual(self.call("ana", "POST", f"/api/segments/{self.segment}/code", body)[0], 400, body)
        self.assertEqual(self.code("ana")[0], 404)

    def test_choosing_for_a_booking_that_is_not_parking_is_refused(self):
        status, stay = self.call("ana", "POST", "/api/segments", {**STAY, "travelers": [{"person_id": self.person["ana"]}]})
        self.assertEqual(status, 200)
        status, got = self.call("ana", "POST", f"/api/segments/{stay['id']}/code", {"email": 0, "image": 0})
        self.assertEqual(status, 400, got)


if __name__ == "__main__":
    unittest.main()
