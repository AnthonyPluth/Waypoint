import json
import unittest
from datetime import date

from sqlalchemy import select

from tests import test_mail_followup as followups
from tests.privacy import no_leaks
from tests.test_mail_extract import FLIGHT, eml, message
from tests.test_mail_scan import NOW, eml as fixture_eml
from tests.test_trips import BACK, HOTEL, OUT, Household
from waypoint.domain import money, offline, trips
from waypoint.domain.mail import ai, extract, price
from waypoint.server.api import trips as api
from waypoint.server.common import ApiError
from waypoint.storage.models import Segment

USD = money.Price
STAY_TOTAL = b"<table><tr><td>Total</td><td>$1,240.00</td></tr></table></body>"
CODE = followups.CODE


def priced_hotel(total: str = "$1,240.00", checkout: str | None = None) -> bytes:
    raw = fixture_eml("hotel_jsonld").replace(b"</body>", f"<table><tr><td>Total</td><td>{total}</td></tr></table></body>".encode())
    return raw.replace(b"2026-11-27T10:00:00+00:00", checkout.encode()) if checkout else raw


class ReaderTests(unittest.TestCase):
    CASES = [
        ("Total: $1,240.00", USD(124000, "USD")),
        ("Grand Total $1,234.56 USD", USD(123456, "USD")),
        ("Total\n$310.00", USD(31000, "USD")),
        ("Total1.234,56 €", USD(123456, "EUR")),
        ("Total: 1.234,56 €", USD(123456, "EUR")),
        ("Total 1 240,00 €", USD(124000, "EUR")),
        ("Total charged: EUR 310,00", USD(31000, "EUR")),
        ("Total (USD): 1,240.00", USD(124000, "USD")),
        ("Total: CHF 1'240.00", USD(124000, "CHF")),
        ("Total: ¥12,300", USD(12300, "JPY")),
        ("Total: £99.5", USD(9950, "GBP")),
        ("Estimated total: C$ 410.20", USD(41020, "CAD")),
        ("Total: $1,240.00 CAD", USD(124000, "CAD")),
        ("Amount charged\n$55.10", USD(5510, "USD")),
        ("Subtotal: $100.00\nTaxes: $20.00\nTotal: $120.00", USD(12000, "USD")),
        ("Total: $120.00\nGrand total: $120.00", USD(12000, "USD")),
        ("Total: $120.00\nTotal: $130.00", None),
        ("Deposit: $50.00", None),
        ("Subtotal: $50.00", None),
        ("Taxes and fees: $50.00", None),
        ("Total taxes: $50.00", None),
        ("Total: 12,500 points + $5.60", None),
        ("Total: -$50.00", None),
        ("Total refund: $50.00", None),
        ("Total per night: $100.00", None),
        ("Total: $100.00 per night", None),
        ("Total due at pickup: $50.00", None),
        ("Total: $0.00", None),
        ("Total: $1,240.00 (€1,150.00)", None),
        ("Total: 1,240.00", None),
        ("Total: $1.5000", None),
        ("Total: $9,999,999,999.00", None),
        ("Hotel total: $200.00", None),
    ]

    def test_only_an_amount_labelled_as_the_total_is_read_and_in_the_currency_it_names(self):
        for text, expected in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(price.read(text), expected)

    def test_the_amount_is_in_the_currencys_smallest_unit(self):
        self.assertEqual(price.read("Total: KWD 12.345"), USD(12345, "KWD"))
        self.assertEqual(price.read("Total: JPY 12,300"), USD(12300, "JPY"))
        self.assertEqual(price.read("Total: JPY 12.5"), None)

    def test_structured_data_gives_an_amount_and_its_currency(self):
        self.assertEqual(price.structured("1240.50", "usd"), USD(124050, "USD"))
        self.assertEqual(price.structured(310, "EUR"), USD(31000, "EUR"))
        self.assertEqual(price.structured(99.5, "GBP"), USD(9950, "GBP"))
        self.assertEqual(price.structured("$1,240.00", "USD"), USD(124000, "USD"))
        for total, currency in ((None, "USD"), ("1240", None), ("1240", "dollars"), (True, "USD"), (-5, "USD"), ("abc", "USD"), (0, "USD")):
            with self.subTest(total=total, currency=currency):
                self.assertIsNone(price.structured(total, currency))

    def test_what_the_ai_printed_is_checked_against_the_text_it_was_sent(self):
        self.assertTrue(price.printed("Total: $1,240.00", USD(124000, "USD")))
        self.assertTrue(price.printed("Total 1.240,00 EUR", USD(124000, "EUR")))
        self.assertFalse(price.printed("Total: $1,240.00", USD(124000, "EUR")))
        self.assertFalse(price.printed("Total: $1,240.00", USD(125000, "USD")))


