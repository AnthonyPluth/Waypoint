import unittest

from waypoint.domain.mail import triage

PURCHASES = frozenset({"INBOX", "CATEGORY_PURCHASES"})
RESERVATIONS = frozenset({"INBOX", "CATEGORY_RESERVATIONS"})
NONE = frozenset({"INBOX"})


def head(subject, domain, snippet="", labels=NONE, name=""):
    return triage.Head(subject, domain, snippet, labels, name)


SHOPPING = (
    head("Your order confirmation", "megastore.example", "Thanks for shopping. Order number 114-0000001 will ship soon.", PURCHASES, "Megastore"),
    head("Your order has shipped", "parcel-mart.example", "Your shipment is on its way.", PURCHASES),
    head("Your return is confirmed", "megastore.example", "We have received your return and will refund you soon.", PURCHASES),
    head("Refund issued for your return", "bargain-bay.example", "Your refund of 12.00 is on its way.", PURCHASES),
    head("Order #55-1234 confirmed", "blinds-and-more.example", "Your custom blinds order number is 55-1234.", PURCHASES, "Blinds And More"),
    head("Your package is out for delivery", "ups.com", "Tracking number 1Z0000000000000000.", NONE),
    head("Delivered: your package", "carrier.example", "Your package was delivered today.", NONE),
    head("Thanks for your purchase", "gadget-hub.example", "Receipt inside.", PURCHASES),
    head("Your receipt from Corner Cafe", "pay-receipts.example", "Receipt for your payment.", NONE),
    head("Invoice 8841 is ready", "supplies-direct.example", "Invoice for your order.", NONE),
    head("Your order confirmation", "amazon.com", "Order number 111-2222222.", PURCHASES),
    head("Your order of 3 items", "store.shopify.com", "Thank you for your order.", NONE),
    head("Your return label", "walmart.com", "Return window closes soon.", NONE),
    head("Booking confirmed", "selectblinds.com", "Your booking for a measuring visit is confirmed.", NONE),
    head("Your table at Olive Street Kitchen", "tablebook.example", "Table for 4, Friday 7:30 pm.", RESERVATIONS, "TableBook"),
    head("Your delivery slot", "grocer.example", "Pick a slot for Friday.", PURCHASES),
    head("Your order confirmation", "megastore.example", "Order number 114-0000002.", RESERVATIONS),
    head("Appointment", "clinic-booking.example", "Your appointment on Tuesday at 9:00.", RESERVATIONS),
)

CATEGORISED = (
    head("Your reservation is confirmed", "tablebook.example", "Table for 4 at Olive Street Kitchen, Friday 7:30 pm.", RESERVATIONS, "TableBook"),
    head("Appointment confirmed", "clinic-booking.example", "Your appointment is confirmed for Tuesday at 9:00.", RESERVATIONS),
    head("Booking your delivery slot", "grocer.example", "Confirm a slot for your delivery.", PURCHASES),
    head("Tickets confirmed: Saturday concert", "gigs.example", "Your seats for the concert are confirmed.", RESERVATIONS),
    head("予約確認", "salon-booking.example", "ご予約ありがとうございます。", PURCHASES),
)

