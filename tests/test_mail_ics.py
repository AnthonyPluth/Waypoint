import base64
import email
import email.message
import email.policy
import unittest
from pathlib import Path

from tests.privacy import no_leaks
from tests.test_mail_generic_kinds_scan import GenericKindCase
from tests.test_mail_scan import NOW
from waypoint.domain.mail import extract, ics

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
CANARIES = ("CANARY-BODY-ICS-6F3K", "CANARY-ICS-NOTE-9M2T", "CANARY-SENDER-ICS-4X8B")


def calendar(*events: str) -> str:
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Invented//EN", *events, "END:VCALENDAR"]) + "\r\n"


def event(summary: str, start: str, end: str, location: str = "", description: str = "", uid: str = "u1@invented.example") -> str:
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{summary}", start, end]
    if location:
        lines.append(f"LOCATION:{location}")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    return "\r\n".join([*lines, "END:VEVENT"])


FLIGHT = event("Skyline Air BA 9871 JFK to LHR", "DTSTART;TZID=America/New_York:20261121T190000", "DTEND;TZID=Europe/London:20261122T071000",
               description="Booking reference: ZK4R9T\\nCANARY-ICS-NOTE-9M2T")
HOTEL = event("Hotel Aurora", "DTSTART;TZID=America/Denver:20261208T150000", "DTEND;TZID=America/Denver:20261210T110000",
              location="12 Main Street\\, Denver\\, CO", description="Reservation number: HA55120")
RENTAL = event("Car rental - Roadside Rentals", "DTSTART;TZID=America/Denver:20261205T103000", "DTEND;TZID=America/Denver:20261209T160000",
               location="Denver International Airport (DEN)", description="Confirmation number: RR55821")
TRAIN = event("Train: Paris Gare de Lyon to Lyon Part-Dieu", "DTSTART;TZID=Europe/Paris:20261121T091200", "DTEND;TZID=Europe/Paris:20261121T111400",
              description="Booking number: RX90412")
CRUISE = event("Blue Horizon Cruise on the Voyager", "DTSTART;TZID=America/Chicago:20261121T160000", "DTEND;TZID=America/Chicago:20261128T080000",
               location="Galveston, TX")
LUNCH = event("Lunch with Sam", "DTSTART;TZID=America/Denver:20261208T120000", "DTEND;TZID=America/Denver:20261208T130000", location="Cafe Rosa")
FLIGHT_LD = ('{"@type":"FlightReservation","reservationNumber":"ABC123","underName":{"name":"Jane Doe"},'
             '"reservationFor":{"@type":"Flight","flightNumber":"EX 7","airline":{"iataCode":"EX","name":"Example Air"},'
             '"departureAirport":{"iataCode":"jfk"},"departureTime":"2026-11-20T19:00:00-05:00",'
             '"arrivalAirport":{"iataCode":"LHR"},"arrivalTime":"2026-11-21T07:10:00Z"}}')
BODY = "<html><body><p>CANARY-BODY-ICS-6F3K Your trip is attached.</p></body></html>"
GENERIC_CAR = ("<html><body><p>Car rental</p><p>Pick-up location: SFO</p><p>Pick-up date: Dec 8, 2026 12:00 PM</p>"
               "<p>Drop-off location: LAX</p><p>Drop-off date: Dec 10, 2026 3:00 PM</p></body></html>")
NO_ZONE = FLIGHT.replace(";TZID=America/New_York", "").replace(";TZID=Europe/London", "")


def mime(html: str, *calendars: str, sender: str = "Skyline Air <reservations@skyline-air.example>") -> bytes:
    msg = email.message.EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Date"] = sender, "traveller@gmail.example", "Your trip", "Wed, 14 Oct 2026 12:00:00 +0100"
    msg.set_content(html, subtype="html")
    for i, text in enumerate(calendars):
        msg.add_attachment(text.encode(), maintype="text", subtype="calendar", filename=f"trip{i}.ics")
    return msg.as_bytes()


def read(raw: bytes) -> extract.Message:
    return extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")})


