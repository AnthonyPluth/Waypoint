import unittest

from waypoint.domain import seatmaps
from waypoint.domain.mail import seats


class LayoutTests(unittest.TestCase):
    def test_every_entry_has_each_letter_in_exactly_one_position_per_cabin(self):
        for name, cabins in seatmaps.LAYOUTS.items():
            for cabin, layout in cabins.items():
                with self.subTest(aircraft=name, cabin=cabin):
                    letters = layout.letters()
                    self.assertEqual(len(letters), len(set(letters)))
                    self.assertTrue(letters.isalpha() and letters.isupper() and "I" not in letters)
                    self.assertEqual({layout.position(x) for x in letters}, {"window", "aisle", "middle"} - ({"middle"} if not layout.middle else set()))
                    for x in letters:
                        self.assertEqual(sum(x in part for part in (layout.window, layout.aisle, layout.middle)), 1)

    def test_every_entry_is_for_a_family_the_names_resolve_to(self):
        self.assertTrue(set(seatmaps.LAYOUTS) <= {name for name, _ in seatmaps.FAMILIES})

    def test_the_window_is_the_outermost_letter_of_the_cabin(self):
        for name, cabins in seatmaps.LAYOUTS.items():
            for cabin, layout in cabins.items():
                with self.subTest(aircraft=name, cabin=cabin):
                    self.assertEqual(layout.window[0], "A")
                    self.assertEqual(max(layout.letters()), layout.window[-1])

    def test_positions(self):
        for aircraft, letter, expected in (("Boeing 777", "F", "middle"), ("Boeing 737", "F", "window"), ("Airbus A350", "H", "middle"),
                                           ("Boeing 787", "G", "aisle"), ("Airbus A220", "B", None),
                                           ("Airbus A330", "C", None), ("Embraer E175", "A", None), (None, "A", None)):
            with self.subTest(aircraft=aircraft, letter=letter):
                self.assertEqual(seatmaps.position(aircraft, "economy", letter), expected)

    def test_a_family_without_a_layout_is_left_out(self):
        for name in ("Airbus A220", "Airbus A330", "Airbus A380", "Boeing 767", "Embraer E170", "Embraer E175", "Embraer E190", "Bombardier CRJ"):
            self.assertNotIn(name, seatmaps.LAYOUTS)


class FamilyTests(unittest.TestCase):
    def test_names_and_codes_resolve_to_the_family(self):
        for text, family in (("Boeing 737-800", "Boeing 737"), ("Boeing 737 MAX 8", "Boeing 737"), ("B738", "Boeing 737"),
                             ("b737", "Boeing 737"), ("Airbus A321neo", "Airbus A320 family"), ("Airbus A319-100", "Airbus A320 family"),
                             ("A20N", "Airbus A320 family"), ("Airbus A220-300", "Airbus A220"), ("BCS3", "Airbus A220"),
                             ("Airbus A330-300", "Airbus A330"), ("Airbus A350-900", "Airbus A350"), ("Airbus A380-800", "Airbus A380"),
                             ("Boeing 757-200", "Boeing 757"), ("Boeing 767-300ER", "Boeing 767"), ("Boeing 777-300ER", "Boeing 777"),
                             ("B77W", "Boeing 777"), ("Boeing 787-9 Dreamliner", "Boeing 787"), ("B789", "Boeing 787"),
                             ("Embraer E175", "Embraer E175"), ("Embraer 190", None), ("E190", "Embraer E190"),
                             ("Bombardier CRJ-900", "Bombardier CRJ"), ("CRJ7", "Bombardier CRJ"),
                             ("Dornier 328", None), ("", None), (None, None), ("Cessna 172", None)):
            with self.subTest(text=text):
                self.assertEqual(seatmaps.family(text), family)


class EmailTextTests(unittest.TestCase):
    def test_a_seat_with_its_word(self):
        for text, found in (("Seat 14A (Window)", ("14A", "window")), ("14C - Aisle", ("14C", "aisle")), ("22 e, middle", ("22E", "middle")),
                            ("14A Window", ("14A", "window")), ("14a", ("14a", None)), ("  14A  ", ("14A", None)), ("", (None, None)),
                            (None, (None, None)), ("Window", ("Window", None))):
            with self.subTest(text=text):
                self.assertEqual(seats.seat_with_position(text), found)

    def test_an_aircraft_in_the_itinerary(self):
        self.assertEqual(seats.aircraft_in("Aircraft: Boeing 737-800 · Meal"), "Boeing 737")
        self.assertEqual(seats.aircraft_in("Equipment Airbus A321neo"), "Airbus A320 family")
        self.assertIsNone(seats.aircraft_in("Flight 737 departs at 7:37"))
        self.assertIsNone(seats.aircraft_in("Airbus"))
        self.assertIsNone(seats.aircraft_in(None))
