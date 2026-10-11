import base64
import unittest
from pathlib import Path
from unittest import mock

from tests.privacy import no_leaks
from waypoint.domain.mail import extract, flights, when, words

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
CANARIES = ("CANARY-BODY-FLIGHT-EN-4J7S", "CANARY-BODY-FLIGHT-DE-8W2L", "CANARY-SENDER-FLIGHT-6P1R", "CANARY-BODY-ORDER-2D9K",
            "CANARY-BODY-ROUND-TRIP-3H8N")


def read(body: str):
    parsed, why = flights.read(f"<html><body>{body}</body></html>", "")
    return parsed, why


def mail(body: str, sender: str = "Skyline Air <reservations@skyline-air.example>", subject: str = "Your trip") -> dict:
    raw = (f"From: {sender}\nSubject: {subject}\nDate: Mon, 12 Oct 2026 09:30:00 -0400\nMIME-Version: 1.0\n"
           f"Content-Type: text/html; charset=utf-8\n\n<html><body>{body}</body></html>").encode()
    return {"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


LABELLED = ("<p>Booking reference: ZK4R9T</p><p>Flight BA 9871</p><p>From: JFK</p><p>Departs: Saturday, November 21, 2026 7:00 PM</p>"
            "<p>To: LHR</p><p>Arrives: Sunday, November 22, 2026 7:10 AM</p>")


class FlightReaderTests(unittest.TestCase):
    def test_labelled_lines_give_a_flight_at_its_airports_wall_clock_times(self):
        with no_leaks(self, *CANARIES):
            parsed, why = read(LABELLED + "<p>CANARY-BODY-FLIGHT-EN-4J7S</p>")
        self.assertIsNone(why)
        [b] = parsed.bookings
        self.assertEqual((b.kind, b.status, b.confirmation, b.provider, b.origin, b.destination, b.start, b.end),
                         ("flight", "confirmed", "ZK4R9T", "British Airways", "JFK", "LHR", "2026-11-21T19:00", "2026-11-22T07:10"))
        self.assertEqual(dict(b.details), {"flight_number": "BA 9871"})
        self.assertEqual(dict(b.generic), {"origin": "airport code", "destination": "airport code", "start_local": "departs",
                                           "end_local": "arrives", "confirmation": "booking reference"})
        self.assertEqual((b.start_zone, b.end_zone), (None, None))

    def test_a_two_column_table_with_the_airports_and_times_side_by_side(self):
        [b] = read("<p>BA 100</p><table><tr><th>Depart</th><th>Arrive</th></tr>"
                   "<tr><td>JFK Nov 21, 2026 7:00 PM</td><td>LHR Nov 22, 2026 7:10 AM</td></tr></table>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start, b.end), ("JFK", "LHR", "2026-11-21T19:00", "2026-11-22T07:10"))

    def test_a_row_per_field_in_a_two_column_table(self):
        [b] = read("<table><tr><td>Flight</td><td>BA 9871</td></tr><tr><td>From</td><td>JFK</td></tr><tr><td>Departs</td><td>2026-11-21 19:00</td></tr>"
                   "<tr><td>To</td><td>LHR</td></tr><tr><td>Arrives</td><td>2026-11-22 07:10</td></tr></table>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start, b.end), ("JFK", "LHR", "2026-11-21T19:00", "2026-11-22T07:10"))

    def test_the_time_on_the_row_after_its_date(self):
        [b] = read("<p>BA 9871</p><p>JFK (New York)</p><p>Departs Nov 21, 2026</p><p>7:00 PM</p><p>LHR (London)</p><p>Arrives Nov 22, 2026</p><p>7:10 AM</p>")[0].bookings
        self.assertEqual((b.start, b.end), ("2026-11-21T19:00", "2026-11-22T07:10"))

    def test_a_multi_leg_itinerary_is_one_booking_per_leg(self):
        parsed, why = read("<p>Confirmation code: QX7M2K</p>"
                           "<p>LH 9001 FRA 21 novembre 2026 15h05 JFK 21 novembre 2026 18h20</p>"
                           "<p>LH 9002 JFK 28.11.2026 21:00 FRA 29.11.2026 10:35</p>")
        self.assertIsNone(why)
        self.assertEqual([(b.origin, b.destination, b.start, b.end, b.confirmation, dict(b.details)["flight_number"]) for b in parsed.bookings],
                         [("FRA", "JFK", "2026-11-21T15:05", "2026-11-21T18:20", "QX7M2K", "LH 9001"),
                          ("JFK", "FRA", "2026-11-28T21:00", "2026-11-29T10:35", "QX7M2K", "LH 9002")])
        self.assertEqual({b.provider for b in parsed.bookings}, {"Lufthansa"})

    def test_a_leg_with_its_details_on_following_lines(self):
        parsed, _ = read("<h3>Outbound</h3><p>Flight AF 9001</p><p>Departure: CDG, 2026-12-01 09:15</p><p>Arrival: JFK, 2026-12-01 11:50</p>"
                         "<h3>Return</h3><p>Flight AF 9002</p><p>Departure: JFK, 2026-12-08 17:00</p><p>Arrival: CDG, 2026-12-09 06:30</p>")
        self.assertEqual([(b.origin, b.destination, b.start, b.end) for b in parsed.bookings],
                         [("CDG", "JFK", "2026-12-01T09:15", "2026-12-01T11:50"), ("JFK", "CDG", "2026-12-08T17:00", "2026-12-09T06:30")])

    def test_a_confirmation_code_that_looks_like_a_flight_number_is_not_one(self):
        parsed, why = read("<p>Booking reference: ZK0000</p>" + LABELLED.replace("Booking reference: ZK4R9T", ""))
        self.assertEqual(([dict(b.details)["flight_number"] for b in parsed.bookings], parsed.unread, why, parsed.bookings[0].confirmation),
                         (["BA 9871"], 0, None, "ZK0000"))

    def test_each_leg_keeps_its_own_confirmation_code_and_others_share_the_messages(self):
        parsed, _ = read("<p>Booking reference: SHARED1</p>"
                         "<p>BA 9871</p><p>Booking reference: AAAA11</p><p>From: JFK</p><p>Departs: 2026-11-21 19:00</p><p>To: LHR</p><p>Arrives: 2026-11-22 07:10</p>"
                         "<p>BA 9872</p><p>Booking reference: BBBB22</p><p>From: LHR</p><p>Departs: 2026-11-28 10:00</p><p>To: JFK</p><p>Arrives: 2026-11-28 13:00</p>"
                         "<p>BA 9873</p><p>From: JFK</p><p>Departs: 2026-12-05 10:00</p><p>To: LHR</p><p>Arrives: 2026-12-05 22:00</p>")
        self.assertEqual([b.confirmation for b in parsed.bookings], ["AAAA11", "BBBB22", "SHARED1"])

    def test_words_that_only_contain_a_departure_or_arrival_word_are_not_labels(self):
        for row in ("Sale price", "Department of travel", "Salida", "Arrivals board"):
            with self.subTest(row):
                self.assertEqual(bool(words.DEPARTURE.search(row) or words.ARRIVAL.search(row)), row == "Salida")
        self.assertTrue(words.ARRIVAL.search("Arrival: LHR") and words.DEPARTURE.search("出発: HND") and words.DEPARTURE.search("Départ"))

    def test_the_same_leg_listed_twice_is_one_booking(self):
        parsed, _ = read(LABELLED + "<p>Summary: BA 9871</p>" + LABELLED)
        self.assertEqual(len(parsed.bookings), 1)

    def test_french_german_spanish_and_japanese_labels_and_dates(self):
        for body, expected in (
            ("<p>Code de réservation : XY12AB</p><p>Vol AF 9001</p><p>Départ : CDG le 21 novembre 2026 à 15h05</p><p>Arrivée : JFK le 21 novembre 2026 à 18h20</p>",
             ("CDG", "JFK", "2026-11-21T15:05", "2026-11-21T18:20", "XY12AB")),
            ("<p>Buchungscode: NL3X8Q</p><p>Flug LH 9001</p><p>Abflug: FRA, 21. November 2026 15:05 Uhr</p><p>Ankunft: JFK, 21. November 2026 18:20 Uhr</p>",
             ("FRA", "JFK", "2026-11-21T15:05", "2026-11-21T18:20", "NL3X8Q")),
            ("<p>Código de reserva: MD45XZ</p><p>Vuelo IB 9001</p><p>Salida: MAD, 21 de noviembre de 2026 15:05</p><p>Llegada: JFK, 21 de noviembre de 2026 18:20</p>",
             ("MAD", "JFK", "2026-11-21T15:05", "2026-11-21T18:20", "MD45XZ")),
            ("<p>予約番号: JL45XZ</p><p>JL 9001</p><p>出発: HND 2026年11月21日 15時05分</p><p>到着: LAX 2026年11月21日 09:20</p>",
             ("HND", "LAX", "2026-11-21T15:05", "2026-11-21T09:20", "JL45XZ")),
        ):
            with self.subTest(expected[0]):
                [b] = read(body)[0].bookings
                self.assertEqual((b.origin, b.destination, b.start, b.end, b.confirmation), expected)

    def test_bilingual_labels_in_one_message(self):
        [b] = read("<p>Buchungscode / Booking reference: NL3X8Q</p><p>LH 9001</p><p>Abflug / Departs: FRA, 21.11.2026 15:05</p>"
                   "<p>Ankunft / Arrives: JFK, 21.11.2026 18:20</p>")[0].bookings
        self.assertEqual((b.confirmation, b.start, b.end), ("NL3X8Q", "2026-11-21T15:05", "2026-11-21T18:20"))

    def test_dates_in_cancellation_and_booking_text_are_ignored(self):
        [b] = read("<p>Booked on Oct 10, 2026 10:00 AM</p><p>Cancel before Oct 20, 2026 6:00 PM for a refund</p>" + LABELLED
                   + "<p>No-show policy: fees apply from Nov 21, 2026 7:00 PM</p>")[0].bookings
        self.assertEqual((b.start, b.end), ("2026-11-21T19:00", "2026-11-22T07:10"))

    def test_times_stay_at_each_airport_and_are_not_converted(self):
        [b] = read("<p>BA 9871</p><p>From: LHR</p><p>Departs: 2026-03-29 09:00</p><p>To: SYD</p><p>Arrives: 2026-03-30 07:20</p>")[0].bookings
        self.assertEqual((b.start, b.end), ("2026-03-29T09:00", "2026-03-30T07:20"))

    def test_what_cannot_be_read_gets_a_reason_and_no_booking(self):
        for body, why in (
            ("<p>BA 9871</p><p>From: JFK</p><p>Departs: 2026-11-21 19:00</p><p>Arrives: 2026-11-22 07:10</p>", "fewer than two known airports found for the flight"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: ZZZ</p><p>Departs: 2026-11-21 19:00</p><p>Arrives: 2026-11-22 07:10</p>", "fewer than two known airports found for the flight"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Via: CDG (Paris)</p><p>Departs: 2026-11-21 19:00</p><p>Arrives: 2026-11-22 07:10</p>", "more than two airports found for one flight"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Departs: 2026-11-21 19:00</p>", "no departure and arrival date and time found"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Departs: 2026-11-21</p><p>Arrives: 2026-11-22</p>", "no departure and arrival date and time found"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Departs: Nov 21 7:00 PM</p><p>Arrives: Nov 22 7:10 AM</p>", "no departure and arrival date and time found"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Departs: 2026-11-22 07:10</p><p>Arrives: 2026-11-21 19:00</p>", "arrival isn't after departure"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Departs: 2026-11-21 19:00</p><p>Arrives: 2026-11-21 20:00</p>", "arrival isn't after departure"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Departs: 2026-11-21 19:00</p><p>Arrives: 2026-11-24 07:10</p>", "flight is longer than 30 hours"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: JFK</p><p>Departs: 2026-11-21 19:00</p><p>Arrives: 2026-11-21 21:00</p>", "fewer than two known airports found for the flight"),
            ("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Departs: 2026-11-21 19:00</p><p>Arrives: 2026-11-22 07:10</p><p>Departs: 2026-11-23 19:00</p>",
             "more than two dates and times for one flight"),
        ):
            with self.subTest(why, body=body[:40]):
                parsed, found = read(body)
                self.assertEqual((parsed.bookings, found), ((), why))

    def test_mail_with_no_flight_number_is_not_a_flight_mail(self):
        self.assertEqual(read("<p>Hello, your newsletter. JFK to LHR deals Nov 21, 2026 7:00 PM</p>")[1], "")
        self.assertEqual(read("<p>Order 12 of PM 5 at 3:30 PM</p>")[1], "")

    def test_a_flight_number_of_an_unknown_airline_is_not_one(self):
        with mock.patch.object(flights.reference, "airline_names", return_value={"LH": "Lufthansa"}):
            self.assertEqual(read(LABELLED)[1], "")

    def test_a_broken_leg_does_not_hide_the_good_one_and_is_counted(self):
        parsed, why = read("<p>BA 9871</p><p>From: JFK</p><p>To: LHR</p><p>Departs: 2026-11-21 19:00</p><p>Arrives: 2026-11-22 07:10</p>"
                           "<p>BA 9872</p><p>From: LHR</p><p>To: JFK</p><p>Departs: 2026-11-28 10:00</p>")
        self.assertIsNone(why)
        self.assertEqual(([b.start for b in parsed.bookings], parsed.unread), (["2026-11-21T19:00"], 1))

    def test_dates_read_in_each_language(self):
        for text, day in (("21 novembre 2026", (2026, 11, 21)), ("1er décembre 2026", (2026, 12, 1)), ("21. November 2026", (2026, 11, 21)),
                          ("21.11.2026", (2026, 11, 21)), ("21 de noviembre de 2026", (2026, 11, 21)), ("21/11/2026", (2026, 11, 21)),
                          ("11/21/2026", (2026, 11, 21)), ("Nov 21, 2026", (2026, 11, 21)), ("2026年11月21日", (2026, 11, 21)),
                          ("juin 3, 2026", (2026, 6, 3)), ("15 juil. 2026", (2026, 7, 15)), ("3 März 2026", (2026, 3, 3))):
            with self.subTest(text):
                found = when.find_date(text)
                self.assertEqual(found and (found.year, found.month, found.day), day)
        self.assertIsNone(when.find_date("04/05/2026"))
        self.assertIsNone(when.find_date("31 Foo 2026"))


class ReadingOrderTests(unittest.TestCase):
    JSONLD = ('<script type="application/ld+json">{"@type":"FlightReservation","reservationNumber":"MK1234",'
              '"reservationFor":{"@type":"Flight","flightNumber":"EX 7","airline":{"iataCode":"EX","name":"Example Air"},'
              '"departureAirport":{"iataCode":"JFK"},"departureTime":"2026-11-20T19:00:00",'
              '"arrivalAirport":{"iataCode":"LHR"},"arrivalTime":"2026-11-21T07:10:00"}}</script>')

    def test_markup_beats_the_generic_reader(self):
        m = extract.read(mail(self.JSONLD + LABELLED))
        self.assertEqual([(b.confirmation, b.generic) for b in m.bookings], [("MK1234", ())])

    def test_a_vendor_parser_beats_the_generic_reader(self):
        raw = (FIXTURES / "southwest" / "booking.eml").read_bytes()
        m = extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")})
        self.assertTrue(m.bookings)
        self.assertEqual([b.generic for b in m.bookings], [()] * len(m.bookings))

    def test_a_complete_stay_beats_a_flight_in_the_same_message(self):
        stay = "<p>Hotel: Harbour Inn</p><p>Check-in: 2026-11-21 15:00</p><p>Check-out: 2026-11-24 11:00</p>"
        m = extract.read(mail(stay + LABELLED))
        self.assertEqual([b.kind for b in m.bookings], ["hotel"])

    def test_flights_left_out_because_a_stay_won_are_counted_as_unread(self):
        stay = "<p>Hotel: Harbour Inn</p><p>Check-in: 2026-11-21 15:00</p><p>Check-out: 2026-11-24 11:00</p>"
        m = extract.read(mail(stay + LABELLED))
        self.assertEqual(([b.kind for b in m.bookings], m.unread), (["hotel"], 1))
        self.assertEqual(extract.read(mail(stay)).unread, 0)

    def test_the_flight_reader_is_used_when_no_stay_is_found(self):
        m = extract.read(mail(LABELLED))
        self.assertEqual(([b.kind for b in m.bookings], m.markup, m.sender_domain), (["flight"], True, "skyline-air.example"))

    def test_an_incomplete_stay_does_not_stop_a_flight_being_read(self):
        m = extract.read(mail("<p>Check-in: 2026-11-21</p>" + LABELLED))
        self.assertEqual([b.kind for b in m.bookings], ["flight"])

    def test_nothing_readable_leaves_the_reasons_of_each_reader(self):
        m = extract.read(mail("<p>Hotel: Inn</p><p>Check-in: 2026-11-21</p><p>BA 9871</p><p>From: JFK</p>"))
        self.assertEqual(m.bookings, ())
        self.assertEqual(m.gaps, ("generic reader: no check-out date found", "generic reader: fewer than two known airports found for the flight"))

    def test_a_reader_that_fails_is_reported_without_its_text_and_the_next_one_still_runs(self):
        boom = mock.Mock(side_effect=ValueError("CANARY-BODY-ORDER-2D9K"))
        with mock.patch.object(extract, "GENERIC_READERS", (boom, flights.read)), no_leaks(self, *CANARIES):
            m = extract.read(mail(LABELLED + "<p>CANARY-BODY-ORDER-2D9K</p>", sender="Skyline <a@skyline-air.example>"))
        self.assertEqual([b.kind for b in m.bookings], ["flight"])

    def test_the_fixtures_are_read(self):
        for name, expected in (("flight_generic_en", ("JFK", "LHR", "2026-11-21T19:00", "2026-11-22T07:10", "ZK4R9T")),
                               ("flight_generic_de", ("FRA", "JFK", "2026-11-21T15:05", "2026-11-21T18:20", "NL3X8Q"))):
            with self.subTest(name), no_leaks(self, *CANARIES):
                raw = (FIXTURES / f"{name}.eml").read_bytes()
                [b] = extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}).bookings
                self.assertEqual((b.origin, b.destination, b.start, b.end, b.confirmation), expected)


def block(title: str, day: str, number: str, left: str, right: str, extra: str = "Economy · 2h 50m · Nonstop") -> str:
    return (f"<table><tr><td>{title}</td><td>{day}</td></tr><tr><td>{extra}</td></tr><tr><td>{number}</td></tr>"
            f"<tr><td>{left}</td><td>{right}</td></tr></table>")


BANNER = ("<table><tr><td>Rewards Travel</td></tr><tr><td>Your flights are booked. Confirmation code: Q7M2KD</td></tr></table>"
          "<p>CANARY-BODY-ROUND-TRIP-3H8N</p>")
OUTBOUND = block("Outbound to Denver", "Sat, Dec 5, 2026", "Delta DL 1204", "Boston BOS 7:15 AM", "Denver DEN 10:05 AM")
RETURN = block("Return to Boston", "Fri, Dec 11, 2026", "Delta DL 1377", "Denver DEN 4:20 PM", "Boston BOS 9:50 PM", "Economy · 3h 40m · Nonstop")


def legs(parsed):
    return [(b.origin, b.destination, b.start, b.end, dict(b.details)["flight_number"], b.confirmation) for b in parsed.bookings]


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(no_leaks(self, *CANARIES))

    def test_a_round_trip_card_site_email_is_one_flight_per_leg_from_every_reading_path(self):
        raw = (FIXTURES / "flight_round_trip_card_site.eml").read_bytes()
        message = {"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}
        expected = [("BOS", "DEN", "2026-12-05T07:15", "2026-12-05T10:05", "DL 1204", "Q7M2KD"),
                    ("DEN", "BOS", "2026-12-11T16:20", "2026-12-11T21:50", "DL 1377", "Q7M2KD")]
        found = extract.read(message)
        generic, why = flights.read("", extract.plain_text(message))
        self.assertEqual((legs(found), found.unread, found.gaps), (expected, 0, ()))
        self.assertEqual((legs(generic), why), (expected, None))
        self.assertEqual({b.provider for b in found.bookings}, {"Delta Air Lines"})
        self.assertEqual([(b.start_zone, b.end_zone) for b in found.bookings], [(None, None)] * 2)

    def test_the_fixture_has_no_markup_and_no_vendor_parser_so_the_generic_reader_is_what_reads_it(self):
        raw = (FIXTURES / "flight_round_trip_card_site.eml").read_bytes()
        self.assertNotIn(b"ld+json", raw)
        self.assertNotIn(b"schema.org", raw)
        self.assertIsNone(extract.parsers.for_sender("rewards-travel.example"))

    def test_the_date_is_the_one_in_each_legs_own_block(self):
        parsed, why = read(BANNER + OUTBOUND + RETURN)
        self.assertIsNone(why)
        self.assertEqual([(b.start[:10], b.end[:10]) for b in parsed.bookings], [("2026-12-05", "2026-12-05"), ("2026-12-11", "2026-12-11")])

    def test_a_one_way_is_one_booking(self):
        parsed, why = read(BANNER + OUTBOUND)
        self.assertEqual((legs(parsed), why, parsed.unread), ([("BOS", "DEN", "2026-12-05T07:15", "2026-12-05T10:05", "DL 1204", "Q7M2KD")], None, 0))

    def test_an_airport_in_both_legs_is_not_one_flight(self):
        parsed, _ = read(BANNER + OUTBOUND + RETURN)
        self.assertEqual([(b.origin, b.destination) for b in parsed.bookings], [("BOS", "DEN"), ("DEN", "BOS")])

    def test_the_same_flight_number_each_way_is_still_two_flights(self):
        parsed, _ = read(BANNER + OUTBOUND + RETURN.replace("DL 1377", "DL 1204"))
        self.assertEqual([(b.origin, b.start[:10]) for b in parsed.bookings], [("BOS", "2026-12-05"), ("DEN", "2026-12-11")])

    def test_a_leg_with_no_time_is_reported_and_the_other_leg_is_still_read(self):
        no_time = block("Return to Boston", "Fri, Dec 11, 2026", "Delta DL 1377", "Denver DEN", "Boston BOS")
        parsed, why = read(BANNER + OUTBOUND + no_time)
        self.assertIsNone(why)
        self.assertEqual((legs(parsed), parsed.unread), ([("BOS", "DEN", "2026-12-05T07:15", "2026-12-05T10:05", "DL 1204", "Q7M2KD")], 1))
        parsed, _ = read(BANNER + block("Outbound to Denver", "Sat, Dec 5, 2026", "Delta DL 1204", "Boston BOS", "Denver DEN") + RETURN)
        self.assertEqual(([b.origin for b in parsed.bookings], parsed.unread), (["DEN"], 1))

    def test_a_duration_is_not_read_as_a_time_of_day(self):
        self.assertIsNone(when.find_time("Economy 2h 50m Nonstop"))
        self.assertIsNone(when.find_time("3h 40min"))
        self.assertEqual(when.find_time("à 15h05").hour, 15)

    def test_an_overnight_flight_lands_the_next_day(self):
        parsed, _ = read(BANNER + block("Outbound to Denver", "Sat, Dec 5, 2026", "Delta DL 1204", "Boston BOS 10:30 PM", "Denver DEN 12:40 AM", "Economy · 4h 10m · Nonstop"))
        self.assertEqual(legs(parsed), [("BOS", "DEN", "2026-12-05T22:30", "2026-12-06T00:40", "DL 1204", "Q7M2KD")])

    def test_an_arrival_that_is_not_after_the_departure_is_not_guessed(self):
        parsed, why = read(BANNER + block("Outbound to Denver", "Sat, Dec 5, 2026", "Delta DL 1204", "Boston BOS 7:15 AM", "Denver DEN 5:15 AM"))
        self.assertEqual((parsed.bookings, why), ((), "arrival isn't after departure"))

    def test_a_flight_to_itself_is_never_read(self):
        parsed, why = read(BANNER + block("Outbound to Denver", "Sat, Dec 5, 2026", "Delta DL 1204", "Boston BOS 7:15 AM", "Boston BOS 10:05 AM"))
        self.assertEqual((parsed.bookings, why), ((), "departure and arrival airport are the same"))

    def test_a_block_flight_longer_than_the_limit_is_rejected(self):
        zones = {"AAA": "Pacific/Kiritimati", "BBB": "Etc/GMT+12"}
        with mock.patch.object(flights.reference, "airport_zones", return_value=zones):
            parsed, why = read(BANNER + block("Outbound", "Sat, Dec 5, 2026", "Delta DL 1204", "Alpha AAA 12:05 AM", "Bravo BBB 11:50 PM"))
        self.assertEqual((parsed.bookings, why), ((), f"flight is longer than {flights.MAX_HOURS} hours"))

    def test_a_block_without_a_date_of_its_own_is_not_given_one_from_elsewhere(self):
        undated = "<table><tr><td>Outbound to Denver</td></tr><tr><td>Delta DL 1204</td></tr><tr><td>Boston BOS 7:15 AM</td><td>Denver DEN 10:05 AM</td></tr></table>"
        parsed, why = read("<p>Trip Dec 5, 2026 - Dec 11, 2026</p>" + BANNER + undated)
        self.assertEqual(parsed.bookings, ())
        self.assertTrue(why)
