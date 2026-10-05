"""Importing past flights from a CSV export (waypoint/domain/flight_import): each format's parser against made-up exports
(invented flights on real airports), reading a file (the format from its header, an empty or unknown or too long file), the
preview (new, already in Waypoint, can't be read), saving (segments from an import, grouped into trips, the same file
twice adds nothing, times kept where they happen) and AGENTS.md's promises (a trip is seen only by who is on it or booked
it; a notes column in the file is kept nowhere: no_leaks)."""
import csv
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import select

from tests.privacy import no_leaks
from tests.shared import ServerCase, fetch
from tests.test_trips import Household, RouteCase
from waypoint.domain import flight_import, trips, visibility
from waypoint.domain.flight_import import Proposed, Skipped
from waypoint.domain.visibility import Viewer
from waypoint.server import ROUTES
from waypoint.server.api import flight_import as api
from waypoint.server.common import ApiError, _current
from waypoint.storage.models import Segment

FIXTURES = Path(__file__).parent / "fixtures" / "flight_import"
CANARIES = ("CANARY-NOTES-FLIGHTY-4D7Q", "CANARY-NOTES-FLIGHTY-9K2M", "CANARY-NOTES-FR24-6P1S",
            "CANARY-NOTES-OPENFLIGHTS-2C8H", "CANARY-NOTES-AITA-8V3R", "CANARY-PNR-QQ7Z")


def export(name: str) -> bytes:
    return (FIXTURES / f"{name}.csv").read_bytes()


def parsed(name: str) -> flight_import.Parsed:
    return flight_import.read(export(name))


def flights(rows):
    return [r for r in rows if isinstance(r, Proposed)]


class ReadTests(unittest.TestCase):
    def test_each_format_is_recognised_from_its_header(self):
        for name, fmt in (("flighty", "Flighty"), ("myflightradar24", "myFlightRadar24"), ("openflights", "OpenFlights"),
                          ("appintheair", "App in the Air")):
            with self.subTest(name):
                self.assertEqual(parsed(name).format, fmt)

    def test_a_header_none_of_them_has_says_what_is_supported(self):
        with self.assertRaises(flight_import.Unreadable) as e:
            flight_import.read(b"Date,Place\n2025-01-01,Home\n")
        for name in ("Flighty", "myFlightRadar24", "OpenFlights", "App in the Air"):
            self.assertIn(name, str(e.exception))

    def test_an_empty_file_or_one_without_flights_is_refused_with_why(self):
        for data, said in ((b"", "empty"), (b"  \n\n", "empty"), (b"\xef\xbb\xbf" + export("openflights").split(b"\n")[0] + b"\n", "no flights"),
                           (export("openflights").split(b"\n")[0] + b"\n,,,,\n", "no flights")):
            with self.subTest(data=data[:20]):
                with self.assertRaises(flight_import.Unreadable) as e:
                    flight_import.read(data)
                self.assertIn(said, str(e.exception))

    def test_a_file_that_is_not_text_is_refused(self):
        with self.assertRaises(flight_import.Unreadable):
            flight_import.read(b"\xff\xfe\x00\x01 not text \x80\x81")
        with self.assertRaises(flight_import.Unreadable):
            flight_import.read(b"Date,From,To\n" + b"x" * 200_000 + b"\n")   # a cell past what the CSV reader takes

    def test_a_byte_order_mark_and_blank_lines_are_fine_and_lines_count_from_the_header(self):
        data = b"\xef\xbb\xbf" + export("appintheair").replace(b"\n2025-09-19", b"\n\n,,,,,,,,,\n2025-09-19")
        rows = flight_import.read(data).rows
        self.assertEqual([r.line for r in rows if isinstance(r, Proposed)], [2, 5, 6])

    def test_more_than_ten_thousand_rows_is_refused_with_why(self):
        header, row = export("appintheair").split(b"\n")[:2]
        many = header + b"\n" + (row + b"\n") * (flight_import.MAX_ROWS + 1)
        with self.assertRaises(flight_import.Unreadable) as e:
            flight_import.read(many)
        self.assertIn("10,000", str(e.exception))
        flight_import.read(header + b"\n" + (row + b"\n") * flight_import.MAX_ROWS)


