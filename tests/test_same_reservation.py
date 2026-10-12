import dataclasses

from sqlalchemy import select

from tests.test_trip_people import TripPeopleCase
from waypoint.domain import trips
from waypoint.domain.mail import ingest
from waypoint.domain.mail.booking import Booking, Place
from waypoint.storage.models import Segment

SAILING = Booking(kind="cruise", status="confirmed", confirmation="55001122", provider="Example Cruise Line",
                  start="2027-03-02T15:00", end="2027-03-07T08:00", origin="PORT EXAMPLE", destination="PORT EXAMPLE",
                  start_zone="America/New_York", end_zone="America/New_York", details=(("ship", "Example Star"), ("room", "7001")))
STAY = Booking(kind="hotel", status="confirmed", confirmation="7700123", provider="Harbour Place",
               start="2027-03-01T15:00", end="2027-03-02T12:00", origin="Harbour Place London Riverside & Conference Centre",
               destination=None, start_place=Place("London", "GB"), end_place=Place("London", "GB"))
LEG = Booking(kind="flight", status="confirmed", confirmation="QX7M2K", provider="Example Air",
              start="2027-03-01T08:50", end="2027-03-01T11:05", origin="JFK", destination="BOS",
              details=(("flight_number", "EX 101"),))
RENTAL = Booking(kind="car", status="confirmed", confirmation="R1234567", provider="Example Cars",
                 start="2027-03-07T09:00", end="2027-03-08T04:00", origin="Boston Logan International Airport (BOS)",
                 destination="Boston Logan International Airport (BOS)", start_zone="America/New_York", end_zone="America/New_York")


def said(b: Booking, **swaps) -> Booking:
    return dataclasses.replace(b, **swaps)


class SameReservationCase(TripPeopleCase):
    def file(self, b: Booking, held=None):
        return ingest.file_booking(self.c, self.jane, b, held=held)

    def kind(self, kind: str) -> list[Segment]:
        self.c.orm.expire_all()
        return list(self.c.orm.scalars(select(Segment).where(Segment.kind == kind).order_by(Segment.id)).all())


class ASecondEmailForOneReservationIsOneBooking(SameReservationCase):
    def test_an_email_with_dates_only_joins_the_timed_booking_and_keeps_its_times(self):
        self.assertEqual(self.file(SAILING), "added")
        self.assertEqual(self.file(said(SAILING, start="2027-03-02T00:00", end="2027-03-07T00:00")), "attached")
        [cruise] = self.kind("cruise")
        self.assertEqual((cruise.start_local, cruise.end_local, cruise.status), ("2027-03-02T15:00", "2027-03-07T08:00", "confirmed"))

    def test_an_email_with_times_fills_a_booking_that_had_dates_only_without_calling_it_changed(self):
        self.file(said(SAILING, start="2027-03-02T00:00", end="2027-03-07T00:00"))
        self.assertEqual(self.file(SAILING), "updated")
        [cruise] = self.kind("cruise")
        self.assertEqual((cruise.start_local, cruise.end_local, cruise.status), ("2027-03-02T15:00", "2027-03-07T08:00", "confirmed"))

    def test_a_port_written_as_its_city_is_the_same_sailing_and_the_port_stays_as_it_was(self):
        self.file(SAILING)
        self.assertEqual(self.file(said(SAILING, origin="Example City, FL", destination="Example City, FL")), "attached")
        [cruise] = self.kind("cruise")
        self.assertEqual((cruise.origin, cruise.destination), ("PORT EXAMPLE", "PORT EXAMPLE"))

    def test_a_hotel_written_by_its_brand_alone_is_the_same_stay(self):
        self.file(STAY)
        self.assertEqual(self.file(said(STAY, origin="Harbour Place", provider="Harbour Place Hotels")), "attached")
        [stay] = self.kind("hotel")
        self.assertEqual((stay.origin, stay.provider), ("Harbour Place London Riverside & Conference Centre", "Harbour Place"))

    def test_an_airline_written_short_with_no_flight_number_is_the_same_flight(self):
        self.file(LEG)
        self.assertEqual(self.file(said(LEG, provider="Example", details=())), "attached")
        [leg] = self.kind("flight")
        self.assertEqual((leg.provider, trips.decode_details(leg.details)["flight_number"]), ("Example Air", "EX 101"))

    def test_a_round_trip_read_as_one_flight_with_no_number_joins_the_outbound_leg(self):
        self.file(LEG)
        self.assertEqual(self.file(said(LEG, end="2027-03-08T09:30", details=())), "attached")
        [leg] = self.kind("flight")
        self.assertEqual(leg.end_local, "2027-03-01T11:05")

    def test_a_rental_desk_written_by_its_airport_code_is_the_same_rental(self):
        self.file(RENTAL)
        self.assertEqual(self.file(said(RENTAL, origin="BOS", destination="BOS")), "attached")
        [car] = self.kind("car")
        self.assertEqual(car.origin, "Boston Logan International Airport (BOS)")

    def test_a_new_time_is_still_a_change_to_the_booking(self):
        self.file(SAILING)
        self.assertEqual(self.file(said(SAILING, start="2027-03-02T13:00")), "updated")
        [cruise] = self.kind("cruise")
        self.assertEqual((cruise.start_local, cruise.status), ("2027-03-02T13:00", "changed"))

    def test_a_rental_moved_to_another_desk_is_a_change(self):
        self.file(RENTAL)
        self.assertEqual(self.file(said(RENTAL, origin="Example Downtown Branch", destination="Example Downtown Branch")), "updated")
        [car] = self.kind("car")
        self.assertEqual((car.origin, car.status), ("Example Downtown Branch", "changed"))


