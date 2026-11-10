import base64
import email.message
import itertools
import json
import secrets
import struct
import threading
import time
import unittest
import zlib
from unittest import mock
from datetime import datetime

from sqlalchemy import delete, func, insert, select, update

from tests.privacy import no_leaks
from tests.shared import ServerCase, fetch
from tests.test_mail_ai import ScanAiCase
from tests.test_mail_scan import NOW, ScanCase, b64
from waypoint import oidc
from waypoint.domain import calendar, offline, people, trips, visibility
from waypoint.domain.visibility import Viewer
from waypoint.domain.mail import ai, gatecode, review, scan
from waypoint.server import mcp_server
from waypoint.server.api import assistant as assistant_api
from waypoint.server.api import review as review_api
from waypoint.server.common import _current
from waypoint.storage import backup, db, gate_codes, secretbox, stored_mail
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import AuthSession, Mailbox, Person, ReviewItem, Segment, SegmentCode, SegmentMessage, StoredMessage, Trip, User

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

    def test_a_picture_chosen_by_hand_survives_reading_the_same_email_again_and_an_edit_and_a_strictly_newer_email_replaces_it(self):
        mine = png(64, 64, CANARY_OTHER)
        message = raw_of("Your parking reservation", {"qr": QR, "mine": mine})
        self.keep("m1", message)
        self.assertEqual(self.image(), {"type": "image/png", "data": QR})
        self.assertTrue(self.read(lambda conn: gate_codes.choose(conn, self.segment, 0, 1, NOW)))
        chosen = {"type": "image/png", "data": mine}
        self.assertEqual(self.image(), chosen)
        self.keep("m1", message, now=NOW + 5)
        self.read(lambda conn: stored_mail.link(conn, self.segment, self.mailbox, "m1"))
        self.assertEqual(self.image(), chosen)
        self.read(lambda conn: trips.edit_segment(conn, self.jane, self.segment, {"end_local": "2026-12-05T03:00"}))
        self.assertEqual(self.image(), chosen)
        self.keep("m2", raw_of("Reminder", {"qr": OTHER_QR}, day="Mon, 19 Oct 2026 09:00:00 +0100"))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-19"), {"type": "image/png", "data": OTHER_QR}))

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
        self.assertEqual([s["gate_code"] for s in saved["trips"][0]["trip"]["segments"]], [None])
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
                self.assertEqual((status, json.loads(raw)), (404, {"error": "No such image"}))
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