class ParserTests(unittest.TestCase):
    def test_flighty(self):
        rows = parsed("flighty").rows
        first = rows[0]
        assert isinstance(first, Proposed)
        self.assertEqual((first.day, first.origin, first.destination, first.flight_number, first.airline, first.seat, first.cabin),
                         ("2025-03-01", "JFK", "LAX", "DL1001", "DL", "14C", "Economy"))
        # the gate times (actual before scheduled), with their offsets kept and not applied
        self.assertEqual((first.dep.time, first.dep.offset, first.arr.time, first.arr.offset), ("08:12", -300, "11:29", -480))
        self.assertEqual([type(r).__name__ for r in rows], ["Proposed", "Proposed", "Proposed", "Proposed", "Skipped", "Skipped"])
        self.assertIsNone(flights(rows)[1].dep)   # a missing time stays missing
        self.assertIn("cancelled", rows[4].reason)
        self.assertEqual((rows[4].line, rows[5].line), (6, 7))
        self.assertIn("date", rows[5].reason)

    def test_myflightradar24(self):
        rows = parsed("myflightradar24").rows
        first = flights(rows)[0]
        self.assertEqual((first.day, first.origin, first.destination, first.flight_number, first.airline, first.seat, first.cabin),
                         ("2025-05-10", "SYD", "LAX", "QF11", "Qantas", "63A", "Economy"))
        self.assertEqual((first.dep.time, first.arr.time, first.arr.day), ("21:30", "17:50", None))
        self.assertEqual(flights(rows)[2].flight_number, None)
        self.assertEqual(flights(rows)[2].dep, None)
        self.assertIsInstance(rows[3], Skipped)
        self.assertIn("origin", rows[3].reason)

    def test_openflights(self):
        rows = parsed("openflights").rows
        first, second, bare = flights(rows)
        self.assertEqual((first.day, first.flight_number, first.cabin, first.seat, first.dep, first.arr),
                         ("2025-07-04", "BA304", "Economy", "12A", None, None))
        self.assertEqual((second.day, second.dep.time, second.cabin), ("2025-07-11", "18:45", "Business"))
        # an ICAO code isn't an IATA one: the row can't be read, and says which airport
        skipped = [r for r in rows if isinstance(r, Skipped)]
        self.assertEqual(len(skipped), 1)
        self.assertIn("EGLL", skipped[0].reason)
        self.assertEqual((bare.origin, bare.destination, bare.flight_number, bare.dep), ("AMS", "FRA", None, None))

    def test_app_in_the_air(self):
        rows = parsed("appintheair").rows
        first = flights(rows)[0]
        self.assertEqual((first.day, first.origin, first.destination, first.flight_number, first.seat, first.cabin, first.dep.time, first.arr.time),
                         ("2025-09-12", "FRA", "JFK", "LH400", "22K", "Economy", "10:30", "13:15"))
        self.assertEqual(len(rows), 3)

    def test_a_row_without_a_day_or_an_airport_says_which(self):
        for name in ("flighty", "myflightradar24", "openflights", "appintheair"):
            first = next(csv.DictReader(io.StringIO(export(name).decode())))
            for column, value, said in (("Date", "soon", "date"), ("From", "", "origin airport"), ("To", "Nowhere Field", "destination airport")):
                with self.subTest(name=name, column=column):
                    out = io.StringIO()
                    writer = csv.DictWriter(out, list(first))
                    writer.writeheader()
                    writer.writerow({**first, column: value})
                    got = flight_import.read(out.getvalue().encode()).rows[0]
                    self.assertIsInstance(got, Skipped)
                    self.assertIn(said, got.reason)

    def test_no_parser_reads_a_notes_column_or_a_booking_reference(self):
        for name in ("flighty", "myflightradar24", "openflights", "appintheair"):
            with self.subTest(name):
                shown = repr(parsed(name).rows)
                for canary in CANARIES:
                    self.assertNotIn(canary, shown)


class Importer(Household):
    """Jane (a member) importing; Sam and Mia are other people."""

    def preview(self, name, who=None):
        return flight_import.preview(self.c, who or self.jane, parsed(name).rows)

    def statuses(self, rows):
        return [r["status"] for r in rows]

    def save_new(self, name, travelers=None, who=None):
        who = who or self.jane
        new = [r for r in self.preview(name, who) if r["status"] == "new"]
        mine = travelers if travelers is not None else [{"person_id": who.person_id, "name": None}]
        return flight_import.save(self.c, who, [{k: r[k] for k in ("day", "origin", "destination", "flight_number", "airline",
                                                                    "start_local", "end_local", "seat", "cabin")} for r in new], mine)


