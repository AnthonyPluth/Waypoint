import json
from unittest import mock

from sqlalchemy import insert, select

from tests.shared import DbCase
from waypoint.storage import backup, db, schema, secretbox, stored_mail
from waypoint.storage.models import Mailbox, ReviewItem, Segment, StoredMessage, Trip

CONTENT: stored_mail.Content = {"subject": "Your itinerary: CANARY-KEPT-SUBJECT-5T2K", "sender_domain": "example-air.example", "received": "2026-10-17",
                                "text": "Hello CANARY-KEPT-BODY-8W3M.", "html": "<p>Hello CANARY-KEPT-BODY-8W3M.</p>", "truncated": False,
                                "full": True, "layout": "<p>Hello CANARY-KEPT-BODY-8W3M.</p>", "images": []}


class KeptMessageTests(DbCase):
    def setUp(self):
        super().setUp()
        db.init(self.path)
        with db.session() as conn:
            self.box = int(conn.execute(insert(Mailbox).values(owner_sub="u-jane", address="jane@gmail.example", token=secretbox.encrypt("t"),
                                                               status="connected", created=1.0)).lastrowid)
            conn.execute(insert(Trip).values(id=1, name="T", auto=True))
            for i in (1, 2):
                conn.execute(insert(Segment).values(id=i, trip_id=1, kind="flight", status="confirmed", start_local="2026-11-20T19:00", start_zone="UTC",
                                                    end_local="2026-11-21T07:10", end_zone="UTC", source="email"))

    def test_a_message_is_kept_as_one_encrypted_value_and_comes_back_as_it_was(self):
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", CONTENT, 5.0)
            raw = conn.execute(select(StoredMessage.content)).scalar()
            self.assertTrue(secretbox.is_encrypted(raw))
            self.assertNotIn("CANARY-KEPT", raw)
            self.assertEqual(stored_mail.get(conn, self.box, "m1"), CONTENT)
            self.assertIsNone(stored_mail.get(conn, self.box, "other"))

    def test_keeping_a_message_again_replaces_it(self):
        with db.session() as conn:
            first = stored_mail.put(conn, self.box, "m1", CONTENT, 5.0)
            again = stored_mail.put(conn, self.box, "m1", {**CONTENT, "text": "Changed"}, 9.0)
            self.assertEqual(first, again)
            found = stored_mail.get(conn, self.box, "m1")
            assert found
            self.assertEqual(found["text"], "Changed")

    def test_a_message_that_cannot_be_unlocked_or_isnt_what_was_kept_reads_as_none(self):
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", CONTENT, 5.0)
            conn.execute(StoredMessage.__table__.update().values(content=secretbox.PREFIX + "bad"))
            self.assertIsNone(stored_mail.get(conn, self.box, "m1"))
            conn.execute(StoredMessage.__table__.update().values(content=secretbox.encrypt(json.dumps([1, 2]))))
            self.assertIsNone(stored_mail.get(conn, self.box, "m1"))
            conn.execute(StoredMessage.__table__.update().values(content=secretbox.encrypt(json.dumps({"subject": 5, "text": None, "html": 7}))))
            self.assertEqual(stored_mail.get(conn, self.box, "m1"), {"subject": None, "sender_domain": None, "received": None, "text": "",
                                                                      "html": None, "truncated": False, "full": False, "layout": None, "images": []})

    def test_subjects_come_without_opening_the_messages_and_are_encrypted_on_their_own(self):
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", CONTENT, 5.0)
            stored_mail.put(conn, self.box, "m2", {**CONTENT, "subject": None}, 5.0)
            raw = conn.execute(select(StoredMessage.subject).where(StoredMessage.message_id == "m1")).scalar()
            self.assertTrue(secretbox.is_encrypted(raw))
            self.assertNotIn("CANARY-KEPT", raw)
            self.assertEqual(stored_mail.subjects(conn, [self.box]), {(self.box, "m1"): CONTENT["subject"], (self.box, "m2"): None})
            self.assertEqual(stored_mail.subjects(conn, [self.box + 99]), {})
            self.assertEqual(stored_mail.subjects(conn, []), {})
            with mock.patch.object(stored_mail, "get", side_effect=AssertionError("opened a message")):
                stored_mail.subjects(conn, [self.box])
            conn.execute(StoredMessage.__table__.update().values(subject=secretbox.PREFIX + "bad"))
            self.assertEqual(stored_mail.subjects(conn, [self.box])[(self.box, "m1")], None)

    def test_a_booking_keeps_the_messages_it_was_made_from_newest_first(self):
        with db.session() as conn:
            stored_mail.put(conn, self.box, "old", {**CONTENT, "subject": "First"}, 1.0)
            stored_mail.put(conn, self.box, "new", {**CONTENT, "subject": "Update"}, 2.0)
            self.assertFalse(stored_mail.link(conn, 1, self.box, "none-kept"))
            self.assertTrue(stored_mail.link(conn, 1, self.box, "old"))
            self.assertTrue(stored_mail.link(conn, 1, self.box, "new"))
            stored_mail.link(conn, 1, self.box, "new")
            self.assertEqual([c["subject"] for c in stored_mail.for_segment(conn, 1)], ["Update", "First"])
            self.assertEqual(stored_mail.for_segment(conn, 2), [])
            self.assertEqual(stored_mail.with_messages(conn, [1, 2]), {1})
            self.assertEqual(stored_mail.with_messages(conn, []), set())

    def test_images_are_kept_with_the_message_and_only_the_four_types_come_back(self):
        pixels = {"type": "image/png", "data": "iVBORw0KGgo="}
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", {**CONTENT, "images": [pixels]}, 5.0)
            raw = conn.execute(select(StoredMessage.content)).scalar()
            self.assertNotIn("iVBORw0KGgo", raw)
            self.assertEqual(stored_mail.get(conn, self.box, "m1")["images"], [pixels])
            hostile = [pixels, {"type": "image/svg+xml", "data": "PHN2Zz4="}, {"type": "text/html", "data": "PGI+"}, {"type": "image/png"}, "x", None,
                       {"type": "image/gif", "data": 5}, {"type": "image/webp", "data": "UklGRg=="}]
            conn.execute(StoredMessage.__table__.update().values(content=secretbox.encrypt(json.dumps({**CONTENT, "images": hostile}))))
            self.assertEqual([i["type"] for i in stored_mail.get(conn, self.box, "m1")["images"]], ["image/png", "image/webp"])
            conn.execute(StoredMessage.__table__.update().values(content=secretbox.encrypt(json.dumps({**CONTENT, "images": "nope", "layout": 5, "full": "yes"}))))
            found = stored_mail.get(conn, self.box, "m1")
            self.assertEqual((found["images"], found["layout"], found["full"]), ([], None, False))

    def test_a_booking_reads_the_images_of_its_own_messages_alone(self):
        pixels = {"type": "image/png", "data": "iVBORw0KGgo="}
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", {**CONTENT, "images": [pixels]}, 5.0)
            stored_mail.link(conn, 1, self.box, "m1")
            [email] = stored_mail.for_segment(conn, 1)
            self.assertEqual(stored_mail.images_for_segment(conn, 1, email["id"]), [pixels])
            self.assertIsNone(stored_mail.images_for_segment(conn, 2, email["id"]))
            self.assertIsNone(stored_mail.images_for_segment(conn, 1, email["id"] + 1))
            conn.execute(StoredMessage.__table__.update().values(content=secretbox.PREFIX + "bad"))
            self.assertIsNone(stored_mail.images_for_segment(conn, 1, email["id"]))

    def test_a_message_goes_when_neither_an_item_nor_a_booking_holds_it(self):
        with db.session() as conn:
            for mid in ("item", "booking", "both", "nobody"):
                stored_mail.put(conn, self.box, mid, CONTENT, 1.0)
            for mid in ("item", "both"):
                conn.execute(insert(ReviewItem).values(mailbox_id=self.box, message_id=mid, sender_domain="x.example", reason="no_markup", created=1.0))
            for mid in ("booking", "both"):
                stored_mail.link(conn, 1, self.box, mid)
            self.assertEqual(stored_mail.prune(conn), 1)
            left = {m for (m,) in conn.execute(select(StoredMessage.message_id))}
            self.assertEqual(left, {"item", "booking", "both"})
            conn.execute(ReviewItem.__table__.delete())
            self.assertEqual(stored_mail.prune(conn), 1)
            conn.execute(Segment.__table__.delete().where(Segment.id == 1))
            self.assertEqual(stored_mail.prune(conn), 2)
            self.assertEqual(conn.execute(select(StoredMessage.id)).fetchall(), [])

    def test_a_mailbox_that_goes_takes_its_messages_and_the_links(self):
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", CONTENT, 1.0)
            stored_mail.link(conn, 1, self.box, "m1")
            conn.execute(Mailbox.__table__.delete().where(Mailbox.id == self.box))
            self.assertEqual(conn.execute(select(StoredMessage.id)).fetchall(), [])
            self.assertEqual(conn.execute(select(schema.segment_messages.c.segment_id)).fetchall(), [])
            self.assertEqual(conn.execute(select(Segment.id)).fetchall(), [(1,), (2,)])

    def test_a_backup_carries_kept_messages_encrypted_and_never_in_the_clear(self):
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", CONTENT, 1.0)
            stored_mail.link(conn, 1, self.box, "m1")
            conn.commit()
            exported = backup.export(conn)
            columns = exported["tables"]["stored_messages"]["columns"]
            [row] = exported["tables"]["stored_messages"]["rows"]
            self.assertTrue(secretbox.is_encrypted(row[columns.index("content")]))
            self.assertTrue(secretbox.is_encrypted(row[columns.index("subject")]))
            self.assertEqual(len(exported["tables"]["segment_messages"]["rows"]), 1)
            self.assertNotIn(b"CANARY-KEPT", backup.dump(conn))
            self.assertNotIn(b"CANARY-KEPT", __import__("gzip").decompress(backup.dump(conn)))

    def test_a_message_kept_before_encryption_is_encrypted_at_start(self):
        with db.session() as conn:
            stored_mail.put(conn, self.box, "m1", CONTENT, 1.0)
            conn.execute(StoredMessage.__table__.update().values(content=json.dumps(dict(CONTENT))))
            self.assertGreaterEqual(secretbox.encrypt_stored(conn), 1)
            self.assertTrue(secretbox.is_encrypted(conn.execute(select(StoredMessage.content)).scalar()))
            self.assertEqual(stored_mail.get(conn, self.box, "m1"), CONTENT)