class PickedByAiTests(ScanAiCase, Kept):
    TWO = raw_of("Your parking reservation", {"a": QR, "b": OTHER_QR})

    def answer(self, content: str, status: int = 200) -> None:
        self.fake.content, self.fake.status = content, status

    def keep_two(self) -> None:
        scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment], NOW)

    def test_local_with_several_candidates_and_a_vision_model_makes_the_picked_picture_the_code(self):
        self.turn_on(auto=False)
        self.answer('{"picture": 2}')
        with no_leaks(self, CANARY_TEXT, database=self.path, sent_ok=True):
            self.keep_two()
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-16"), {"type": "image/png", "data": OTHER_QR}))
        [(path, _, body)] = self.fake.requests
        self.assertTrue(path.endswith("/api/chat"))
        user = body["messages"][1]
        self.assertEqual(user["images"], [base64.b64encode(QR).decode(), base64.b64encode(OTHER_QR).decode()])
        self.assertNotIn("PK30417", json.dumps(body["messages"]))

    def test_a_reminder_with_several_candidates_is_settled_the_same_way(self):
        self.turn_on(auto=False)
        self.answer('{"picture": 1}')
        self.add_mail("m-reminder", mail("Your parking reservation: QR code reminder", {"a": QR, "b": OTHER_QR},
                                         f"Show this at the gate. Reservation PK30417. {CANARY_TEXT}", day="Mon, 19 Oct 2026 09:00:00 +0100"))
        with no_leaks(self, CANARY_TEXT, database=self.path, sent_ok=True):
            self.scan()
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-19"), {"type": "image/png", "data": QR}))
        self.assertNotIn(CANARY_TEXT, json.dumps(self.fake.requests[0][2]))

    def test_an_error_a_timeout_a_text_only_model_and_an_unusable_answer_leave_the_picker_as_it_is(self):
        self.turn_on(auto=False)
        for content, status in (("{}", 500), ("{}", 400), ("I can only read text.", 200), ('{"picture": 0}', 200), ('{"picture": 3}', 200),
                                ('{"picture": "1"}', 200), ('{"picture": true}', 200), ("[1]", 200), ("", 200)):
            with self.subTest(content=content, status=status):
                self.answer(content, status)
                with db.session() as conn:
                    conn.execute(SegmentCode.__table__.delete())
                self.keep_two()
                self.assertEqual((self.state(), self.image()), (("choose", "2026-10-16"), None))

    def test_a_connection_that_fails_leaves_the_picker_as_it_is(self):
        self.turn_on(auto=False)
        with db.session() as conn:
            db.set_setting(conn, sk.AI_OLLAMA_URL, "http://127.0.0.1:1")
        self.keep_two()
        self.assertEqual((self.state(), self.image()), (("choose", "2026-10-16"), None))

    def test_openrouter_and_off_send_no_picture(self):
        for mode in ("openrouter", "off"):
            with self.subTest(mode=mode):
                self.fake.reset()
                with db.session() as conn:
                    conn.execute(SegmentCode.__table__.delete())
                self.turn_on(mode, auto=False)
                with db.session() as conn:
                    db.set_setting(conn, sk.AI_OPENROUTER_MODEL, "m/model")
                    db.set_setting(conn, sk.AI_OPENROUTER_KEY, "sk-test-key-1234")
                with no_leaks(self, *CANARIES, database=self.path):
                    self.keep_two()
                self.assertEqual(self.fake.requests, [])
                self.assertEqual(self.state(), ("choose", "2026-10-16"))

    def test_one_candidate_and_a_booking_that_already_has_a_code_send_no_picture(self):
        self.turn_on(auto=False)
        scan._keep_quietly(self.mailbox, "m-one", raw_of("Your parking reservation", {"a": QR}), [self.segment], NOW)
        self.assertEqual(self.fake.requests, [])
        scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment], NOW + 1)
        self.assertEqual(self.fake.requests, [])
        self.assertEqual(self.image(), {"type": "image/png", "data": QR})

    def test_a_picture_chosen_by_a_person_is_never_overwritten_by_the_ai(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        self.keep_two()
        self.assertTrue(self.read(lambda conn: gate_codes.choose(conn, self.segment, 0, 0, NOW)))
        self.answer('{"picture": 2}')
        self.assertFalse(gatecode.settle(self.segment, self.mailbox, "m-two", NOW + 5))
        self.assertEqual(self.image(), {"type": "image/png", "data": QR})
        self.assertEqual(len(self.fake.requests), 1)

    def race(self, commit) -> None:
        real = gate_codes._sealed
        fired = []

        def wrapped(*args, **kwargs):
            if not fired:
                fired.append(True)
                commit()
            return real(*args, **kwargs)

        patcher = mock.patch.object(gate_codes, "_sealed", wrapped)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_choice_committed_after_the_reads_is_not_overwritten_by_the_ai(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        self.keep_two()
        self.answer('{"picture": 2}')
        self.race(lambda: self.read(lambda conn: gate_codes.choose(conn, self.segment, 0, 0, NOW + 5)))
        self.assertFalse(gatecode.settle(self.segment, self.mailbox, "m-two", NOW + 20))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-16"), {"type": "image/png", "data": QR}))

    def test_a_newer_single_picture_email_committed_after_the_reads_is_not_overwritten_by_the_ai(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        self.keep_two()
        self.answer('{"picture": 2}')
        newer = raw_of("Your parking reservation", {"x": png(410, 410, b"NEWER-X")}, day="Sat, 17 Oct 2026 09:00:00 +0100")
        self.race(lambda: scan.keep_message(self.mailbox, "m-newer", newer, [self.segment], NOW + 10))
        self.assertFalse(gatecode.settle(self.segment, self.mailbox, "m-two", NOW + 20))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-17"), {"type": "image/png", "data": png(410, 410, b"NEWER-X")}))

    def test_a_segment_that_stops_being_parking_before_the_write_gets_no_code(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        self.keep_two()
        self.answer('{"picture": 2}')

        def change() -> None:
            with db.session() as conn:
                conn.execute(update(Segment).where(Segment.id == self.segment).values(kind="hotel"))

        self.race(change)
        self.assertFalse(gatecode.settle(self.segment, self.mailbox, "m-two", NOW + 20))
        self.assertEqual(self.image(), None)

    def test_pictures_settled_while_a_choice_commits_during_the_pick_never_replace_it(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        self.keep_two()
        self.answer('{"picture": 2}')
        pictures = [{"type": "image/png", "data": QR}, {"type": "image/png", "data": OTHER_QR}]
        self.read(lambda conn: conn.execute(SegmentCode.__table__.update().values(opened_by=None)))
        self.fake.on_request = lambda n: self.read(lambda conn: gate_codes.choose(conn, self.segment, 0, 0, NOW + 5))
        self.assertFalse(gatecode.settle_pictures(self.segment, self.mailbox, pictures[::-1], "2026-10-16", NOW + 20))
        self.assertEqual(self.image(), {"type": "image/png", "data": QR})

    def test_a_held_day_newer_than_the_candidate_blocks_the_write(self):
        with db.session() as conn:
            conn.execute(SegmentCode.__table__.delete())
            gate_codes._set(conn, self.segment, self.mailbox, None, "2026-10-20", NOW)
        picture = {"type": "image/png", "data": QR}
        with db.session() as conn:
            self.assertFalse(gate_codes.keep_chosen(conn, self.segment, self.mailbox, picture, "2026-10-16", NOW))
            self.assertFalse(gate_codes.keep_chosen(conn, self.segment, self.mailbox, picture, None, NOW))
            self.assertTrue(gate_codes.keep_chosen(conn, self.segment, self.mailbox, picture, "2026-10-20", NOW))
        self.assertEqual((self.state(), self.image()), (("ready", "2026-10-20"), picture))

    def test_more_pictures_than_the_limit_are_not_sent(self):
        self.turn_on(auto=False)
        many = {f"p{n}": png(200 + n, 200 + n, bytes([n]) * 9) for n in range(ai.MAX_PICTURES + 1)}
        scan._keep_quietly(self.mailbox, "m-many", raw_of("Your parking reservation", many), [self.segment], NOW)
        self.assertEqual((self.fake.requests, self.state()), ([], ("choose", "2026-10-16")))

    def test_a_failure_inside_the_pick_is_reported_without_values_and_never_stops_the_scan(self):
        self.turn_on(auto=False)
        with mock.patch.object(ai, "pick_picture", side_effect=RuntimeError(CANARY_TEXT)), mock.patch.object(gatecode.monitoring, "report") as report:
            self.keep_two()
        report.assert_called_once()
        self.assertEqual(report.call_args.kwargs, {"values": False})
        self.assertEqual((self.state(), self.image()), (("choose", "2026-10-16"), None))

    def test_a_busy_database_is_not_swallowed(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        self.keep_two()
        with mock.patch.object(ai, "pick_picture", side_effect=RuntimeError("busy")), mock.patch.object(gatecode.db, "is_busy", return_value=True):
            with self.assertRaises(RuntimeError):
                gatecode.settle(self.segment, self.mailbox, "m-two", NOW)

    def test_settling_does_nothing_without_a_choice_waiting_or_enough_candidates(self):
        self.turn_on(auto=False)
        self.assertFalse(gatecode.settle(self.segment, self.mailbox, "m-two", NOW))
        self.assertFalse(gatecode.settle_pictures(self.segment, self.mailbox, [{"type": "image/png", "data": QR}], None, NOW))
        self.assertFalse(gatecode.settle_pictures(self.segment, self.mailbox, [{"type": "image/png", "data": QR}] * 2, None, NOW))
        self.assertEqual(self.fake.requests, [])
        self.keep_two()
        self.fake.reset()
        self.assertFalse(gatecode.settle_pictures(self.segment, self.mailbox, [{"type": "image/png", "data": QR}] * 2, None, NOW))
        self.assertFalse(gatecode.settle_pictures(self.segment, self.mailbox, [{"type": "image/png", "data": QR}] * 2, "2026-10-16", NOW))
        self.assertEqual(self.fake.requests, [])

    def test_an_older_reminder_settled_by_the_ai_never_replaces_a_newer_choice_still_waiting(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        self.add_mail("m-new", mail("Your parking reservation: QR code reminder", {"a": QR, "b": OTHER_QR},
                                    f"Show this at the gate. Reservation PK30417. {CANARY_TEXT}", day="Mon, 19 Oct 2026 09:00:00 +0100"))
        self.scan()
        self.assertEqual((self.state(), self.image()), (("choose", "2026-10-19"), None))
        self.answer('{"picture": 1}')
        self.add_mail("m-old", mail("Your parking reservation: QR code reminder", {"c": png(310, 310, b"OLDER-ONE-1"), "d": png(320, 320, b"OLDER-TWO-2")},
                                    f"Show this at the gate. Reservation PK30417. {CANARY_TEXT}", day="Fri, 16 Oct 2026 09:00:00 +0100"))
        self.scan()
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual((self.state(), self.image()), (("choose", "2026-10-19"), None))

    def test_a_message_linked_while_the_ai_is_thinking_never_changes_which_picture_is_saved(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        self.keep_two()
        self.answer('{"picture": 2}')
        newer = raw_of("Your parking reservation", {"x": png(410, 410, b"NEWER-X"), "y": png(420, 420, b"NEWER-Y")}, day="Sat, 17 Oct 2026 09:00:00 +0100")
        self.fake.on_request = lambda n: scan.keep_message(self.mailbox, "m-newer", newer, [self.segment], NOW + 10)
        gatecode.settle(self.segment, self.mailbox, "m-two", NOW + 20)
        self.assertEqual((self.state(), self.image()), (("choose", "2026-10-17"), None))


class AiFiledTests(ScanAiCase, Kept):
    PARKING_ANSWER = json.dumps({"kind": "parking", "provider": "Example Parking", "confirmation": "PK30417", "origin": "Example Airport Long-Term Lot",
                                 "start_local": "2026-12-01T05:15", "end_local": "2026-12-04T03:00",
                                 "start_zone": "America/New_York", "end_zone": "America/New_York"})

    def setUp(self):
        super().setUp()
        self.read(lambda conn: conn.execute(Segment.__table__.delete()))
        self.add_mail("m-ai", mail("Your parking reservation PK30417 is confirmed", {"a": QR, "b": OTHER_QR},
                                   f"Reservation PK30417 is confirmed. Entry QR codes below. {CANARY_TEXT}"))

    def answers(self, picture: str, status: int = 200) -> None:
        def on_request(n: int) -> None:
            self.fake.content, self.fake.status = (self.PARKING_ANSWER, 200) if n == 1 else (picture, status)
        self.fake.on_request = on_request

    def parking(self) -> list[int]:
        return [s["id"] for s in self.segments() if s["kind"] == "parking"]

    def code(self, segment: int):
        return self.state(segment), self.image(segment)

    def waiting_item(self) -> None:
        self.scan()
        self.assertEqual((self.parking(), len(self.items())), ([], 1))

    def test_a_booking_the_automatic_pass_files_is_settled_after_it_commits(self):
        self.turn_on()
        self.answers('{"picture": 2}')
        with no_leaks(self, CANARY_TEXT, database=self.path, sent_ok=True):
            self.scan()
        [segment] = self.parking()
        self.assertEqual(self.code(segment), (("ready", "2026-10-16"), {"type": "image/png", "data": OTHER_QR}))
        self.assertEqual(len(self.fake.requests), 2)
        self.assertNotIn("images", self.fake.requests[0][2]["messages"][1])

    def test_a_booking_filed_by_ask_ai_is_settled_after_it_commits(self):
        self.waiting_item()
        self.turn_on(auto=False)
        self.answers('{"picture": 1}')
        scan._ask(self.mailbox, "m-ai", "Reservation PK30417 is confirmed.", NOW)
        [segment] = self.parking()
        self.assertEqual(self.code(segment), (("ready", "2026-10-16"), {"type": "image/png", "data": QR}))

    def test_a_second_parking_booking_the_ai_could_not_file_stops_the_pick(self):
        self.turn_on()
        unfinished = json.dumps({"kind": "parking", "origin": "Other Lot", "start_local": "2026-12-01T05:15", "end_local": "2026-12-04T03:00"})
        reply = json.dumps({"bookings": [json.loads(self.PARKING_ANSWER), json.loads(unfinished)]})
        self.fake.content = reply
        self.scan()
        self.assertEqual(len(self.parking()), 1)
        self.assertTrue(all("images" not in body["messages"][1] for _, _, body in self.fake.requests))
        self.assertEqual(self.code(self.parking()[0]), (("choose", "2026-10-16"), None))

    def test_a_second_parking_booking_the_ai_response_held_but_parsing_rejected_stops_the_pick(self):
        self.turn_on()
        rejected = {"kind": "parking", "provider": "Example Parking", "confirmation": "PK30417"}
        self.fake.content = json.dumps({"bookings": [json.loads(self.PARKING_ANSWER), rejected]})
        self.scan()
        self.assertEqual(len(self.parking()), 1)
        self.assertTrue(all("images" not in body["messages"][1] for _, _, body in self.fake.requests))
        self.assertEqual(self.code(self.parking()[0]), (("choose", "2026-10-16"), None))

    def test_a_failing_settle_still_leaves_the_booking_filed_with_the_choice_open(self):
        self.turn_on()
        self.answers("{}", 500)
        self.scan()
        [segment] = self.parking()
        self.assertEqual(self.code(segment), (("choose", "2026-10-16"), None))
        self.assertEqual(self.items(), [])

    def test_a_settle_that_raises_does_not_stop_the_booking_or_the_scan(self):
        self.turn_on()
        self.answers('{"picture": 1}')
        with mock.patch.object(ai, "pick_picture", side_effect=RuntimeError("boom")):
            result = self.scan()
        self.assertEqual(result.state, "done")
        [segment] = self.parking()
        self.assertEqual(self.code(segment), (("choose", "2026-10-16"), None))

    def test_the_wait_for_pictures_is_capped_by_what_is_left_of_the_scans_time(self):
        self.turn_on()
        self.answers('{"picture": 1}')
        with mock.patch.object(ai, "pick_picture", wraps=ai.pick_picture) as picked:
            self.scan()
        [(_, _, timeout)] = [c.args for c in picked.call_args_list]
        self.assertLessEqual(timeout, scan.BUDGET)

    def test_with_hardly_any_time_left_no_picture_is_sent_and_the_choice_stays_open(self):
        self.turn_on()
        self.answers('{"picture": 1}')
        with mock.patch.object(scan, "_clock", side_effect=itertools.chain([0.0], itertools.repeat(scan.BUDGET - 1))):
            self.scan()
        [segment] = self.parking()
        self.assertEqual(self.code(segment), (("choose", "2026-10-16"), None))
        self.assertEqual(len(self.fake.requests), 1)


class OneMessageOnlyTests(ScanAiCase, Kept):
    TWO = raw_of("Your parking reservation", {"a": QR, "b": OTHER_QR})
    NEWER = raw_of("Your parking reservation", {"c": png(310, 310, b"NEWER-ONE-1"), "d": png(320, 320, b"NEWER-TWO-2")},
                   day="Mon, 19 Oct 2026 09:00:00 +0100")

    def answer(self, content: str, status: int = 200) -> None:
        self.fake.content, self.fake.status = content, status

    def test_only_the_pictures_of_the_message_that_reopened_the_choice_are_sent(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment], NOW)
        self.fake.reset()
        self.answer('{"picture": 2}')
        scan._keep_quietly(self.mailbox, "m-newer", self.NEWER, [self.segment], NOW + 1)
        [(_, _, body)] = self.fake.requests
        sent = body["messages"][1]["images"]
        self.assertNotIn(base64.b64encode(QR).decode(), sent)
        self.assertNotIn(base64.b64encode(OTHER_QR).decode(), sent)
        self.assertEqual(len(sent), 2)
        self.assertEqual(self.read(lambda conn: gate_codes.states(conn, [self.segment])[self.segment]), ("ready", "2026-10-19"))

    def test_two_parking_bookings_in_one_message_are_left_to_a_person(self):
        self.turn_on(auto=False)
        other = self.park({**PARKING, "confirmation": "PK30418"})
        self.answer('{"picture": 1}')
        scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment, other], NOW)
        self.assertEqual(self.fake.requests, [])
        self.assertEqual([(self.state(n), self.image(n)) for n in (self.segment, other)], [(("choose", "2026-10-16"), None)] * 2)

    def test_one_filed_parking_booking_beside_an_unresolved_one_is_left_to_a_person(self):
        self.turn_on(auto=False)
        self.answer('{"picture": 1}')
        scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment], NOW, parked=2)
        self.assertEqual(self.fake.requests, [])
        self.assertEqual((self.state(), self.image()), (("choose", "2026-10-16"), None))

    def test_exactly_one_parking_booking_in_the_message_still_settles(self):
        self.turn_on(auto=False)
        self.answer('{"picture": 1}')
        scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment], NOW, parked=1)
        self.assertEqual(self.image(), {"type": "image/png", "data": QR})

    def test_a_stay_beside_one_parking_booking_does_not_stop_the_pick(self):
        self.turn_on(auto=False)
        stay = self.park(STAY)
        self.answer('{"picture": 1}')
        scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment, stay], NOW)
        self.assertEqual(self.image(), {"type": "image/png", "data": QR})

    def test_the_ordinary_scan_paths_send_no_picture_when_the_scan_has_no_time_left(self):
        self.turn_on(auto=False)
        self.answer('{"picture": 1}')
        with mock.patch.object(scan, "_clock", return_value=float(scan.BUDGET)):
            scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment], NOW, 0.0)
            scan.keep_code(self.mailbox, self.segment, self.NEWER, NOW + 1, 0.0)
        self.assertEqual(self.fake.requests, [])
        self.assertEqual((self.state(), self.image()), (("choose", "2026-10-19"), None))

    def test_the_ordinary_scan_paths_cap_the_picture_wait_by_the_time_left(self):
        self.turn_on(auto=False)
        self.answer("{}", 500)
        with mock.patch.object(scan, "_clock", return_value=100.0), mock.patch.object(ai, "pick_picture", wraps=ai.pick_picture) as picked:
            scan._keep_quietly(self.mailbox, "m-two", self.TWO, [self.segment], NOW, 0.0)
            scan.keep_code(self.mailbox, self.segment, self.NEWER, NOW + 1, 0.0)
        self.assertEqual([c.args[2] for c in picked.call_args_list], [scan.BUDGET - 100.0] * 2)