class PreviewTests(Importer):
    def test_a_flighty_export_as_new_unreadable_and_already_here(self):
        existing = self.add(self.jane, {"kind": "flight", "origin": "SEA", "destination": "SFO", "start_local": "2025-04-02T07:30",
                                        "end_local": "2025-04-02T09:40", "details": {"flight_number": "AS2002"}})
        rows = self.preview("flighty")
        self.assertEqual(self.statuses(rows), ["new", "new", "unreadable", "exists", "unreadable", "unreadable"])
        self.assertEqual(rows[2]["reason"], "Waypoint doesn’t know the airport ZZZ")
        self.assertEqual(rows[3]["reason"], "Already in Waypoint")
        self.assertIn("cancelled", rows[4]["reason"])
        self.assertEqual(existing["start_local"][:10], rows[3]["day"])

    def test_times_are_kept_at_their_airports(self):
        first = self.preview("flighty")[0]
        # 08:12 in New York and 11:29 in Los Angeles, as the file's offsets say: not converted to anything else
        self.assertEqual((first["start_local"], first["end_local"]), ("2025-03-01T08:12", "2025-03-01T11:29"))

    def test_an_offset_that_is_not_the_airports_is_put_at_its_zone(self):
        csv = export("flighty").decode().splitlines()
        row = csv[1].replace("2025-03-01T08:12:00-05:00", "2025-03-01T13:12:00Z").replace("2025-03-01T11:29:00-08:00", "2025-03-01T19:29:00Z")
        first = flight_import.preview(self.c, self.jane, flight_import.read(("\n".join([csv[0], row]) + "\n").encode()).rows)[0]
        self.assertEqual((first["start_local"], first["end_local"]), ("2025-03-01T08:12", "2025-03-01T11:29"))

    def test_an_arrival_with_only_a_time_lands_on_the_day_it_first_can(self):
        sydney_la, la_sydney = self.preview("myflightradar24")[:2]
        self.assertEqual((sydney_la["start_local"], sydney_la["end_local"]), ("2025-05-10T21:30", "2025-05-10T17:50"))
        self.assertEqual((la_sydney["start_local"], la_sydney["end_local"]), ("2025-05-24T22:00", "2025-05-26T06:00"))

    def test_a_missing_time_is_left_empty(self):
        row = self.preview("flighty")[1]
        self.assertEqual((row["status"], row["start_local"], row["end_local"]), ("new", None, None))
        departs_only = self.preview("openflights")[1]
        self.assertEqual((departs_only["start_local"], departs_only["end_local"]), (None, None))

    def test_the_same_route_and_day_is_the_same_flight_and_so_is_the_same_number_and_day(self):
        self.add(self.jane, {"kind": "flight", "origin": "FRA", "destination": "JFK", "start_local": "2025-09-12T09:00",
                             "end_local": "2025-09-12T12:00"})                                   # no flight number: the route and day
        self.add(self.jane, {"kind": "flight", "origin": "XXX", "destination": "YYY", "start_local": "2025-09-19T09:00",
                             "end_local": "2025-09-19T12:00", "start_zone": "UTC", "end_zone": "UTC",
                             "details": {"flight_number": "LH 401"}})                         # another route, the same number and day
        self.assertEqual(self.statuses(self.preview("appintheair")), ["exists", "exists", "new"])

    def test_a_cancelled_segment_is_not_the_flight(self):
        self.add(self.jane, {"kind": "flight", "origin": "FRA", "destination": "JFK", "start_local": "2025-09-12T09:00",
                             "end_local": "2025-09-12T12:00", "status": "cancelled"})
        self.assertEqual(self.statuses(self.preview("appintheair"))[0], "new")

    def test_a_flight_repeated_in_the_file_is_added_once(self):
        lines = export("appintheair").decode().splitlines()
        again = flight_import.read(("\n".join([*lines, lines[1]]) + "\n").encode()).rows
        self.assertEqual(self.statuses(flight_import.preview(self.c, self.jane, again)), ["new", "new", "new", "exists"])

    def test_what_someone_else_has_is_not_compared(self):
        self.add(self.sam, {"kind": "flight", "origin": "FRA", "destination": "JFK", "start_local": "2025-09-12T09:00",
                            "end_local": "2025-09-12T12:00"})
        self.assertEqual(self.statuses(self.preview("appintheair"))[0], "new")