def flight_leg(leg: int) -> str:
    return (FLIGHT if leg == 1 else FLIGHT.replace('"departureAirport":{"iataCode":"jfk"}', '"departureAirport":{"iataCode":"LHR"}')
            .replace('"arrivalAirport":{"iataCode":"LHR"}', '"arrivalAirport":{"iataCode":"JFK"}').replace("2026-11-20T19:00:00-05:00", "2026-11-28T11:00:00Z")
            .replace("2026-11-21T07:10:00Z", "2026-11-28T14:05:00-05:00"))


def trip_email(body: str) -> bytes:
    nodes = ",".join(flight_leg(n) for n in (1, 2))
    return eml(f'<html><head><script type="application/ld+json">[{nodes}]</script></head><body>{body}</body></html>')


class ExtractTests(unittest.TestCase):
    def read(self, raw: bytes) -> extract.Message:
        return extract.read(message(raw))

    def test_a_total_in_a_confirmations_text_goes_on_its_one_booking(self):
        [b] = self.read(priced_hotel()).bookings
        self.assertEqual(b.price, USD(124000, "USD"))

    def prices(self, raw: bytes) -> dict[str, money.Price | None]:
        return {b.origin or "": b.price for b in self.read(raw).bookings}

    def test_a_total_that_covers_a_round_trip_goes_on_the_first_flight_only(self):
        self.assertEqual(self.prices(trip_email("<p>Total: $412.80</p>")), {"JFK": USD(41280, "USD"), "LHR": None})

    def test_two_bookings_with_different_codes_get_no_text_total(self):
        second = flight_leg(2).replace("ABC123", "DEF456")
        raw = eml(f'<html><head><script type="application/ld+json">[{flight_leg(1)},{second}]</script></head><body>Total: $412.80</body></html>')
        self.assertEqual(self.prices(raw), {"JFK": None, "LHR": None})

    def test_structured_totals_are_read_and_a_repeated_total_is_counted_once(self):
        def priced(node: str, total: str, currency: str) -> str:
            return json.dumps({**json.loads(node), "totalPrice": total, "priceCurrency": currency})

        def page(*nodes: str) -> bytes:
            return eml(f'<html><head><script type="application/ld+json">[{",".join(nodes)}]</script></head><body>x</body></html>')

        self.assertEqual(self.prices(page(priced(flight_leg(1), "412.80", "USD"), priced(flight_leg(2), "412.80", "USD"))),
                         {"JFK": USD(41280, "USD"), "LHR": None})
        other = flight_leg(2).replace("ABC123", "DEF456")
        self.assertEqual(self.prices(page(priced(flight_leg(1), "412.80", "USD"), priced(other, "100", "EUR"))),
                         {"JFK": USD(41280, "USD"), "LHR": USD(10000, "EUR")})

    def test_a_cancelled_booking_has_no_cost(self):
        raw = priced_hotel().replace(b"ReservationConfirmed", b"ReservationCancelled")
        [b] = self.read(raw).bookings
        self.assertEqual((b.status, b.price), ("cancelled", None))

    def test_an_email_with_no_total_or_an_unclear_one_leaves_the_cost_empty(self):
        [b] = self.read(fixture_eml("hotel_jsonld")).bookings
        self.assertIsNone(b.price)
        [b] = self.read(priced_hotel("$100.00").replace(b"</body>", b"<p>Total: $120.00</p></body>")).bookings
        self.assertIsNone(b.price)

    def test_a_receipt_with_no_booking_of_its_own_carries_its_total(self):
        raw = followups.follow("Your receipt", f"Thanks. Your stay at the hotel is paid.\nReservation number: {CODE}\nAmount charged: €310,00")
        found = self.read(raw)
        self.assertEqual((found.bookings, found.price), ((), USD(31000, "EUR")))
        cancelled = followups.follow("Your reservation was cancelled", f"Reservation number: {CODE}\nTotal: €310,00")
        self.assertIsNone(self.read(cancelled).price)


