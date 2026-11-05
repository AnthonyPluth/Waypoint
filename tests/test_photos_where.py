import unittest
from datetime import timedelta

from sqlalchemy import update

from waypoint.domain import photos, trips, visibility
from waypoint.domain.photomatch import GAP, PAD
from waypoint.storage.models import Segment, SegmentRecipient
from tests.test_photomatch import DENVER, PUEBLO, SALT_LAKE, at, point
from tests.test_trips import CRUISE, HOTEL, OUT, PORTS, Household

STAY = point(1, "hotel", "2026-06-01T15:00", "2026-06-04T11:00", DENVER)
FLIGHT = point(2, "flight", "2026-06-06T08:00", "2026-06-06T10:00", DENVER, SALT_LAKE)
RENTAL = point(3, "car", "2026-06-06T11:00", "2026-06-09T11:00")
TRAIN = point(4, "train", "2026-06-20T09:00", "2026-06-20T18:00", PUEBLO)
CHECKOUT = at("2026-06-04T11:00")
LATER = {**OUT, "start_local": "2026-09-10T19:00", "end_local": "2026-09-11T07:10"}


class WhereWas(unittest.TestCase):
    CASES = [
        ("during a stay", [STAY], at("2026-06-02T12:00"), (*DENVER, 1)),
        ("after checkout within GAP", [STAY], CHECKOUT + GAP - timedelta(minutes=1), (*DENVER, 1)),
        ("after checkout at GAP", [STAY], CHECKOUT + GAP, (*DENVER, 1)),
        ("after checkout beyond GAP", [STAY], CHECKOUT + GAP + timedelta(minutes=1), None),
        ("a flight under way", [STAY, FLIGHT], at("2026-06-06T09:00"), None),
        ("after a flight lands, its destination", [FLIGHT], at("2026-06-07T09:00"), (*SALT_LAKE, 2)),
        ("an unplaced booking under way falls back to the flight before", [FLIGHT, RENTAL], at("2026-06-07T09:00"), (*SALT_LAKE, 2)),
        ("before a flight, its origin", [FLIGHT], at("2026-06-05T09:00"), (*DENVER, 2)),
        ("long before the next booking", [FLIGHT], at("2026-06-04T07:59"), None),
        ("a train under way gives its city", [TRAIN], at("2026-06-20T12:00"), (*PUEBLO, 4)),
        ("nothing at all", [], at("2026-06-20T12:00"), None),
    ]

    def test_each_case(self):
        for name, points, instant, expected in self.CASES:
            with self.subTest(name):
                self.assertEqual(photos.where_was(points, instant), expected)

    def test_a_port_call_beats_the_whole_cruise(self):
        cruise = point(5, "cruise", "2026-03-01T16:30", "2026-03-08T07:00", (25.77, -80.19), zone="America/New_York")
        call = point(5, "cruise", "2026-03-02T08:00", "2026-03-02T17:00", (25.06, -77.34), zone="America/Nassau")
        self.assertEqual(photos.where_was([cruise, call], at("2026-03-02T12:00", "America/Nassau")), (25.06, -77.34, 5))
        self.assertEqual(photos.where_was([cruise, call], at("2026-03-03T12:00", "America/Nassau")), (25.77, -80.19, 5))


