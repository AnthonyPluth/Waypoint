import unittest
from datetime import UTC, datetime, timedelta

from waypoint.domain import photomatch, trips
from waypoint.domain.photomatch import GAP, PAD, HomeIn, Match, PhotoIn, SegmentPoint, TripWindow
from waypoint.storage.models import Trip

DENVER = (39.7392, -104.9903)
BOULDER = (40.0150, -105.2705)
PUEBLO = (38.2544, -104.6091)
SALT_LAKE = (40.7608, -111.8910)
SANTA_FE = (35.6870, -105.9378)
TAOS = (36.4072, -105.5734)
LAS_VEGAS_NM = (35.5942, -105.2228)
WALSENBURG = (37.6247, -104.7803)
MIDWAY = (36.05, -105.75)
ZONE = "America/Denver"


def at(local, zone=ZONE):
    return trips.instant(local, zone)


def point(segment_id, kind, start, end, where=None, to=None, zone=ZONE, timed=True):
    return SegmentPoint(segment_id, kind, at(start, zone), at(end, zone), *(where or (None, None)), *(to or (None, None)), timed=timed)


def trip(trip_id, start_date=None, end_date=None):
    return Trip(id=trip_id, name="Trip", start_date=start_date, end_date=end_date)


def built(trip_id, *points, start_date=None, end_date=None):
    found = photomatch.window(trip(trip_id, start_date, end_date), list(points))
    assert found is not None
    return found


def photo(local, where=None, zone=ZONE):
    lat, lon = where or (None, None)
    return PhotoIn(at(local, zone).astimezone(UTC), lat, lon, 7)


ROAD_TRIP = built(1, point(10, "hotel", "2026-06-01T15:00", "2026-06-29T11:00", DENVER))
SHORT_TRIP = built(2, point(20, "hotel", "2026-06-10T15:00", "2026-06-13T11:00", SANTA_FE))
TWIN_TRIP = built(3, point(30, "hotel", "2026-06-10T15:00", "2026-06-13T11:00", TAOS))
UNPLACED_TRIP = built(4, point(40, "hotel", "2026-06-10T15:00", "2026-06-13T11:00"))


class Window(unittest.TestCase):
    def test_a_window_runs_from_the_first_start_to_the_last_end_padded_by_pad(self):
        got = built(1, point(11, "hotel", "2026-06-03T15:00", "2026-06-05T11:00", DENVER),
                    point(12, "flight", "2026-06-01T08:00", "2026-06-01T10:00", zone="America/New_York"))
        self.assertEqual(got.start, at("2026-06-01T08:00", "America/New_York") - PAD)
        self.assertEqual(got.end, at("2026-06-05T11:00") + PAD)
        self.assertEqual((got.start.tzinfo, got.end.tzinfo), (UTC, UTC))
        self.assertEqual([p.segment_id for p in got.points], [11, 12])

    def test_a_visit_only_trip_spans_its_dates_in_its_zone(self):
        zone = "Asia/Tokyo"
        visits = [point(50, "visit", "2026-04-02T00:00", "2026-04-05T00:00", zone=zone, timed=False),
                  point(51, "visit", "2026-04-05T00:00", "2026-04-12T00:00", zone=zone, timed=False)]
        got = built(5, *visits, start_date="2026-04-02", end_date="2026-04-12")
        self.assertEqual(got.start, datetime(2026, 4, 1, 3, 0, tzinfo=UTC))
        self.assertEqual(got.end, datetime(2026, 4, 13, 2, 59, tzinfo=UTC))
        self.assertEqual(photomatch.match(photo("2026-04-12T21:00", zone=zone), [got], None).match, "time")

    def test_a_trip_with_one_timed_booking_uses_the_bookings_instants(self):
        got = built(6, point(60, "visit", "2026-04-02T00:00", "2026-04-04T00:00", timed=False),
                    point(61, "hotel", "2026-04-02T15:00", "2026-04-03T11:00", DENVER), start_date="2026-04-02", end_date="2026-04-04")
        self.assertEqual(got.end, at("2026-04-04T00:00") + PAD)

    def test_a_trip_without_live_bookings_has_no_window(self):
        self.assertIsNone(photomatch.window(trip(7, "2026-04-02", "2026-04-04"), []))


