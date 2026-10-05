"""The API contract (waypoint/server/contract.py, docs/openapi.json, frontend/src/lib/api-types.ts): each covered route's
real reply, plus the cases that add fields (a signed-in person, a last backup), matches docs/openapi.json; the
generated files are current; and tools/api_contract.py describes the types it's given."""
import ast
import importlib.util
import json
import unittest
from pathlib import Path

from waypoint.storage import backup, db, secretbox
from waypoint.storage.models import Mailbox
from waypoint.storage import settings_keys as sk
from unittest import mock

from sqlalchemy import insert

from waypoint import oidc
from waypoint.providers import gmail
from waypoint.domain import people as people_domain
from waypoint.domain import trips
from waypoint.domain.mail import review
from waypoint.domain.visibility import Viewer
from waypoint.server import jobs
from waypoint.server.api import ai as ai_api
from waypoint.server.api import backups, flight_import as flight_import_api, flightstatus as flightstatus_api, mailboxes, people, state, stats as stats_api
from waypoint.server.api import review as review_api
from waypoint.providers import flightstatus as flight_service
from waypoint.server.api import trips as trips_api
from waypoint.server.api import loyalty
from waypoint.server.api import reminders as reminders_api
from waypoint.server.common import _current
from tests.shared import DbCase

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("api_contract", ROOT / "tools" / "api_contract.py")
assert _spec and _spec.loader
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

OPENAPI = json.loads((ROOT / "docs/openapi.json").read_text())