class WhatContradictsIsAskedOrKeptApart(SameReservationCase):
    def test_another_ship_under_the_same_code_waits_for_a_person(self):
        self.file(SAILING)
        held: list[ingest.Held] = []
        self.assertEqual(self.file(said(SAILING, details=(("ship", "Example Dawn"),)), held), "ambiguous")
        [cruise] = self.kind("cruise")
        self.assertEqual([candidates for _, candidates in held], [[cruise.id]])

    def test_another_hotel_under_the_same_code_waits_for_a_person(self):
        self.file(STAY)
        held: list[ingest.Held] = []
        self.assertEqual(self.file(said(STAY, origin="Quayside Lodge Docklands"), held), "ambiguous")
        self.assertEqual(len(self.kind("hotel")), 1)
        self.assertEqual(len(held), 1)

    def test_another_company_under_the_same_code_waits_for_a_person(self):
        self.file(RENTAL)
        held: list[ingest.Held] = []
        self.assertEqual(self.file(said(RENTAL, provider="Other Rentals"), held), "ambiguous")
        self.assertEqual(len(self.kind("car")), 1)

    def test_with_no_one_to_ask_a_contradicting_email_is_its_own_booking(self):
        self.file(SAILING)
        self.assertEqual(self.file(said(SAILING, details=(("ship", "Example Dawn"),))), "added")
        self.assertEqual(len(self.kind("cruise")), 2)

    def test_another_flight_number_or_route_under_the_same_code_is_another_leg(self):
        self.file(LEG)
        self.assertEqual(self.file(said(LEG, details=(("flight_number", "EX 202"),))), "added")
        self.assertEqual(self.file(said(LEG, origin="BOS", destination="JFK", start="2027-03-05T18:00", end="2027-03-05T19:20", details=())), "added")
        self.assertEqual(len(self.kind("flight")), 3)

    def test_the_same_code_weeks_apart_is_another_booking(self):
        self.file(STAY)
        self.assertEqual(self.file(said(STAY, start="2027-04-01T15:00", end="2027-04-02T12:00")), "added")
        self.assertEqual(len(self.kind("hotel")), 2)

    def test_a_booking_someone_else_can_see_is_never_offered_to_ask_about(self):
        ingest.file_booking(self.c, self.sam, SAILING)
        held: list[ingest.Held] = []
        self.assertEqual(self.file(said(SAILING, details=(("ship", "Example Dawn"),)), held), "added")
        self.assertEqual(held, [])