class CalendarReaderTests(unittest.TestCase):
    def one(self, *events: str) -> extract.Booking:
        with no_leaks(self, *CANARIES):
            found = read(mime(BODY, calendar(*events)))
        [b] = found.bookings
        self.assertTrue(found.markup)
        return b

    def test_a_flight_event_is_a_flight_at_the_events_own_zones(self):
        b = self.one(FLIGHT)
        self.assertEqual((b.kind, b.confirmation, b.origin, b.destination, b.start, b.end),
                         ("flight", "ZK4R9T", "JFK", "LHR", "2026-11-21T19:00", "2026-11-22T07:10"))
        self.assertEqual((b.start_zone, b.end_zone, dict(b.details)), ("America/New_York", "Europe/London", {"flight_number": "BA 9871"}))
        self.assertTrue(b.generic)

    def test_a_hotel_event_is_a_stay_with_its_address(self):
        b = self.one(HOTEL)
        self.assertEqual((b.kind, b.confirmation, b.origin, b.start, b.end, b.start_zone, dict(b.details)),
                         ("hotel", "HA55120", "Hotel Aurora", "2026-12-08T15:00", "2026-12-10T11:00", "America/Denver",
                          {"address": "12 Main Street, Denver, CO"}))

    def test_an_all_day_hotel_event_takes_check_in_and_check_out_times_and_says_so(self):
        b = self.one(event("Hotel Aurora", "DTSTART;VALUE=DATE:20261208", "DTEND;VALUE=DATE:20261210", location="Denver International Airport (DEN)"))
        self.assertEqual((b.start, b.end, dict(b.details)["time_unknown"], b.start_zone), ("2026-12-08T15:00", "2026-12-10T11:00", "yes", "America/Denver"))

    def test_a_rental_event_is_a_rental_at_one_place(self):
        b = self.one(RENTAL)
        self.assertEqual((b.kind, b.confirmation, b.origin, b.destination, b.start, b.end, b.start_zone),
                         ("car", "RR55821", "Denver International Airport (DEN)", "Denver International Airport (DEN)", "2026-12-05T10:30",
                          "2026-12-09T16:00", "America/Denver"))

    def test_a_train_event_splits_its_route(self):
        b = self.one(TRAIN)
        self.assertEqual((b.kind, b.confirmation, b.origin, b.destination, b.start, b.end, b.start_zone),
                         ("train", "RX90412", "Paris Gare de Lyon", "Lyon Part-Dieu", "2026-11-21T09:12", "2026-11-21T11:14", "Europe/Paris"))

    def test_a_cruise_event_is_a_cruise_from_and_to_its_port(self):
        b = self.one(CRUISE)
        self.assertEqual((b.kind, b.origin, b.destination, b.start, b.end, b.start_zone, dict(b.details)),
                         ("cruise", "Galveston, TX", "Galveston, TX", "2026-11-21T16:00", "2026-11-28T08:00", "America/Chicago",
                          {"ship": "Blue Horizon Cruise on the Voyager"}))

    def test_an_event_naming_no_kind_is_ignored(self):
        found = read(mime(BODY, calendar(LUNCH)))
        self.assertEqual((found.bookings, found.unread, found.markup, found.gaps), ((), 0, False, ()))

    def test_only_the_events_that_name_a_kind_become_bookings(self):
        found = read(mime(BODY, calendar(LUNCH.replace("u1@", "u2@"), HOTEL, LUNCH.replace("u1@", "u3@"))))
        self.assertEqual([b.kind for b in found.bookings], ["hotel"])

    def test_the_same_event_twice_is_one_booking(self):
        self.assertEqual(len(read(mime(BODY, calendar(HOTEL, HOTEL), calendar(HOTEL))).bookings), 1)

    def test_several_events_give_several_bookings(self):
        other = event("Hotel Orion", "DTSTART;TZID=Europe/London:20261122T150000", "DTEND;TZID=Europe/London:20261125T110000", uid="u9")
        self.assertEqual([b.kind for b in read(mime(BODY, calendar(FLIGHT, other))).bookings], ["flight", "hotel"])

    def test_folded_lines_are_joined(self):
        folded = FLIGHT.replace("SUMMARY:Skyline Air BA 9871 JFK", "SUMMARY:Skyline Air BA 98\r\n 71 JFK")
        self.assertEqual(dict(self.one(folded).details)["flight_number"], "BA 9871")

    def test_a_malformed_attachment_is_skipped_and_the_message_is_still_read(self):
        for junk in ("not a calendar at all", "BEGIN:VEVENT\r\nDTSTART:garbage\r\nSUMMARY:Hotel X\r\n", "\x00\x01BEGIN:VEVENT\r\nEND:VEVENT"):
            with self.subTest(junk):
                self.assertEqual([b.kind for b in read(mime(GENERIC_CAR, junk)).bookings], ["car"])

    def test_a_malformed_attachment_alone_gives_no_booking(self):
        found = read(mime(BODY, "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Hotel X\r\nDTSTART:garbage\r\nEND:VEVENT\r\nEND:VCALENDAR"))
        self.assertEqual((found.bookings, found.broken), ((), False))

    def test_an_event_that_cant_be_completed_gives_a_reason_and_no_booking(self):
        cases = {
            "event has no time zone": NO_ZONE,
            "event ends before it starts": FLIGHT.replace("20261122T071000", "20261121T101000"),
            "event has no start and end time": FLIGHT.replace("DTSTART;TZID=America/New_York:20261121T190000", "DTSTART;VALUE=DATE:20261121"),
            "no departure and arrival station found": TRAIN.replace("Paris Gare de Lyon to Lyon Part-Dieu", "Paris Gare de Lyon"),
            "event has no location": CRUISE.replace("LOCATION:Galveston, TX\r\n", ""),
        }
        for why, text in cases.items():
            with self.subTest(why):
                parsed, reason = ics.read([calendar(text)])
                self.assertEqual((parsed.bookings, reason), ((), why))

    def test_an_unknown_zone_gives_no_booking(self):
        parsed, reason = ics.read([calendar(FLIGHT.replace("America/New_York", "Mars/Olympus"))])
        self.assertEqual(parsed.bookings, ())
        self.assertTrue(reason)

    def test_the_attachment_is_not_part_of_what_is_read_for_keeping(self):
        self.assertNotIn("CANARY-ICS-NOTE-9M2T", repr(read(mime(BODY, calendar(FLIGHT)))))