class ReviewPathTests(ScanAiCase, Kept):
    TWO = raw_of("Your parking reservation", {"a": QR, "b": OTHER_QR}, text=f"Reservation PK30417. {CANARY_TEXT}")
    SUGGESTION = {"kind": "parking", "provider": "Example Parking", "confirmation": "PK30417", "origin": "Example Airport Long-Term Lot",
                  "start_local": "2026-12-01T05:15", "end_local": "2026-12-04T03:00", "start_zone": "America/New_York", "end_zone": "America/New_York"}
    HOTEL = {**SUGGESTION, "kind": "hotel", "origin": "Harbour Hotel", "confirmation": "H88231"}

    def setUp(self):
        super().setUp()
        self.turn_on(auto=False)
        self.fake.content = '{"picture": 2}'

    def fresh(self, held=None, suggestions=None, reason="no_markup", raw=None, parking=None) -> int:
        def reset(conn):
            for table in (ReviewItem, SegmentCode, SegmentMessage, StoredMessage):
                conn.execute(table.__table__.delete())
        self.read(reset)
        self.fake.reset()
        self.fake.content = '{"picture": 2}'
        scan.keep_message(self.mailbox, "m-r", raw or self.TWO, [], NOW)

        def hold(conn):
            review.add(conn, self.mailbox, "m-r", "mail.exampleparking.example", "2026-10-16", "match" if held else reason, NOW, held=held, parking=parking)
            if suggestions:
                review.set_suggestions(conn, self.mailbox, "m-r", suggestions, None)
        self.read(hold)
        return int(self.read(lambda conn: conn.execute(select(ReviewItem.id)).scalar()))

    def act(self, handler, q, body, item):
        _current.user = {"sub": "u-jane"}
        try:
            return handler(None, q, body, str(item))
        finally:
            _current.user = None

    def paths(self):
        held = [(self.SUGGESTION, [self.segment])]
        seg = str(self.segment)
        return {
            "match": (dict(held=held), lambda i: self.act(review_api.api_review_match, {}, {"entry": 1, "segment_id": self.segment}, i)),
            "attach then dismiss": ({}, lambda i: (self.act(review_api.api_review_attach, {}, dict(self.SUGGESTION), i),
                                                   self.act(review_api.api_review_dismiss, {"segment": [seg]}, None, i))),
            "dismiss with the booking": ({}, lambda i: self.act(review_api.api_review_dismiss, {"segment": [seg]}, None, i)),
            "assistant match": (dict(held=held), lambda i: self.act(assistant_api.api_assistant_review_match, {}, {"entry": 1, "segment_id": self.segment}, i)),
            "assistant create from a held booking": (dict(held=held), lambda i: self.act(assistant_api.api_assistant_review_create, {}, {"entry": 1}, i)),
            "assistant create from a suggestion": (dict(suggestions=[self.SUGGESTION]), lambda i: self.act(assistant_api.api_assistant_review_create, {}, {}, i)),
            "assistant create from one of several suggestions": (dict(suggestions=[self.SUGGESTION, self.HOTEL]),
                                                                  lambda i: self.act(assistant_api.api_assistant_review_create, {}, {"entry": 1}, i)),
        }

    def each(self):
        for name, (setup, run) in self.paths().items():
            with self.subTest(path=name):
                yield name, self.fresh(**setup), run

    def watch(self, seen: list):
        def look(n: int) -> None:
            seen.append(self.read(lambda conn: (
                conn.execute(select(func.count()).select_from(SegmentMessage).where(SegmentMessage.segment_id == self.segment)).scalar(),
                gate_codes.states(conn, [self.segment])[self.segment])))
        return look

    def test_every_review_path_picks_the_picture_after_it_commits(self):
        for _, item, run in self.each():
            seen: list = []
            self.fake.on_request = self.watch(seen)
            with no_leaks(self, CANARY_TEXT, database=self.path, sent_ok=True):
                run(item)
            self.assertEqual(seen, [(1, ("choose", "2026-10-16"))])
            self.assertEqual((self.state(), self.image()), (("ready", "2026-10-16"), {"type": "image/png", "data": OTHER_QR}))
            [(_, _, body)] = self.fake.requests
            self.assertEqual(body["messages"][1]["images"], [base64.b64encode(QR).decode(), base64.b64encode(OTHER_QR).decode()])
            self.assertNotIn(CANARY_TEXT, json.dumps(body["messages"]))

    def test_only_the_pictures_of_the_message_the_person_resolved_are_sent(self):
        item = self.fresh(held=[(self.SUGGESTION, [self.segment])])
        scan.keep_message(self.mailbox, "m-old", raw_of("Your parking reservation", {"c": png(310, 310, b"OLDER-ONE-1"), "d": png(320, 320, b"OLDER-TWO-2")},
                                                         day="Mon, 12 Oct 2026 09:00:00 +0100"), [self.segment], NOW - 5)
        self.fake.on_request = None
        self.act(review_api.api_review_match, {}, {"entry": 1, "segment_id": self.segment}, item)
        [(_, _, body)] = self.fake.requests
        self.assertEqual(len(body["messages"][1]["images"]), 2)
        self.assertNotIn(base64.b64encode(png(310, 310, b"OLDER-ONE-1")).decode(), body["messages"][1]["images"])
        self.assertEqual(self.image(), {"type": "image/png", "data": OTHER_QR})

    def test_a_model_that_fails_leaves_the_choice_open_and_the_review_action_still_succeeds(self):
        for content, status in (("{}", 500), ("I can only read text.", 200), ('{"picture": 3}', 200), ("", 200)):
            for name, item, run in self.each():
                self.fake.content, self.fake.status = content, status
                run(item)
                self.assertEqual((self.state(), self.image()), (("choose", "2026-10-16"), None), (name, content))
                self.assertEqual(len(self.fake.requests), 1)
                self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(SegmentMessage)).scalar()), 1)

    def test_a_pick_that_raises_is_reported_without_values_and_never_fails_the_action(self):
        for name, item, run in self.each():
            with mock.patch.object(ai, "pick_picture", side_effect=RuntimeError(CANARY_TEXT)), mock.patch.object(gatecode.monitoring, "report") as report:
                run(item)
            report.assert_called_once()
            self.assertEqual(report.call_args.kwargs, {"values": False})
            self.assertEqual(self.state(), ("choose", "2026-10-16"), name)

    def test_a_busy_database_after_the_commit_never_fails_the_action(self):
        for _, item, run in self.each():
            with mock.patch.object(ai, "pick_picture", side_effect=RuntimeError("busy")), mock.patch.object(gatecode.db, "is_busy", return_value=True):
                run(item)
            self.assertEqual(self.state(), ("choose", "2026-10-16"))

    def test_a_slow_model_is_cut_off_at_the_cap_so_the_reply_waits_no_longer_than_that(self):
        with mock.patch.object(ai, "pick_picture", wraps=ai.pick_picture) as picked:
            self.act(review_api.api_review_match, {}, {"entry": 1, "segment_id": self.segment}, self.fresh(held=[(self.SUGGESTION, [self.segment])]))
        self.assertEqual([c.args[2] for c in picked.call_args_list], [gatecode.REVIEW_CAP])
        item = self.fresh(held=[(self.SUGGESTION, [self.segment])])
        self.fake.on_request = lambda n: time.sleep(1.5)
        began = time.monotonic()
        with mock.patch.object(gatecode, "REVIEW_CAP", 0.2):
            self.act(review_api.api_review_match, {}, {"entry": 1, "segment_id": self.segment}, item)
        self.assertLess(time.monotonic() - began, 1.2)
        self.assertEqual((self.state(), self.image()), (("choose", "2026-10-16"), None))
        self.assertEqual(self.read(lambda conn: conn.execute(select(func.count()).select_from(ReviewItem)).scalar()), 0)
        time.sleep(1.5)

    def test_openrouter_and_off_send_nothing_whatever_the_review_path(self):
        for mode in ("openrouter", "off"):
            self.turn_on(mode, auto=False)
            with db.session() as conn:
                db.set_setting(conn, sk.AI_OPENROUTER_MODEL, "m/model")
                db.set_setting(conn, sk.AI_OPENROUTER_KEY, "sk-test-key-1234")
            for name, item, run in self.each():
                with no_leaks(self, *CANARIES, database=self.path):
                    run(item)
                self.assertEqual(self.fake.requests, [], (mode, name))
                self.assertEqual(self.state(), ("choose", "2026-10-16"))

    def test_two_parking_bookings_in_the_message_are_left_to_a_person(self):
        other = self.park({**PARKING, "confirmation": "PK30418"})
        both = [(self.SUGGESTION, [self.segment]), ({**self.SUGGESTION, "confirmation": "PK30418"}, [other])]
        for handler, body in ((review_api.api_review_match, {"entry": 1, "segment_id": self.segment}),
                              (assistant_api.api_assistant_review_match, {"entry": 1, "segment_id": self.segment})):
            item = self.fresh(held=both)
            self.act(handler, {}, body, item)
            self.assertEqual((self.fake.requests, self.state()), ([], ("choose", "2026-10-16")))
        item = self.fresh(suggestions=[self.SUGGESTION, {**self.SUGGESTION, "confirmation": "PK30418"}])
        self.act(assistant_api.api_assistant_review_create, {}, {"entry": 1}, item)
        self.assertEqual((self.fake.requests, self.state()), ([], ("choose", "2026-10-16")))

    def test_a_message_already_filed_for_a_second_parking_booking_is_left_to_a_person(self):
        other = self.park({**PARKING, "confirmation": "PK30418"})
        item = self.fresh(held=[(self.SUGGESTION, [self.segment])])
        self.read(lambda conn: stored_mail.link(conn, other, self.mailbox, "m-r"))
        self.act(review_api.api_review_match, {}, {"entry": 1, "segment_id": self.segment}, item)
        self.assertEqual((self.fake.requests, self.state()), ([], ("choose", "2026-10-16")))

    def test_a_stay_resolved_from_review_sends_no_picture(self):
        stay = self.park(STAY)
        item = self.fresh(held=[({**self.HOTEL}, [stay])])
        self.act(review_api.api_review_match, {}, {"entry": 1, "segment_id": stay}, item)
        self.assertEqual(self.fake.requests, [])

    def test_an_item_dismissed_with_no_booking_sends_nothing(self):
        item = self.fresh()
        self.act(review_api.api_review_dismiss, {}, None, item)
        self.assertEqual(self.fake.requests, [])

    def test_an_older_message_than_the_one_that_opened_the_choice_sends_nothing(self):
        for name, item, run in self.each():
            scan.keep_message(self.mailbox, "m-new", raw_of("Your parking reservation", {"x": png(410, 410, b"NEWER-X"), "y": png(420, 420, b"NEWER-Y")},
                                                             day="Mon, 19 Oct 2026 09:00:00 +0100"), [self.segment], NOW + 10)
            with no_leaks(self, *CANARIES, database=self.path):
                run(item)
            self.assertEqual((self.fake.requests, self.state(), self.image()), ([], ("choose", "2026-10-19"), None), name)

    def test_one_action_that_attaches_and_then_dismisses_makes_one_request(self):
        for content, status in (("{}", 500), ('{"picture": 2}', 200)):
            item = self.fresh()
            self.fake.content, self.fake.status = content, status
            self.act(review_api.api_review_attach, {}, dict(self.SUGGESTION), item)
            self.act(review_api.api_review_dismiss, {"segment": [str(self.segment)]}, None, item)
            self.assertEqual(len(self.fake.requests), 1, content)

    def test_repeating_an_attach_that_already_committed_succeeds_the_same_way_and_asks_nothing(self):
        item = self.fresh()
        first = self.act(review_api.api_review_attach, {}, dict(self.SUGGESTION), item)
        again = self.act(review_api.api_review_attach, {}, dict(self.SUGGESTION), item)
        self.assertEqual((first, again, self.fake.requests), ({"ok": True, "segment_id": self.segment}, {"ok": True, "segment_id": self.segment}, []))

    def test_two_attaches_of_one_item_to_different_bookings_send_nothing_when_each_is_finished(self):
        other = self.park({**PARKING, "confirmation": "PK30418"})
        item = self.fresh()
        self.act(review_api.api_review_attach, {}, dict(self.SUGGESTION), item)
        self.act(review_api.api_review_attach, {}, {**self.SUGGESTION, "confirmation": "PK30418"}, item)
        self.assertEqual(self.fake.requests, [])
        self.act(review_api.api_review_dismiss, {"segment": [str(self.segment)]}, None, item)
        self.assertEqual(self.fake.requests, [])
        self.assertEqual(self.state(other), ("choose", "2026-10-16"))

    def test_a_booking_linked_to_the_message_before_counts_toward_the_limit_of_one(self):
        other = self.park({**PARKING, "confirmation": "PK30418"})
        item = self.fresh()
        self.read(lambda conn: stored_mail.link(conn, other, self.mailbox, "m-r"))
        done = self.read(lambda conn: review.dismiss(conn, "u-jane", item, (self.jane, [self.segment])))
        self.assertEqual((done.segments, done.parking), ((self.segment,), 2))

    @unittest.skipUnless(db.using_postgres(), "Postgres only: SQLite serializes writers itself")
    def test_two_requests_for_the_same_item_are_resolved_one_after_the_other(self):
        other = self.park({**PARKING, "confirmation": "PK30418"})
        item = self.fresh()
        outcome: list = []

        def second():
            with db.session() as conn:
                outcome.append(review.dismiss(conn, "u-jane", item, (self.jane, [other])))

        with db.session() as conn:
            first = review.dismiss(conn, "u-jane", item, (self.jane, [self.segment]))
            thread = threading.Thread(target=second)
            thread.start()
            thread.join(1.0)
            self.assertTrue(thread.is_alive())
        thread.join(10)
        self.assertEqual((first.segments, outcome), ((self.segment,), [None]))
        self.assertEqual(self.read(lambda conn: stored_mail.message_ids(conn, [other])), {})

    def two(self, **more) -> dict:
        return raw_of("Your parking reservation", {"a": QR, "b": OTHER_QR}, text=f"Reservation PK30417. {CANARY_TEXT}", **more)

    def test_only_the_message_that_opened_the_choice_is_sent_however_the_dates_compare(self):
        undated = self.two(day="")
        cases = (("equal day", "Fri, 16 Oct 2026 09:00:00 +0100", self.two(), 0),
                 ("older day", "Mon, 19 Oct 2026 09:00:00 +0100", self.two(), 0),
                 ("no day on the item", "Fri, 16 Oct 2026 09:00:00 +0100", undated, 0),
                 ("no day on either", "", undated, 0),
                 ("a newer day reopens the choice", "Wed, 14 Oct 2026 09:00:00 +0100", self.two(), 1))
        for label, opener_day, raw, sent in cases:
            for name, setup, run in ((n, s, r) for n, (s, r) in self.paths().items()):
                with self.subTest(case=label, path=name):
                    item = self.fresh(raw=raw, **setup)
                    scan.keep_message(self.mailbox, "m-open", self.two(day=opener_day), [self.segment], NOW - 1)
                    self.fake.reset()
                    self.fake.content = '{"picture": 2}'
                    with no_leaks(self, *CANARIES, database=self.path, sent_ok=bool(sent)):
                        run(item)
                    self.assertEqual(len(self.fake.requests), sent)

    def test_the_message_that_opened_the_choice_gets_its_pick_by_a_review_action(self):
        for name, setup, run in ((n, s, r) for n, (s, r) in self.paths().items()):
            with self.subTest(path=name):
                item = self.fresh(**setup)
                run(item)
                self.assertEqual(len(self.fake.requests), 1)

    def test_a_choice_opened_before_the_opener_was_kept_sends_nothing_for_any_message(self):
        item = self.fresh(held=[(self.SUGGESTION, [self.segment])])
        scan.keep_message(self.mailbox, "m-open", self.two(), [self.segment], NOW - 1)
        self.read(lambda conn: conn.execute(SegmentCode.__table__.update().values(opened_by=None)))
        self.act(review_api.api_review_match, {}, {"entry": 1, "segment_id": self.segment}, item)
        self.assertEqual((self.fake.requests, self.state()), ([], ("choose", "2026-10-16")))

    def test_a_follow_up_with_the_same_day_does_not_reopen_the_choice_and_a_newer_one_does(self):
        self.turn_on(auto=False)
        scan.keep_message(self.mailbox, "m-open", self.two(), [self.segment], NOW)
        self.fake.reset()
        scan.keep_code(self.mailbox, self.segment, self.two(), NOW + 1)
        self.assertEqual(self.fake.requests, [])
        scan._keep_quietly(self.mailbox, "m-same", self.two(), [self.segment], NOW + 2)
        self.assertEqual(self.fake.requests, [])
        self.fake.content = '{"picture": 1}'
        scan.keep_code(self.mailbox, self.segment, self.two(day="Mon, 19 Oct 2026 09:00:00 +0100"), NOW + 3)
        self.assertEqual(len(self.fake.requests), 1)

    def test_a_message_dated_between_the_first_opener_and_the_one_that_reopened_sends_nothing(self):
        for name, setup, run in ((n, s, r) for n, (s, r) in self.paths().items()):
            with self.subTest(path=name):
                item = self.fresh(raw=self.two(day="Sat, 17 Oct 2026 09:00:00 +0100"), **setup)
                scan.keep_message(self.mailbox, "m-first", self.two(day="Fri, 16 Oct 2026 09:00:00 +0100"), [self.segment], NOW - 2)
                scan.keep_message(self.mailbox, "m-last", self.two(day="Mon, 19 Oct 2026 09:00:00 +0100"), [self.segment], NOW - 1)
                self.fake.reset()
                self.fake.content = '{"picture": 1}'
                with no_leaks(self, *CANARIES, database=self.path):
                    run(item)
                self.assertEqual((self.fake.requests, self.state(), self.image()), ([], ("choose", "2026-10-19"), None))
                opener = self.read(lambda conn: conn.execute(select(SegmentCode.opened_by)).scalar())
                self.assertEqual(opener, self.read(lambda conn: gate_codes.stored_id(conn, self.mailbox, "m-last")))

    def test_the_scan_paths_leave_a_message_dated_between_them_unsent(self):
        scan.keep_message(self.mailbox, "m-first", self.two(day="Fri, 16 Oct 2026 09:00:00 +0100"), [self.segment], NOW)
        scan.keep_message(self.mailbox, "m-last", self.two(day="Mon, 19 Oct 2026 09:00:00 +0100"), [self.segment], NOW + 1)
        self.fake.reset()
        scan._keep_quietly(self.mailbox, "m-mid", self.two(day="Sat, 17 Oct 2026 09:00:00 +0100"), [self.segment], NOW + 2)
        scan.keep_code(self.mailbox, self.segment, self.two(day="Sat, 17 Oct 2026 09:00:00 +0100"), NOW + 3)
        self.assertEqual((self.fake.requests, self.state()), ([], ("choose", "2026-10-19")))

    def test_a_message_that_held_a_second_parking_booking_sends_nothing_whatever_was_dropped_or_could_not_be_read(self):
        for name, setup, run in ((n, s, r) for n, (s, r) in self.paths().items()):
            with self.subTest(path=name):
                item = self.fresh(parking=2, **setup)
                run(item)
                self.assertEqual((self.fake.requests, self.state()), ([], ("choose", "2026-10-16")), name)

    def test_dropping_one_of_two_parking_bookings_and_resolving_the_other_sends_nothing(self):
        other = self.park({**PARKING, "confirmation": "PK30418"})
        both = [(self.SUGGESTION, [self.segment]), ({**self.SUGGESTION, "confirmation": "PK30418"}, [other])]
        for handler in (review_api.api_review_match, assistant_api.api_assistant_review_match):
            item = self.fresh(held=both, parking=2)
            self.act(review_api.api_review_dismiss, {"entry": ["2"]}, None, item)
            self.act(handler, {}, {"entry": 1, "segment_id": self.segment}, item)
            self.assertEqual((self.fake.requests, self.state()), ([], ("choose", "2026-10-16")))

    def test_a_single_parking_message_still_picks(self):
        item = self.fresh(held=[(self.SUGGESTION, [self.segment])], parking=1)
        self.act(review_api.api_review_match, {}, {"entry": 1, "segment_id": self.segment}, item)
        self.assertEqual((len(self.fake.requests), self.image()), (1, {"type": "image/png", "data": OTHER_QR}))

    def test_the_count_of_parking_bookings_the_ai_read_is_kept_and_never_lowered(self):
        item = self.fresh()
        reading = json.dumps({"bookings": [{"kind": "parking", "origin": f"Lot {n}", "start_local": "2026-12-01T05:15", "end_local": "2026-12-04T03:00"} for n in "AB"]})
        self.fake.content = reading
        scan._ask(self.mailbox, "m-r", "Reservation PK30417", NOW)
        count = lambda: self.read(lambda conn: conn.execute(select(ReviewItem.parking)).scalar())
        self.assertEqual(count(), 2)
        self.read(lambda conn: review.raise_parking(conn, self.mailbox, "m-r", 1))
        self.assertEqual(count(), 2)
        self.read(lambda conn: review.raise_parking(conn, self.mailbox, "m-r", 3))
        self.assertEqual(count(), 3)
