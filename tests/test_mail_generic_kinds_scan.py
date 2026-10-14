import json

from tests.privacy import no_leaks
from tests.test_mail_scan import NOW, ScanCase, eml


class GenericKindCase(ScanCase):
    CANARIES: tuple[str, ...] = ()
    DOMAIN = ""

    def filed(self, raw: bytes):
        self.add_mail("first", raw)
        with no_leaks(self, *self.CANARIES, database=self.path):
            result = self.scan()
        self.assertEqual((result.bookings, result.review), (1, 0))
        self.assertEqual(self.items(), [])
        self.assertEqual(self.scanned()["first"], "booking")
        [booking] = self.segments()
        self.assertNotIn("CANARY", json.dumps(booking))
        return {**booking, **booking["details"]}


class GenericCarScanTests(GenericKindCase):
    CANARIES = ("CANARY-BODY-CAR-EN-3K7M", "CANARY-BODY-CAR-DE-8H2Q", "CANARY-SENDER-CAR-4F6X")
    DOMAIN = "roadside-rentals.example"

    def first(self) -> bytes:
        return eml("car_generic_en").replace(b"Roadside Rentals <", b"CANARY-SENDER-CAR-4F6X Rentals <")

    def second(self) -> bytes:
        return (eml("car_generic_en").replace(b"RR55821", b"RR99999").replace(b"December 5, 2026", b"December 12, 2026")
                .replace(b"December 9, 2026", b"December 16, 2026"))

    def test_a_rental_from_a_new_sender_is_filed_automatically(self):
        s = self.filed(self.first())
        self.assertEqual((s["kind"], s["provider"], s["confirmation"], s["origin"], s["destination"], s["start_local"], s["end_local"]),
                         ("car", "Roadside Rentals", "RR55821", "Denver International Airport (DEN)", "Seattle-Tacoma International Airport (SEA)",
                          "2026-12-05T10:30", "2026-12-09T16:00"))
        self.assertEqual((s["start_zone"], s["end_zone"]), ("America/Denver", "America/Los_Angeles"))

    def test_each_complete_email_is_filed_without_sender_confirmation(self):
        self.filed(self.first())
        self.add_mail("second", self.second())
        self.scan(now=NOW + 30)
        self.assertEqual(self.items(), [])
        self.assertEqual(len(self.segments()), 2)
        self.assertIn("second", self.scanned())

    def test_without_sender_trust_later_mail_is_filed_directly(self):
        self.filed(self.first())
        self.add_mail("second", self.second())
        with no_leaks(self, *self.CANARIES, database=self.path):
            result = self.scan(now=NOW + 60)
        self.assertEqual((result.bookings, result.review), (1, 0))
        later = next(s for s in self.segments() if s["confirmation"] == "RR99999")
        self.assertEqual((later["start_local"], later["start_zone"], later["end_local"], later["end_zone"], later["details"]),
                         ("2026-12-12T10:30", "America/Denver", "2026-12-16T16:00", "America/Los_Angeles", {"car_class": "Compact"}))

    def test_a_german_rental_is_read_too_and_stays_on_the_server(self):
        self.put("car_generic_de")
        with no_leaks(self, *self.CANARIES, database=self.path):
            self.scan()
        [s] = self.segments()
        s = {**s, **s["details"]}
        self.assertEqual(self.items(), [])
        self.assertEqual((s["origin"], s["start_local"], s["end_local"], s["start_zone"], s["confirmation"]),
                         ("Flughafen München (MUC)", "2026-12-05T10:30", "2026-12-09T16:00", "Europe/Berlin", "MW90417"))
        self.assertEqual(s["end_zone"], s["start_zone"])


