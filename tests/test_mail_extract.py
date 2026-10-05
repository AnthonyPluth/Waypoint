"""Reading a message for its bookings (waypoint/domain/mail/extract.py): schema.org JSON-LD and microdata for each kind of
reservation, from synthetic emails (invented names, codes and numbers; real airports). Nothing here touches a database."""
import base64
import unittest
from pathlib import Path

from waypoint.domain.mail import extract

FIXTURES = Path(__file__).parent / "fixtures" / "mail"


def message(raw: bytes) -> dict:
    """A message as Gmail's API gives it with format=raw."""
    return {"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


def fixture(name: str) -> extract.Message:
    return extract.read(message((FIXTURES / f"{name}.eml").read_bytes()))


def eml(html: str, subject: str = "Hello", sender: str = "Example Air <a@example-air.example>", ctype: str = "text/html") -> bytes:
    return (f"From: {sender}\nSubject: {subject}\nDate: Mon, 12 Oct 2026 09:30:00 -0400\nMIME-Version: 1.0\n"
            f"Content-Type: {ctype}; charset=utf-8\n\n{html}").encode()


def ld(node: str) -> bytes:
    return eml(f'<html><head><script type="application/ld+json">{node}</script></head><body>x</body></html>')


FLIGHT = ('{"@type":"FlightReservation","reservationNumber":"ABC123","underName":{"name":"Jane Doe"},'
          '"reservationFor":{"@type":"Flight","flightNumber":"EX 7","airline":{"iataCode":"EX","name":"Example Air"},'
          '"departureAirport":{"iataCode":"jfk"},"departureTime":"2026-11-20T19:00:00-05:00",'
          '"arrivalAirport":{"iataCode":"LHR"},"arrivalTime":"2026-11-21T07:10:00Z"}}')


class FixtureTests(unittest.TestCase):
    def test_a_flight_in_json_ld(self):
        m = fixture("flight_jsonld")
        self.assertEqual((m.sender_domain, m.received, m.unread, m.broken, m.markup),
                         ("example-air.example", "2026-10-12", 0, False, True))
        [b] = m.bookings
        self.assertEqual((b.kind, b.status, b.confirmation, b.provider, b.origin, b.destination),
                         ("flight", "confirmed", "QX7M2K", "Example Air", "JFK", "LHR"))
        self.assertEqual((b.start, b.end), ("2026-11-20T19:00:00-05:00", "2026-11-21T07:10:00+00:00"))
        self.assertEqual(dict(b.details), {"flight_number": "EX 101", "terminal": "7", "seat": "21C", "cabin": "Economy"})
        self.assertEqual(b.manage_url, "https://example-air.example/manage/QX7M2K")
        self.assertEqual(b.passengers, (extract.Passenger("Jane Doe", "FXLOY-4400123"),))

    def test_a_flight_in_microdata(self):
        [b] = fixture("flight_microdata").bookings
        self.assertEqual((b.kind, b.confirmation, b.origin, b.destination, b.start, b.end),
                         ("flight", "PL4N9R", "JFK", "SFO", "2026-12-08T08:00:00-05:00", "2026-12-08T11:20:00-08:00"))
        self.assertEqual(dict(b.details), {"flight_number": "EX 311"})
        self.assertEqual(b.passengers, (extract.Passenger("DOE/MIA MISS"),))

    def test_a_hotel_a_car_and_a_train(self):
        [hotel] = fixture("hotel_jsonld").bookings
        self.assertEqual((hotel.kind, hotel.confirmation, hotel.origin, hotel.destination, hotel.start_place, hotel.provider),
                         ("hotel", "H88231", "Harbour Hotel", None, extract.Place("London", "GB"), "Harbour Hotel"))
        self.assertEqual(dict(hotel.details), {"address": "1 Quay Street, London, GB", "phone": "+44 20 7946 0000", "room": "Family room"})
        [car] = fixture("car_jsonld").bookings
        self.assertEqual((car.kind, car.provider, car.origin, car.destination, car.start, car.end),
                         ("car", "Example Rentals", "San Francisco Airport", "San Francisco Airport",
                          "2026-12-08T12:00:00-08:00", "2026-12-10T15:00:00-08:00"))
        self.assertEqual(dict(car.details)["car_class"], "Compact")
        [train] = fixture("train_jsonld").bookings
        self.assertEqual((train.kind, train.provider, train.origin, train.destination, train.start_place, train.end_place),
                         ("train", "Example Rail", "London St Pancras", "Paris Gare du Nord", extract.Place("London", "GB"),
                          extract.Place("Paris", "FR")))
        self.assertEqual(dict(train.details), {"seat": "12A", "cabin": "Standard"})

    def test_mail_with_no_markup_has_no_bookings(self):
        m = fixture("no_markup")
        self.assertEqual((m.bookings, m.unread, m.markup, m.broken), ((), 0, False, False))

    def test_a_reservation_missing_what_it_needs_is_counted_not_guessed(self):
        m = fixture("incomplete")
        self.assertEqual((m.bookings, m.unread, m.markup), ((), 1, True))


class MarkupTests(unittest.TestCase):
    def read(self, raw: bytes) -> extract.Message:
        return extract.read(message(raw))

    def test_airport_codes_are_upper_case_and_the_airlines_code_joins_the_number(self):
        [b] = self.read(ld(FLIGHT)).bookings
        self.assertEqual((b.origin, dict(b.details)["flight_number"]), ("JFK", "EX 7"))

    def test_json_ld_in_a_list_or_a_graph(self):
        for node in (f"[{FLIGHT}]", '{"@graph":[{"@type":"Organization"},' + FLIGHT + "]}"):
            with self.subTest(node=node[:12]):
                self.assertEqual(len(self.read(ld(node)).bookings), 1)

    def test_a_type_with_its_full_address_or_as_a_list(self):
        node = FLIGHT.replace('"FlightReservation"', '["http://schema.org/FlightReservation"]', 1)
        self.assertEqual(len(self.read(ld(node)).bookings), 1)

    def test_the_same_booking_in_json_ld_and_microdata_is_one(self):
        both = eml(f'<script type="application/ld+json">{FLIGHT}</script>'
                   '<div itemscope itemtype="http://schema.org/FlightReservation"><meta itemprop="reservationNumber" content="ABC123"/>'
                   '<div itemprop="underName" itemscope itemtype="http://schema.org/Person"><meta itemprop="name" content="Jane Doe"/></div>'
                   '<div itemprop="reservationFor" itemscope itemtype="http://schema.org/Flight"><meta itemprop="flightNumber" content="EX 7"/>'
                   '<div itemprop="airline" itemscope itemtype="http://schema.org/Airline"><meta itemprop="iataCode" content="EX"/>'
                   '<meta itemprop="name" content="Example Air"/></div>'
                   '<div itemprop="departureAirport" itemscope itemtype="http://schema.org/Airport"><meta itemprop="iataCode" content="jfk"/></div>'
                   '<meta itemprop="departureTime" content="2026-11-20T19:00:00-05:00"/>'
                   '<div itemprop="arrivalAirport" itemscope itemtype="http://schema.org/Airport"><meta itemprop="iataCode" content="LHR"/></div>'
                   '<meta itemprop="arrivalTime" content="2026-11-21T07:10:00Z"/></div></div>')
        self.assertEqual(len(self.read(both).bookings), 1)

    def test_microdata_text_and_attribute_values(self):
        html = ('<div itemscope itemtype="https://schema.org/LodgingReservation"><span itemprop="reservationNumber"> H1  22 </span>'
                '<time itemprop="checkinTime" datetime="2026-11-21T15:00:00+00:00">Nov 21</time>'
                '<time itemprop="checkoutTime" datetime="2026-11-27T10:00:00+00:00">Nov 27</time>'
                '<div itemprop="reservationFor" itemscope itemtype="https://schema.org/LodgingBusiness"><span itemprop="name">Harbour <b>Hotel</b></span>'
                '<div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress"><span itemprop="addressLocality">London</span>'
                '<span itemprop="addressCountry">GB</span></div></div>'
                '<a itemprop="url" href="https://example-stays.example/r/1">manage</a><br/></div>')
        [b] = self.read(eml(html)).bookings
        self.assertEqual((b.confirmation, b.origin, b.start_place, b.manage_url, b.start, b.end),
                         ("H1 22", "Harbour Hotel", extract.Place("London", "GB"), "https://example-stays.example/r/1",
                          "2026-11-21T15:00:00+00:00", "2026-11-27T10:00:00+00:00"))

    def test_a_cancelled_reservation(self):
        node = FLIGHT.replace('"reservationNumber"', '"reservationStatus":"http://schema.org/ReservationCancelled","reservationNumber"')
        self.assertEqual(self.read(ld(node)).bookings[0].status, "cancelled")

    def test_a_link_that_is_not_http_is_dropped(self):
        node = FLIGHT.replace('"reservationNumber"', '"url":"javascript:alert(1)","reservationNumber"')
        self.assertIsNone(self.read(ld(node)).bookings[0].manage_url)

    def test_one_membership_number_is_the_only_travellers_but_not_one_of_several(self):
        one = FLIGHT.replace('"reservationNumber"', '"programMembership":{"memberNumber":"M-1"},"reservationNumber"')
        self.assertEqual(self.read(ld(one)).bookings[0].passengers, (extract.Passenger("Jane Doe", "M-1"),))
        two = one.replace('"underName":{"name":"Jane Doe"}', '"underName":[{"name":"Jane Doe"},{"givenName":"Sam","familyName":"Doe"}]')
        self.assertEqual(self.read(ld(two)).bookings[0].passengers, (extract.Passenger("Jane Doe"), extract.Passenger("Sam Doe")))

    def test_another_kind_of_reservation_is_seen_but_not_read(self):
        m = self.read(ld('{"@type":"FoodEstablishmentReservation","reservationNumber":"T1"}'))
        self.assertEqual((m.bookings, m.unread, m.markup), ((), 1, True))

    def test_markup_that_is_not_json_or_not_a_reservation_is_not_a_booking(self):
        for html in ('<script type="application/ld+json">{not json</script>', '<script type="application/ld+json">"just text"</script>',
                     '<script type="application/ld+json">{"@type":"EmailMessage"}</script>', "<p>plain</p>",
                     '<script>var x = {"@type":"FlightReservation"};</script>'):
            with self.subTest(html=html[:40]):
                m = self.read(eml(html))
                self.assertEqual((m.bookings, m.unread, m.markup), ((), 0, False))

    def test_a_message_that_cannot_be_decoded_is_broken(self):
        for raw in ({}, {"raw": ""}, {"raw": 5}, {"raw": "***"}):
            with self.subTest(raw=raw):
                m = extract.read(raw)
                self.assertTrue(m.broken)
                self.assertEqual(m.bookings, ())

    def test_the_sender_and_the_day_as_written(self):
        m = self.read(eml("<p>x</p>", sender='"Example, Air" <No-Reply@Mail.Example-Air.example>', subject="Hi"))
        self.assertEqual((m.sender_domain, m.received), ("mail.example-air.example", "2026-10-12"))
        none = self.read(b"Subject: x\n\n")
        self.assertEqual((none.sender_domain, none.received), (None, None))
        bad_date = self.read(b"From: a@example.com\nDate: not a date\n\nx")
        self.assertEqual((bad_date.sender_domain, bad_date.received), ("example.com", None))

    def test_only_html_parts_are_read_and_a_bad_charset_is_skipped(self):
        multipart = (b"From: a@example-air.example\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=b\n\n"
                     b"--b\nContent-Type: text/plain\n\n<script type=\"application/ld+json\">" + FLIGHT.encode() + b"</script>\n"
                     b"--b\nContent-Type: text/html; charset=no-such-charset\n\n<p>x</p>\n--b--\n")
        self.assertEqual(self.read(multipart).bookings, ())

    def test_deeply_nested_markup_does_not_break_the_read(self):
        self.assertEqual(self.read(ld("[" * 5000 + "]" * 5000)).bookings, ())
        self.assertEqual(self.read(eml("<div>" * 3000 + "</div>" * 3000)).bookings, ())


class WallClockTests(unittest.TestCase):
    def test_a_time_with_its_places_offset_keeps_what_is_written(self):
        self.assertEqual(extract.wall_clock("2026-03-01T22:15:00+13:00"), "2026-03-01T22:15:00")
        self.assertEqual(extract.wall_clock("2026-03-01T22:15:00+13:00", "Pacific/Auckland"), "2026-03-01T22:15:00")
        self.assertEqual(extract.wall_clock("2026-03-01T22:15:00+00:00", "Europe/London"), "2026-03-01T22:15:00")   # (London in March is UTC)
        self.assertEqual(extract.wall_clock("2026-03-01T22:15"), "2026-03-01T22:15:00")
        self.assertEqual(extract.wall_clock("2026-03-01 22:15:00"), "2026-03-01T22:15:00")

    def test_a_time_in_utc_or_another_offset_than_the_places_is_moved_into_its_own_zone_and_needs_one(self):
        self.assertEqual(extract.wall_clock("2026-03-01T09:15:00Z", "Pacific/Auckland"), "2026-03-01T22:15:00")
        self.assertEqual(extract.wall_clock("2026-03-01T09:15:00+00:00", "Pacific/Auckland"), "2026-03-01T22:15:00")
        self.assertEqual(extract.wall_clock("2026-07-01T12:00:00+00:00", "Europe/London"), "2026-07-01T13:00:00")   # (BST)
        self.assertIsNone(extract.wall_clock("2026-03-01T09:15:00+00:00"))
        self.assertIsNone(extract.wall_clock("2026-03-01T09:15:00Z"))
        self.assertIsNone(extract.wall_clock("2026-03-01T09:15:00Z", "Not/AZone"))

    def test_a_date_alone_or_nonsense_is_not_a_time(self):
        for text in ("2026-03-01", "tomorrow", "", "2026-13-45T10:00"):
            with self.subTest(text=text):
                self.assertIsNone(extract.wall_clock(text, "Europe/London"))


if __name__ == "__main__":
    unittest.main()
