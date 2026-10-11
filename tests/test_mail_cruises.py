import base64
import unittest
from pathlib import Path
from unittest import mock

from tests.privacy import no_leaks
from waypoint.domain.mail import cruises, extract

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
CANARIES = ("CANARY-BODY-CRUISE-EN-2V8S", "CANARY-BODY-CRUISE-ES-7K3W", "CANARY-BODY-CRUISE-ORDER-4M9H")


def read(body: str):
    parsed, why = cruises.read(f"<html><body>{body}</body></html>", "")
    return parsed, why


def mail(body: str, sender: str = "Blue Horizon Cruises <bookings@blue-horizon.example>") -> dict:
    raw = (f"From: {sender}\nSubject: Your cruise\nDate: Mon, 12 Oct 2026 09:30:00 -0500\nMIME-Version: 1.0\n"
           f"Content-Type: text/html; charset=utf-8\n\n<html><body>{body}</body></html>").encode()
    return {"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


LABELLED = ("<p>Your cruise is booked.</p><p>Booking number: BH772013</p><p>Cruise line: Blue Horizon Cruises</p><p>Ship: Blue Horizon Voyager</p>"
            "<p>Embarkation port: Southampton</p><p>Embarkation date: Nov 21, 2026 4:00 PM</p>"
            "<p>Disembarkation port: Southampton</p><p>Disembarkation date: Nov 28, 2026 8:00 AM</p>")


class CruiseReaderTests(unittest.TestCase):
    def test_labelled_lines_give_a_cruise_at_its_ports_wall_clock_times(self):
        with no_leaks(self, *CANARIES):
            parsed, why = read(LABELLED + "<p>CANARY-BODY-CRUISE-EN-2V8S</p>")
        self.assertIsNone(why)
        [b] = parsed.bookings
        self.assertEqual((b.kind, b.status, b.confirmation, b.provider, b.origin, b.destination, b.start, b.end),
                         ("cruise", "confirmed", "BH772013", "Blue Horizon Cruises", "Southampton", "Southampton", "2026-11-21T16:00", "2026-11-28T08:00"))
        self.assertEqual((b.start_zone, b.end_zone, dict(b.details), b.ports), ("Europe/London", "Europe/London", {"ship": "Blue Horizon Voyager"}, ()))
        self.assertEqual(dict(b.generic), {"origin": "embarkation port", "destination": "disembarkation port", "start_local": "embarkation date",
                                           "end_local": "disembarkation date", "confirmation": "booking number", "provider": "cruise line"})

    def test_a_cruise_between_two_ports_keeps_each_ports_zone(self):
        [b] = read("<p>Cruise</p><p>Ship: Blue Horizon Voyager</p><p>Embarkation: Galveston, TX, Nov 21, 2026</p><p>Disembarkation: Vancouver, Nov 28, 2026</p>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start_zone, b.end_zone), ("Galveston, TX", "Vancouver", "America/Chicago", "America/Vancouver"))

    def test_a_row_per_field_in_a_table_and_a_header_row(self):
        [b] = read("<p>Cruise</p><table><tr><td>Ship</td><td>Blue Horizon Voyager</td></tr><tr><th>Embarkation</th><th>Disembarkation</th></tr>"
                   "<tr><td>Southampton, Nov 21, 2026</td><td>Southampton, Nov 28, 2026</td></tr></table>")[0].bookings
        self.assertEqual((b.origin, b.destination, b.start[:10], b.end[:10]), ("Southampton", "Southampton", "2026-11-21", "2026-11-28"))

    def test_the_line_alone_or_the_ship_alone_is_enough(self):
        body = "<p>Cruise</p><p>{}</p><p>Embarkation port: Southampton</p><p>Embarkation date: Nov 21, 2026</p><p>Disembarkation port: Southampton</p><p>Disembarkation date: Nov 28, 2026</p>"
        [by_line] = read(body.format("Cruise line: Blue Horizon"))[0].bookings
        [by_ship] = read(body.format("Ship: Blue Horizon Voyager"))[0].bookings
        self.assertEqual((by_line.provider, dict(by_line.details)), ("Blue Horizon", {"time_unknown": "yes"}))
        self.assertEqual((by_ship.provider, dict(by_ship.details)), (None, {"ship": "Blue Horizon Voyager", "time_unknown": "yes"}))

    def test_a_cruise_with_no_times_takes_noon_and_morning_and_says_so(self):
        [b] = read("<p>Cruise</p><p>Ship: Voyager</p><p>Embarkation port: Southampton</p><p>Embarkation date: Nov 21, 2026</p>"
                   "<p>Disembarkation port: Southampton</p><p>Disembarkation date: Nov 28, 2026</p>")[0].bookings
        self.assertEqual((b.start, b.end, dict(b.details)["time_unknown"]), ("2026-11-21T12:00", "2026-11-28T08:00", "yes"))

    def test_ports_of_call_are_not_read(self):
        [b] = read(LABELLED + "<p>Day 2: Le Havre, arrive 8:00 AM, depart 6:00 PM</p><p>Port: Cozumel</p><p>Arrival: Nov 24, 2026 8:00 AM</p>")[0].bookings
        self.assertEqual((b.origin, b.start, b.end, b.ports), ("Southampton", "2026-11-21T16:00", "2026-11-28T08:00", ()))

    def test_french_german_spanish_and_japanese_labels(self):
        for body, expected in (
            ("<p>Croisière</p><p>Numéro de réservation : FR12345</p><p>Compagnie de croisière : Exemple Croisières</p><p>Port d'embarquement : Southampton</p>"
             "<p>Date d'embarquement : 21 novembre 2026</p><p>Port de débarquement : Southampton</p><p>Date de débarquement : 28 novembre 2026</p>",
             ("FR12345", "Exemple Croisières", "2026-11-21T12:00", "2026-11-28T08:00")),
            ("<p>Kreuzfahrt</p><p>Buchungsnummer: DE12345</p><p>Reederei: Beispiel Reederei</p><p>Einschiffungshafen: Hamburg (HAM)</p>"
             "<p>Einschiffungsdatum: 21.11.2026 16:00 Uhr</p><p>Ausschiffungshafen: Hamburg (HAM)</p><p>Ausschiffungsdatum: 28.11.2026 07:30 Uhr</p>",
             ("DE12345", "Beispiel Reederei", "2026-11-21T16:00", "2026-11-28T07:30")),
            ("<p>Crucero</p><p>Código de reserva: ES12345</p><p>Naviera: Ejemplo Cruceros</p><p>Puerto de embarque: Lisboa (LIS)</p>"
             "<p>Fecha de embarque: 21 de noviembre de 2026</p><p>Puerto de desembarque: Lisboa (LIS)</p><p>Fecha de desembarque: 28 de noviembre de 2026</p>",
             ("ES12345", "Ejemplo Cruceros", "2026-11-21T12:00", "2026-11-28T08:00")),
            ("<p>クルーズ</p><p>予約番号: JP12345</p><p>クルーズ会社: テストクルーズ</p><p>乗船港: 横浜 (HND)</p><p>乗船日時: 2026年11月21日 16:00</p>"
             "<p>下船港: 横浜 (HND)</p><p>下船日時: 2026年11月28日 08時30分</p>", ("JP12345", "テストクルーズ", "2026-11-21T16:00", "2026-11-28T08:30")),
        ):
            with self.subTest(expected[0]):
                [b] = read(body)[0].bookings
                self.assertEqual((b.confirmation, b.provider, b.start, b.end), expected)

    def test_dates_in_cancellation_and_policy_text_are_ignored(self):
        [b] = read("<p>Booked on Oct 10, 2026</p><p>Cancellations after Aug 30, 2026 are charged in full. Final payment due Sep 1, 2026</p>" + LABELLED
                   + "<p>Terms: embarkation closes Nov 21, 2026 2:00 PM</p>")[0].bookings
        self.assertEqual((b.start, b.end), ("2026-11-21T16:00", "2026-11-28T08:00"))

    def test_what_cannot_be_read_gets_a_reason_and_no_booking(self):
        ports = "<p>Embarkation port: Southampton</p><p>Embarkation date: Nov 21, 2026</p><p>Disembarkation port: Southampton</p><p>Disembarkation date: Nov 28, 2026</p>"
        for body, why in (
            ("<p>Cruise</p>" + ports, "no ship or cruise line found"),
            ("<p>Cruise</p><p>Ship: Voyager</p><p>Embarkation date: Nov 21, 2026</p><p>Disembarkation date: Nov 28, 2026</p>", "no embarkation and disembarkation port found"),
            ("<p>Cruise</p><p>Ship: Voyager</p><p>Embarkation port: Southampton</p><p>Disembarkation port: Southampton</p>", "no embarkation and disembarkation date found"),
            ("<p>Cruise</p><p>Ship: Voyager</p>" + ports.replace("Disembarkation port: Southampton", "Disembarkation port: Somewhere Quay"), "port's time zone unknown"),
            ("<p>Cruise</p><p>Ship: Voyager</p>" + ports.replace("Nov 28, 2026", "Nov 21, 2026"), "disembarkation isn't after embarkation"),
            ("<p>Cruise</p><p>Ship: Voyager</p>" + ports.replace("Nov 28, 2026", "Jun 28, 2027"), "cruise is longer than 200 days"),
        ):
            with self.subTest(why):
                parsed, found = read(body)
                self.assertEqual((parsed.bookings, found), ((), why))

    def test_mail_that_is_not_about_a_cruise_is_not_read_as_one(self):
        for body in ("<p>Hello, your newsletter</p>", "<p>Departure port: Southampton</p><p>Departure date: Nov 21, 2026</p>", "<p>Your cruise is booked</p>"):
            with self.subTest(body):
                self.assertEqual(read(body), (cruises.Parsed(), ""))


class CruiseOrderTests(unittest.TestCase):
    def test_the_fixtures_are_read(self):
        for name, expected in (
            ("cruise_generic_en", ("BH772013", "Blue Horizon Cruises", "2026-11-21T16:00", "2026-11-28T08:00", "America/Chicago", "Blue Horizon Voyager")),
            ("cruise_generic_es", ("NE553208", "Naviera Ejemplo", "2026-11-21T12:00", "2026-11-28T08:00", "Europe/Lisbon", "Estrella del Atlántico")),
        ):
            with self.subTest(name), no_leaks(self, *CANARIES):
                raw = (FIXTURES / f"{name}.eml").read_bytes()
                m = extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")})
                [b] = m.bookings
                self.assertEqual((b.confirmation, b.provider, b.start, b.end, b.start_zone, dict(b.details)["ship"]), expected)
                self.assertTrue(m.markup and b.generic)

    def test_a_vendor_parser_beats_the_generic_reader(self):
        raw = (FIXTURES / "disneycruise" / "booking.eml").read_bytes()
        m = extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")})
        self.assertTrue(m.bookings)
        self.assertEqual([b.generic for b in m.bookings], [()] * len(m.bookings))

    def test_a_reader_that_fails_is_reported_without_its_text_and_the_next_one_still_runs(self):
        boom = mock.Mock(side_effect=ValueError("CANARY-BODY-CRUISE-ORDER-4M9H"))
        with mock.patch.object(extract, "GENERIC_READERS", (boom, cruises.read)), no_leaks(self, *CANARIES):
            m = extract.read(mail(LABELLED + "<p>CANARY-BODY-CRUISE-ORDER-4M9H</p>"))
        self.assertEqual([b.kind for b in m.bookings], ["cruise"])

    def test_nothing_readable_leaves_the_reason(self):
        m = extract.read(mail("<p>Cruise</p><p>Ship: Voyager</p><p>Embarkation port: Southampton</p><p>Embarkation date: Nov 21, 2026</p>"))
        self.assertEqual(m.bookings, ())
        self.assertIn("generic reader: no embarkation and disembarkation port found", m.gaps)