class SaveTests(Importer):
    def segments(self, who):
        return [s for s in visibility.visible_segments(self.c, who)]

    def test_new_flights_become_segments_from_an_import_booked_by_the_importer(self):
        done = self.save_new("flighty")
        self.assertEqual((done.added, done.existing), (3, 0))
        found = self.segments(self.jane)
        self.assertEqual({s.source for s in found}, {"import"})
        self.assertEqual({s.booked_by for s in found}, {self.jane.person_id})
        seg = next(s for s in found if s.origin == "JFK")
        self.assertEqual((seg.kind, seg.start_local, seg.start_zone, seg.end_local, seg.end_zone, seg.provider),
                         ("flight", "2025-03-01T08:12", "America/New_York", "2025-03-01T11:29", "America/Los_Angeles", "DL"))
        self.assertEqual(trips.decode_details(seg.details), {"flight_number": "DL1001", "seat": "14C", "cabin": "Economy"})
        got = trips.get_segment(self.c, self.jane, seg.id)
        assert got is not None
        self.assertEqual(got["travelers"][0]["person_id"], self.jane.person_id)

    def test_flights_are_grouped_into_trips_by_the_usual_grouping(self):
        self.save_new("flighty")
        listing = trips.listing(self.c, self.jane)
        self.assertEqual([len(t["segments"]) for t in listing], [2, 1])   # JFK→LAX and the way back a week later; SEA→SFO in April
        self.save_new("openflights")
        self.assertEqual(len(trips.listing(self.c, self.jane)), 4)

    def test_importing_the_same_file_again_adds_nothing(self):
        for name in ("flighty", "myflightradar24", "openflights", "appintheair"):
            with self.subTest(name):
                first = self.save_new(name)
                self.assertGreater(first.added, 0)
                before = len(self.segments(self.jane))
                again = flight_import.save(self.c, self.jane, [
                    {k: r[k] for k in ("day", "origin", "destination", "flight_number", "airline", "start_local", "end_local", "seat", "cabin")}
                    for r in self.preview(name) if r["status"] == "exists"], [{"person_id": self.jane.person_id, "name": None}])
                self.assertEqual((again.added, len(self.segments(self.jane))), (0, before))
                self.assertEqual(self.statuses_of_all_new(name), 0)

    def statuses_of_all_new(self, name):
        return sum(1 for r in self.preview(name) if r["status"] == "new")

    def test_a_flight_with_no_times_counts_in_distance_but_not_in_time(self):
        self.save_new("flighty")
        seg = next(s for s in self.segments(self.jane) if s.origin == "LAX")
        self.assertEqual((seg.start_local, seg.end_local), ("2025-03-08T00:00", "2025-03-08T03:00"))   # no duration: the same moment
        self.assertEqual(trips.decode_details(seg.details)["time_unknown"], "yes")
        self.assertEqual((seg.origin, seg.destination), ("LAX", "JFK"))   # the places, so the distance
        self.assertEqual(trips.instant(seg.end_local, seg.end_zone), trips.instant(seg.start_local, seg.start_zone))

    def test_the_importer_picks_who_was_on_them(self):
        self.save_new("appintheair", travelers=self.on(self.jane.person_id, self.mia))
        for who, sees in ((self.jane, True), (Viewer(self.mia), True), (self.sam, False)):
            with self.subTest(person=who.person_id):
                self.assertEqual(len(trips.listing(self.c, who)) > 0, sees)
        seg = trips.listing(self.c, self.jane)[0]["segments"][0]
        self.assertEqual(sorted(t["name"] for t in seg["travelers"]), ["Jane Doe", "Mia Doe"])

    def test_flights_for_a_guest_alone_are_seen_by_the_importer_who_booked_them(self):
        self.save_new("appintheair", travelers=self.on(self.mia))
        self.assertEqual(len(trips.listing(self.c, self.jane)), 2)   # FRA→JFK with the way back, and MUC→ZRH
        self.assertEqual(trips.listing(self.c, self.sam), [])

    def test_a_flight_that_cannot_be_a_segment_adds_none(self):
        good = {"day": "2025-01-02", "origin": "ORD", "destination": "DEN", "start_local": None, "end_local": None}
        bad_one = {"day": "2025-01-01", "origin": "JFK", "destination": "LAX", "start_local": None, "end_local": None}
        for bad, why in (({**bad_one, "origin": "QQQ"}, "time zone"), ({**bad_one, "day": "2025-13-01"}, "day"),
                         ({**bad_one, "start_local": "2025-01-01T10:00", "end_local": "2025-01-01T01:00"}, "ends before"),
                         ({**bad_one, "origin": "JFK1"}, "airport code")):
            with self.subTest(why):
                with self.assertRaises(trips.Invalid) as e:
                    flight_import.save(self.c, self.jane, [good, bad], self.on(self.jane.person_id))
                self.assertIn(why, str(e.exception))
        self.assertEqual(flight_import.save(self.c, self.jane, [], []).added, 0)

    def test_what_was_not_chosen_is_kept_nowhere(self):
        self.save_new("flighty")
        everything = json.dumps([[str(v) for v in row] for row in self.c.execute(select(Segment)).fetchall()])
        for canary in CANARIES:
            self.assertNotIn(canary, everything)