class Matching(unittest.TestCase):
    CASES = [
        ("GPS near a booking", photo("2026-06-05T12:00", BOULDER), [ROAD_TRIP], None, ("place", 1, 10)),
        ("GPS between near and far", photo("2026-06-05T12:00", PUEBLO), [ROAD_TRIP], None, ("time", 1, 10)),
        ("GPS far from every booking", photo("2026-06-05T12:00", SALT_LAKE), [ROAD_TRIP], None, ("far", 1, 10)),
        ("no GPS in one window", photo("2026-06-05T12:00"), [ROAD_TRIP], None, ("time", 1, 10)),
        ("nested windows, GPS near the long trip", photo("2026-06-11T12:00", BOULDER), [ROAD_TRIP, SHORT_TRIP], None, ("place", 1, 10)),
        ("nested windows, GPS near the short trip", photo("2026-06-11T12:00", SANTA_FE), [ROAD_TRIP, SHORT_TRIP], None, ("place", 2, 20)),
        ("nested windows without GPS, shorter wins", photo("2026-06-11T12:00"), [ROAD_TRIP, SHORT_TRIP], None, ("time", 2, 20)),
        ("nested windows, GPS within the margin, shorter wins", photo("2026-06-11T12:00", WALSENBURG), [ROAD_TRIP, SHORT_TRIP], None, ("time", 2, 20)),
        ("nested windows, one trip unplaced, shorter wins", photo("2026-06-11T12:00", BOULDER), [ROAD_TRIP, UNPLACED_TRIP], None, ("time", 4, 40)),
        ("one window, nothing placed", photo("2026-06-11T12:00", BOULDER), [UNPLACED_TRIP], None, ("time", 4, 40)),
        ("equal windows without GPS", photo("2026-06-11T12:00"), [SHORT_TRIP, TWIN_TRIP], None, ("ambiguous", None, None)),
        ("equal windows, GPS can’t tell them apart", photo("2026-06-11T12:00", MIDWAY), [SHORT_TRIP, TWIN_TRIP], None, ("ambiguous", None, None)),
        ("equal windows settled by GPS", photo("2026-06-11T12:00", SANTA_FE), [SHORT_TRIP, TWIN_TRIP], None, ("place", 2, 20)),
        ("inside the Home radius inside a window", photo("2026-06-05T12:00", BOULDER), [ROAD_TRIP], HomeIn(40.02, -105.25, "zip"), ("home", None, None)),
        ("outside the Home radius", photo("2026-06-05T12:00", BOULDER), [ROAD_TRIP], HomeIn(40.06, -105.27, "address"), ("place", 1, 10)),
        ("a Home known only to the city suppresses nothing", photo("2026-06-05T12:00", BOULDER), [ROAD_TRIP], HomeIn(*BOULDER, "city"), ("place", 1, 10)),
        ("outside every window", photo("2026-07-15T12:00", BOULDER), [ROAD_TRIP, SHORT_TRIP], None, ("none", None, None)),
        ("Home outside every window", photo("2026-07-15T12:00", BOULDER), [ROAD_TRIP], HomeIn(*BOULDER, "address"), ("none", None, None)),
        ("no windows at all", photo("2026-06-05T12:00", BOULDER), [], None, ("none", None, None)),
        ("just inside the padding before", photo("2026-06-01T03:01", DENVER), [ROAD_TRIP], None, ("place", 1, 10)),
        ("just outside the padding before", photo("2026-06-01T02:59", DENVER), [ROAD_TRIP], None, ("none", None, None)),
        ("just inside the padding after", photo("2026-06-29T22:59", DENVER), [ROAD_TRIP], None, ("place", 1, 10)),
        ("just outside the padding after", photo("2026-06-29T23:01", DENVER), [ROAD_TRIP], None, ("none", None, None)),
    ]

    def test_each_case(self):
        for name, shot, windows, home, (kind, trip_id, segment_id) in self.CASES:
            with self.subTest(name):
                got = photomatch.match(shot, windows, home)
                self.assertEqual((got.match, got.trip_id, got.segment_id), (kind, trip_id, segment_id))
                self.assertEqual(got.distance_km is None, shot.latitude is None or segment_id is None or got.trip_id == 4)

    def test_the_distance_is_to_the_nearest_booking(self):
        got = photomatch.match(photo("2026-06-05T12:00", BOULDER), [ROAD_TRIP], None)
        self.assertAlmostEqual(got.distance_km or 0, 39.1, delta=1)

    def test_a_flight_is_placed_at_both_its_airports(self):
        flight = built(8, point(80, "flight", "2026-06-01T08:00", "2026-06-01T10:00", DENVER, SALT_LAKE),
                       point(81, "hotel", "2026-06-01T15:00", "2026-06-04T11:00", PUEBLO))
        got = photomatch.match(photo("2026-06-02T12:00", SALT_LAKE), [flight], None)
        self.assertEqual(got, Match("place", 8, 80, 0.0))

    def test_equal_distances_prefer_the_booking_under_way(self):
        again = built(9, point(90, "hotel", "2026-06-01T15:00", "2026-06-03T11:00", DENVER),
                      point(91, "hotel", "2026-06-05T15:00", "2026-06-08T11:00", DENVER))
        self.assertEqual(photomatch.match(photo("2026-06-06T12:00", BOULDER), [again], None).segment_id, 91)
        self.assertEqual(photomatch.match(photo("2026-06-04T09:00", BOULDER), [again], None).segment_id, 90)

    def test_without_gps_the_booking_nearest_in_time_is_kept(self):
        again = built(9, point(90, "hotel", "2026-06-01T15:00", "2026-06-03T11:00", DENVER),
                      point(91, "hotel", "2026-06-05T15:00", "2026-06-08T11:00", DENVER))
        self.assertEqual(photomatch.match(photo("2026-06-05T10:00"), [again], None).segment_id, 91)
        self.assertEqual(photomatch.match(photo("2026-06-04T01:00"), [again], None).segment_id, 90)

    def test_the_match_is_the_same_every_time(self):
        shot = photo("2026-06-11T12:00", LAS_VEGAS_NM)
        windows = [ROAD_TRIP, SHORT_TRIP, TWIN_TRIP]
        self.assertEqual({photomatch.match(shot, order, None) for order in (windows, windows[::-1], windows[1:] + windows[:1])},
                         {photomatch.match(shot, windows, None)})


class Thresholds(unittest.TestCase):
    def test_the_decided_values(self):
        self.assertEqual((photomatch.PAD, photomatch.NEAR, photomatch.FAR, photomatch.MARGIN, GAP, photomatch.CLUSTER),
                         (timedelta(hours=12), 100.0, 400.0, 25.0, timedelta(hours=36), 5.0))
        self.assertEqual(photomatch.HOME, {"address": 2.0, "zip": 8.0, "city": None})

    def test_a_window_reports_its_length(self):
        self.assertEqual(SHORT_TRIP.length, timedelta(days=2, hours=20) + 2 * PAD)
        self.assertIsInstance(SHORT_TRIP, TripWindow)
