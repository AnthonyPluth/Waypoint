import unittest

from sqlalchemy import insert, select

from tests import test_mail_scan as base
from tests.privacy import no_leaks
from tests.shared import DbCase
from waypoint.domain.mail import glance, review
from waypoint.storage.models import Mailbox

NOW = 1_790_000_000.0
DAY = 86400.0
SUBJECT, SENDER, BODY = "CANARY-SUBJECT-GLANCE-4K7Q", "CANARY-SENDER-GLANCE-8M2X", "CANARY-BODY-GLANCE-5T9W"


class GapLabelTests(unittest.TestCase):
    def test_what_a_reader_lacks_becomes_one_of_a_few_fixed_labels(self):
        for lack, label in (("departure time", "no start time"), ("check-in time", "no start time"), ("pick-up time", "no start time"),
                            ("arrival time", "no end time"), ("check-out time", "no end time"), ("drop-off time", "no end time"),
                            ("origin airport", "no place"), ("hotel name", "no place"), ("arrival station", "no place"),
                            ("unknown airport", "no place"), ("place's time zone unknown", "no place"),
                            ("dates without times", "dates without times"),
                            ("time isn't a date and time", "time can’t be read"), ("time offset doesn't match its place", "time can’t be read"),
                            ("details", "something else"), ("generic reader: whatever the reader said", "something else"), ("", "something else")):
            self.assertEqual(glance.gap_label(lack), label, lack)
            self.assertIn(label, glance.GAP_LABELS)

    def test_the_commonest_label_wins_and_the_first_seen_breaks_a_tie(self):
        self.assertEqual(glance.gap_of(["arrival time", "departure time", "arrival time"]), "no end time")
        self.assertEqual(glance.gap_of(["destination airport", "departure time"]), "no place")
        self.assertEqual(glance.gap_of([]), "something else")


