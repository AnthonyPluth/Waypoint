import base64
import unittest
from pathlib import Path

from tests.privacy import no_leaks
from tests.test_mail_scan import ScanCase
from waypoint.domain.mail import buttons, extract

SPOTHERO = Path(__file__).parent / "fixtures" / "mail" / "spothero" / "booking.eml"
CANARY = "CANARY-BODY-BUTTON-LINK-8N5V"
URL = "https://example.test/manage/ABC123"


def anchor(text: str, href: str = URL) -> str:
    return f'<p>Hello</p><a href="{href}">{text}</a>'


def read(data: bytes) -> extract.Message:
    return extract.read({"id": "m1", "raw": base64.urlsafe_b64encode(data).decode().rstrip("=")})


def mail(body: str, sender: str = "Vendor <hello@vendor.example>") -> bytes:
    return (f"From: {sender}\nSubject: x\nDate: Mon, 01 Mar 2027 10:00:00 -0600\nMIME-Version: 1.0\n"
            f"Content-Type: text/html; charset=utf-8\n\n<html><body>{body}</body></html>").encode()


def jsonld(code: str, link: str | None = None) -> str:
    extra = f',"modifyReservationUrl":"{link}"' if link else ""
    return ('<script type="application/ld+json">{"@type":"FlightReservation","reservationNumber":"' + code + '"' + extra
            + ',"reservationFor":{"@type":"Flight","flightNumber":"WN 5","airline":{"iataCode":"WN","name":"Southwest Airlines"},'
            '"departureAirport":{"iataCode":"DAL"},"departureTime":"2027-03-05T08:05:00",'
            '"arrivalAirport":{"iataCode":"HOU"},"arrivalTime":"2027-03-05T09:10:00"}}</script>')


class ButtonTests(unittest.TestCase):
    def test_a_button_to_manage_or_view_the_booking_is_found(self):
        for text in ("Manage Booking", "View your reservation", "View Parking Pass", "Change or cancel your trip", "Modify reservation",
                     "See itinerary", "Go to my booking"):
            with self.subTest(text=text):
                self.assertEqual(buttons.manage_link([anchor(text)]), URL)

    def test_a_button_that_is_a_picture_is_read_by_its_alt_text(self):
        self.assertEqual(buttons.manage_link([f'<a href="{URL}"><img src="https://example.test/b.png" alt="Manage booking"></a>']), URL)

    def test_other_links_in_a_booking_email_are_not_taken_for_it(self):
        for text in ("Unsubscribe", "View in browser", "View your receipt", "Manage your email preferences", "View booking invoice",
                     "Download the app", "Refer a friend", "Privacy policy", "Book again", "View points statement", "Manage your account"):
            with self.subTest(text=text):
                self.assertIsNone(buttons.manage_link([anchor(text)]))

    def test_a_link_that_is_not_a_plain_https_address_is_not_taken(self):
        for href in ("http://example.test/m", "mailto:a@example.test", "javascript:alert(1)", "https://", "#", "", "//example.test/m",
                     "https://example.test/" + "a" * buttons.LIMIT, "https://example.test/unsubscribe?u=1", "https://[", "https://[::1", "https://a]b"):
            with self.subTest(href=href[:40]):
                self.assertIsNone(buttons.manage_link([anchor("Manage booking", href)]))

    def test_the_first_button_wins_and_a_later_message_part_is_tried_when_the_first_has_none(self):
        both = anchor("View reservation", "https://example.test/one") + anchor("Manage booking", "https://example.test/two")
        self.assertEqual(buttons.manage_link([both]), "https://example.test/one")
        self.assertEqual(buttons.manage_link(["<p>none</p>", anchor("Manage booking")]), URL)

    def test_markup_that_cannot_be_parsed_finds_nothing(self):
        self.assertIsNone(buttons.manage_link(["<<<", "<a href=", ""]))
        self.assertIsNone(buttons.manage_link([]))


class ExtractTests(unittest.TestCase):
    def test_a_booking_with_no_link_of_its_own_gets_the_emails_button(self):
        [b] = read(mail(jsonld("K7QW2N") + anchor("Manage booking"))).bookings
        self.assertEqual(b.manage_url, URL)

    def test_the_link_in_the_emails_data_wins_over_the_button(self):
        [b] = read(mail(jsonld("K7QW2N", "https://example.test/data") + anchor("Manage booking"))).bookings
        self.assertEqual(b.manage_url, "https://example.test/data")

    def test_a_vendor_parsed_email_gets_its_button_too(self):
        [b] = read(SPOTHERO.read_bytes()).bookings
        self.assertEqual(b.manage_url, "https://example.test/pass")

    def test_an_email_for_several_reservations_is_given_no_one_link(self):
        body = jsonld("K7QW2N") + jsonld("ZZ9999") + anchor("Manage booking")
        found = read(mail(body)).bookings
        self.assertEqual(sorted({b.confirmation for b in found}), ["K7QW2N", "ZZ9999"])
        self.assertEqual([b.manage_url for b in found], [None, None])

    def test_several_bookings_with_no_code_are_given_no_one_link_but_a_single_one_is(self):
        body = jsonld("").replace('"reservationNumber":"",', "") + anchor("Manage booking")
        [single] = read(mail(body)).bookings
        self.assertEqual((single.confirmation, single.manage_url), (None, URL))
        two = jsonld("").replace('"reservationNumber":"",', "") + jsonld("").replace('"reservationNumber":"",', "").replace("WN 5", "WN 6") + anchor("Manage booking")
        found = read(mail(two)).bookings
        self.assertEqual([(b.confirmation, b.manage_url) for b in found], [(None, None), (None, None)])

    def test_a_message_with_a_malformed_button_address_is_still_read(self):
        [b] = read(mail(jsonld("K7QW2N") + anchor("Manage booking", "https://["))).bookings
        self.assertEqual((b.confirmation, b.manage_url), ("K7QW2N", None))

    def test_an_email_without_a_button_leaves_the_link_empty(self):
        [b] = read(mail(jsonld("K7QW2N") + anchor("Unsubscribe"))).bookings
        self.assertIsNone(b.manage_url)


class ScanTests(ScanCase):
    def test_the_button_becomes_the_bookings_open_link(self):
        state = b"1 Example Avenue, Austin, TX 78701"
        self.add_mail("spot", SPOTHERO.read_bytes().replace(b"1 Example Avenue", state).replace(b"Happy Parking!", b"Happy Parking! " + CANARY.encode()))
        with no_leaks(self, CANARY, database=self.path):
            self.scan()
        [s] = self.segments()
        self.assertEqual((s["manage_url"], s["links"]["app"]), ("https://example.test/pass", "https://example.test/pass"))


if __name__ == "__main__":
    unittest.main()