class ReaderOrderTests(unittest.TestCase):
    def test_markup_beats_a_calendar_attachment(self):
        raw = mime(f'<html><head><script type="application/ld+json">{FLIGHT_LD}</script></head><body>x</body></html>', calendar(HOTEL))
        [b] = read(raw).bookings
        self.assertEqual((b.kind, b.confirmation), ("flight", "ABC123"))

    def test_a_vendor_parser_beats_a_calendar_attachment(self):
        base = email.message_from_bytes((FIXTURES / "southwest" / "booking.eml").read_bytes(), policy=email.policy.default)
        base.add_attachment(calendar(HOTEL).encode(), maintype="text", subtype="calendar", filename="trip.ics")
        found = read(base.as_bytes())
        self.assertEqual({b.kind for b in found.bookings}, {"flight"})
        self.assertEqual(found.bookings[0].confirmation, "K7QW2N")

    def test_a_calendar_attachment_beats_a_generic_reader(self):
        self.assertEqual([b.kind for b in read(mime(GENERIC_CAR, calendar(HOTEL))).bookings], ["hotel"])

    def test_a_generic_reader_runs_when_the_calendar_gives_nothing(self):
        self.assertEqual([b.kind for b in read(mime(GENERIC_CAR, calendar(LUNCH))).bookings], ["car"])

    def test_a_partial_calendar_event_never_replaces_a_complete_generic_booking(self):
        found = read(mime(GENERIC_CAR, calendar(NO_ZONE)))
        self.assertEqual([(b.kind, b.origin) for b in found.bookings], [("car", "SFO")])

    def test_a_complete_calendar_booking_stands_when_the_body_is_partial(self):
        found = read(mime("<html><body><p>Car rental</p><p>Pick-up location: SFO</p></body></html>", calendar(RENTAL)))
        self.assertEqual([(b.kind, b.origin) for b in found.bookings], [("car", "Denver International Airport (DEN)")])
        self.assertEqual(found.unread, 0)


class CalendarScanTests(GenericKindCase):
    CANARIES = CANARIES
    DOMAIN = "skyline-air.example"

    def first(self) -> bytes:
        return mime(BODY, calendar(FLIGHT), sender="CANARY-SENDER-ICS-4X8B Air <reservations@skyline-air.example>")

    def second(self) -> bytes:
        later = FLIGHT.replace("20261121T190000", "20261201T190000").replace("20261122T071000", "20261202T071000").replace("ZK4R9T", "ZK0000")
        return mime(BODY, calendar(later))

    def test_a_calendar_flight_from_a_new_sender_is_a_suggestion_with_its_read_fields_outlined(self):
        s = self.suggestion(self.first())["suggestions"][0]
        self.assertEqual((s["kind"], s["confirmation"], s["origin"], s["destination"], s["start_local"], s["end_local"], s["start_zone"]),
                         ("flight", "ZK4R9T", "JFK", "LHR", "2026-11-21T19:00", "2026-11-22T07:10", "America/New_York"))
        self.assertEqual(s["sources"]["start_local"], "DTSTART")

    def test_it_asks_once_per_sender_until_confirmed(self):
        self.suggestion(self.first())
        self.add_mail("second", self.second())
        self.scan(now=NOW + 30)
        self.assertEqual(len(self.items()), 1)

    def test_confirming_trusts_the_sender_and_later_calendar_mail_is_filed_directly(self):
        item = self.suggestion(self.first())
        self.confirm(item, kind="flight", confirmation="ZK4R9T", provider="British Airways", start_local="2026-11-21T19:00", start_zone="America/New_York",
                     end_local="2026-11-22T07:10", end_zone="Europe/London", origin="JFK", destination="LHR", details={"flight_number": "BA 9871"})
        self.add_mail("second", self.second())
        with no_leaks(self, *CANARIES, database=self.path):
            result = self.scan(now=NOW + 60)
        self.assertEqual((result.bookings, result.review), (1, 0))
        later = next(s for s in self.segments() if s["confirmation"] == "ZK0000")
        self.assertEqual((later["start_local"], later["start_zone"], later["end_local"], later["end_zone"]),
                         ("2026-12-01T19:00", "America/New_York", "2026-12-02T07:10", "Europe/London"))