class AiTests(unittest.TestCase):
    SENT = "Confirmation code: QW4R7T flight from BOS to DEN\nTotal: $1,240.00\nDeposit: $100.00"
    GOOD = {"kind": "flight", "provider": "Example Air", "confirmation": "QW4R7T", "origin": "BOS", "destination": "DEN",
            "start_local": "2026-12-02T07:15", "end_local": "2026-12-02T10:05"}

    def parse(self, extra, sent=SENT):
        return ai.parse(json.dumps({"bookings": [{**self.GOOD, **extra}]}), sent).bookings[0]

    def test_a_total_the_email_prints_is_kept_with_its_currency(self):
        found = self.parse({"total": "1,240.00", "currency": "USD"})
        self.assertEqual((found["price_minor"], found["price_currency"]), (124000, "USD"))
        found = self.parse({"total": 1240, "currency": "usd"})
        self.assertEqual(found["price_minor"], 124000)

    def test_a_total_the_email_doesnt_print_or_without_a_currency_is_dropped_and_the_booking_kept(self):
        for extra in ({"total": "999.00", "currency": "USD"}, {"total": "1,240.00", "currency": "EUR"}, {"total": "1,240.00"},
                      {"currency": "USD"}, {"total": [1], "currency": "USD"}, {"total": "-1,240.00", "currency": "USD"}):
            with self.subTest(extra=extra):
                found = self.parse(extra)
                self.assertNotIn("price_minor", found)
                self.assertEqual(found["origin"], "BOS")

    def test_one_total_repeated_on_every_booking_of_a_code_is_kept_once(self):
        second = {**self.GOOD, "origin": "DEN", "destination": "BOS", "start_local": "2026-12-09T07:15", "end_local": "2026-12-09T10:05",
                  "total": "1,240.00", "currency": "USD"}
        first = {**self.GOOD, "total": "1,240.00", "currency": "USD"}
        sent = self.SENT + " DEN to BOS"
        out, back = ai.parse(json.dumps({"bookings": [first, second]}), sent).bookings
        self.assertEqual((out.get("price_minor"), back.get("price_minor")), (124000, None))

    def test_the_prompt_asks_for_the_total_and_nothing_about_what_is_sent_changes(self):
        self.assertIn('"total"', ai.SYSTEM)
        self.assertIn('"currency"', ai.SYSTEM)
        self.assertEqual(ai.redact("Total: $1,240.00\nCard 4111 1111 1111 1111"), "Total: $1,240.00\nCard [removed]")


class CostCase(Household):
    def stay(self, **extra):
        return self.add(self.jane, {**HOTEL, "confirmation": "H1", "provider": "Harbour", **extra}, None, self.on(self.jane.person_id))

    def costs(self, trip_id):
        found = trips.get(self.c, self.jane, trip_id)
        assert found is not None
        return found["costs"]