class CandidateWindows(Household):
    def setUp(self):
        super().setUp()
        self.jid, self.sid = self.jane.person_id, self.sam.person_id

    def windows(self, person_id):
        return {w.trip_id: w for w in photos.candidate_windows(self.c, person_id)}

    def test_a_flight_is_placed_at_its_airports_and_a_stay_at_its_stored_point(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid))
        stay = self.add(self.jane, HOTEL, flight["trip_id"], self.on(self.jid))
        self.c.execute(update(Segment).where(Segment.id == stay["id"]).values(latitude=51.5, longitude=-0.12))
        self.c.orm.expire_all()
        got = self.windows(self.jid)[flight["trip_id"]]
        placed = {p.segment_id: (p.origin, p.destination) for p in got.points}
        self.assertEqual(placed[stay["id"]], ((51.5, -0.12), (51.5, -0.12)))
        (jfk, lhr) = placed[flight["id"]]
        self.assertAlmostEqual(jfk[0], 40.64, delta=0.1)
        self.assertAlmostEqual(lhr[1], -0.46, delta=0.1)
        self.assertEqual(got.start, trips.instant(OUT["start_local"], "America/New_York") - PAD)
        self.assertEqual(got.end, trips.instant(HOTEL["end_local"], "Europe/London") + PAD)

    def test_a_train_is_placed_only_at_its_destination(self):
        train = self.add(self.jane, {"kind": "train", "origin": "Example Central", "destination": "Example Junction", "provider": "Example Rail",
                                     "start_local": "2026-06-20T09:00", "end_local": "2026-06-20T18:00",
                                     "start_zone": "America/Denver", "end_zone": "America/Denver"}, None, self.on(self.jid))
        self.c.execute(update(Segment).where(Segment.id == train["id"]).values(latitude=38.25, longitude=-104.6))
        self.c.orm.expire_all()
        got = self.windows(self.jid)[train["trip_id"]]
        (only,) = got.points
        self.assertEqual((only.origin, only.destination), (None, (38.25, -104.6)))
        self.assertIsNone(photos.where_was(got.points, trips.instant("2026-06-20T07:00", "America/Denver")))
        self.assertEqual(photos.where_was(got.points, trips.instant("2026-06-20T20:00", "America/Denver")), (38.25, -104.6, train["id"]))

    def test_a_cancelled_booking_doesnt_count(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid))
        stay = self.add(self.jane, HOTEL, flight["trip_id"], self.on(self.jid))
        trips.edit_segment(self.c, self.jane, stay["id"], {"status": "cancelled"})
        got = self.windows(self.jid)[flight["trip_id"]]
        self.assertEqual([p.segment_id for p in got.points], [flight["id"]])

    def test_a_cruise_is_placed_at_its_ports(self):
        cruise = self.add(self.jane, {**CRUISE, "itinerary": [*PORTS, {"name": "Port Example", "zone": "America/Cancun",
                                                                      "arrive_local": "2026-03-06T08:00", "depart_local": None}]},
                          None, self.on(self.jid))
        got = self.windows(self.jid)[cruise["trip_id"]]
        self.assertEqual(len(got.points), 3)
        nassau = got.points[1]
        self.assertEqual((nassau.start, nassau.end), (trips.instant("2026-03-02T08:00", "America/Nassau"), trips.instant("2026-03-02T17:00", "America/Nassau")))
        self.assertIsNotNone(got.points[0].origin)
        self.assertEqual(photos.where_was(got.points, trips.instant("2026-03-02T12:00", "America/Nassau"))[:2], nassau.origin)

    def test_a_cruise_with_no_stored_point_takes_its_first_port(self):
        cruise = self.add(self.jane, {**CRUISE, "origin": "Port Example", "destination": "Port Example", "itinerary": PORTS}, None, self.on(self.jid))
        self.c.execute(update(Segment).where(Segment.id == cruise["id"]).values(latitude=None, longitude=None))
        self.c.orm.expire_all()
        got = self.windows(self.jid)[cruise["trip_id"]]
        self.assertEqual(got.points[0].origin, got.points[1].origin)

    def test_only_the_trips_the_person_is_on_are_candidates(self):
        own = self.add(self.jane, OUT, None, self.on(self.jid))
        booked_for_mia = self.add(self.jane, LATER, None, self.on(self.mia))
        self.c.orm.add(SegmentRecipient(segment_id=booked_for_mia["id"], person_id=self.sid))
        self.c.orm.flush()
        self.assertNotEqual(own["trip_id"], booked_for_mia["trip_id"])
        self.assertIsNotNone(visibility.visible_trip(self.c, self.sam, booked_for_mia["trip_id"]))
        self.assertEqual(set(self.windows(self.jid)), {own["trip_id"]})
        self.assertEqual(set(self.windows(self.mia)), {booked_for_mia["trip_id"]})
        self.assertEqual(self.windows(self.sid), {})
        self.assertEqual(self.windows(self.joan), {})

    def test_a_trip_whose_every_booking_is_cancelled_has_no_window(self):
        flight = self.add(self.jane, OUT, None, self.on(self.jid))
        trips.edit_segment(self.c, self.jane, flight["id"], {"status": "cancelled"})
        self.assertEqual(self.windows(self.jid), {})
