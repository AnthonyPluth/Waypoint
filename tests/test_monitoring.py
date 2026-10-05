import io
import json
import os
import time
import unittest
import urllib.request
from unittest import mock


import sentry_sdk

from waypoint import monitoring, server
from waypoint.server.handler import _traced, trace_name

from tests.shared import own_database, serve

DSN = "https://publickey@o123.ingest.us.sentry.io/456"
SERVICE = "https://user:secretpass@api.travel.example/v2"


class Capture(sentry_sdk.transport.Transport):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.events = []
        self.items: list[tuple[str, object]] = []   # everything else: transactions, check-ins, logs, metrics

    def capture_envelope(self, envelope):
        self.events += [i.payload.json for i in envelope.items if i.type == "event"]
        self.items += [(i.type, i.payload.json) for i in envelope.items if i.type != "event"]

    def of(self, kind):
        return [p for t, p in self.items if t == kind]


ALL_ON = {"SENTRY_DSN": DSN}   # everything is on with just a DSN


def start(env=None) -> Capture:
    """Reporting on (with ALL_ON unless `env` says otherwise), sending to a Capture instead of Sentry."""
    with mock.patch.dict(os.environ, env or ALL_ON), mock.patch("builtins.print"):
        assert monitoring.init()
    transport = Capture()
    sentry_sdk.get_client().transport = transport
    return transport