class TripCostTests(CostCase):
    def test_a_cost_entered_by_hand_is_stored_in_minor_units_and_marked_manual(self):
        got = self.stay(price={"amount_minor": 124000, "currency": "USD"})
        self.assertEqual(got["price"], {"amount_minor": 124000, "currency": "USD", "source": "manual"})
        row = self.c.orm.get(Segment, got["id"])
        assert row is not None
        self.assertEqual((row.price_minor, row.price_currency, row.price_source), (124000, "USD", "manual"))
        self.assertIsNone(self.add(self.jane, OUT, None, self.on(self.jane.person_id))["price"])

    def test_a_bad_cost_is_refused(self):
        for bad in ({"amount_minor": -1, "currency": "USD"}, {"amount_minor": 1.5, "currency": "USD"}, {"amount_minor": 100, "currency": "usd"},
                    {"amount_minor": 100, "currency": "DOLLARS"}, {"amount_minor": money.MAX_MINOR + 1, "currency": "USD"}):
            with self.subTest(bad=bad), self.assertRaises(trips.Invalid):
                self.stay(price=bad)

    def test_a_cost_can_be_added_fixed_and_cleared_without_touching_the_rest(self):
        got = self.stay()
        again = trips.edit_segment(self.c, self.jane, got["id"], {"price": {"amount_minor": 5000, "currency": "EUR"}})
        assert again is not None
        self.assertEqual(again["price"], {"amount_minor": 5000, "currency": "EUR", "source": "manual"})
        self.assertEqual(again["locked_fields"], [])
        fixed = trips.edit_segment(self.c, self.jane, got["id"], {"price": {"amount_minor": 6000, "currency": "EUR"}})
        assert fixed is not None
        self.assertEqual(fixed["price"]["amount_minor"], 6000)
        kept = trips.edit_segment(self.c, self.jane, got["id"], {"provider": "Harbour Group"})
        assert kept is not None
        self.assertEqual(kept["price"]["amount_minor"], 6000)
        cleared = trips.edit_segment(self.c, self.jane, got["id"], {"price": None})
        assert cleared is not None
        self.assertIsNone(cleared["price"])
        row = self.c.orm.get(Segment, got["id"])
        assert row is not None
        self.assertEqual((row.price_minor, row.price_currency, row.price_source), (None, None, None))

    def test_saving_an_email_cost_unchanged_leaves_it_an_email_cost(self):
        got = self.stay()
        row = self.c.orm.get(Segment, got["id"])
        assert row is not None
        trips.set_price(row, {"amount_minor": 7000, "currency": "USD"}, "email")
        self.c.orm.flush()
        same = trips.edit_segment(self.c, self.jane, got["id"], {"price": {"amount_minor": 7000, "currency": "USD"}})
        assert same is not None
        self.assertEqual(same["price"]["source"], "email")
        changed = trips.edit_segment(self.c, self.jane, got["id"], {"price": {"amount_minor": 7100, "currency": "USD"}})
        assert changed is not None
        self.assertEqual(changed["price"]["source"], "manual")

    def test_a_trips_total_is_kept_per_currency_and_never_converted(self):
        one = self.add(self.jane, {**OUT, "price": {"amount_minor": 41280, "currency": "USD"}}, None, self.on(self.jane.person_id))
        self.add(self.jane, {**HOTEL, "price": {"amount_minor": 90000, "currency": "USD"}}, one["trip_id"], self.on(self.jane.person_id))
        self.add(self.jane, {**BACK, "price": {"amount_minor": 31000, "currency": "EUR"}}, one["trip_id"], self.on(self.jane.person_id))
        self.assertEqual(self.costs(one["trip_id"]), {"totals": [{"currency": "USD", "amount_minor": 131280}, {"currency": "EUR", "amount_minor": 31000}],
                                                    "priced": 3, "bookings": 3})

    def test_a_cancelled_booking_keeps_its_cost_but_is_not_counted(self):
        one = self.add(self.jane, {**OUT, "price": {"amount_minor": 41280, "currency": "USD"}}, None, self.on(self.jane.person_id))
        gone = self.add(self.jane, {**HOTEL, "status": "cancelled", "price": {"amount_minor": 90000, "currency": "USD"}}, one["trip_id"],
                        self.on(self.jane.person_id))
        self.assertEqual(self.costs(one["trip_id"]), {"totals": [{"currency": "USD", "amount_minor": 41280}], "priced": 1, "bookings": 1})
        shown = trips.get_segment(self.c, self.jane, gone["id"])
        assert shown is not None
        self.assertEqual(shown["price"]["amount_minor"], 90000)

    def test_bookings_without_a_cost_are_counted_and_one_confirmation_is_one_booking(self):
        first = self.add(self.jane, {**OUT, "confirmation": "ZZ9", "provider": "Example Air", "price": {"amount_minor": 41280, "currency": "USD"}},
                         None, self.on(self.jane.person_id))
        self.add(self.jane, {**BACK, "confirmation": "ZZ9", "provider": "Example Air"}, first["trip_id"], self.on(self.jane.person_id))
        self.add(self.jane, HOTEL, first["trip_id"], self.on(self.jane.person_id))
        self.assertEqual(self.costs(first["trip_id"]), {"totals": [{"currency": "USD", "amount_minor": 41280}], "priced": 1, "bookings": 2})

    def test_a_trip_with_no_costs_has_an_empty_total(self):
        got = self.stay()
        self.assertEqual(self.costs(got["trip_id"]), {"totals": [], "priced": 0, "bookings": 1})

    def test_merging_trips_adds_their_totals(self):
        a = self.add(self.jane, {**OUT, "price": {"amount_minor": 1000, "currency": "USD"}}, None, self.on(self.jane.person_id))
        b = self.add(self.jane, {**BACK, "start_local": "2026-09-08T11:00", "end_local": "2026-09-08T14:05", "price": {"amount_minor": 500, "currency": "USD"}},
                     self.add(self.jane, {**HOTEL, "start_local": "2026-09-02T15:00", "end_local": "2026-09-08T10:00"}, None, self.on(self.jane.person_id))["trip_id"],
                     self.on(self.jane.person_id))
        self.assertNotEqual(a["trip_id"], b["trip_id"])
        merged = trips.merge(self.c, self.jane, a["trip_id"], b["trip_id"])
        assert merged is not None
        self.assertEqual(merged["costs"]["totals"], [{"currency": "USD", "amount_minor": 1500}])