class GlanceTests(DbCase):
    def setUp(self):
        super().setUp()
        self.ana = self.box("u-ana", "ana@gmail.example", share=False)
        self.ben = self.box("u-ben", "ben@gmail.example", share=True)

    def box(self, owner, address, share):
        self.c.execute(insert(Mailbox).values(owner_sub=owner, address=address, token="t", status="connected", created=1.0, share_review=share))
        return int(self.c.execute(select(Mailbox.id).where(Mailbox.address == address)).scalar())

    def add(self, box, name, domain, reason, at=NOW, gap=None):
        review.add(self.c, box, name, domain, "2026-10-01", reason, at, None, gap)

    def glance(self, owner="u-ana", box=None, now=NOW):
        return glance.glance(self.c, owner, box or self.ana, now)

    def test_nothing_waiting_is_all_zero_and_empty(self):
        self.assertEqual(self.glance(), {"waiting": 0, "days": 30, "reasons": [], "gaps": [], "domains": [], "scans": []})

    def test_counts_by_reason_include_the_last_30_days_separately(self):
        self.add(self.ana, "a", "x.example", "no_markup")
        self.add(self.ana, "b", "x.example", "no_markup", NOW - 29 * DAY)
        self.add(self.ana, "c", "y.example", "no_markup", NOW - 31 * DAY)
        self.add(self.ana, "d", "y.example", "broken")
        self.add(self.ana, "e", "z.example", "generic", NOW - 40 * DAY)
        self.add(self.ana, "f", "z.example", "match")
        found = self.glance()
        self.assertEqual(found["waiting"], 6)
        self.assertEqual(found["reasons"], [
            {"reason": "no_markup", "waiting": 3, "recent": 2}, {"reason": "broken", "waiting": 1, "recent": 1},
            {"reason": "match", "waiting": 1, "recent": 1}, {"reason": "generic", "waiting": 1, "recent": 0}])

    def test_domains_are_ordered_by_count_then_name_and_capped_at_ten_with_their_commonest_reason(self):
        for n in range(12):
            self.add(self.ana, f"d{n}", f"site{n:02}.example", "no_markup")
        for n in range(3):
            self.add(self.ana, f"big{n}", "big.example", "incomplete" if n else "broken")
        self.add(self.ana, "big-x", "big.example", "broken")
        self.add(self.ana, "big-y", "big.example", "broken")
        self.add(self.ana, "tie1", "tie.example", "match")
        self.add(self.ana, "tie2", "tie.example", "generic")
        self.add(self.ana, "none", "", "no_markup")
        found = self.glance()["domains"]
        self.assertEqual(len(found), 10)
        self.assertEqual([(d["domain"], d["count"], d["reason"]) for d in found[:4]],
                         [("big.example", 5, "broken"), ("tie.example", 2, "match"), ("", 1, "no_markup"), ("site00.example", 1, "no_markup")])
        self.assertEqual([d["domain"] for d in found[4:]], [f"site{n:02}.example" for n in range(1, 7)])
        self.assertIsNone(found[2]["item_id"])
        self.assertIsInstance(found[0]["item_id"], int)

    def test_a_domain_row_offers_its_newest_item_and_says_when_it_is_a_travel_company_waypoint_knows(self):
        self.add(self.ana, "old", "seaside-stays.example", "no_markup")
        self.add(self.ana, "new", "seaside-stays.example", "no_markup")
        self.add(self.ana, "air", "mail.united.com", "no_markup")
        by = {d["domain"]: d for d in self.glance()["domains"]}
        newest = max(i["id"] for i in review.listing(self.c, "u-ana") if i["sender_domain"] == "seaside-stays.example")
        self.assertEqual((by["seaside-stays.example"]["item_id"], by["seaside-stays.example"]["known_sender"]), (newest, False))
        self.assertTrue(by["mail.united.com"]["known_sender"])

    def test_gaps_count_the_fixed_labels_of_incomplete_items_only(self):
        self.add(self.ana, "a", "x.example", "incomplete", gap="no place")
        self.add(self.ana, "b", "x.example", "incomplete", gap="no place")
        self.add(self.ana, "c", "x.example", "incomplete", gap="no start time")
        self.add(self.ana, "d", "x.example", "incomplete", gap="no end time")
        self.add(self.ana, "e", "x.example", "incomplete")
        self.add(self.ana, "f", "x.example", "incomplete", gap="CANARY free text that is not a label")
        self.add(self.ana, "g", "x.example", "no_markup", gap="no place")
        self.assertEqual(self.glance()["gaps"], [{"label": "no place", "count": 2}, {"label": "no start time", "count": 1},
                                                  {"label": "no end time", "count": 1}])

    def test_scans_are_the_last_ten_within_30_days_newest_first_with_what_each_added(self):
        for scan_no in range(12):
            for n in range(scan_no % 3 + 1):
                self.add(self.ana, f"s{scan_no}-{n}", "x.example", "no_markup", NOW - scan_no * DAY)
        self.add(self.ana, "old", "x.example", "no_markup", NOW - 31 * DAY)
        found = self.glance()["scans"]
        self.assertEqual([s["added"] for s in found], [1, 2, 3, 1, 2, 3, 1, 2, 3, 1])
        self.assertEqual(found[0]["at"], "2026-09-21T14:13:20+00:00")
        self.assertEqual(found[1]["at"], "2026-09-20T14:13:20+00:00")

    def test_it_counts_only_the_viewers_own_mailbox_and_never_a_shared_one_or_a_stranger_s(self):
        self.add(self.ana, "a", "ana-only.example", "no_markup")
        self.add(self.ben, "b", "ben-only.example", "broken")
        self.assertEqual([d["domain"] for d in self.glance("u-ana")["domains"]], ["ana-only.example"])
        self.assertEqual(self.glance("u-ana")["waiting"], 1)
        self.assertEqual([d["domain"] for d in self.glance("u-ben", self.ben)["domains"]], ["ben-only.example"])
        self.assertIsNone(self.glance("u-ana", self.ben))
        self.assertIsNone(self.glance("u-ben", self.ana))
        self.assertIsNone(self.glance("u-nobody"))
        self.assertIsNone(self.glance(box=9999))

    def test_nothing_from_a_subject_sender_or_body_reaches_the_counts(self):
        with no_leaks(self, SUBJECT, SENDER, BODY, database=self.path):
            self.add(self.ana, SUBJECT.lower(), "seaside-stays.example", "no_markup")
            found = self.glance()
        self.assertEqual(found["waiting"], 1)
        self.assertNotIn("CANARY", repr(found))


class GapRecordedByAScanTests(base.ScanCase):
    def test_an_item_with_a_reader_that_found_part_of_a_booking_records_its_commonest_missing_piece(self):
        self.put("incomplete", "no_markup")
        with no_leaks(self, *base.CANARIES, database=self.path):
            self.scan()
        gaps = self.read(lambda conn: dict(conn.execute(select(base.ReviewItem.message_id, base.ReviewItem.gap)).fetchall()))
        self.assertEqual(gaps, {"msg-incomplete": "no place", "msg-no_markup": None})
        found = self.read(lambda conn: glance.glance(conn, "u-jane", self.mailbox, base.NOW))
        self.assertEqual(found["gaps"], [{"label": "no place", "count": 1}])
        self.assertEqual(found["scans"], [{"at": "2026-09-21T14:13:20+00:00", "added": 2}])
        self.assertEqual({r["reason"]: r["waiting"] for r in found["reasons"]}, {"incomplete": 1, "no_markup": 1})


if __name__ == "__main__":
    unittest.main()