TRAVEL = (
    head("Your reservation is confirmed", "grand-harbour-group.example", "Check-in Nov 21, check-out Nov 27. Reservation number HX4471.", NONE, "Grand Harbour Hotels"),
    head("Booking confirmation", "stayfinder.example", "Your hotel booking for 3 nights is confirmed.", NONE, "StayFinder"),
    head("Your trip is booked", "card-issuer-travel.example", "Flight itinerary and hotel confirmation inside.", NONE, "Card Travel Center"),
    head("Reservation number 55120", "little-pines-inn.example", "Check-in from 3 pm, check-out by 11 am.", NONE, "Little Pines Inn"),
    head("Your reservation at Little Pines Inn", "little-pines-inn.example", "Your reservation number is 55120 at our inn.", NONE),
    head("ご予約確認", "onsen-stay.example", "ご宿泊のご予約ありがとうございます。チェックイン 15:00", NONE),
    head("宿泊のご予約を承りました", "ryokan-example.example", "ご予約番号 12345", NONE),
    head("Online check-in is open for your cruise", "sea-voyages.example", "Check in for your sailing on Saturday.", NONE, "Sea Voyages Cruise Line"),
    head("Your e-ticket receipt", "delta.com", "Receipt for your e-ticket.", NONE),
    head("Your receipt", "grand-harbour-group.example", "Invoice for your stay is attached.", NONE, "Grand Harbour Hotels"),
    head("Invoice for your trip", "united.com", "Order number and tracking for your itinerary.", NONE),
    head("Reservation modified", "harbour-stays.example", "We have received your request to change the dates", NONE),
    head("Your booking has been changed", "stayfinder.example", "Your hotel booking was changed as requested.", NONE),
    head("Your boarding pass", "skyline-airways.example", "Flight 410 boards at 7:15 am.", NONE, "Skyline Airways"),
    head("Rental car confirmation", "wheels-hire.example", "Your rental car is reserved. Pick-up date Nov 21.", NONE),
    head("Train tickets confirmed", "rail-booker.example", "Your train leaves at 9:05.", NONE),
    head("Order your breakfast: your hotel booking is confirmed", "harbour-stays.example", "Hotel check-in is open.", NONE),
    head("Flight itinerary", "chase.com", "Your trip itinerary", NONE),
)


class CorpusTests(unittest.TestCase):
    def test_every_shopping_message_is_skipped(self):
        loose = [(h.subject, h.sender_domain) for h in SHOPPING if triage.decide(h) != "skip"]
        self.assertEqual(loose, [])

    def test_every_travel_message_is_read(self):
        missed = [(h.subject, h.sender_domain) for h in TRAVEL if triage.decide(h) != "read"]
        self.assertEqual(missed, [])

    def test_shopping_mail_is_counted_as_not_travel_and_travel_mail_never_is(self):
        self.assertTrue(triage.shopping(SHOPPING[0]))
        self.assertTrue(triage.shopping(next(h for h in SHOPPING if h.sender_domain == "amazon.com")))
        self.assertFalse([h.subject for h in TRAVEL if triage.shopping(h)])
        self.assertFalse([h.subject for h in CATEGORISED if triage.shopping(h)])


class CategoryTests(unittest.TestCase):
    def test_gmails_purchases_category_alone_never_reads_a_message(self):
        self.assertEqual(triage.decide(head("Notes", "pat.example", "Details inside.", PURCHASES)), "skip")
        self.assertEqual(triage.decide(head("Your appointment", "pat.example", "Tuesday at 9:00.", PURCHASES)), "skip")

    def test_gmails_reservations_category_alone_never_reads_a_message(self):
        self.assertEqual(triage.decide(head("Notes", "pat.example", "Details inside.", RESERVATIONS)), "skip")
        self.assertEqual(triage.decide(head("Table for two", "tablebook.example", "Friday at 7:30.", RESERVATIONS)), "skip")

    def test_a_category_with_a_generic_word_and_no_travel_word_or_retail_word_is_read(self):
        missed = [h.subject for h in CATEGORISED if triage.decide(h) != "read"]
        self.assertEqual(missed, [])

    def test_a_category_with_a_generic_word_and_a_retail_word_is_skipped(self):
        for labels in (PURCHASES, RESERVATIONS):
            self.assertEqual(triage.decide(head("Your order is confirmed", "pat.example", "Thanks.", labels)), "skip")
            self.assertEqual(triage.decide(head("Booking: your return", "pat.example", "Thanks.", labels)), "skip")

    def test_a_category_with_a_generic_word_from_a_retail_sender_is_skipped(self):
        self.assertEqual(triage.decide(head("Your booking is confirmed", "megastore.amazon.com", "Thanks.", PURCHASES)), "skip")

    def test_a_generic_word_without_a_category_is_skipped(self):
        self.assertEqual(triage.decide(head("Your reservation is confirmed", "tablebook.example", "Table for 4.", NONE)), "skip")

    def test_the_reservations_category_still_reads_a_message_with_a_travel_word(self):
        self.assertEqual(triage.decide(head("Your reservation", "tablebook.example", "Hotel check-in at 3 pm.", RESERVATIONS)), "read")

    def test_a_categorised_generic_message_is_strong_enough_for_review(self):
        self.assertTrue(triage.strong(CATEGORISED[0]))
        self.assertFalse(triage.strong(head("Your booking", "pat.example", "Thanks.", NONE)))


