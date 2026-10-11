import json
import os
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.test_mail_scan import ScanCase, eml
from tests.test_trips import RouteCase
from waypoint import monitoring
from waypoint.domain.mail import ai, extract, review
from waypoint.storage import db
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import ReviewItem, Setting

BODY = "CANARY-BODY-AI-5J2K"
IDS = ("TT87654321", "4111 1111 1111 1111", "2207781905", "FXLOY-4400123")
QUOTED, FOOTER = "CANARY-QUOTED-REPLY-8D1L", "CANARY-FOOTER-SIGNATURE-4M9W"
KEY = "sk-or-test-key-7f3a91c2b8"
REPLY_CANARY = "CANARY-REPLY-HOSTILE-6X2P"
GOOD = {"kind": "flight", "provider": "Example Air", "confirmation": "QW4R7T", "origin": "BOS", "destination": "DEN",
        "start_local": "2026-12-02T07:15", "end_local": "2026-12-02T10:05"}


class FakeAi(HTTPServer):

    def __init__(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                s = self.server
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                s.requests.append((self.path, dict(self.headers), body))
                if s.on_request:
                    s.on_request(len(s.requests))
                if s.status != 200:
                    out = {"error": {"message": "nope"}}
                elif self.path.endswith("/api/chat"):
                    out = {"message": {"role": "assistant", "content": s.content}}
                else:
                    out = {"choices": [{"message": {"role": "assistant", "content": s.content}}]}
                data = json.dumps(out).encode()
                self.send_response(s.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        super().__init__(("127.0.0.1", 0), Handler)
        self.reset()

    def reset(self):
        self.requests: list = []
        self.content = json.dumps(GOOD)
        self.status = 200
        self.on_request = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


def serve_fake_ai(case) -> FakeAi:
    fake = FakeAi()
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    case.addClassCleanup(fake.server_close)
    case.addClassCleanup(fake.shutdown)
    return fake


class RedactTests(unittest.TestCase):
    TEXT = (f"Hello. {BODY}\nFlight EX 303 departs 2026-12-02T07:15 from BOS.\nFrequent flyer: FXLOY-4400123\n"
            "SkyMiles number: 2207781905\nKnown Traveler Number: TT87654321\nCard 4111 1111 1111 1111 on 2026-10-18.\n"
            f"Confirmation code: QW4R7T\n> {QUOTED}\nUnsubscribe here\n-- \n{FOOTER}\n")

    def test_numbers_that_look_like_loyalty_known_traveler_or_card_numbers_are_removed(self):
        out = ai.redact(self.TEXT)
        for number in IDS:
            self.assertNotIn(number, out)
        self.assertIn(ai.REMOVED, out)

    def test_unlabelled_letter_prefixed_ids_are_removed_but_codes_and_flights_stay(self):
        out = ai.redact("Passenger TT87654321 and ABC1234567 and AB-12345678. Code QW4R7T, flight EX 303, room 4401.")
        for number in ("TT87654321", "ABC1234567", "12345678"):
            self.assertNotIn(number, out)
        for kept in ("QW4R7T", "EX 303", "4401"):
            self.assertIn(kept, out)

    def test_what_is_needed_to_read_a_booking_stays(self):
        out = ai.redact(self.TEXT)
        for kept in (BODY, "EX 303", "2026-12-02T07:15", "BOS", "QW4R7T", "2026-10-18"):
            self.assertIn(kept, out)

    def test_quoted_replies_footers_and_signatures_are_cut(self):
        out = ai.redact(self.TEXT)
        for gone in (QUOTED, FOOTER, "Unsubscribe"):
            self.assertNotIn(gone, out)
        self.assertNotIn(QUOTED, ai.redact(f"Booked.\nOn Mon, 5 Oct 2026, Jane Doe wrote:\n{QUOTED}\nmore"))

    def test_the_households_saved_numbers_go_wherever_they_are_written(self):
        out = ai.redact("Member FX LOY-44 00123 and fxloy4400123 and ABCD-9 here", known=("FXLOY-4400123", "ABCD-9"))
        self.assertNotIn("4400123", out)
        self.assertNotIn("ABCD-9", out)
        self.assertNotIn("00123", out)

    def test_dates_and_times_are_not_mistaken_for_numbers(self):
        text = "Depart 2026-12-02 07:15, return 2026-12-09 10:05, flight EX 1234, room 4401."
        self.assertEqual(ai.redact(text), text)

    def test_a_postal_address_is_not_a_loyalty_number_but_a_loyalty_number_still_goes(self):
        text = ("Hotel: Harbour Hotel\nAddress: 1 Quay Road, Cardiff CF10 1AA, UK\nAccount number: AB 1234567\n"
                "Rewards member FXLOY-4400123\nPhone: +44 117 555 0100\nAddress: 300 Cardinal Way, Tower Hill 4400")
        out = ai.redact(text)
        for kept in ("1 Quay Road, Cardiff CF10 1AA, UK", "+44 117 555 0100", "300 Cardinal Way, Tower Hill 4400"):
            self.assertIn(kept, out)
        for gone in ("AB 1234567", "FXLOY-4400123"):
            self.assertNotIn(gone, out)

    def test_labels_with_plurals_and_no_spaces_still_remove_their_numbers(self):
        for label in ("Memberships number", "Members ID", "Accounts", "loyaltyNo", "cardnumber", "membernumber", "AccountNo", "Rewards", "frequentflyer"):
            with self.subTest(label=label):
                out = ai.redact(f"{label}: AB 1234567X1")
                self.assertNotIn("1234567", out)
                self.assertIn(ai.REMOVED, out)

    def test_only_so_much_goes_out(self):
        self.assertEqual(len(ai.redact("word " * 10_000)), ai.MAX_SENT)
        self.assertEqual(ai.redact("   \n"), "")


class ParseTests(unittest.TestCase):
    SENT = "Confirmation code: QW4R7T flight from BOS to DEN"

    def parse(self, reply, sent=SENT):
        return ai.parse(reply if isinstance(reply, str) else json.dumps(reply), sent).bookings[0]

    def refused(self, reply, text=ai.BAD_REPLY):
        with self.assertRaises(ai.AiError) as caught:
            self.parse(reply)
        self.assertEqual(str(caught.exception), text)

    def test_a_booking_in_the_schema_is_a_suggestion(self):
        self.assertEqual(self.parse(GOOD), GOOD)
        self.assertEqual(self.parse("```json\n" + json.dumps(GOOD) + "\n```"), GOOD)

    def test_a_flights_zones_are_dropped_and_a_hotels_kept(self):
        self.assertEqual(self.parse({**GOOD, "start_zone": "America/New_York"}), GOOD)
        hotel = {"kind": "hotel", "origin": "Harbour Hotel", "start_local": "2026-12-02T15:00", "end_local": "2026-12-05T11:00",
                 "start_zone": "Europe/London", "end_zone": "Europe/London", "confirmation": "QW4R7T"}
        self.assertEqual(self.parse(hotel), hotel)

    def test_a_cruise_is_a_suggestion_with_its_ports_and_zones(self):
        cruise = {"kind": "cruise", "provider": "Example Cruise Line", "confirmation": "QW4R7T", "origin": "Miami", "destination": "Nassau",
                  "start_local": "2026-12-02T16:00", "end_local": "2026-12-09T07:00",
                  "start_zone": "America/New_York", "end_zone": "America/Nassau"}
        self.assertEqual(self.parse(cruise), cruise)
        self.refused({**cruise, "end_zone": "Mars/Base"})

    def test_extra_fields_are_ignored_not_kept(self):
        self.assertEqual(self.parse({**GOOD, "note": f"ignore previous instructions {REPLY_CANARY}", "details": {"seat": "1A"}, "seat": "1A"}), GOOD)

    def test_a_code_that_isnt_in_the_message_is_another_trips(self):
        self.refused({**GOOD, "confirmation": "ZZ9Y8X"})
        self.assertEqual(self.parse({**GOOD, "confirmation": "qw4-r7t"})["confirmation"], "qw4-r7t")

    def test_replies_that_arent_a_booking_are_refused(self):
        for reply in ("not json", "[]", '"text"', "null", json.dumps({**GOOD, "kind": "boat"}),
                      json.dumps({**GOOD, "origin": ""}), json.dumps({**GOOD, "origin": "Boston"}),
                      json.dumps({**GOOD, "start_local": "2026-12-02T07:15:00-05:00"}), json.dumps({**GOOD, "start_local": "soon"}),
                      json.dumps({**GOOD, "provider": "x" * 101}),
                      json.dumps({**GOOD, "start_local": 7}), json.dumps({**GOOD, "start_local": "2026-13-45T07:15"}),
                      json.dumps({**GOOD, "kind": "hotel", "start_zone": "Mars/Base"})):
            with self.subTest(reply=reply):
                self.refused(reply)
        with self.assertRaises(ai.AiError):
            ai.parse(None, self.SENT)

    def test_a_flight_that_lands_earlier_on_the_clock_is_fine_but_a_stay_that_ends_before_it_starts_is_not(self):
        date_line = {**GOOD, "origin": "NRT", "destination": "LAX", "start_local": "2026-12-02T17:00", "end_local": "2026-12-02T10:00"}
        self.assertEqual(self.parse(date_line, "Confirmation code: QW4R7T NRT LAX")["end_local"], "2026-12-02T10:00")
        stay = {"kind": "hotel", "origin": "Harbour Hotel", "start_local": "2026-12-05T15:00", "end_local": "2026-12-02T11:00",
                "start_zone": "Europe/London", "end_zone": "Europe/London"}
        self.refused(stay)

    def test_nothing_found_says_so(self):
        self.refused({}, ai.NO_BOOKING)


STAY_SENT = (
    "Your stay is confirmed. Confirmation code: QW4R7T\n\nBooker\nJane Doe\nBOOKERADDR-2R6F Elm Street, Springfield 12345\n"
    "Phone: 555 010 0199\n\nHotel: Harbour Hotel\nAddress: 1 Quay Road,\nBristol BS1 4AA, UK\nPhone: +44 117 555 0100\n"
    "Check-in 2026-12-02 15:00, check-out 2026-12-05 11:00\n")
STAY = {"kind": "hotel", "provider": "Example Stays", "confirmation": "QW4R7T", "origin": "Harbour Hotel",
        "start_local": "2026-12-02T15:00", "end_local": "2026-12-05T11:00", "start_zone": "Europe/London", "end_zone": "Europe/London"}


class AddressTests(unittest.TestCase):
    def parse(self, extra, sent=STAY_SENT, base=STAY):
        return ai.parse(json.dumps({**base, **extra}), sent).bookings[0]

    def test_a_hotels_address_and_phone_are_the_propertys_not_the_bookers(self):
        found = self.parse({"address": "1 Quay Road, Bristol BS1 4AA, UK", "phone": "+44 117 555 0100"})
        self.assertEqual((found["address"], found["phone"]), ("1 Quay Road, Bristol BS1 4AA, UK", "+44 117 555 0100"))

    def test_an_address_split_over_lines_and_commas_still_counts_as_in_the_email(self):
        self.assertEqual(self.parse({"address": "1 quay road bristol bs1-4aa uk"})["address"], "1 quay road bristol bs1-4aa uk")

    def test_the_bookers_address_and_phone_are_dropped_and_the_rest_is_kept(self):
        found = self.parse({"address": "BOOKERADDR-2R6F Elm Street, Springfield 12345", "phone": "555 010 0199"})
        self.assertEqual(found, STAY)

    def test_a_parking_suggestion_keeps_a_lot_address_that_is_in_the_email_and_drops_one_that_is_not(self):
        sent = "Confirmation code: PK1234\nLot: Example Long-Term Lot\nAddress: 1 Terminal Road, Jamaica, NY\nEntry 2026-12-02 08:00, exit 2026-12-05 21:00\n"
        lot = {"kind": "parking", "provider": "Example Parking", "confirmation": "PK1234", "origin": "Example Long-Term Lot",
               "start_local": "2026-12-02T08:00", "end_local": "2026-12-05T21:00", "start_zone": "America/New_York", "end_zone": "America/New_York"}
        self.assertEqual(self.parse({"address": "1 Terminal Road, Jamaica, NY"}, sent, lot)["address"], "1 Terminal Road, Jamaica, NY")
        self.assertEqual(self.parse({"address": "9 Invented Street, Nowhere"}, sent, lot), lot)

    def test_an_address_in_a_block_labelled_guest_or_billing_is_dropped(self):
        for label in ("Guest", "Billing address", "Billed to", "Booked by"):
            with self.subTest(label=label):
                sent = f"Confirmation code: QW4R7T\n\nHotel: Harbour Hotel\n\n{label}\n7 Mill Lane, Leeds LS1 1AA\n"
                self.assertEqual(self.parse({"address": "7 Mill Lane, Leeds LS1 1AA"}, sent), STAY)

    def test_an_address_that_is_not_in_the_email_is_dropped_and_the_rest_kept(self):
        self.assertEqual(self.parse({"address": "9 Invented Street, Nowhere"}), STAY)
        self.assertEqual(self.parse({"phone": "+44 117 000 0000"}), STAY)

    def test_an_email_with_no_address_fills_the_rest_and_leaves_it_empty(self):
        sent = "Confirmation code: QW4R7T. Harbour Hotel, 2026-12-02 15:00 to 2026-12-05 11:00."
        self.assertEqual(self.parse({}, sent), STAY)
        self.assertEqual(self.parse({"address": ""}, sent), STAY)

    def test_an_address_is_one_short_plain_line(self):
        long = "1 Quay Road " + "x" * 190
        sent = STAY_SENT + "Contact reception@harbour.example or 0117 555 0100\n" + long
        self.assertEqual(self.parse({"address": long}, sent), STAY)
        self.assertEqual(self.parse({"address": "1 Quay Road, Bristol BS1 4AA, UK reception@harbour.example"}, sent), STAY)
        self.assertEqual(self.parse({"address": "1 Quay Road, Bristol BS1 4AA, UK 0117 555 0100"}, sent), STAY)
        self.assertEqual(self.parse({"address": "1 Quay Road,\nBristol   BS1 4AA, UK"})["address"], "1 Quay Road, Bristol BS1 4AA, UK")

    def test_a_models_extra_keys_do_not_fail_the_suggestion(self):
        self.assertEqual(self.parse({"note": REPLY_CANARY, "extras": {"a": 1}, "loyalty": 5, "phone": 12345}), STAY)

    def test_a_car_and_a_cruise_and_a_train_take_their_pick_up_and_terminal_addresses(self):
        car = {"kind": "car", "provider": "Example Rentals", "origin": "Bristol Airport", "destination": "Bristol Airport",
               "start_local": "2026-12-02T10:00", "end_local": "2026-12-05T10:00", "confirmation": "QW4R7T"}
        sent = "Confirmation code: QW4R7T\n\nPick-up: Bristol Airport\nAddress: 4 Runway Drive, Bristol BS48 3DY\nPhone: 0117 555 0142\n"
        found = ai.parse(json.dumps({**car, "address": "4 Runway Drive, Bristol BS48 3DY", "phone": "0117 555 0142"}), sent).bookings[0]
        self.assertEqual((found["address"], found["phone"]), ("4 Runway Drive, Bristol BS48 3DY", "0117 555 0142"))
        cruise = {"kind": "cruise", "provider": "Example Cruise Line", "origin": "Miami", "destination": "Nassau", "confirmation": "QW4R7T",
                  "start_local": "2026-12-02T16:00", "end_local": "2026-12-09T07:00", "start_zone": "America/New_York", "end_zone": "America/Nassau"}
        sent = ("Confirmation code: QW4R7T\nShip: Example Voyager\nCabin: 8123\nDeck: 8\nEmbarkation: Miami\n"
                "Terminal address: 1015 North America Way, Miami FL 33132\nPhone: 305 555 0188\n")
        found = ai.parse(json.dumps({**cruise, "address": "1015 North America Way, Miami FL 33132", "phone": "305 555 0188",
                                     "room": "8123", "ship": "Example Voyager", "deck": "8"}), sent).bookings[0]
        self.assertEqual({k: found.get(k) for k in ("address", "phone", "room", "ship", "deck")},
                         {"address": "1015 North America Way, Miami FL 33132", "phone": "305 555 0188", "room": "8123",
                          "ship": "Example Voyager", "deck": "8"})
        invented = ai.parse(json.dumps({**cruise, "room": "9999", "ship": "Other Ship", "deck": "Z9"}), sent).bookings[0]
        self.assertEqual({k for k in invented if k in ai.OPTIONAL}, set())
        train = {"kind": "train", "provider": "Example Rail", "origin": "Bristol Temple Meads", "destination": "London Paddington",
                 "start_local": "2026-12-02T10:00", "end_local": "2026-12-02T11:45", "confirmation": "QW4R7T"}
        sent = "Confirmation code: QW4R7T\nDeparts Bristol Temple Meads, Temple Gate, Bristol BS1 6QF\n"
        found = ai.parse(json.dumps({**train, "address": "Temple Gate, Bristol BS1 6QF", "phone": "0117 555 0101"}), sent).bookings[0]
        self.assertEqual((found["address"], "phone" in found), ("Temple Gate, Bristol BS1 6QF", False))

    def test_a_flight_never_takes_an_address_or_the_other_details(self):
        sent = "Confirmation code: QW4R7T BOS DEN. 1 Quay Road, Bristol BS1 4AA, UK. Phone +44 117 555 0100. Cabin 8123"
        found = ai.parse(json.dumps({**GOOD, "address": "1 Quay Road, Bristol BS1 4AA, UK", "phone": "+44 117 555 0100", "room": "8123"}), sent).bookings[0]
        self.assertEqual(found, GOOD)
        found = ai.parse(json.dumps({**STAY, "room": "8123", "ship": "Example Voyager", "deck": "8"}), sent + " Example Voyager").bookings[0]
        self.assertEqual(found, STAY)

    def test_the_prompt_asks_for_them_only_for_the_kinds_they_belong_to(self):
        prompt = ai.SYSTEM
        self.assertIn('For a hotel, car, train, cruise or parking only, also "address"', prompt)
        self.assertIn('For a hotel, car or cruise only, also "phone"', prompt)
        self.assertIn('For a cruise only, also "room" (the cabin), "ship" and "deck"', prompt)
        self.assertIn("Never give an address, phone, room, ship or deck for a flight", prompt)
        self.assertIn("never the address of the guest, the booker, the cardholder or a billing address", prompt)
        self.assertIn("a block labelled booker, guest or billing", prompt)
        self.assertEqual((ai.ADDRESS_KINDS, ai.PHONE_KINDS), (("hotel", "car", "train", "cruise", "parking"), ("hotel", "car", "cruise")))


ROUND_TRIP_BODY = "CANARY-BODY-ROUND-TRIP-AI-7K4D"
ROUND_TRIP_SENT = (f"{ROUND_TRIP_BODY}\nConfirmation code: Q7M2KD\nOutbound to Denver Sat, Dec 5, 2026\nEconomy 2h 50m Nonstop\nDelta DL 1204\n"
                   "Boston BOS 7:15 AM Denver DEN 10:05 AM\nReturn to Boston Fri, Dec 11, 2026\nEconomy 3h 40m Nonstop\nDelta DL 1377\n"
                   "Denver DEN 4:20 PM Boston BOS 9:50 PM\n")
OUTBOUND = {"kind": "flight", "provider": "Delta", "confirmation": "Q7M2KD", "origin": "BOS", "destination": "DEN", "flight_number": "DL 1204",
            "cabin": "Economy", "start_local": "2026-12-05T07:15", "end_local": "2026-12-05T10:05"}
RETURN = {"kind": "flight", "provider": "Delta", "confirmation": "Q7M2KD", "origin": "DEN", "destination": "BOS", "flight_number": "DL 1377",
          "cabin": "Economy", "start_local": "2026-12-11T16:20", "end_local": "2026-12-11T21:50"}
JOINED = {**OUTBOUND, "destination": "BOS", "flight_number": "DL 1204", "end_local": "2026-12-11T21:50"}


class BookingListTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(no_leaks(self, ROUND_TRIP_BODY))

    def parse(self, reply, sent=ROUND_TRIP_SENT):
        return ai.parse(json.dumps(reply), sent)

    def test_a_reply_with_two_bookings_is_two_suggestions_each_checked_on_its_own(self):
        reading = self.parse({"bookings": [OUTBOUND, RETURN]})
        self.assertEqual((reading.bookings, reading.error), ([OUTBOUND, RETURN], None))

    def test_a_single_object_is_still_accepted(self):
        self.assertEqual(self.parse(OUTBOUND), ai.Reading([OUTBOUND]))
        self.assertEqual(self.parse({"bookings": [OUTBOUND]}), ai.Reading([OUTBOUND]))

    def test_the_old_reading_of_a_round_trip_is_a_bad_reply(self):
        for joined in (JOINED, {**JOINED, "origin": "BOS", "destination": "BOS"}):
            with self.subTest(destination=joined["destination"]), self.assertRaises(ai.AiError) as caught:
                self.parse(joined)
            self.assertEqual(str(caught.exception), ai.BAD_REPLY)

    def test_a_flight_to_the_same_airport_is_a_bad_reply(self):
        with self.assertRaises(ai.AiError) as caught:
            self.parse({"bookings": [{**OUTBOUND, "destination": "BOS", "end_local": "2026-12-05T10:05"}]})
        self.assertEqual(str(caught.exception), ai.BAD_REPLY)

    def test_a_flight_longer_than_the_limit_is_rejected_with_a_reason(self):
        for long in ({**OUTBOUND, "end_local": "2026-12-11T21:50"}, {**OUTBOUND, "end_local": "2026-12-07T10:05"}):
            with self.subTest(end=long["end_local"]), self.assertRaises(ai.AiError) as caught:
                self.parse({"bookings": [long]})
            self.assertEqual(str(caught.exception), ai.TOO_LONG)
        self.assertEqual(self.parse({"bookings": [{**OUTBOUND, "end_local": "2026-12-06T10:05"}]}).error, None)

    def test_an_arrival_that_is_not_after_the_departure_is_a_bad_reply(self):
        with self.assertRaises(ai.AiError) as caught:
            self.parse({**OUTBOUND, "end_local": "2026-12-05T05:00"})
        self.assertEqual(str(caught.exception), ai.BAD_REPLY)

    def test_the_limit_counts_the_airports_zones_not_the_clock_alone(self):
        sent = "Confirmation code: Q7M2KD SYD LAX"
        leg = {"kind": "flight", "confirmation": "Q7M2KD", "origin": "SYD", "destination": "LAX", "start_local": "2026-12-05T10:00", "end_local": "2026-12-05T06:00"}
        self.assertEqual(self.parse({"bookings": [leg]}, sent).bookings, [leg])

    def test_one_valid_and_one_invalid_leg_keeps_the_valid_one_and_reports_the_other(self):
        bad_code = {**RETURN, "confirmation": "ZZ9Y8X"}
        for bad, why in ((bad_code, ai.BAD_REPLY), ({**RETURN, "destination": "DEN"}, ai.BAD_REPLY), ({**RETURN, "end_local": "2026-12-20T21:50"}, ai.TOO_LONG)):
            with self.subTest(why=why):
                reading = self.parse({"bookings": [OUTBOUND, bad]})
                self.assertEqual(reading.bookings, [OUTBOUND])
                self.assertEqual(reading.error, f"Only 1 of the AI’s 2 bookings could be used. {why}")

    def test_when_no_leg_is_valid_the_reply_is_refused(self):
        with self.assertRaises(ai.AiError) as caught:
            self.parse({"bookings": [{**OUTBOUND, "confirmation": "ZZ9Y8X"}, {**RETURN, "destination": "DEN"}]})
        self.assertEqual(str(caught.exception), ai.BAD_REPLY)

    def test_an_empty_list_or_object_says_nothing_was_found(self):
        for reply in ({"bookings": []}, {}, {"bookings": [{}]}):
            with self.subTest(reply=reply), self.assertRaises(ai.AiError) as caught:
                self.parse(reply)
            self.assertEqual(str(caught.exception), ai.NO_BOOKING)

    def test_a_list_that_is_not_a_list_of_objects_or_is_too_long_is_a_bad_reply(self):
        for reply in ({"bookings": OUTBOUND}, {"bookings": ["BOS"]}, {"bookings": [OUTBOUND] * (ai.MAX_BOOKINGS + 1)}, [OUTBOUND]):
            with self.subTest(reply=str(reply)[:30]), self.assertRaises(ai.AiError) as caught:
                self.parse(reply)
            self.assertEqual(str(caught.exception), ai.BAD_REPLY)

    def test_the_same_leg_twice_is_one_suggestion(self):
        self.assertEqual(self.parse({"bookings": [OUTBOUND, OUTBOUND]}), ai.Reading([OUTBOUND]))

    def test_each_leg_keeps_its_own_flight_number_and_cabin_only_when_the_email_has_them(self):
        reading = self.parse({"bookings": [{**OUTBOUND, "flight_number": "dl1204"}, {**RETURN, "flight_number": "DL 9999", "cabin": "First"}]})
        self.assertEqual([(b.get("flight_number"), b.get("cabin")) for b in reading.bookings], [("DL1204", "Economy"), (None, None)])

    def test_a_hotels_never_takes_a_flight_number(self):
        reading = ai.parse(json.dumps({**STAY, "flight_number": "DL 1204", "cabin": "Economy"}), STAY_SENT + " DL 1204 Economy")
        self.assertEqual(reading.bookings, [STAY])

    def test_the_prompt_asks_for_a_list_with_one_booking_per_flight(self):
        self.assertIn('with only the key "bookings"', ai.SYSTEM)
        self.assertIn("A round trip is two flights", ai.SYSTEM)
        self.assertIn("a flight never leaves from and arrives at the same airport", ai.SYSTEM)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        from tests.shared import own_database
        self.path = own_database(self)
        self.c = db.connect(self.path)
        self.addCleanup(self.c.close)
        env = mock.patch.dict(os.environ)
        env.start()
        os.environ.pop(ai.KEY_ENV, None)
        self.addCleanup(env.stop)

    def test_it_is_off_until_turned_on_and_needs_what_it_sends_with(self):
        self.assertEqual((ai.mode(self.c), ai.config(self.c)), ("off", None))
        db.set_setting(self.c, sk.AI_MODE, "local")
        self.assertIsNone(ai.config(self.c))
        db.set_setting(self.c, sk.AI_OLLAMA_URL, "http://ollama.example:1234")
        db.set_setting(self.c, sk.AI_OLLAMA_MODEL, "llama3")
        self.assertEqual(ai.config(self.c), ai.Config("local", "llama3", url="http://ollama.example:1234"))
        db.set_setting(self.c, sk.AI_MODE, "bogus")
        self.assertIsNone(ai.config(self.c))

    def test_the_key_is_stored_encrypted_and_the_environments_wins(self):
        db.set_setting(self.c, sk.AI_MODE, "openrouter")
        db.set_setting(self.c, sk.AI_OPENROUTER_MODEL, "some/model")
        self.assertIsNone(ai.config(self.c))
        db.set_setting(self.c, sk.AI_OPENROUTER_KEY, KEY)
        self.assertEqual(ai.saved_key(self.c), (KEY, "saved"))
        self.assertTrue(self.c.execute(select(Setting.value).where(Setting.key == sk.AI_OPENROUTER_KEY)).scalar().startswith("enc:v1:"))
        self.assertNotIn(KEY, self.c.execute(select(Setting.value).where(Setting.key == sk.AI_OPENROUTER_KEY)).scalar())
        os.environ[ai.KEY_ENV] = "env-key-0123456789"
        self.assertEqual(ai.saved_key(self.c), ("env-key-0123456789", "env"))
        cfg = ai.config(self.c)
        self.assertEqual(cfg.key if cfg else None, "env-key-0123456789")
        self.assertNotIn("env-key", repr(cfg))

    def test_the_key_is_one_of_the_secrets_and_the_environments_is_scrubbed_from_logs(self):
        self.assertIn(sk.AI_OPENROUTER_KEY, sk.SECRETS)
        os.environ[ai.KEY_ENV] = "env-key-0123456789"
        self.assertNotIn("env-key-0123456789", monitoring.scrub("failed with env-key-0123456789 in it"))

    def test_addresses_and_model_names_are_checked(self):
        self.assertEqual(ai.clean_url(" http://ollama.example:11434/ "), "http://ollama.example:11434")
        for bad in ("ftp://x.example", "ollama.example", "http://u:p@x.example", "http://x.example?a=1", "http://x.example:99999", "file:///etc"):
            self.assertIsNone(ai.clean_url(bad), bad)
        self.assertEqual(ai.clean_model("anthropic/claude-haiku-4.5"), "anthropic/claude-haiku-4.5")
        self.assertIsNone(ai.clean_model("two words"))


class SuggestTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fake = serve_fake_ai(cls)

    def setUp(self):
        self.fake.reset()
        self.local = ai.Config("local", "llama3", url=self.fake.url)
        self.router = ai.Config("openrouter", "some/model", key=KEY)
        patch = mock.patch.object(ai, "HOSTS", ai.Hosts(self.fake.url + "/api/v1", allow_http=True))
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_local_request_goes_to_the_ollama_server_asking_for_json(self):
        self.assertEqual(ai.suggest(self.local, "Confirmation code: QW4R7T flight BOS DEN").bookings, [GOOD])
        path, headers, body = self.fake.requests[0]
        self.assertEqual((path, body["model"], body["stream"], body["format"]), ("/api/chat", "llama3", False, "json"))
        self.assertNotIn("Authorization", headers)

    def test_an_openrouter_request_denies_data_collection_and_allows_only_zero_retention(self):
        ai.suggest(self.router, "Confirmation code: QW4R7T flight BOS DEN")
        path, headers, body = self.fake.requests[0]
        self.assertEqual(path, "/api/v1/chat/completions")
        self.assertEqual(body["provider"], {"data_collection": "deny", "zdr": True})
        self.assertEqual((body["model"], body["response_format"]), ("some/model", {"type": "json_object"}))
        self.assertEqual(headers["Authorization"], f"Bearer {KEY}")

    def test_openrouter_is_only_reached_over_https_unless_a_test_says_otherwise(self):
        self.assertFalse(ai.request(self.router, "text")[3] and not ai.HOSTS.allow_http)
        self.assertEqual(ai.Hosts().openrouter, "https://openrouter.ai/api/v1")
        self.assertFalse(ai.Hosts().allow_http)

    def test_what_is_sent_is_the_redacted_text_only(self):
        ai.suggest(self.local, f"Confirmation code: QW4R7T BOS DEN\nKnown Traveler Number: TT87654321\n> {QUOTED}")
        sent = json.dumps(self.fake.requests[0][2])
        self.assertIn("QW4R7T", sent)
        self.assertNotIn("TT87654321", sent)
        self.assertNotIn(QUOTED, sent)

    def test_a_service_that_refuses_or_fails_is_a_fixed_message(self):
        for status, text in ((401, ai.REFUSED), (403, ai.REFUSED), (429, ai.LIMITED), (500, ai.FAILED)):
            self.fake.status = status
            with self.subTest(status=status), self.assertRaises(ai.AiError) as caught:
                ai.suggest(self.local, "Confirmation code: QW4R7T")
            self.assertEqual(str(caught.exception), text)
        self.fake.status = 404
        with self.assertRaises(ai.AiError) as caught:
            ai.suggest(self.router, "Confirmation code: QW4R7T")
        self.assertEqual(str(caught.exception), ai.NO_PRIVATE_PROVIDER)

    def test_a_service_that_cant_be_reached_is_a_fixed_message(self):
        gone = ai.Config("local", "llama3", url="http://127.0.0.1:1")
        with self.assertRaises(ai.AiError) as caught:
            ai.suggest(gone, "Confirmation code: QW4R7T")
        self.assertEqual(str(caught.exception), ai.UNREACHABLE)
        with mock.patch.object(ai.tls, "urlopen", side_effect=urllib.error.URLError("CANARY-NET-DETAILS-2Q8R")), \
                self.assertRaises(ai.AiError) as caught:
            ai.suggest(self.local, "Confirmation code: QW4R7T")
        self.assertNotIn("CANARY", str(caught.exception))

    def test_a_hostile_or_malformed_reply_is_no_suggestion(self):
        for content in (json.dumps({**GOOD, "confirmation": "ZZ9Y8X"}),
                        "I am sorry, " + REPLY_CANARY, json.dumps([GOOD])):
            self.fake.content = content
            with self.subTest(content=content[:30]), self.assertRaises(ai.AiError) as caught:
                ai.suggest(self.local, "Confirmation code: QW4R7T BOS DEN")
            self.assertNotIn("CANARY", str(caught.exception))
        self.fake.content = "{}"
        with self.assertRaises(ai.AiError) as caught:
            ai.suggest(self.local, "Confirmation code: QW4R7T")
        self.assertEqual(str(caught.exception), ai.NO_BOOKING)
        self.fake.requests.clear()
        with self.assertRaises(ai.AiError):
            ai.suggest(self.local, "")
        self.assertEqual(self.fake.requests, [])


class PlainTextTests(unittest.TestCase):
    def test_a_messages_text_comes_from_its_plain_part_or_its_html(self):
        import base64
        raw = lambda b: {"raw": base64.urlsafe_b64encode(b).decode().rstrip("=")}
        self.assertIn(BODY, extract.plain_text(raw(eml("no_markup_ids"))))
        html = extract.plain_text(raw(eml("no_markup")))
        self.assertIn("CANARY-BODY-NOMARKUP-6H9C Flight EX 202", html)
        self.assertNotIn("<p>", html)
        self.assertEqual(extract.plain_text({"raw": "!!"}), "")
        self.assertEqual(extract.plain_text({}), "")


class ScanAiCase(ScanCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fake = serve_fake_ai(cls)

    def setUp(self):
        super().setUp()
        self.fake.reset()
        env = mock.patch.dict(os.environ)
        env.start()
        os.environ.pop(ai.KEY_ENV, None)
        self.addCleanup(env.stop)

    def turn_on(self, mode="local"):
        with db.session() as conn:
            db.set_setting(conn, sk.AI_MODE, mode)
            db.set_setting(conn, sk.AI_OLLAMA_URL, self.fake.url)
            db.set_setting(conn, sk.AI_OLLAMA_MODEL, "llama3")

    def turn_off(self):
        with db.session() as conn:
            db.set_setting(conn, sk.AI_MODE, "off")


class ScanTests(ScanAiCase):
    def test_it_does_nothing_unless_turned_on(self):
        self.put("no_markup_ids")
        self.assertEqual(self.scan().review, 1)
        self.assertEqual(self.fake.requests, [])
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["suggestion_error"]), ([], None))

    def test_a_queued_message_gets_a_suggestion_for_a_person_to_confirm(self):
        self.turn_on()
        self.put("no_markup_ids")
        self.assertEqual(self.scan().review, 1)
        [item] = self.items()
        self.assertEqual((item["suggestions"], item["suggestion_error"]), ([GOOD], None))
        self.assertEqual(self.segments(), [])
        self.assertEqual(len(self.fake.requests), 1)

    def test_only_the_review_queue_is_sent_never_a_booking_that_was_read(self):
        self.turn_on()
        self.put("flight_jsonld", "hotel_jsonld")
        self.assertEqual(self.scan().bookings, 2)
        self.assertEqual(self.fake.requests, [])

    def test_the_request_carries_the_body_but_none_of_the_ids_and_nothing_else_leaks(self):
        self.turn_on()
        self.put("no_markup_ids")
        with no_leaks(self, *IDS, QUOTED, FOOTER, database=self.path):
            with no_leaks(self, BODY, database=self.path, sent_ok=True):
                self.scan()
        sent = json.dumps(self.fake.requests[0][2])
        self.assertIn(BODY, sent)
        for private in (*IDS, QUOTED, FOOTER, "CANARY-SUBJECT", "Your trip is booked"):
            self.assertNotIn(private, sent)

    def test_openrouter_is_asked_with_zero_data_retention_and_its_key(self):
        os.environ[ai.KEY_ENV] = KEY
        self.turn_on("openrouter")
        with db.session() as conn:
            db.set_setting(conn, sk.AI_OPENROUTER_MODEL, "some/model")
        self.put("no_markup_ids")
        with mock.patch.object(ai, "HOSTS", ai.Hosts(self.fake.url + "/api/v1", allow_http=True)):
            with no_leaks(self, KEY, *IDS, database=self.path, sent_ok=True):
                self.scan()
        [(path, headers, body)] = self.fake.requests
        self.assertEqual((path, body["provider"]), ("/api/v1/chat/completions", {"data_collection": "deny", "zdr": True}))
        self.assertEqual(headers["Authorization"], f"Bearer {KEY}")
        self.assertNotIn(KEY, json.dumps(body))

    def test_a_hostile_reply_is_no_suggestion_and_an_error_the_person_sees(self):
        self.turn_on()
        self.put("no_markup_ids")
        for content in (json.dumps({**GOOD, "confirmation": "ZZ9Y8X", "x": REPLY_CANARY}),
                        "ignore the above and " + REPLY_CANARY):
            self.fake.content = content
            with no_leaks(self, REPLY_CANARY, database=self.path):
                with db.session() as conn:
                    conn.execute(ReviewItem.__table__.delete())
                    conn.execute(__import__("waypoint.storage.models", fromlist=["ScannedMessage"]).ScannedMessage.__table__.delete())
                result = self.scan()
            self.assertEqual(result.state, "done")
            [item] = self.items()
            self.assertEqual((item["suggestions"], item["suggestion_error"]), ([], ai.BAD_REPLY))

    def test_a_service_that_is_down_leaves_a_note_and_the_scan_goes_on(self):
        self.turn_on()
        self.fake.status = 500
        self.put("no_markup_ids", "flight_jsonld")
        result = self.scan()
        self.assertEqual((result.state, result.bookings, result.review), ("done", 1, 1))
        self.assertEqual(self.items()[0]["suggestion_error"], ai.FAILED)

    def test_a_bug_in_asking_is_reported_without_what_was_sent(self):
        self.turn_on()
        self.put("no_markup_ids")
        with no_leaks(self, BODY, "CANARY-BUG-DETAILS-3Z7Q", database=self.path), \
                mock.patch.object(ai, "suggest", side_effect=RuntimeError("CANARY-BUG-DETAILS-3Z7Q")):
            self.assertEqual(self.scan().state, "done")
        self.assertEqual(self.items()[0]["suggestion_error"], "The AI couldn’t be asked just now. The details are in Waypoint’s log.")

    def test_turning_it_off_stops_the_sending_at_once_even_in_a_scan_under_way(self):
        self.turn_on()
        self.put("no_markup_ids")
        self.add_mail("msg-second", eml("no_markup_ids"))
        self.add_mail("msg-third", eml("no_markup_ids"))
        self.fake.on_request = lambda n: self.turn_off() if n == 1 else None
        self.assertEqual(self.scan().review, 3)
        self.assertEqual(len(self.fake.requests), 1)
        notes = sorted(bool(i["suggestions"]) for i in self.items())
        self.assertEqual(notes, [False, False, True])

    def test_an_item_keeps_nothing_of_the_email_but_its_suggestion(self):
        self.turn_on()
        self.put("no_markup_ids")
        with no_leaks(self, BODY, QUOTED, FOOTER, *IDS, database=self.path, sent_ok=True):
            self.scan()
        with db.session() as conn:
            kept = conn.execute(select(ReviewItem.suggestion, ReviewItem.suggestion_error)).fetchone()
        self.assertEqual(json.loads(kept[0]), [GOOD])
        self.assertEqual(review.count(self.c, "u-jane"), 1)


class RoundTripScanTests(ScanAiCase):
    CANARY = "CANARY-BODY-ROUND-TRIP-3H8N"

    def unreadable(self) -> bytes:
        raw = eml("flight_round_trip_card_site").replace(b"Subject: Your flights are booked", b"Subject: Your flight itinerary")
        for left, right in ((b"BOS 7:15 AM", b"BOS morning"), (b"DEN 10:05 AM", b"DEN morning"), (b"DEN 4:20 PM", b"DEN afternoon"),
                            (b"BOS 9:50 PM", b"BOS evening")):
            raw = raw.replace(left, right)
        return raw

    def ask(self, reply) -> review.ItemOut:
        self.turn_on()
        self.add_mail("round-trip", self.unreadable())
        self.fake.content = json.dumps(reply)
        with no_leaks(self, self.CANARY, database=self.path, sent_ok=True):
            self.assertEqual(self.scan().review, 1)
        [item] = self.items()
        return item

    def test_the_generic_reader_leaves_a_round_trip_with_no_times_to_the_ai(self):
        self.add_mail("round-trip", self.unreadable())
        self.assertEqual(self.scan().review, 1)
        self.assertEqual(self.segments(), [])
        self.assertEqual(self.fake.requests, [])

    def test_a_reply_with_two_flights_is_two_suggestions_in_order(self):
        item = self.ask({"bookings": [OUTBOUND, RETURN]})
        self.assertEqual((item["suggestions"], item["suggestion_error"]), ([OUTBOUND, RETURN], None))
        self.assertEqual(self.segments(), [])
        with db.session() as conn:
            kept = conn.execute(select(ReviewItem.suggestion)).scalar()
        self.assertEqual(json.loads(kept), [OUTBOUND, RETURN])

    def test_the_old_single_booking_reading_of_the_round_trip_is_refused(self):
        item = self.ask({**JOINED, "destination": "BOS"})
        self.assertEqual((item["suggestions"], item["suggestion_error"]), ([], ai.BAD_REPLY))

    def test_one_good_leg_is_kept_and_the_other_reported(self):
        item = self.ask({"bookings": [OUTBOUND, {**RETURN, "end_local": "2026-12-30T21:50"}]})
        self.assertEqual((item["suggestions"], item["suggestion_error"]),
                         ([OUTBOUND], f"Only 1 of the AI’s 2 bookings could be used. {ai.TOO_LONG}"))

    def test_an_item_stored_with_one_booking_before_still_reads(self):
        item = self.ask({"bookings": [OUTBOUND]})
        with db.session() as conn:
            conn.execute(ReviewItem.__table__.update().values(suggestion=json.dumps(OUTBOUND)))
        self.assertEqual(self.items()[0]["suggestions"], [OUTBOUND])
        self.assertEqual(item["suggestions"], [OUTBOUND])


class AiApiTests(RouteCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            for key in (sk.AI_MODE, sk.AI_OLLAMA_URL, sk.AI_OLLAMA_MODEL, sk.AI_OPENROUTER_MODEL, sk.AI_OPENROUTER_KEY):
                db.set_setting(conn, key, None)
        env = mock.patch.dict(os.environ)
        env.start()
        os.environ.pop(ai.KEY_ENV, None)
        self.addCleanup(env.stop)

    def test_it_starts_off(self):
        self.assertEqual(self.ok("ana", "GET", "/api/ai"), {"mode": "off", "ollama_url": "", "ollama_model": "", "openrouter_model": "", "key": None})

    def test_choosing_local_needs_an_address_and_a_model(self):
        status, body = self.call("ana", "POST", "/api/ai", {"mode": "local"})
        self.assertEqual((status, body["error"]), (400, "Enter the Ollama address and the model to use"))
        got = self.ok("ana", "POST", "/api/ai", {"mode": "local", "ollama_url": "http://ollama.example:11434/", "ollama_model": "llama3"})
        self.assertEqual((got["mode"], got["ollama_url"], got["ollama_model"]), ("local", "http://ollama.example:11434", "llama3"))
        self.assertEqual(self.ok("ben", "GET", "/api/ai"), got)
        self.assertEqual(self.ok("ana", "POST", "/api/ai", {"mode": "off"})["ollama_model"], "llama3")

    def test_choosing_openrouter_needs_a_model_and_a_key_which_never_comes_back(self):
        status, body = self.call("ana", "POST", "/api/ai", {"mode": "openrouter"})
        self.assertEqual((status, body["error"]), (400, "Enter the OpenRouter model to use"))
        status, body = self.call("ana", "POST", "/api/ai", {"mode": "openrouter", "openrouter_model": "some/model"})
        self.assertEqual(status, 400)
        self.assertIn("key", body["error"])
        got = self.ok("ana", "POST", "/api/ai", {"mode": "openrouter", "openrouter_model": "some/model", "openrouter_key": KEY})
        self.assertEqual((got["mode"], got["key"]), ("openrouter", "saved"))
        self.assertNotIn(KEY, json.dumps(self.ok("ana", "GET", "/api/ai")))
        with db.session() as conn:
            stored = conn.execute(select(Setting.value).where(Setting.key == sk.AI_OPENROUTER_KEY)).scalar()
        self.assertTrue(stored.startswith("enc:v1:"))
        self.assertEqual(self.ok("ana", "POST", "/api/ai", {"mode": "openrouter"})["key"], "saved")
        self.assertEqual(self.call("ana", "POST", "/api/ai", {"mode": "openrouter", "openrouter_key": ""})[0], 400)
        os.environ[ai.KEY_ENV] = "env-key-0123456789"
        self.assertEqual(self.ok("ana", "GET", "/api/ai")["key"], "env")

    def test_what_isnt_valid_is_refused_and_changes_nothing(self):
        for body in ({"mode": "cloud"}, {}, {"mode": "local", "ollama_url": "ftp://x.example", "ollama_model": "m"},
                     {"mode": "local", "ollama_url": "http://x.example", "ollama_model": "two words"},
                     {"mode": "local", "ollama_url": 5, "ollama_model": "m"}, {"mode": "openrouter", "openrouter_model": "a b"},
                     {"mode": "off", "openrouter_key": "k" * 201}):
            with self.subTest(body=body):
                self.assertEqual(self.call("ana", "POST", "/api/ai", body)[0], 400)
        self.assertEqual(self.ok("ana", "GET", "/api/ai")["mode"], "off")

    def test_review_items_carry_the_suggestion_to_their_owner_alone(self):
        from waypoint.storage.models import Mailbox
        with db.session() as conn:
            conn.execute(Mailbox.__table__.delete())
            conn.execute(Mailbox.__table__.insert().values(owner_sub="sub-ana", address="ana@gmail.example", token="enc:v1:x",
                                                           status="connected", created=1.0))
            box = conn.execute(select(Mailbox.id)).scalar()
            review.add(conn, box, "m1", "example-air.example", "2026-10-18", "no_markup", 1.0)
            review.set_suggestions(conn, box, "m1", [GOOD], None)   # type: ignore[list-item]
        [item] = self.ok("ana", "GET", "/api/review")["items"]
        self.assertEqual((item["suggestions"], item["suggestion_error"]), ([GOOD], None))
        self.assertEqual(self.ok("ben", "GET", "/api/review")["items"], [])
        with db.session() as conn:
            conn.execute(Mailbox.__table__.delete())


class ScanAddressTests(ScanAiCase):
    BOOKER = ("CANARY-BOOKER-ADDR-2R6F", "CANARY-BOOKER-PHONE-4T8N")
    PROPERTY = {"address": "1 Quay Road, Bristol BS1 4AA, UK", "phone": "+44 117 555 0100"}

    def reply(self, **extra):
        self.fake.content = json.dumps({**STAY, **extra})

    def ask(self):
        self.turn_on()
        self.put("no_markup_stay")
        with no_leaks(self, *self.BOOKER, REPLY_CANARY, database=self.path, sent_ok=True):
            self.assertEqual(self.scan().review, 1)
        return self.items()[0]

    def test_the_propertys_address_and_phone_reach_the_suggestion_not_the_bookers(self):
        self.reply(**self.PROPERTY, note=REPLY_CANARY)
        item = self.ask()
        self.assertEqual((item["suggestions"], item["suggestion_error"]), ([{**STAY, **self.PROPERTY}], None))
        sent = self.fake.requests[0][2]
        self.assertEqual(set(sent), {"model", "messages", "stream", "format", "options"})
        self.assertEqual([m["role"] for m in sent["messages"]], ["system", "user"])
        self.assertIn("1 Quay Road,\nBristol BS1 4AA, UK", sent["messages"][1]["content"])

    def test_the_bookers_address_is_dropped_and_never_stored_or_logged(self):
        self.reply(address="CANARY-BOOKER-ADDR-2R6F Elm Street, Springfield 12345", phone="555 010 0199 CANARY-BOOKER-PHONE-4T8N")
        item = self.ask()
        self.assertEqual((item["suggestions"], item["suggestion_error"]), ([STAY], None))

    def test_an_address_that_is_not_in_the_email_leaves_the_rest_of_the_suggestion(self):
        self.reply(address="9 Invented Street, Nowhere")
        item = self.ask()
        self.assertEqual((item["suggestions"], item["suggestion_error"]), ([STAY], None))


if __name__ == "__main__":
    unittest.main()