class GenericTrainScanTests(GenericKindCase):
    CANARIES = ("CANARY-BODY-TRAIN-EN-6D4N", "CANARY-BODY-TRAIN-FR-9B5T", "CANARY-SENDER-TRAIN-8Z2P")
    DOMAIN = "rail-exemple.example"

    def first(self) -> bytes:
        return eml("train_generic_fr").replace(b"Rail Exemple <", b"CANARY-SENDER-TRAIN-8Z2P Rail <")

    def test_a_train_from_a_new_sender_is_filed_automatically(self):
        s = self.filed(self.first())
        self.assertEqual((s["kind"], s["provider"], s["confirmation"], s["origin"], s["destination"], s["start_local"], s["end_local"], s["start_zone"]),
                         ("train", "Rail Exemple", "RX90412", "Paris Gare de Lyon", "Lyon Part-Dieu", "2026-11-21T09:12", "2026-11-21T11:14", "Europe/Paris"))
        self.assertEqual(s["end_zone"], s["start_zone"])

    def test_without_sender_trust_later_mail_with_two_legs_is_filed_directly(self):
        self.filed(self.first())
        self.add_mail("second", eml("train_generic_en").replace(b"alpine-rail.example", b"rail-exemple.example"))
        with no_leaks(self, *self.CANARIES, database=self.path):
            result = self.scan(now=NOW + 60)
        self.assertEqual((result.bookings, result.review), (2, 0))
        out, back = (next(s for s in self.segments() if s["origin"] == o) for o in ("Zurich HB", "Milan Centrale"))
        self.assertEqual((out["start_local"], out["start_zone"], out["end_local"], out["end_zone"], out["confirmation"]),
                         ("2026-11-21T09:02", "Europe/Zurich", "2026-11-21T12:25", "Europe/Rome", "AR48219"))
        self.assertEqual((back["start_local"], back["start_zone"], back["end_local"], back["end_zone"]),
                         ("2026-11-28T15:35", "Europe/Rome", "2026-11-28T18:58", "Europe/Zurich"))

    def test_a_train_across_zones_files_both_zones(self):
        raw = eml("train_generic_en").replace(b"alpine-rail.example", b"rail-exemple.example")
        self.add_mail("first", raw)
        self.scan()
        self.assertEqual({(s["start_zone"], s["end_zone"]) for s in self.segments()}, {("Europe/Zurich", "Europe/Rome"), ("Europe/Rome", "Europe/Zurich")})


class GenericCruiseScanTests(GenericKindCase):
    CANARIES = ("CANARY-BODY-CRUISE-EN-2V8S", "CANARY-BODY-CRUISE-ES-7K3W", "CANARY-SENDER-CRUISE-5J9R")
    DOMAIN = "blue-horizon.example"

    def first(self) -> bytes:
        return eml("cruise_generic_en").replace(b"Blue Horizon Cruises <", b"CANARY-SENDER-CRUISE-5J9R Cruises <")

    def second(self) -> bytes:
        return (eml("cruise_generic_en").replace(b"BH772013", b"BH999999").replace(b"November 21, 2026", b"December 5, 2026")
                .replace(b"November 28, 2026", b"December 12, 2026"))

    def test_a_cruise_from_a_new_sender_is_filed_automatically(self):
        s = self.filed(self.first())
        self.assertEqual((s["kind"], s["provider"], s["confirmation"], s["origin"], s["destination"], s["ship"], s["start_local"], s["end_local"], s["start_zone"]),
                         ("cruise", "Blue Horizon Cruises", "BH772013", "Galveston, TX", "Galveston, TX", "Blue Horizon Voyager",
                          "2026-11-21T16:00", "2026-11-28T08:00", "America/Chicago"))

    def test_without_sender_trust_later_mail_is_filed_directly(self):
        self.filed(self.first())
        self.add_mail("second", self.second())
        with no_leaks(self, *self.CANARIES, database=self.path):
            result = self.scan(now=NOW + 60)
        self.assertEqual((result.bookings, result.review), (1, 0))
        later = next(s for s in self.segments() if s["confirmation"] == "BH999999")
        self.assertEqual((later["start_local"], later["start_zone"], later["end_local"], later["end_zone"], later["details"]),
                         ("2026-12-05T16:00", "America/Chicago", "2026-12-12T08:00", "America/Chicago", {"ship": "Blue Horizon Voyager"}))

    def test_a_spanish_cruise_is_read_too(self):
        self.put("cruise_generic_es")
        with no_leaks(self, *self.CANARIES, database=self.path):
            self.scan()
        [s] = self.segments()
        s = {**s, **s["details"]}
        self.assertEqual(self.items(), [])
        self.assertEqual((s["origin"], s["start_zone"], s["ship"], s["confirmation"]), ("Lisboa (LIS)", "Europe/Lisbon", "Estrella del Atlántico", "NE553208"))