class PrivacyTests(Importer):
    def test_a_notes_column_and_a_booking_reference_reach_neither_the_database_nor_the_log(self):
        with no_leaks(self, *CANARIES, database=self.path):
            for name in ("flighty", "myflightradar24", "openflights", "appintheair"):
                self.save_new(name)
            _current.user = {"sub": "u-jane", "name": "Jane Doe", "email": "u-jane@example.com"}
            self.addCleanup(setattr, _current, "user", None)
            api.api_import_preview(self.c, {}, export("flighty"))
            with self.assertRaises(ApiError):
                api.api_import_preview(self.c, {}, export("flighty").replace(b"From,To", b"Origin,Dest"))


class RouteTests(RouteCase):
    def upload(self, who, data, path="/api/import/preview"):
        status, _, body = fetch(self.base, "POST", path, data, {"X-Waypoint": "1", "Content-Type": "text/csv", **self.who[who]})
        return status, json.loads(body or b"{}")

    def rows_to_save(self, preview):
        return [{k: r[k] for k in ("day", "origin", "destination", "flight_number", "airline", "start_local", "end_local", "seat", "cabin")}
                for r in preview["rows"] if r["status"] == "new"]

    def test_preview_then_save_then_the_same_file_again(self):
        status, preview = self.upload("ana", export("flighty"))
        self.assertEqual(status, 200, preview)
        self.assertEqual((preview["format"], preview["me"]), ("Flighty", self.person["ana"]))
        self.assertEqual([r["status"] for r in preview["rows"]], ["new", "new", "unreadable", "new", "unreadable", "unreadable"])
        self.assertEqual(self.ok("ana", "GET", "/api/trips"), {"trips": []})   # nothing is saved by a preview
        saved = self.ok("ana", "POST", "/api/import", {"flights": self.rows_to_save(preview)})
        self.assertEqual(saved, {"added": 3, "existing": 0})
        listing = self.ok("ana", "GET", "/api/trips")["trips"]
        segs = [s for t in listing for s in t["segments"]]
        self.assertEqual({s["source"] for s in segs}, {"import"})
        self.assertEqual({s["booked_by"] for s in segs}, {self.person["ana"]})
        again = self.upload("ana", export("flighty"))[1]
        self.assertEqual([r["status"] for r in again["rows"]], ["exists", "exists", "unreadable", "exists", "unreadable", "unreadable"])
        self.assertEqual(self.ok("ana", "POST", "/api/import", {"flights": self.rows_to_save(preview)}), {"added": 0, "existing": 3})

    def test_travellers_are_chosen_and_the_trips_follow_the_usual_rule(self):
        _, preview = self.upload("ana", export("appintheair"))
        self.ok("ana", "POST", "/api/import", {"flights": self.rows_to_save(preview), "person_ids": [self.person["ana"], self.person["ben"]]})
        for who, count in (("ana", 2), ("ben", 2), ("cy", 0)):
            with self.subTest(who):
                self.assertEqual(len(self.ok(who, "GET", "/api/trips")["trips"]), count)

    def test_who_was_on_them_is_needed_and_must_be_in_people(self):
        _, preview = self.upload("ana", export("appintheair"))
        flights = self.rows_to_save(preview)
        for body in ({"flights": flights, "person_ids": []}, {"flights": flights, "person_ids": ["x"]},
                     {"flights": flights, "person_ids": [987654]}, {"flights": flights, "person_ids": "ana"},
                     {"flights": []}, {"flights": "all"}, {}, {"flights": [5]}, {"flights": [{**flights[0], "origin": 4}]},
                     {"flights": [{**flights[0], "day": "yesterday"}]}):
            with self.subTest(body=str(body)[:60]):
                status, got = self.call("ana", "POST", "/api/import", body)
                self.assertEqual(status, 400, got)
                self.assertTrue(got["error"])
        self.assertEqual(self.ok("ana", "GET", "/api/trips"), {"trips": []})   # none of those added anything

    def test_at_most_a_thousand_flights_at_a_time(self):
        _, preview = self.upload("ana", export("appintheair"))
        status, got = self.call("ana", "POST", "/api/import", {"flights": self.rows_to_save(preview)[:1] * (api.MAX_FLIGHTS + 1)})
        self.assertEqual(status, 400)
        self.assertIn("1,000", got["error"])

    def test_a_file_the_server_cannot_import_says_why(self):
        self.assertEqual(self.upload("ana", b"")[1]["error"], "Choose a CSV file exported from another app.")
        status, got = self.upload("ana", b"Date,Place\n2025-01-01,Home\n")
        self.assertEqual(status, 400)
        self.assertIn("OpenFlights", got["error"])
        status, got = self.upload("ana", b"x" * (api.MAX_FILE + 1))
        self.assertEqual((status, got["error"]), (400, "That file is larger than 5 MB."))

    def test_too_many_rows(self):
        header, row = export("appintheair").split(b"\n")[:2]
        with mock.patch.object(flight_import, "MAX_ROWS", 2):
            status, got = self.upload("ana", header + b"\n" + (row + b"\n") * 3)
        self.assertEqual(status, 400)
        self.assertIn("more than 2 rows", got["error"])

    def test_both_routes_are_in_the_table(self):
        self.assertIn(("POST", "/api/import/preview"), [(m, p) for m, p, _ in ROUTES])
        self.assertIn(("POST", "/api/import"), [(m, p) for m, p, _ in ROUTES])