class WordTests(unittest.TestCase):
    def test_a_generic_word_alone_does_not_read_a_message_from_an_unknown_sender(self):
        for word in ("confirmation", "booking", "reservation", "ご予約", "確認"):
            self.assertEqual(triage.decide(head(f"Your {word}", "somewhere.example", "All set.")), "skip", word)

    def test_a_generic_word_with_a_travel_word_in_the_senders_name_reads(self):
        self.assertEqual(triage.decide(head("Your booking", "somewhere.example", "All set.", NONE, "Seaside Hotels")), "read")
        self.assertEqual(triage.decide(head("Your booking", "somewhere.example", "All set.", NONE, "Pat Doe")), "skip")

    def test_a_reservation_number_with_a_place_counts_as_a_travel_word(self):
        self.assertEqual(triage.travel_words("Reservation number 123 at Pine Lodge"), 1)
        self.assertEqual(triage.travel_words("Reservation number 123"), 0)

    def test_a_retail_word_without_a_travel_word_is_skipped_even_with_a_generic_word(self):
        self.assertEqual(triage.decide(head("Booking: your order number", "somewhere.example", "Confirmed.")), "skip")

    def test_a_travel_word_beats_a_retail_word(self):
        self.assertEqual(triage.decide(head("Your hotel order receipt", "somewhere.example", "Check-in details.")), "read")

    def test_a_hotel_or_airline_in_the_senders_name_beats_a_retail_word(self):
        self.assertEqual(triage.decide(head("Your invoice", "somewhere.example", "", NONE, "Seaside Hotels")), "read")
        self.assertEqual(triage.decide(head("Your invoice", "somewhere.example", "", NONE, "Skyline Airways")), "read")
        self.assertEqual(triage.decide(head("Your invoice", "somewhere.example", "", NONE, "Pat Doe")), "skip")

    def test_a_known_travel_sender_is_never_skipped_by_a_retail_word(self):
        for domain in ("delta.com", "marriott.com", "hertz.com", "booking.com"):
            self.assertEqual(triage.decide(head("Your receipt and invoice", domain, "Order shipped, return refund.")), "read", domain)

    def test_a_retail_or_shipping_domain_is_skipped_even_with_a_generic_word_and_its_subdomains(self):
        self.assertEqual(triage.decide(head("Your reservation is confirmed", "mail.amazon.com", "Confirmed.")), "skip")
        self.assertEqual(triage.decide(head("Your booking", "fedex.com", "Confirmed.")), "skip")

    def test_a_modification_of_a_booking_is_read(self):
        self.assertEqual(triage.decide(head("Your reservation was modified", "somewhere.example", "")), "read")
        self.assertEqual(triage.decide(head("Your order was cancelled", "somewhere.example", "")), "skip")


class StrengthTests(unittest.TestCase):
    def test_two_travel_words_or_a_known_sender_is_strong(self):
        self.assertTrue(triage.strong(head("Your hotel", "somewhere.example", "Check-in at 3 pm.")))
        self.assertTrue(triage.strong(head("Hello", "delta.com", "")))
        self.assertFalse(triage.strong(head("Your hotel booking", "somewhere.example", "All set.")))


if __name__ == "__main__":
    unittest.main()