class MonitoringTests(unittest.TestCase):
    def tearDown(self):
        sentry_sdk.get_client().close()
        sentry_sdk.init(dsn=None)
        monitoring._enabled = False

    def test_off_without_a_dsn(self):
        with mock.patch.dict(os.environ, {"SENTRY_DSN": ""}):
            self.assertFalse(monitoring.init())
            self.assertIsNone(monitoring.browser_config())
            self.assertNotIn("sentry.io", server.content_security_policy("n"))
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                with mock.patch("traceback.print_exc"):
                    monitoring.report()   # just logged

    def test_what_a_service_said_is_kept_safe(self):
        # A service's message or an API's error is kept and shown: no long numbers (a booking's, a card's) in it.
        self.assertEqual(monitoring.public_text("Northwind Air: booking 123456789 needs a new login (HTTP 401)"),
                         "Northwind Air: booking [number] needs a new login (HTTP 401)")
        self.assertEqual(monitoring.public_text(f"refused at {SERVICE}/accounts?x=1"),
                         monitoring.scrub(f"refused at {SERVICE}/accounts?x=1"))
        self.assertIsNone(monitoring.public_text(None))

    def test_secrets_are_blanked(self):
        text = f"Couldn't reach {SERVICE}/accounts?start-date=1 with access-production-1234abcd-9f00-4c1e"
        out = monitoring.scrub(text)
        for secret in ("secretpass", "user:", "start-date", "1234abcd"):
            self.assertNotIn(secret, out)
        self.assertIn("api.travel.example/v2/accounts", out)

    def test_a_report_carries_the_error_and_nothing_private(self):
        with mock.patch.dict(os.environ, {"SENTRY_DSN": DSN, "WAYPOINT_VERSION": "v9.9.9"}):
            self.assertTrue(monitoring.init())
        transport = Capture()
        sentry_sdk.get_client().transport = transport
        balance = sum([1000, 234.56])   # a local variable: its value must not be sent  # noqa: F841
        try:
            raise ValueError(f"SimpleFIN said no: {SERVICE}?token=abc")
        except ValueError:
            with mock.patch("traceback.print_exc"):
                monitoring.report(ref="abcd1234")
        sentry_sdk.flush()
        self.assertEqual(len(transport.events), 1)
        ev = transport.events[0]
        self.assertEqual((ev["release"], ev["tags"]["ref"]), ("v9.9.9", "abcd1234"))
        exc = ev["exception"]["values"][0]
        self.assertEqual(exc["type"], "ValueError")
        self.assertNotIn("secretpass", exc["value"])
        self.assertNotIn("token=abc", exc["value"])
        self.assertTrue(all("vars" not in f for f in exc["stacktrace"]["frames"]))
        self.assertNotIn("1234.56", str(ev))

    def test_database_errors_lose_the_row_they_were_writing(self):
        import sqlalchemy as sa
        engine = sa.create_engine("sqlite://")
        with engine.begin() as c:
            c.exec_driver_sql("CREATE TABLE tx (id INTEGER PRIMARY KEY, payee TEXT, amount REAL)")
            c.exec_driver_sql("INSERT INTO tx VALUES (1, 'WHOLE FOODS', 87.12)")
        transport = start({"SENTRY_DSN": DSN})
        try:
            with engine.begin() as c:
                # raw SQL: a throwaway table on a plain engine, with the bound parameters the error report must drop
                c.execute(sa.text("INSERT INTO tx VALUES (:id, :payee, :amount)"), {"id": 1, "payee": "WHOLE FOODS", "amount": 87.12})
        except sa.exc.IntegrityError as e:
            self.assertIn("WHOLE FOODS", str(e))   # what SQLAlchemy says, and the local log keeps
            with mock.patch("traceback.print_exception"):
                monitoring.report(e)
        sentry_sdk.flush()
        value = transport.events[0]["exception"]["values"][-1]["value"]
        self.assertNotIn("WHOLE FOODS", value)
        self.assertNotIn("87.12", value)
        self.assertIn("[SQL: INSERT INTO tx VALUES", value)   # the query itself helps, and holds no data
        self.assertIn("[parameters: [Filtered]]", value)
        # Postgres's own details name the values too.
        pg = ("(psycopg.errors.NotNullViolation) null value in column \"category\" violates not-null constraint\n"
              "DETAIL:  Failing row contains (tx-9, 2026-09-01, -87.12, WHOLE FOODS, null).\n"
              "[SQL: INSERT INTO transactions ...]\n[parameters: {'id': 'tx-9', 'amount': -87.12}]\n"
              "(Background on this error at: https://sqlalche.me/e/20/gkpj)")
        dup = "DETAIL:  Key (plaid_account_id)=(p-csp) already exists."
        out = monitoring.scrub(pg) + monitoring.scrub(dup)
        for private in ("WHOLE FOODS", "87.12", "tx-9", "p-csp"):
            self.assertNotIn(private, out)
        self.assertIn("Failing row contains ([Filtered])", out)
        self.assertIn("Key (plaid_account_id)=([Filtered]) already exists", out)
        self.assertIn("(Background on this error at: https://sqlalche.me/e/20/gkpj)", out)
        # Text that repeats a marker is scrubbed in linear time (a regex could take minutes on it).
        import time
        for marker in ("[parameters: ", "Failing row contains (", "Key (", "Key ()=("):
            started = time.monotonic()
            monitoring.scrub(marker * 50_000)
            self.assertLess(time.monotonic() - started, 1, marker)

    def test_request_details_are_trimmed(self):
        ev = monitoring._before_send({"request": {"method": "POST", "url": "https://waypoint.example/api/backup/inspect?x=1",
                                                  "data": {"guests": 5}, "cookies": {"waypoint_session": "s"},
                                                  "headers": {"Authorization": "Bearer t"}},
                                      "user": {"email": "a@b.c"}, "extra": {"body": "x"}}, {})
        self.assertEqual(ev, {"request": {"method": "POST", "url": "https://waypoint.example/api/backup/inspect"}, "message": None})
        crumb = monitoring._before_breadcrumb({"category": "httplib", "data": {"url": SERVICE + "/accounts?a=1",
                                               "http.query": "a=1"}}, {})
        self.assertEqual(crumb["data"], {"url": "https://api.travel.example/v2/accounts"})
        crumb = monitoring._before_breadcrumb({"category": "query", "message": "SELECT 1 WHERE x=?", "data": {"params": [5]}}, {})
        self.assertNotIn("data", crumb)

    def test_the_web_app_may_report_to_sentry_only(self):
        with mock.patch.dict(os.environ, {"SENTRY_DSN": DSN, "SENTRY_BROWSER_DSN": ""}):
            self.assertEqual(monitoring.browser_config()["dsn"], DSN)
            self.assertIn("connect-src 'self' https://o123.ingest.us.sentry.io;", server.content_security_policy("n"))
            # Workers are the service worker (/sw.js) only: no blob: scripts, which a replay's compression worker would need.
            self.assertIn("worker-src 'self';", server.content_security_policy("n"))
            self.assertNotIn("blob:", server.content_security_policy("n"))
        with mock.patch.dict(os.environ, {"SENTRY_DSN": DSN, "WAYPOINT_SENTRY_BROWSER": "0"}):
            self.assertIsNone(monitoring.browser_config())
        with mock.patch.dict(os.environ, {"SENTRY_DSN": "http://k@evil.example/1"}):   # not https: never allowed
            self.assertIsNone(monitoring.browser_config())
            self.assertIsNone(monitoring.browser_origin())


    def test_who_is_signed_in_is_a_code_that_does_not_say_who(self):
        key = {"WAYPOINT_SECRET_KEY": "k" * 40}
        with mock.patch.dict(os.environ, key):
            ann = monitoring.user_id({"sub": "google|1234567890", "email": "ann@example.com", "name": "Ann"})
            self.assertRegex(ann, r"^[0-9a-f]{16}$")
            self.assertEqual(monitoring.user_id({"sub": "google|1234567890"}), ann)   # the same person, the same code
            self.assertNotEqual(monitoring.user_id({"sub": "google|1234567891"}), ann)
            self.assertEqual(monitoring.user_id({"name": None, "email": None, "local": True}), "local")   # no OIDC
            self.assertIsNone(monitoring.user_id(None))
            self.assertIsNone(monitoring.user_id({"email": "ann@example.com"}))   # no sign-in id: nobody
            with mock.patch.dict(os.environ, {**ALL_ON, **key}):
                self.assertEqual(monitoring.browser_config({"sub": "google|1234567890"})["user_id"], ann)
                self.assertIsNone(monitoring.browser_config()["user_id"])
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": "j" * 40}):   # someone else's Waypoint: another code
            self.assertNotEqual(monitoring.user_id({"sub": "google|1234567890"}), ann)

    def test_a_request_says_who_asked_and_nothing_else_does(self):
        transport = start()
        ann = {"sub": "google|1234567890", "email": "ann@example.com", "name": "Ann"}
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": "k" * 40}), mock.patch("sys.stderr"):
            code = monitoring.user_id(ann)
            monitoring.set_user(ann)   # outside a request: the scope is shared, so nothing is set
            monitoring.report(RuntimeError("before"))
            with monitoring.request("GET", "/api/state", {}):
                monitoring.set_user(ann)
                monitoring.report(RuntimeError("during"))
            monitoring.report(RuntimeError("after"))
        sentry_sdk.flush()
        users = {e["exception"]["values"][0]["value"]: e.get("user") for e in transport.events}
        self.assertEqual(users, {"before": None, "during": {"id": code}, "after": None})
        self.assertNotIn("ann@example.com", json.dumps(transport.events))

    def test_everything_is_on_with_just_a_dsn(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SENTRY_")}
        with mock.patch.dict(os.environ, {**env, "SENTRY_DSN": DSN}, clear=True):
            cfg = monitoring.browser_config()
            self.assertEqual(set(cfg), {"dsn", "environment", "release", "user_id"})   # the web app turns on all of its own
            self.assertNotIn("replay", json.dumps(cfg).lower())   # and never Session Replay
            self.assertEqual(cfg["environment"], "production")
            self.assertTrue(monitoring.browser_profiling())
        transport = start({**env, "SENTRY_DSN": DSN})
        opts = sentry_sdk.get_client().options
        self.assertEqual((opts["traces_sample_rate"], opts["profile_session_sample_rate"], opts["profile_lifecycle"]),
                         (1.0, 1.0, "trace"))
        self.assertEqual((opts["enable_logs"], opts["enable_metrics"]), (True, True))
        self.assertTrue(monitoring.tracing())
        with mock.patch("builtins.print"):
            monitoring.log("hello")
        monitoring.metric("count", "waypoint.test", 1)
        self.assertIsNotNone(monitoring.cron_start("x", None))
        sentry_sdk.flush()
        self.assertTrue(transport.of("log"))
        self.assertIn("waypoint.test", json.dumps(transport.items))

    def test_a_retired_setting_set_to_off_is_warned_about(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SENTRY_")}
        with mock.patch.dict(os.environ, {**env, "SENTRY_AI_CONTENT": "0", "SENTRY_REPLAY_SAMPLE_RATE": "0.1",
                                          "SENTRY_LOGS": "true"}, clear=True):
            self.assertEqual(monitoring.retired_off(), ["SENTRY_REPLAY_SAMPLE_RATE", "SENTRY_AI_CONTENT"])
        printed = io.StringIO()
        with mock.patch("sys.stderr", printed):
            start({**env, "SENTRY_DSN": DSN, "SENTRY_AI_CONTENT": "off"})
        self.assertIn("SENTRY_AI_CONTENT is no longer read", printed.getvalue())
        with mock.patch.dict(os.environ, {**env, "SENTRY_AI_CONTENT": "0"}, clear=True), mock.patch("sys.stderr", io.StringIO()) as quiet:
            self.assertFalse(monitoring.init())   # without a DSN nothing's sent, so there's nothing to warn about
        self.assertEqual(quiet.getvalue(), "")
        # The web app reports with its own DSN alone, so that's warned about too.
        with mock.patch.dict(os.environ, {**env, "SENTRY_BROWSER_DSN": DSN, "SENTRY_REPLAY_SAMPLE_RATE": "0"}, clear=True), \
                mock.patch("sys.stderr", io.StringIO()) as browser_only:
            self.assertFalse(monitoring.init())
        self.assertIn("SENTRY_REPLAY_SAMPLE_RATE is no longer read", browser_only.getvalue())

    def test_a_replay_setting_is_warned_about_whatever_its_value(self):
        # Waypoint never sends replays, so a replay rate is warned about even set to on, not quietly ignored.
        env = {k: v for k, v in os.environ.items() if not k.startswith("SENTRY_")}
        for value in ("1", "1.0", "true", "on", "0", "0.25"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {**env, "SENTRY_REPLAY_SAMPLE_RATE": value,
                                                                         "SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE": value}, clear=True):
                self.assertEqual(monitoring.retired_off(), ["SENTRY_REPLAY_SAMPLE_RATE", "SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE"])
        printed = io.StringIO()
        with mock.patch("sys.stderr", printed):
            start({**env, "SENTRY_DSN": DSN, "SENTRY_REPLAY_SAMPLE_RATE": "1"})
        self.assertIn("SENTRY_REPLAY_SAMPLE_RATE is no longer read", printed.getvalue())
        self.assertIn("never records sessions or sends replays", printed.getvalue())
        self.assertNotIn("replays,", printed.getvalue())   # replays aren't among what's sent
        with mock.patch.dict(os.environ, {**env, "SENTRY_DSN": DSN, "SENTRY_REPLAY_SAMPLE_RATE": "1"}, clear=True):
            self.assertNotIn("replay", json.dumps(monitoring.browser_config()).lower())

    def test_the_web_app_gets_no_config_without_a_dsn(self):
        with mock.patch.dict(os.environ, {"SENTRY_DSN": "", "SENTRY_BROWSER_DSN": ""}):
            self.assertIsNone(monitoring.browser_config())
            self.assertFalse(monitoring.browser_profiling())

    def test_nothing_is_sent_without_a_dsn(self):
        self.assertFalse(monitoring._enabled)
        with monitoring.request("GET", "/api/state", {}) as tx, mock.patch("builtins.print"):
            monitoring.log("hello")
            monitoring.metric("count", "waypoint.test", 1)
            self.assertIsNone(monitoring.cron_start("x", "0 7 * * *"))
        self.assertIsNone(tx)
        self.assertFalse(monitoring.tracing())
        self.assertEqual(monitoring.trace_meta(), "")

    def test_requests_are_named_by_route(self):
        cases = {"/api/state": "/api/state", "/api/backup/inspect": "/api/backup/inspect", "/api/restore": "/api/restore",
                 "/api/nope/secret-name": "/api/*", "/api/trips/kyoto%20spring": "/api/*",
                 "/": "/", "/trips/kyoto": "/", "/auth/callback": "/auth/callback", "/auth/login": "/auth/login",
                 "/auth/whatever": "/", "/oauth/token": "/"}
        for path, name in cases.items():
            self.assertEqual(trace_name(path), name, path)
        for path in ("/healthz", "/assets/index-abc.js", "/sw.js", "/logo.svg", "/page.css"):
            self.assertFalse(_traced(path), path)
        for path in ("/", "/api/state", "/api/backup", "/auth/login", "/auth/callback", "/settings"):
            self.assertTrue(_traced(path), path)

    def test_a_request_is_traced_without_its_query_or_values(self):
        own_database(self)
        transport = start()
        base = serve(self)
        trace_id = "abcdef0123456789abcdef0123456789"
        req = urllib.request.Request(f"{base}/api/state?q=rent-money&limit=5",
                                     headers={"sentry-trace": f"{trace_id}-1234567890abcdef-1"})
        with mock.patch("builtins.print"):
            with urllib.request.urlopen(req, timeout=20) as r:
                self.assertEqual(r.status, 200)
            urllib.request.urlopen(f"{base}/healthz", timeout=20).close()
        # The server finishes a request's transaction just after it has sent the response, so on a busy machine the
        # transaction can still be on its way: wait for it (briefly) rather than read the transport too soon.
        deadline = time.monotonic() + 10
        while True:
            sentry_sdk.flush()
            txs = transport.of("transaction")
            if txs or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        self.assertEqual([t["transaction"] for t in txs], ["GET /api/state"])   # /healthz isn't traced
        tx = txs[0]
        self.assertEqual(tx["contexts"]["trace"]["trace_id"], trace_id)   # continues the web app's trace
        self.assertEqual(tx["contexts"]["trace"]["data"]["http.response.status_code"], 200)
        self.assertEqual(tx["user"], {"id": "local"})   # who asked (without OIDC everyone is "local"; see user_id)
        self.assertTrue(any(sp["op"] == "db" for sp in tx["spans"]))   # database queries, as spans
        self.assertNotIn("rent-money", json.dumps(tx))
        logs = json.dumps(transport.of("log"))
        self.assertIn("GET /api/state 200", logs)
        self.assertNotIn("127.0.0.1", logs)   # the access log line in Sentry has no address

    def test_spans_lose_queries_and_credentials(self):
        tx = monitoring._before_send_transaction({
            "request": {"url": "https://waypoint.test/api/x?q=1", "headers": {"a": "b"}},
            "user": {"id": "3f2a9c1d0b7e4a65", "email": "a@b.c", "ip_address": "10.1.2.3"},
            "spans": [{"op": "http.client", "description": f"GET {SERVICE}/accounts?start-date=1",
                       "data": {"url": SERVICE + "/accounts", "http.query": "start-date=1", "db.params": [5]}}],
        }, {})
        text = json.dumps(tx)
        for secret in ("secretpass", "start-date", "headers", "a@b.c", "10.1.2.3", "db.params"):
            self.assertNotIn(secret, text)
        self.assertEqual(tx["user"], {"id": "3f2a9c1d0b7e4a65"})   # the code for who's signed in, and nothing else
        self.assertEqual(tx["spans"][0]["data"]["url"], "https://api.travel.example/v2/accounts")

    def test_background_work_is_traced_and_timed(self):
        transport = start()
        with monitoring.task("nightly backup"), monitoring.span("db", "SELECT 1"):
            pass
        with self.assertRaises(RuntimeError), monitoring.task("nightly backup"):
            raise RuntimeError("no")
        sentry_sdk.flush()
        self.assertEqual([t["transaction"] for t in transport.of("transaction")][:1], ["nightly backup"])
        metrics = json.dumps(transport.items)
        self.assertIn("waypoint.task.duration", metrics)
        self.assertIn('"error"', metrics)

    def test_profiling_runs_with_every_trace(self):
        start()
        opts = sentry_sdk.get_client().options
        self.assertEqual((opts["profile_session_sample_rate"], opts["profile_lifecycle"]), (1.0, "trace"))
        self.assertEqual(opts["trace_propagation_targets"], [])   # no headers to banks

    def test_a_scheduled_job_checks_in_and_an_unscheduled_one_makes_no_monitor(self):
        transport = start({**ALL_ON, "TZ": "America/Chicago"})
        with mock.patch.dict(os.environ, {"TZ": "America/Chicago"}):
            monitoring.cron_finish(monitoring.cron_start("waypoint-nightly-backup", "0 7 * * *"), True)
            monitoring.cron_finish(monitoring.cron_start("waypoint-nightly-backup", "0 7 * * *"), False)
            # Without a schedule (run by hand), it checks in without one: it doesn't create a daily monitor.
            monitoring.cron_finish(monitoring.cron_start("waypoint-nightly-backup", None), True)
        sentry_sdk.flush()
        checkins = transport.of("check_in")
        self.assertEqual([c["status"] for c in checkins], ["in_progress", "ok", "in_progress", "error", "in_progress", "ok"])
        self.assertTrue(all("monitor_config" not in c for c in checkins[4:]))
        self.assertEqual({c["monitor_slug"] for c in checkins}, {"waypoint-nightly-backup"})
        self.assertEqual(checkins[0]["monitor_config"]["schedule"], {"type": "crontab", "value": "0 7 * * *"})
        self.assertEqual(checkins[0]["monitor_config"]["timezone"], "America/Chicago")
        self.assertEqual(checkins[0]["check_in_id"], checkins[1]["check_in_id"])

    def test_the_monitor_uses_waypoints_own_time_zone(self):
        for tz, zone in (("America/Chicago", "America/Chicago"), (":Europe/Berlin", "Europe/Berlin"), ("UTC", "UTC"),
                         ("EST5EDT", None), ("CST6CDT,M3.2.0,M11.1.0", None), ("/usr/share/zoneinfo/Asia/Tokyo", None)):
            with mock.patch.dict(os.environ, {"TZ": tz}):
                self.assertEqual(monitoring.local_timezone(), zone, tz)
        env = {k: v for k, v in os.environ.items() if k != "TZ"}
        with mock.patch.dict(os.environ, env, clear=True):   # no TZ: the system's zone
            with mock.patch("os.path.realpath", return_value="/usr/share/zoneinfo/America/Denver"):
                self.assertEqual(monitoring.local_timezone(), "America/Denver")
            with mock.patch("os.path.realpath", return_value="/etc/localtime"), \
                    mock.patch("builtins.open", mock.mock_open(read_data="Australia/Perth\n")):
                self.assertEqual(monitoring.local_timezone(), "Australia/Perth")
        # A zone that can't be told: the check-in doesn't create the monitor (its schedule would be off by hours).
        transport = start({**ALL_ON, "TZ": "EST5EDT"})
        with mock.patch.dict(os.environ, {"TZ": "EST5EDT"}):
            monitoring.cron_finish(monitoring.cron_start("waypoint-bank-sync", "0 7 * * *"), True)
        sentry_sdk.flush()
        self.assertTrue(all("monitor_config" not in c for c in transport.of("check_in")))
        self.assertEqual(len(transport.of("check_in")), 2)

    def test_logs_are_scrubbed_and_can_say_less_than_the_console(self):
        transport = start()
        with mock.patch("builtins.print") as printed:
            monitoring.log(f"Couldn't reach {SERVICE}", "warning")
            monitoring.log("bad value 1234.56", "warning", remote="bad value")
        self.assertIn("secretpass", str(printed.call_args_list[0]))   # the local log is unchanged
        sentry_sdk.flush()
        sent = json.dumps(transport.of("log"))
        self.assertIn("api.travel.example", sent)
        self.assertNotIn("secretpass", sent)
        self.assertNotIn("1234.56", sent)

    def _ask_once(self, env=None):
        """One agent run asking a model about one made-up hotel stay; returns what reached Sentry, as spans' attributes."""
        transport = start(env)
        reply = {"id": "gen-1", "model": "anthropic/claude-haiku-4.5",
                 "choices": [{"finish_reason": "stop", "message": {"content": '[{"i": 0, "kind": "Lodging", "confidence": 0.9}]'}}],
                 "usage": {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128}}
        prompt = "Which kind of stay is this? HARBOR INN #123, 2026-09-01, 87.12"
        with monitoring.task("sync"), monitoring.ai_agent("Trip sorter", "sync"), \
                monitoring.ai_call("anthropic/claude-haiku-4.5", prompt, max_tokens=500) as s:
            monitoring.ai_result(s, reply, "anthropic/claude-haiku-4.5", reply["choices"][0]["message"]["content"])
        sentry_sdk.flush()
        spans = {sp["name"]: {k: v["value"] for k, v in sp["attributes"].items()} | {"trace_id": sp["trace_id"]}
                 for batch in transport.of("span") for sp in batch["items"]}
        return transport, spans

    def test_an_ai_task_is_an_agent_and_only_its_spans_hold_the_prompt(self):
        transport, spans = self._ask_once()
        agent, chat = spans["invoke_agent Trip sorter"], spans["chat anthropic/claude-haiku-4.5"]
        self.assertEqual((agent["sentry.op"], agent["gen_ai.agent.name"], agent["gen_ai.pipeline.name"]),
                         ("gen_ai.invoke_agent", "Trip sorter", "sync"))
        self.assertEqual((chat["sentry.op"], chat["gen_ai.agent.name"], chat["gen_ai.provider.name"]),
                         ("gen_ai.chat", "Trip sorter", "openrouter"))
        self.assertEqual((chat["gen_ai.usage.input_tokens"], chat["gen_ai.usage.output_tokens"], chat["gen_ai.response.model"]),
                         (120, 8, "anthropic/claude-haiku-4.5"))
        self.assertTrue(chat["gen_ai.conversation.id"].startswith("trip-sorter-"))   # the run is one conversation
        self.assertEqual(chat["trace_id"], transport.of("transaction")[0]["contexts"]["trace"]["trace_id"])
        # The prompt and reply are on the chat span; nothing else carries what they do.
        items = json.loads(json.dumps(transport.items))
        for batch in (p for t, p in items if t == "span"):
            for sp in batch["items"]:
                for k in ("gen_ai.input.messages", "gen_ai.output.messages"):
                    sp["attributes"].pop(k, None)
        everything = json.dumps(items)
        for private in ("HARBOR INN", "87.12", "Lodging"):
            self.assertNotIn(private, everything)
        self.assertIn("waypoint.ai.tokens", everything)

    def test_the_prompt_and_reply_are_on_the_chat_span(self):
        _, spans = self._ask_once()
        chat = spans["chat anthropic/claude-haiku-4.5"]
        sent = json.loads(chat["gen_ai.input.messages"])
        self.assertEqual(sent[0]["role"], "user")
        self.assertIn("HARBOR INN", sent[0]["parts"][0]["content"])
        self.assertIn("Lodging", chat["gen_ai.output.messages"])

    def test_mcp_calls_name_the_tool_not_its_arguments(self):
        transport = start()
        msg = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "trips", "arguments": {"q": "my-landlord"}}}
        with monitoring.task("mcp"), monitoring.mcp_call(msg) as sp:
            monitoring.mcp_result(sp, {"result": {"isError": True}})
        sentry_sdk.flush()
        span = transport.of("transaction")[0]["spans"][0]
        self.assertEqual((span["op"], span["description"]), ("mcp.server", "tools/call trips"))
        self.assertEqual((span["data"]["mcp.tool.name"], span["data"]["mcp.tool.result.is_error"]), ("trips", True))
        self.assertNotIn("my-landlord", json.dumps(span))

    def test_the_page_carries_its_trace_to_the_browser(self):
        start()
        with monitoring.request("GET", "/", {}) as tx:
            meta = monitoring.trace_meta()
        self.assertIn(f'<meta name="sentry-trace" content="{tx.trace_id}-', meta)
        self.assertIn('<meta name="baggage"', meta)


if __name__ == "__main__":
    unittest.main()