class LocalHouseholdTests(ServerCase):
    """Without sign-in, on your own machine, the local household imports for nobody in particular and sees every trip."""
    unset = ("OIDC_ISSUER",)

    def test_the_household_previews_and_saves(self):
        status, _, body = fetch(self.base, "POST", "/api/import/preview", export("appintheair"),
                                {"X-Waypoint": "1", "Content-Type": "text/csv"})
        preview = json.loads(body)
        self.assertEqual((status, preview["me"], preview["format"]), (200, None, "App in the Air"))
        flights = [{k: r[k] for k in ("day", "origin", "destination", "flight_number", "start_local", "end_local")}
                   for r in preview["rows"] if r["status"] == "new"]
        status, saved = self.req("POST", "/api/import", {"flights": flights})
        self.assertEqual((status, saved), (200, {"added": 3, "existing": 0}))
        status, again = self.req("POST", "/api/import", {"flights": flights})
        self.assertEqual((status, again), (200, {"added": 0, "existing": 3}))
        self.assertEqual(len(self.req("GET", "/api/trips")[1]["trips"]), 2)


class FileCheckTests(unittest.TestCase):
    def test_an_uploaded_file_is_checked_through_validate(self):
        self.assertEqual(api._v.file(b"a,b\n", "file", 10), b"a,b\n")
        for bad, said in ((b"", "Choose a CSV file"), (b"  \n", "Choose a CSV file"), (None, "Choose a CSV file"),
                          (b"x" * 11, "larger than 0 MB")):
            with self.subTest(bad=bad), self.assertRaises(ApiError) as e:
                api._v.file(bad, "file", 10)
            self.assertIn(said, str(e.exception))


if __name__ == "__main__":
    unittest.main()
