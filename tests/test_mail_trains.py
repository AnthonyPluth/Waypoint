import base64
import unittest
from pathlib import Path
from unittest import mock

from tests.privacy import no_leaks
from waypoint.domain.mail import extract, trains

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
CANARIES = ("CANARY-BODY-TRAIN-EN-6D4N", "CANARY-BODY-TRAIN-FR-9B5T", "CANARY-BODY-TRAIN-ORDER-1S7J")


def read(body: str):
    parsed, why = trains.read(f"<html><body>{body}</body></html>", "")
    return parsed, why


def mail(body: str, sender: str = "Alpine Rail <tickets@alpine-rail.example>") -> dict:
    raw = (f"From: {sender}\nSubject: Your tickets\nDate: Mon, 12 Oct 2026 09:30:00 +0200\nMIME-Version: 1.0\n"
           f"Content-Type: text/html; charset=utf-8\n\n<html><body>{body}</body></html>").encode()
    return {"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


LEG = ("<p>Train: EC 311</p><p>From: Zurich HB</p><p>Departure: 21.11.2026 09:02</p><p>To: Milan Centrale</p><p>Arrival: 21.11.2026 12:25</p>")
LABELLED = "<p>Your train tickets</p><p>Booking reference: AR48219</p><p>Operator: Alpine Rail</p>" + LEG


class TrainReaderTests(unittest.TestCase):
    def test_labelled_lines_give_a_train_at_its_stations_wall_clock_times(self):
        with no_leaks(self, *CANARIES):
            parsed, why = read(LABELLED + "<p>CANARY-BODY-TRAIN-EN-6D4N</p>")
        self.assertIsNone(why)
        [b] = parsed.bookings
        self.assertEqual((b.kind, b.status, b.confirmation, b.provider, b.origin, b.destination, b.start, b.end),
                         ("train", "confirmed", "AR48219", "Alpine Rail", "Zurich HB", "Milan Centrale", "2026-11-21T09:02", "2026-11-21T12:25"))
        self.assertEqual((b.start_zone, b.end_zone), ("Europe/Zurich", "Europe/Rome"))
        self.assertEqual(dict(b.generic), {"origin": "from", "destination": "to", "start_local": "departure", "end_local": "arrival",
                                           "provider": "operator", "confirmation": "booking reference"})

    def test_a_two_column_table_with_a_header_row(self):
        [b] = read("<p>Train tickets</p><table><tr><th>Departure</th><th>Arrival</th></tr>"
                   "<tr><td>Zurich HB, Nov 21, 2026 9:02 AM</td><td>Milan Centrale, Nov 21, 2026 12:25 PM</td></tr></table>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start, b.end), ("Zurich HB", "Milan Centrale", "2026-11-21T09:02", "2026-11-21T12:25"))

    def test_a_row_per_field_in_a_table(self):
        [b] = read("<p>Train</p><table><tr><td>From</td><td>Zurich HB</td></tr><tr><td>Departure date</td><td>2026-11-21</td></tr>"
                   "<tr><td>Departure time</td><td>09:02</td></tr><tr><td>To</td><td>Milan Centrale</td></tr>"
                   "<tr><td>Arrival date</td><td>2026-11-21</td></tr><tr><td>Arrival time</td><td>12:25</td></tr></table>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start, b.end), ("Zurich HB", "Milan Centrale", "2026-11-21T09:02", "2026-11-21T12:25"))

    def test_the_time_on_the_line_after_the_date(self):
        [b] = read("<p>Train</p><p>Departure: Zurich HB, 21.11.2026</p><p>09:02</p><p>Arrival: Milan Centrale, 21.11.2026</p><p>12:25</p>")[0].bookings
        self.assertEqual((b.start, b.end), ("2026-11-21T09:02", "2026-11-21T12:25"))

    def test_an_outbound_and_a_return_are_two_bookings_with_the_shared_code_and_operator(self):
        parsed, why = read("<p>Train tickets</p><p>Booking reference: AR48219</p><p>Operator: Alpine Rail</p><h3>Outbound</h3>" + LEG
                           + "<h3>Return</h3><p>Train: EC 316</p><p>From: Milan Centrale</p><p>Departure: 28.11.2026 15:35</p><p>To: Zurich HB</p><p>Arrival: 28.11.2026 18:58</p>")
        self.assertIsNone(why)
        self.assertEqual([(b.origin, b.destination, b.start, b.end, b.confirmation, b.provider) for b in parsed.bookings],
                         [("Zurich HB", "Milan Centrale", "2026-11-21T09:02", "2026-11-21T12:25", "AR48219", "Alpine Rail"),
                          ("Milan Centrale", "Zurich HB", "2026-11-28T15:35", "2026-11-28T18:58", "AR48219", "Alpine Rail")])

    def test_legs_that_start_with_their_stations_are_told_apart_too(self):
        parsed, _ = read("<p>Train</p><p>From: Zurich HB</p><p>To: Milan Centrale</p><p>Departure: 21.11.2026 09:02</p><p>Arrival: 21.11.2026 12:25</p>"
                         "<p>From: Milan Centrale</p><p>To: Zurich HB</p><p>Departure: 28.11.2026 15:35</p><p>Arrival: 28.11.2026 18:58</p>")
        self.assertEqual([(b.origin, b.start) for b in parsed.bookings], [("Zurich HB", "2026-11-21T09:02"), ("Milan Centrale", "2026-11-28T15:35")])

    def test_the_same_leg_listed_twice_is_one_booking(self):
        self.assertEqual(len(read(LABELLED + "<p>Summary</p>" + LEG)[0].bookings), 1)

    def test_a_broken_leg_does_not_hide_the_good_one_and_is_counted(self):
        parsed, why = read("<p>Train</p>" + LEG + "<p>Train: EC 316</p><p>From: Milan Centrale</p><p>Departure: 28.11.2026 15:35</p><p>To: Zurich HB</p>")
        self.assertIsNone(why)
        self.assertEqual(([b.start for b in parsed.bookings], parsed.unread), (["2026-11-21T09:02"], 1))

    def test_an_arrival_in_another_zone_is_not_converted(self):
        [b] = read("<p>Train</p><p>From: London St Pancras</p><p>Departure: 2026-11-21 09:00</p><p>To: Paris Gare du Nord</p><p>Arrival: 2026-11-21 12:20</p>")[0].bookings
        self.assertEqual((b.start, b.end, b.start_zone, b.end_zone), ("2026-11-21T09:00", "2026-11-21T12:20", "Europe/London", "Europe/Paris"))

    def test_french_german_spanish_and_japanese_labels(self):
        for body, expected in (
            ("<p>Billet de train</p><p>Numéro de réservation : FR12345</p><p>Gare de départ : Paris Gare de Lyon</p><p>Date et heure de départ : 21 novembre 2026 à 09h12</p>"
             "<p>Gare d'arrivée : Lyon Part-Dieu</p><p>Date et heure d'arrivée : 21 novembre 2026 à 11h14</p>",
             ("FR12345", "Paris Gare de Lyon", "2026-11-21T09:12", "2026-11-21T11:14")),
            ("<p>Ihre Zugverbindung</p><p>Buchungsnummer: DE12345</p><p>Abfahrtsbahnhof: Berlin Hbf</p><p>Abfahrt: 21.11.2026 09:12 Uhr</p><p>Ankunftsbahnhof: Munich Hbf</p>"
             "<p>Ankunft: 21.11.2026 13:30 Uhr</p>", ("DE12345", "Berlin Hbf", "2026-11-21T09:12", "2026-11-21T13:30")),
            ("<p>Billete de tren</p><p>Código de reserva: ES12345</p><p>Estación de origen: Madrid Atocha</p><p>Salida: 21 de noviembre de 2026 09:12</p>"
             "<p>Estación de destino: Barcelona Sants (BCN)</p><p>Llegada: 21 de noviembre de 2026 11:45</p>",
             ("ES12345", "Madrid Atocha", "2026-11-21T09:12", "2026-11-21T11:45")),
            ("<p>新幹線の予約</p><p>予約番号: JP12345</p><p>出発駅: 東京駅 (Tokyo)</p><p>出発日時: 2026年11月21日 09:12</p><p>到着駅: 大阪駅 (Osaka)</p>"
             "<p>到着日時: 2026年11月21日 11:30</p>", ("JP12345", "東京駅 (Tokyo)", "2026-11-21T09:12", "2026-11-21T11:30")),
        ):
            with self.subTest(expected[0]):
                [b] = read(body)[0].bookings
                self.assertEqual((b.confirmation, b.origin, b.start, b.end), expected)

    def test_dates_in_cancellation_and_policy_text_are_ignored(self):
        [b] = read("<p>Booked on Oct 10, 2026 10:00</p><p>Exchanges are free until Nov 15, 2026 12:00</p>" + LABELLED
                   + "<p>Cancellation fees apply from Nov 20, 2026 09:00</p><p>Terms: departure after Nov 22, 2026 is not refunded</p>")[0].bookings
        self.assertEqual((b.start, b.end), ("2026-11-21T09:02", "2026-11-21T12:25"))

    def test_what_cannot_be_read_gets_a_reason_and_no_booking(self):
        for body, why in (
            ("<p>Train</p><p>Departure: 21.11.2026 09:02</p><p>Arrival: 21.11.2026 12:25</p>", "no departure and arrival station found"),
            ("<p>Train</p><p>From: Zurich HB</p><p>To: Milan Centrale</p><p>Departure: 21.11.2026</p><p>Arrival: 21.11.2026</p>", "no departure and arrival date and time found"),
            ("<p>Train</p><p>From: Zurich HB</p><p>To: Milan Centrale</p><p>Departure: 09:02</p><p>Arrival: 12:25</p>", "no departure and arrival date and time found"),
            ("<p>Train</p><p>From: Somewhere Plaza</p><p>To: Milan Centrale</p><p>Departure: 21.11.2026 09:02</p><p>Arrival: 21.11.2026 12:25</p>", "station's time zone unknown"),
            ("<p>Train</p><p>From: Zurich HB</p><p>To: Milan Centrale</p><p>Departure: 21.11.2026 12:25</p><p>Arrival: 21.11.2026 09:02</p>", "arrival isn't after departure"),
            ("<p>Train</p><p>From: Zurich HB</p><p>To: Milan Centrale</p><p>Departure: 21.11.2026 09:02</p><p>Arrival: 26.11.2026 09:02</p>", "train trip is longer than 96 hours"),
        ):
            with self.subTest(why, body=body[-50:]):
                parsed, found = read(body)
                self.assertEqual((parsed.bookings, found), ((), why))

    def test_mail_that_is_not_about_a_train_is_not_read_as_one(self):
        for body in ("<p>Hello, your newsletter</p>", "<p>From: Zurich HB</p><p>Departure: 21.11.2026 09:02</p><p>To: Milan Centrale</p><p>Arrival: 21.11.2026 12:25</p>",
                     "<p>Your train is booked</p><p>Have a nice trip</p>",
                     "<p>Your flight BA 9871 and a train to the airport</p><p>From: Zurich HB</p><p>Departure: 21.11.2026 09:02</p><p>To: Milan Centrale</p><p>Arrival: 21.11.2026 12:25</p>"):
            with self.subTest(body):
                self.assertEqual(read(body), (trains.Parsed(), ""))


class TrainOrderTests(unittest.TestCase):
    def test_the_fixtures_are_read(self):
        for name, expected in (
            ("train_generic_en", [("AR48219", "Alpine Rail", "Zurich HB", "Milan Centrale", "2026-11-21T09:02", "2026-11-21T12:25", "Europe/Zurich", "Europe/Rome"),
                                  ("AR48219", "Alpine Rail", "Milan Centrale", "Zurich HB", "2026-11-28T15:35", "2026-11-28T18:58", "Europe/Rome", "Europe/Zurich")]),
            ("train_generic_fr", [("RX90412", "Rail Exemple", "Paris Gare de Lyon", "Lyon Part-Dieu", "2026-11-21T09:12", "2026-11-21T11:14", "Europe/Paris", "Europe/Paris")]),
        ):
            with self.subTest(name), no_leaks(self, *CANARIES):
                raw = (FIXTURES / f"{name}.eml").read_bytes()
                m = extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")})
                self.assertEqual([(b.confirmation, b.provider, b.origin, b.destination, b.start, b.end, b.start_zone, b.end_zone) for b in m.bookings], expected)
                self.assertTrue(m.markup and all(b.generic for b in m.bookings))

    def test_markup_beats_the_generic_reader(self):
        raw = (FIXTURES / "train_jsonld.eml").read_bytes().replace(b"</body>", LABELLED.replace("AR48219", "ZZ9999").encode() + b"</body>")
        [b] = extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}).bookings
        self.assertEqual(b.generic, ())
        self.assertNotEqual(b.confirmation, "ZZ9999")

    def test_a_reader_that_fails_is_reported_without_its_text_and_the_next_one_still_runs(self):
        boom = mock.Mock(side_effect=ValueError("CANARY-BODY-TRAIN-ORDER-1S7J"))
        with mock.patch.object(extract, "GENERIC_READERS", (boom, trains.read)), no_leaks(self, *CANARIES):
            m = extract.read(mail(LABELLED + "<p>CANARY-BODY-TRAIN-ORDER-1S7J</p>"))
        self.assertEqual([b.kind for b in m.bookings], ["train"])

    def test_a_flight_is_read_as_a_flight_even_with_labels_a_train_shares(self):
        m = extract.read(mail("<p>Flight BA 9871</p><p>Booking reference: ZK4R9T</p><p>From: JFK</p><p>Departs: 2026-11-21 19:00</p><p>To: LHR</p><p>Arrives: 2026-11-22 07:10</p>"))
        self.assertEqual([b.kind for b in m.bookings], ["flight"])

    def test_nothing_readable_leaves_the_reason(self):
        m = extract.read(mail("<p>Train</p><p>From: Zurich HB</p><p>To: Milan Centrale</p><p>Departure: 21.11.2026</p>"))
        self.assertEqual(m.bookings, ())
        self.assertIn("generic reader: no departure and arrival date and time found", m.gaps)