def problems(value, schema, at="reply") -> list[str]:
    """What in `value` (parsed JSON) doesn't match `schema` (the JSON schema subset docs/openapi.json uses)."""
    if "$ref" in schema:
        return problems(value, OPENAPI["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]], at)
    if "anyOf" in schema:
        found = [problems(value, s, at) for s in schema["anyOf"]]
        if not all(found):
            return []
        not_null = [f for s, f in zip(schema["anyOf"], found, strict=True) if s != {"type": "null"}]
        if len(not_null) == 1:   # `X | None`, and it isn't None: what's wrong with it as an X
            return not_null[0]
        return [f"{at}: {json.dumps(value)[:80]} is none of the types it can be"]
    if "enum" in schema or "const" in schema:
        allowed = schema["enum"] if "enum" in schema else [schema["const"]]
        return [] if any(value == v and type(value) is type(v) for v in allowed) else [f"{at}: {value!r} isn't one of {allowed}"]
    kinds = schema.get("type")
    if kinds is None:
        return []
    kinds = kinds if isinstance(kinds, list) else [kinds]
    is_a = {"string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool), "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None, "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict)}
    kind = next((k for k in kinds if is_a[k](value)), None)
    if kind is None:
        return [f"{at}: {json.dumps(value)[:80]} isn't {' or '.join(kinds)}"]
    if kind == "array":
        return [p for i, v in enumerate(value) for p in problems(v, schema["items"], f"{at}[{i}]")]
    if kind == "object":
        props = schema.get("properties", {})
        found = [f"{at}: no {k!r}" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            if k in props:
                found += problems(v, props[k], f"{at}.{k}")
            elif schema.get("additionalProperties") is False:
                found.append(f"{at}: {k!r} isn't in the contract")
            elif isinstance(schema.get("additionalProperties"), dict):
                found += problems(v, schema["additionalProperties"], f"{at}.{k}")
        return found
    return []


def reply_schema(route: str) -> dict:
    method, path = route.split(" ", 1)
    address = contract.openapi_path(path)[0]
    return OPENAPI["paths"][address][method.lower()]["responses"]["200"]["content"]["application/json"]["schema"]


def covered() -> set[str]:
    return {f"{m.upper()} {'/'.join('{id}' if s.startswith('{') else s for s in p.split('/'))}"
            for p, ops in OPENAPI["paths"].items() for m in ops}


class Replies(DbCase):
    """Each covered route's reply, as the server would send it (through JSON), against docs/openapi.json."""

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, _current, "user", getattr(_current, "user", None))
        self.checked: set[str] = set()

    def check(self, route: str, reply) -> None:
        self.checked.add(route)
        found = problems(json.loads(json.dumps(reply, allow_nan=False)), reply_schema(route))
        self.assertEqual(found, [], route)

    def test_every_covered_route_is_checked(self):
        self.test_state()
        self.test_backups()
        self.test_mailboxes()
        self.test_review()
        self.test_ai()
        self.test_people()
        self.test_trips()
        self.test_stats()
        self.test_import()
        self.test_flight_status()
        self.test_loyalty()
        self.test_reminders()
        self.assertEqual(self.checked, covered(), "check each route the contract covers here")

    def test_state(self):
        _current.user = {"name": None, "email": None, "local": True}
        self.check("GET /api/state", state.api_state(self.c, {}, {}))
        _current.user = {"sub": "u1", "name": "Rosa Example", "email": "rosa@example.com"}
        db.set_setting(self.c, sk.LAST_BACKUP, "2026-09-30T07:02:00")
        self.check("GET /api/state", state.api_state(self.c, {}, {}))
        _current.user = None
        self.check("GET /api/state", state.api_state(self.c, {}, {}))

    def test_backups(self):
        self.c.commit()
        with db.session() as conn:
            raw = backup.dump(conn)
        self.check("POST /api/backup/inspect", backups.api_backup_inspect(None, {}, raw))
        restored = backups.api_restore(None, {}, raw)
        self.assertTrue(restored["ok"])
        self.check("POST /api/restore", restored)

    def test_mailboxes(self):
        _current.user = {"sub": "u1", "name": "Rosa Example", "email": "rosa@example.com"}
        env = {"GOOGLE_CLIENT_ID": "client.example", "GOOGLE_CLIENT_SECRET": "secret"}
        with mock.patch.dict("os.environ", env):
            self.check("GET /api/mailboxes", mailboxes.api_mailboxes(self.c, {}, {}))   # none yet
            self.check("POST /api/mailboxes/connect", mailboxes.api_mailbox_connect(self.c, {}, {}))
        for status in ("connected", "reconnect", "error"):
            self.c.execute(insert(Mailbox).values(owner_sub="u1", address=f"{status}@gmail.example", token=secretbox.encrypt("t"),
                                                  status=status, last_error=None if status == "connected" else "Said so.",
                                                  last_scan=1790000000.0, created=1.0))
        reply = mailboxes.api_mailboxes(self.c, {}, {})
        self.assertEqual([m["status"] for m in reply["mailboxes"]], ["connected", "reconnect", "error"])
        self.check("GET /api/mailboxes", reply)
        with mock.patch.object(jobs, "scan_now", return_value=True):
            self.check("POST /api/mailboxes/{id}/scan", mailboxes.api_mailbox_scan(self.c, {}, {}, str(reply["mailboxes"][0]["id"])))
        with mock.patch.object(gmail, "_post", return_value={}):
            self.check("DELETE /api/mailboxes/{id}", mailboxes.api_mailbox_disconnect(self.c, {}, {}, str(reply["mailboxes"][0]["id"])))

    def test_review(self):
        _current.user = {"sub": "u1", "name": "Rosa Example", "email": "rosa@example.com"}
        oidc.remember_user(self.c, "u1", "rosa@example.com", "Rosa Example")
        self.check("GET /api/review", review_api.api_review(self.c, {}, {}))   # nothing yet
        box = self.c.execute(insert(Mailbox).values(owner_sub="u1", address="rosa@gmail.example", token=secretbox.encrypt("t"),
                                                    status="connected", created=1.0)).lastrowid
        for n, reason in enumerate(("no_markup", "incomplete", "broken")):
            review.add(self.c, box, f"m{n}", f"air{n}.example", "2026-10-17", reason, 1.0)   # type: ignore[arg-type]
        review.set_suggestion(self.c, box, "m0", {"kind": "flight", "origin": "BOS", "destination": "DEN", "start_local": "2026-12-02T07:15",
                                                  "end_local": "2026-12-02T10:05"}, None)
        review.set_suggestion(self.c, box, "m1", None, "The AI didn’t find a booking in this message.")
        me = Viewer(people_domain.person_for_sub(self.c, "u1"))
        trips.add_segment(self.c, me, {"kind": "flight", "origin": "JFK", "destination": "SFO", "start_local": "2026-12-08T08:00",
                                       "end_local": "2026-12-08T11:20", "travelers": [{"person_id": None, "name": "DOE/MIA MISS"}]}, source="email")
        listed = review_api.api_review(self.c, {}, {})
        self.assertEqual((len(listed["items"]), len(listed["who"])), (3, 1))
        self.check("GET /api/review", listed)
        self.check("POST /api/review/who/{id}", review_api.api_review_who(self.c, {}, {"person_id": me.person_id}, str(listed["who"][0]["id"])))
        self.check("POST /api/review/{id}/ignore", review_api.api_review_ignore(self.c, {}, {}, str(listed["items"][0]["id"])))
        self.check("DELETE /api/review/{id}", review_api.api_review_dismiss(self.c, {}, {}, str(listed["items"][1]["id"])))

    def test_ai(self):
        self.check("GET /api/ai", ai_api.api_ai(self.c, {}, {}))   # off
        self.check("POST /api/ai", ai_api.api_ai_save(self.c, {}, {"mode": "local", "ollama_url": "http://ollama.example:1234", "ollama_model": "llama3"}))
        self.check("POST /api/ai", ai_api.api_ai_save(self.c, {}, {"mode": "openrouter", "openrouter_model": "some/model", "openrouter_key": "sk-or-test-1234567"}))
        self.check("GET /api/ai", ai_api.api_ai(self.c, {}, {}))

    def test_people(self):
        self.check("GET /api/people", people.api_people(self.c, {}, {}))   # nobody yet
        self.check("POST /api/people", people.api_person_add(self.c, {}, {"display_name": "Mia Doe", "aliases": ["DOE/MIA MISS"]}))
        oidc.remember_user(self.c, "u1", "jane.doe@example.com", "Jane Doe")
        listed = people.api_people(self.c, {}, {})
        self.check("GET /api/people", listed)
        self.assertEqual([p["member"] for p in listed["people"]], [True, False])
        pid = listed["people"][1]["id"]
        self.check("POST /api/people/{id}", people.api_person_edit(self.c, {}, {"display_name": "Mia D.", "legal_name": "Mia Rose Doe"}, str(pid)))
        self.check("DELETE /api/people/{id}", people.api_person_remove(self.c, {}, {}, str(pid)))

    def test_import(self):
        _current.user = {"name": None, "email": None, "local": True}
        csv = (ROOT / "tests/fixtures/flight_import/flighty.csv").read_bytes()
        shown = flight_import_api.api_import_preview(self.c, {}, csv)
        self.assertEqual({r["status"] for r in shown["rows"]}, {"new", "unreadable"})
        self.check("POST /api/import/preview", shown)
        flights = [{k: r[k] for k in ("day", "origin", "destination", "flight_number", "start_local", "end_local")}
                   for r in shown["rows"] if r["status"] == "new"]
        self.check("POST /api/import", flight_import_api.api_import(self.c, {}, {"flights": flights}))

    def test_loyalty(self):
        self.check("GET /api/loyalty", loyalty.api_loyalty(self.c, {}, {}))   # none yet
        who = people.api_person_add(self.c, {}, {"display_name": "Mia Doe"})["id"]
        body = {"person_id": who, "kind": "airline", "program": "American AAdvantage", "number": "DEMO1234567", "expiry": "2029-01-31"}
        added = loyalty.api_loyalty_add(self.c, {}, body)
        self.check("POST /api/loyalty", added)
        self.check("GET /api/loyalty", loyalty.api_loyalty(self.c, {}, {}))
        self.check("POST /api/loyalty/{id}", loyalty.api_loyalty_edit(self.c, {}, {**body, "number": None}, str(added["id"])))
        self.check("POST /api/loyalty/{id}/reveal", loyalty.api_loyalty_reveal(self.c, {}, {}, str(added["id"])))
        self.check("DELETE /api/loyalty/{id}", loyalty.api_loyalty_remove(self.c, {}, {}, str(added["id"])))


    def test_reminders(self):
        from tests.test_reminders import subscription
        _current.user = {"name": None, "email": None, "local": True}
        self.check("GET /api/reminders", reminders_api.api_reminders(self.c, {}, {}))
        self.check("POST /api/reminders", reminders_api.api_reminders_set(self.c, {}, {"check_in": False, "day_of": True}))
        endpoint, p256dh, auth = subscription()
        added = reminders_api.api_device_add(self.c, {}, {"endpoint": endpoint, "p256dh": p256dh, "auth": auth})
        self.check("POST /api/reminders/devices", added)
        self.check("POST /api/feed", reminders_api.api_feed_make(self.c, {}, {}))
        self.check("GET /api/reminders", reminders_api.api_reminders(self.c, {}, {}))   # with a device and a feed
        self.check("DELETE /api/reminders/devices/{id}", reminders_api.api_device_remove(self.c, {}, {}, str(added["id"])))
        self.check("DELETE /api/feed", reminders_api.api_feed_off(self.c, {}, {}))

    def test_trips(self):
        _current.user = {"name": None, "email": None, "local": True}
        self.check("GET /api/trips", trips_api.api_trips(self.c, {}, {}))   # none yet
        made = trips_api.api_trip_add(self.c, {}, {"name": "Cabin weekend"})
        self.check("POST /api/trips", made)
        seg = trips_api.api_segment_add(self.c, {}, {"kind": "flight", "origin": "AKL", "destination": "LAX",
                                                      "start_local": "2026-03-01T22:15", "end_local": "2026-03-01T15:10",
                                                      "details": {"seat": "34K"}, "travelers": [{"name": "DOE/JANE MS"}]})
        self.check("POST /api/segments", seg)
        self.check("GET /api/segments/{id}", trips_api.api_segment(self.c, {}, {}, str(seg["id"])))
        self.check("POST /api/segments/{id}", trips_api.api_segment_edit(self.c, {}, {"status": "changed"}, str(seg["id"])))
        self.check("GET /api/trips", trips_api.api_trips(self.c, {}, {}))
        self.check("GET /api/trips/{id}", trips_api.api_trip(self.c, {}, {}, str(seg["trip_id"])))
        self.check("POST /api/trips/{id}", trips_api.api_trip_edit(self.c, {}, {"notes": "Skates"}, str(made["id"])))
        self.check("POST /api/trips/{id}/merge", trips_api.api_trip_merge(self.c, {}, {"merge": seg["trip_id"]}, str(made["id"])))
        other = trips_api.api_segment_add(self.c, {}, {"kind": "hotel", "origin": "Harbour Hotel", "start_zone": "Europe/London",
                                                        "end_zone": "Europe/London", "start_local": "2026-06-02T15:00",
                                                        "end_local": "2026-06-08T10:00", "trip_id": made["id"]})
        self.check("POST /api/trips/{id}/split", trips_api.api_trip_split(self.c, {}, {"segment_ids": [other["id"]]}, str(made["id"])))
        self.check("DELETE /api/segments/{id}", trips_api.api_segment_remove(self.c, {}, {}, str(other["id"])))
        self.check("DELETE /api/trips/{id}", trips_api.api_trip_remove(self.c, {}, {}, str(made["id"])))
        self.check("GET /api/airports/{id}", trips_api.api_airport(self.c, {}, {}, "AKL"))

    def test_stats(self):
        _current.user = {"name": None, "email": None, "local": True}
        trips_api.api_segment_add(self.c, {}, {"kind": "flight", "origin": "JFK", "destination": "LHR",
                                                "start_local": "2026-06-01T19:00", "end_local": "2026-06-02T07:10",
                                                "details": {"flight_number": "BA 112", "seat": "12A", "cabin": "Business"}})
        trips_api.api_segment_add(self.c, {}, {"kind": "hotel", "origin": "Harbour Hotel", "destination": "London",
                                                "provider": "Example Hotels", "start_zone": "Europe/London",
                                                "end_zone": "Europe/London", "start_local": "2026-06-02T15:00",
                                                "end_local": "2026-06-08T10:00"})
        self.check("GET /api/stats", stats_api.api_stats(self.c, {}, {}))
        self.check("GET /api/stats", stats_api.api_stats(self.c, {"person": ["all"], "year": ["2026"]}, {}))
        self.check("GET /api/distance-unit", stats_api.api_distance_unit(self.c, {}, {}))
        self.check("POST /api/distance-unit", stats_api.api_distance_unit_save(self.c, {}, {"distance_unit": "km"}))

    def test_flight_status(self):
        _current.user = {"name": None, "email": None, "local": True}
        with mock.patch.dict("os.environ", {"RAPIDAPI_KEY": "test-key-12345678"}):
            self.check("GET /api/flight-status", flightstatus_api.api_flight_statuses(self.c, {}, {}))   # nothing yet
            seg = trips_api.api_segment_add(self.c, {}, {"kind": "flight", "origin": "JFK", "destination": "LHR",
                                                          "start_local": "2026-11-20T19:00", "end_local": "2026-11-21T07:10",
                                                          "details": {"flight_number": "EX 101"}})
            found = flight_service.Status(state="delayed", origin="JFK", destination="LHR", dep_scheduled="2026-11-20T19:00",
                                          dep_estimated="2026-11-20T19:50", dep_gate="B24", arr_scheduled="2026-11-21T07:10")
            with mock.patch.object(flight_service, "fetch", return_value=found):
                refreshed = flightstatus_api.api_flight_status_refresh(self.c, {}, {}, str(seg["id"]))
            self.assertEqual([s["state"] for s in refreshed["statuses"]], ["delayed"])
            self.check("POST /api/flight-status/{id}", refreshed)
            self.check("GET /api/flight-status", flightstatus_api.api_flight_statuses(self.c, {}, {}))
        db.set_setting(self.c, sk.FLIGHT_STATUS_PAUSED, '{"until": 4102444800, "reason": "rate"}')   # and the paused reply
        with mock.patch.dict("os.environ", {"RAPIDAPI_KEY": "test-key-12345678"}):
            paused = flightstatus_api.api_flight_statuses(self.c, {}, {})
        self.assertEqual(paused["paused"]["reason"], "rate")   # type: ignore[index]
        self.check("GET /api/flight-status", paused)


class Mismatches(unittest.TestCase):
    """The check above notices a reply that isn't the contract's."""

    def test_a_renamed_field_a_wrong_type_and_a_missing_one(self):
        st = {"version": "dev", "database": "sqlite", "user": {"name": None, "email": None, "local": True},
              "last_backup": None, "review_count": 0, "person_id": None}
        schema = reply_schema("GET /api/state")
        self.assertEqual(problems(st, schema), [])
        renamed = {("backed_up" if k == "last_backup" else k): v for k, v in st.items()}
        self.assertEqual(problems(renamed, schema), ["reply: no 'last_backup'", "reply: 'backed_up' isn't in the contract"])
        self.assertEqual(problems({**st, "version": 3}, schema), ["reply.version: 3 isn't string"])
        self.assertEqual(problems({**st, "database": "mysql"}, schema), ["reply.database: 'mysql' isn't one of ['sqlite', 'postgres']"])
        self.assertEqual(problems({**st, "user": {"name": None, "email": None, "local": "yes"}}, schema),
                         ['reply.user.local: "yes" isn\'t boolean'])
        self.assertEqual(problems({**st, "last_backup": 5}, schema), ["reply.last_backup: 5 isn't string or null"])


class Generated(unittest.TestCase):
    def test_the_generated_files_are_current(self):
        doc = contract.build()
        self.assertEqual(contract.OPENAPI_OUT.read_text(), contract.render_json(doc), "run `make api-contract`")
        self.assertEqual(contract.TS_OUT.read_text(), contract.render_ts(doc), "run `make api-contract`")

    def test_only_routes_typed_with_the_contract_s_types_are_covered(self):
        self.assertEqual(covered(), {"GET /api/state", "POST /api/backup/inspect", "POST /api/restore", "GET /api/mailboxes",
                                     "POST /api/mailboxes/connect", "DELETE /api/mailboxes/{id}", "POST /api/mailboxes/{id}/scan",
                                     "GET /api/ai", "POST /api/ai",
                                     "GET /api/review", "POST /api/review/who/{id}", "POST /api/review/{id}/ignore", "DELETE /api/review/{id}",
                                     "GET /api/people", "POST /api/people",
                                     "POST /api/people/{id}", "DELETE /api/people/{id}",
                                     "GET /api/trips", "POST /api/trips", "GET /api/trips/{id}", "POST /api/trips/{id}",
                                     "DELETE /api/trips/{id}", "POST /api/trips/{id}/merge", "POST /api/trips/{id}/split",
                                     "POST /api/segments", "GET /api/segments/{id}", "POST /api/segments/{id}",
                                     "DELETE /api/segments/{id}", "GET /api/airports/{id}",
                                     "POST /api/import/preview", "POST /api/import",
                                     "GET /api/stats", "GET /api/distance-unit", "POST /api/distance-unit", "GET /api/flight-status", "POST /api/flight-status/{id}",
                                     "GET /api/loyalty", "POST /api/loyalty", "POST /api/loyalty/{id}", "DELETE /api/loyalty/{id}",
                                     "POST /api/loyalty/{id}/reveal",
                                     "GET /api/reminders", "POST /api/reminders", "POST /api/reminders/devices",
                                     "DELETE /api/reminders/devices/{id}", "POST /api/feed", "DELETE /api/feed"})
        self.assertNotIn("GET /api/backup", covered())   # typed, but as a download (common.Response)
        self.assertNotIn("GET /api/mailboxes/callback", covered())   # and this one as a redirect

    def describe(self, annotation: str) -> str:
        types = {"Thing": {"doc": None, "fields": []}}
        return contract.ts_type(contract.schema(ast.parse(annotation, mode="eval").body, types, set(), "test"))

    def test_types(self):
        self.assertEqual(self.describe("str | None"), "string | null")
        self.assertEqual(self.describe("int | float"), "number")
        self.assertEqual(self.describe('Literal["a", "b"] | None'), '"a" | "b" | null')
        self.assertEqual(self.describe("list[Thing | None]"), "(Thing | null)[]")
        self.assertEqual(self.describe("dict[str, list[float]]"), "Record<string, number[]>")
        self.assertEqual(self.describe("'Thing'"), "Thing")
        self.assertEqual(self.describe("Any"), "unknown")
        with self.assertRaises(contract.ContractError):
            self.describe("set[str]")

    def test_paths_number_their_ids(self):
        self.assertEqual(contract.openapi_path("/api/things/{id}/parts/{id}/remove"),
                         ("/api/things/{id}/parts/{id2}/remove", ["id", "id2"]))


if __name__ == "__main__":
    unittest.main()