class VisibilityTests(CostCase):
    def test_a_cost_is_seen_by_those_who_see_the_booking_and_nobody_else(self):
        got = self.stay(price={"amount_minor": 124000, "currency": "USD"})
        self.assertIsNone(trips.get(self.c, self.sam, got["trip_id"]))
        self.assertIsNone(trips.get_segment(self.c, self.sam, got["id"]))
        self.assertEqual([t["costs"] for t in trips.listing(self.c, self.sam)], [])
        shared = self.add(self.jane, {**OUT, "price": {"amount_minor": 1000, "currency": "USD"}}, None, self.on(self.jane.person_id, self.sam.person_id))
        seen = trips.get_segment(self.c, self.sam, shared["id"])
        assert seen is not None
        self.assertEqual(seen["price"]["amount_minor"], 1000)

    def test_a_saved_copy_for_offline_carries_the_costs_of_the_trip(self):
        got = self.stay(price={"amount_minor": 124000, "currency": "USD"})
        saved = offline.projection(self.c, self.jane, date(2026, 6, 3))
        [mine] = saved["trips"]
        self.assertEqual(mine["trip"]["costs"]["totals"], [{"currency": "USD", "amount_minor": 124000}])
        self.assertEqual(mine["trip"]["segments"][0]["price"]["amount_minor"], 124000)
        self.assertEqual(mine["trip"]["id"], got["trip_id"])
        self.assertEqual(offline.projection(self.c, self.sam, date(2026, 6, 3))["trips"], [])


class ApiFieldTests(unittest.TestCase):
    def test_a_cost_is_an_amount_in_minor_units_and_a_currency_or_null(self):
        self.assertEqual(api.segment_fields({"price": {"amount_minor": 100, "currency": "USD"}}), {"price": {"amount_minor": 100, "currency": "USD"}})
        self.assertEqual(api.segment_fields({"price": None}), {"price": None})
        for bad in ("12", [], {"amount_minor": "100", "currency": "USD"}, {"amount_minor": True, "currency": "USD"}, {"amount_minor": 100},
                    {"amount_minor": 100, "currency": "usd"}, {"amount_minor": -5, "currency": "USD"}, {"amount_minor": 2_000_000_000, "currency": "USD"}):
            with self.subTest(bad=bad), self.assertRaises(ApiError):
                api.segment_fields({"price": bad})


