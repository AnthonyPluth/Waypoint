import base64
import unittest
from pathlib import Path
from unittest import mock

from tests.privacy import no_leaks
from waypoint.domain.mail import cars, extract

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
CANARIES = ("CANARY-BODY-CAR-EN-3K7M", "CANARY-BODY-CAR-DE-8H2Q", "CANARY-BODY-CAR-ORDER-5Y1C")


def read(body: str):
    parsed, why = cars.read(f"<html><body>{body}</body></html>", "")
    return parsed, why


def mail(body: str, sender: str = "Roadside Rentals <reservations@roadside-rentals.example>") -> dict:
    raw = (f"From: {sender}\nSubject: Your reservation\nDate: Mon, 12 Oct 2026 09:30:00 -0400\nMIME-Version: 1.0\n"
           f"Content-Type: text/html; charset=utf-8\n\n<html><body>{body}</body></html>").encode()
    return {"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


LABELLED = ("<p>Your rental car is booked.</p><p>Confirmation number: 7733-AB</p><p>Rental company: Example Rentals</p><p>Car type: Compact</p>"
            "<p>Pick-up location: San Francisco Airport (SFO)</p><p>Pick-up date: Dec 8, 2026</p><p>Pick-up time: 12:00 PM</p>"
            "<p>Drop-off location: Los Angeles Airport (LAX)</p><p>Drop-off date: Dec 10, 2026</p><p>Drop-off time: 3:00 PM</p>")


class CarReaderTests(unittest.TestCase):
    def test_labelled_lines_give_a_rental_at_its_places_wall_clock_times(self):
        with no_leaks(self, *CANARIES):
            parsed, why = read(LABELLED + "<p>CANARY-BODY-CAR-EN-3K7M</p>")
        self.assertIsNone(why)
        [b] = parsed.bookings
        self.assertEqual((b.kind, b.status, b.confirmation, b.provider, b.origin, b.destination, b.start, b.end),
                         ("car", "confirmed", "7733-AB", "Example Rentals", "San Francisco Airport (SFO)", "Los Angeles Airport (LAX)",
                          "2026-12-08T12:00", "2026-12-10T15:00"))
        self.assertEqual((b.start_zone, b.end_zone, dict(b.details)), ("America/Los_Angeles", "America/Los_Angeles", {"car_class": "Compact"}))
        self.assertEqual(dict(b.generic), {"origin": "pick-up location", "destination": "drop-off location", "start_local": "pick-up date",
                                           "end_local": "drop-off date", "confirmation": "confirmation number", "provider": "rental company"})

    def test_a_one_way_rental_keeps_each_ends_zone_and_clock(self):
        [b] = read("<p>Car rental</p><p>Pick-up: Denver International Airport (DEN), Dec 5, 2026 10:30 AM</p>"
                   "<p>Drop-off: Seattle-Tacoma International Airport (SEA), Dec 9, 2026 4:00 PM</p>")[0].bookings
        self.assertEqual((b.start, b.end, b.start_zone, b.end_zone), ("2026-12-05T10:30", "2026-12-09T16:00", "America/Denver", "America/Los_Angeles"))

    def test_a_two_column_table_with_a_header_row(self):
        [b] = read("<p>Car rental</p><table><tr><th>Pick-up</th><th>Drop-off</th></tr>"
                   "<tr><td>SFO Dec 8, 2026 12:00 PM</td><td>LAX Dec 10, 2026 3:00 PM</td></tr></table>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start, b.end, dict(b.generic)["origin"]), ("SFO", "LAX", "2026-12-08T12:00", "2026-12-10T15:00", "pick-up"))

    def test_a_row_per_field_in_a_table_with_the_value_in_the_next_cell(self):
        [b] = read("<p>Car rental</p><table><tr><td>Pick-up location</td><td>SFO</td></tr><tr><td>Pick-up date and time</td><td>2026-12-08 12:00</td></tr>"
                   "<tr><td>Drop-off location</td><td>LAX</td></tr><tr><td>Drop-off date and time</td><td>2026-12-10 15:00</td></tr></table>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start, b.end), ("SFO", "LAX", "2026-12-08T12:00", "2026-12-10T15:00"))

    def test_a_value_on_the_line_after_its_label(self):
        [b] = read("<p>Car rental</p><p>Pick-up location</p><p>SFO</p><p>Pick-up date and time</p><p>2026-12-08 12:00</p>"
                   "<p>Drop-off location</p><p>LAX</p><p>Drop-off date and time</p><p>2026-12-10 15:00</p>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start), ("SFO", "LAX", "2026-12-08T12:00"))

    def test_the_time_on_the_line_after_the_date(self):
        [b] = read("<p>Car rental</p><p>Pick-up: SFO, Dec 8, 2026</p><p>12:00 PM</p><p>Drop-off: SFO, Dec 10, 2026</p><p>3:00 PM</p>")[0].bookings
        self.assertEqual((b.start, b.end), ("2026-12-08T12:00", "2026-12-10T15:00"))

    def test_one_place_for_both_ends(self):
        for body in ("<p>Pick-up location: SFO</p><p>Drop-off location: Same as pick-up</p>",
                     "<p>Pick-up and return location: SFO</p>", "<p>Rental location: SFO</p>"):
            with self.subTest(body):
                [b] = read("<p>Car rental</p>" + body + "<p>Pick-up date: Dec 8, 2026</p><p>Drop-off date: Dec 10, 2026</p>")[0].bookings
                self.assertEqual((b.origin, b.destination), ("SFO", "SFO"))

    def test_a_rental_without_times_takes_noon_and_says_so(self):
        [b] = read("<p>Car rental</p><p>Pick-up location: SFO</p><p>Pick-up date: Dec 8, 2026</p><p>Drop-off location: SFO</p><p>Drop-off date: Dec 10, 2026</p>")[0].bookings
        self.assertEqual((b.start, b.end, dict(b.details)), ("2026-12-08T12:00", "2026-12-10T12:00", {"time_unknown": "yes"}))

    def test_bilingual_labels_in_one_message(self):
        [b] = read("<p>Mietwagen</p><p>Abholort / Pick-up location: MUC</p><p>Abholdatum / Pick-up date: 05.12.2026 10:30</p>"
                   "<p>Rückgabeort / Drop-off location: MUC</p><p>Rückgabedatum / Drop-off date: 09.12.2026 16:00</p>")[0].bookings
        self.assertEqual((b.origin, b.start, b.end), ("MUC", "2026-12-05T10:30", "2026-12-09T16:00"))

    def test_french_german_spanish_and_japanese_labels(self):
        for body, expected in (
            ("<p>Location de voiture</p><p>Numéro de réservation : FR12345</p><p>Loueur : Exemple Location</p><p>Lieu de prise en charge : Paris Charles de Gaulle (CDG)</p>"
             "<p>Date et heure de prise en charge : 5 décembre 2026 à 10h30</p><p>Lieu de restitution : Paris Charles de Gaulle (CDG)</p>"
             "<p>Date et heure de restitution : 9 décembre 2026 à 16h00</p>",
             ("FR12345", "Exemple Location", "2026-12-05T10:30", "2026-12-09T16:00", "Europe/Paris")),
            ("<p>Mietwagen</p><p>Buchungsnummer: DE12345</p><p>Autovermietung: Beispiel Miete</p><p>Abholort: Flughafen Frankfurt (FRA)</p>"
             "<p>Abholdatum: 05.12.2026</p><p>Abholzeit: 10:30</p><p>Rückgabeort: Flughafen Frankfurt (FRA)</p><p>Rückgabedatum: 09.12.2026</p><p>Rückgabezeit: 16:00</p>",
             ("DE12345", "Beispiel Miete", "2026-12-05T10:30", "2026-12-09T16:00", "Europe/Berlin")),
            ("<p>Coche de alquiler</p><p>Código de reserva: ES12345</p><p>Empresa de alquiler: Ejemplo Alquiler</p><p>Lugar de recogida: Madrid Barajas (MAD)</p>"
             "<p>Fecha y hora de recogida: 5 de diciembre de 2026 10:30</p><p>Lugar de devolución: Madrid Barajas (MAD)</p>"
             "<p>Fecha y hora de devolución: 9 de diciembre de 2026 16:00</p>",
             ("ES12345", "Ejemplo Alquiler", "2026-12-05T10:30", "2026-12-09T16:00", "Europe/Madrid")),
            ("<p>レンタカー</p><p>予約番号: JP12345</p><p>レンタカー会社: テストレンタカー</p><p>受取場所: 成田空港 (NRT)</p><p>受取日時: 2026年12月5日 10:30</p>"
             "<p>返却場所: 成田空港 (NRT)</p><p>返却日時: 2026年12月9日 16時00分</p>",
             ("JP12345", "テストレンタカー", "2026-12-05T10:30", "2026-12-09T16:00", "Asia/Tokyo")),
        ):
            with self.subTest(expected[0]):
                [b] = read(body)[0].bookings
                self.assertEqual((b.confirmation, b.provider, b.start, b.end, b.start_zone), expected)

    def test_dates_in_cancellation_and_policy_text_are_ignored(self):
        [b] = read("<p>Booked on Oct 10, 2026 10:00 AM</p><p>Free cancellation until Dec 1, 2026 6:00 PM</p>" + LABELLED
                   + "<p>Late return fees apply from Dec 10, 2026 3:15 PM</p><p>Return policy: vehicles returned after Dec 11, 2026 are charged a full day</p>")[0].bookings
        self.assertEqual((b.start, b.end), ("2026-12-08T12:00", "2026-12-10T15:00"))

    def test_what_cannot_be_read_gets_a_reason_and_no_booking(self):
        base = "<p>Car rental</p>"
        pick = "<p>Pick-up location: SFO</p><p>Pick-up date: Dec 8, 2026</p>"
        drop = "<p>Drop-off location: SFO</p><p>Drop-off date: Dec 10, 2026</p>"
        for body, why in (
            (base + "<p>Pick-up date: Dec 8, 2026</p>" + drop, "no pick-up location found"),
            (base + pick + "<p>Drop-off date: Dec 10, 2026</p>", "no drop-off location found"),
            (base + "<p>Pick-up location: SFO</p>" + drop, "no pick-up date found"),
            (base + pick + "<p>Drop-off location: SFO</p>", "no drop-off date found"),
            (base + "<p>Pick-up location: Somewhere Plaza</p><p>Pick-up date: Dec 8, 2026</p>" + drop, "pick-up location's time zone unknown"),
            (base + pick + "<p>Drop-off location: Somewhere Plaza</p><p>Drop-off date: Dec 10, 2026</p>", "drop-off location's time zone unknown"),
            (base + pick + "<p>Drop-off location: SFO</p><p>Drop-off date: Dec 7, 2026</p>", "drop-off isn't after pick-up"),
            (base + pick + "<p>Drop-off location: SFO</p><p>Drop-off date: Dec 8, 2026</p>", "drop-off isn't after pick-up"),
            (base + pick + "<p>Drop-off location: SFO</p><p>Drop-off date: Mar 9, 2027</p>", "rental is longer than 90 days"),
            (base + pick + "<p>Drop-off location: SFO</p><p>Drop-off date: Feb 31, 2026</p>", "no drop-off date found"),
        ):
            with self.subTest(why, body=body[-60:]):
                parsed, found = read(body)
                self.assertEqual((parsed.bookings, found), ((), why))

    def test_mail_that_is_not_a_rental_is_not_read_as_one(self):
        for body in ("<p>Hello, your newsletter</p>", "<p>Pick-up location: SFO</p><p>Pick-up date: Dec 8, 2026</p>",
                     "<p>Your car rental is booked</p><p>Have a nice trip</p>"):
            with self.subTest(body):
                self.assertEqual(read(body), (cars.Parsed(), ""))

    def test_a_confirmation_that_is_only_a_word_is_not_a_code(self):
        [b] = read(LABELLED.replace("Confirmation number: 7733-AB", "Confirmation number: confirmed"))[0].bookings
        self.assertIsNone(b.confirmation)

    def test_a_long_company_name_is_cut_to_what_a_booking_holds(self):
        [b] = read(LABELLED.replace("Example Rentals", "R" * 150))[0].bookings
        self.assertEqual(len(b.provider or ""), 100)


class CarOrderTests(unittest.TestCase):
    def test_the_fixtures_are_read(self):
        for name, expected in (("car_generic_en", ("RR55821", "Roadside Rentals", "2026-12-05T10:30", "2026-12-09T16:00", "America/Denver", "America/Los_Angeles")),
                               ("car_generic_de", ("MW90417", "Beispiel Mietwagen", "2026-12-05T10:30", "2026-12-09T16:00", "Europe/Berlin", "Europe/Berlin"))):
            with self.subTest(name), no_leaks(self, *CANARIES):
                raw = (FIXTURES / f"{name}.eml").read_bytes()
                m = extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")})
                [b] = m.bookings
                self.assertEqual((b.confirmation, b.provider, b.start, b.end, b.start_zone, b.end_zone), expected)
                self.assertTrue(m.markup and b.generic)

    def test_markup_beats_the_generic_reader(self):
        raw = (FIXTURES / "car_jsonld.eml").read_bytes().replace(b"</body>", LABELLED.replace("7733-AB", "ZZ9999").encode() + b"</body>")
        [b] = extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}).bookings
        self.assertEqual((b.confirmation, b.generic), ("7733-AB", ()))

    def test_a_reader_that_fails_is_reported_without_its_text_and_the_next_one_still_runs(self):
        boom = mock.Mock(side_effect=ValueError("CANARY-BODY-CAR-ORDER-5Y1C"))
        with mock.patch.object(extract, "GENERIC_READERS", (boom, cars.read)), no_leaks(self, *CANARIES):
            m = extract.read(mail(LABELLED + "<p>CANARY-BODY-CAR-ORDER-5Y1C</p>"))
        self.assertEqual([b.kind for b in m.bookings], ["car"])

    def test_nothing_readable_leaves_the_reason(self):
        m = extract.read(mail("<p>Car rental</p><p>Pick-up location: SFO</p><p>Pick-up date: Dec 8, 2026</p>"))
        self.assertEqual(m.bookings, ())
        self.assertIn("generic reader: no drop-off location found", m.gaps)

    def test_a_complete_rental_beats_an_incomplete_train_and_is_the_one_filed(self):
        m = extract.read(mail(LABELLED + "<p>Train: 1</p><p>From: Zurich HB</p><p>Departure: 21.11.2026 09:02</p>"))
        self.assertEqual(([b.kind for b in m.bookings], m.unread), (["car"], 0))

    def test_a_rental_and_a_complete_train_in_one_message_file_the_rental_and_count_the_train(self):
        train = "<p>Train: 1</p><p>From: Zurich HB</p><p>Departure: 21.11.2026 09:02</p><p>To: Milan Centrale</p><p>Arrival: 21.11.2026 12:25</p>"
        m = extract.read(mail(LABELLED + train))
        self.assertEqual(([b.kind for b in m.bookings], m.unread), (["car"], 1))