class ScanCostTests(followups.FollowUpCase):
    def price_of(self, segment_id):
        return self.read(lambda conn: trips.get_segment(conn, self.jane, segment_id))["price"]

    def test_a_confirmations_total_becomes_the_bookings_cost_read_from_email(self):
        self.add_mail("m-1", priced_hotel())
        self.assertEqual(self.scan().bookings, 1)
        [seg] = self.segments()
        self.assertEqual(seg["price"], {"amount_minor": 124000, "currency": "USD", "source": "email"})
        [t] = self.read(lambda conn: trips.listing(conn, self.jane))
        self.assertEqual(t["costs"]["totals"], [{"currency": "USD", "amount_minor": 124000}])

    def test_a_follow_up_receipt_fills_a_missing_cost_and_never_replaces_one(self):
        segment = self.confirmed()
        self.assertIsNone(self.price_of(segment))
        self.add("m-receipt", followups.follow("Your receipt for your stay", f"CANARY-BODY-COST-4T7R Thanks. Your stay at the hotel is paid.\nReservation number: {CODE}\nAmount charged: €310,00",
                                               followups.STAYS))
        with no_leaks(self, "CANARY-BODY-COST-4T7R", database=self.path):
            self.scan(now=NOW + 60)
        self.assertEqual(self.outcomes()["m-receipt"], "follow-up")
        self.assertEqual(self.price_of(segment), {"amount_minor": 31000, "currency": "EUR", "source": "email"})
        self.add("m-second", followups.follow("Your receipt for your stay", f"Thanks. Your stay at the hotel is paid.\nReservation number: {CODE}\nAmount charged: €999,00", followups.STAYS))
        self.scan(now=NOW + 120)
        self.assertEqual(self.price_of(segment)["amount_minor"], 31000)

    def test_a_follow_up_that_changes_or_cancels_does_not_touch_the_cost(self):
        segment = self.confirmed()
        self.add("m-cancel", followups.follow("Your stay was cancelled", f"Your reservation was cancelled.\nReservation number: {CODE}\nTotal refund: €310,00",
                                               followups.STAYS))
        self.scan(now=NOW + 60)
        self.assertIsNone(self.price_of(segment))

    def test_an_email_never_replaces_a_cost_entered_by_hand(self):
        segment = self.by_hand(price={"amount_minor": 5000, "currency": "USD"})
        self.add_mail("m-1", priced_hotel("$1,240.00"))
        self.scan()
        self.assertEqual(self.price_of(segment), {"amount_minor": 5000, "currency": "USD", "source": "manual"})
        self.add_mail("m-2", priced_hotel("$1,300.00", "2026-11-28T10:00:00+00:00"))
        self.scan(now=NOW + 60)
        self.assertEqual(self.price_of(segment)["amount_minor"], 5000)

    def test_an_email_fills_a_booking_made_by_hand_without_a_cost(self):
        segment = self.by_hand()
        self.add_mail("m-1", priced_hotel())
        self.scan()
        self.assertEqual(self.price_of(segment), {"amount_minor": 124000, "currency": "USD", "source": "email"})

    def test_a_later_email_updates_an_email_cost_only_when_it_changes_the_booking_and_a_repeat_leaves_it(self):
        self.add_mail("m-1", priced_hotel("$1,240.00"))
        self.scan()
        [segment] = self.segments()
        self.add_mail("m-repeat", priced_hotel("$1,111.00"))
        self.scan(now=NOW + 60)
        self.assertEqual(self.price_of(segment["id"])["amount_minor"], 124000)
        self.add_mail("m-change", priced_hotel("$1,300.00", "2026-11-28T10:00:00+00:00"))
        self.scan(now=NOW + 120)
        self.assertEqual(self.price_of(segment["id"]), {"amount_minor": 130000, "currency": "USD", "source": "email"})
        self.add_mail("m-no-total", fixture_eml("hotel_jsonld").replace(b"2026-11-27T10:00:00+00:00", b"2026-11-29T10:00:00+00:00"))
        self.scan(now=NOW + 180)
        self.assertEqual(self.price_of(segment["id"])["amount_minor"], 130000)

    def test_the_stored_cost_holds_no_text_of_the_email(self):
        self.add_mail("m-1", priced_hotel().replace(b"Your stay is booked.", b"Your stay is booked. CANARY-BODY-COST-9K2M"))
        with no_leaks(self, "CANARY-BODY-COST-9K2M", database=self.path):
            self.scan()
        row = self.read(lambda conn: conn.execute(select(Segment.price_minor, Segment.price_currency, Segment.price_source)).fetchone())
        self.assertEqual(tuple(row), (124000, "USD", "email"))


if __name__ == "__main__":
    unittest.main()
