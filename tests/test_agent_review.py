import base64
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("agent_review", ROOT / ".github" / "scripts" / "agent_review.py")
assert _spec and _spec.loader
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)


class Detect(unittest.TestCase):
    def test_an_agent_s_commits_or_description_make_it_an_agent_s_pull_request(self):
        self.assertTrue(ar.is_agent(["fix: x\n\nClaude-Session: https://claude.ai/code/session_x\n"], ""))
        self.assertTrue(ar.is_agent(["fix: x\n\nCo-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>\n"], ""))
        self.assertTrue(ar.is_agent(["fix: x"], "- change\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"))

    def test_a_person_s_pull_request_is_not(self):
        self.assertFalse(ar.is_agent(["fix: x\n\nCo-Authored-By: Pat Doe <pat@example.com>\n"], "Mentions Claude in passing."))


class Report(unittest.TestCase):
    def verdict(self, output, key=""):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(output if isinstance(output, str) else json.dumps(output))
        self.addCleanup(os.unlink, f.name)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": key, "RUN_URL": "https://example.com/run"}):
            return ar.report(f.name)

    def answer(self, *findings, summary="Looks fine."):
        return {"type": "result", "is_error": False, "structured_output": {"summary": summary, "findings": list(findings)}}

    def test_no_findings_passes(self):
        v = self.verdict(self.answer())
        self.assertEqual(v["verdict"], "pass")
        self.assertIn(ar.MARKER, v["comment"])

    def test_advisory_findings_pass(self):
        v = self.verdict(self.answer({"severity": "advisory", "title": "Name", "detail": "Clearer as x."}))
        self.assertEqual((v["verdict"], v["description"]), ("pass", "No blocking findings (1 advisory)"))

    def test_a_blocking_finding_blocks(self):
        v = self.verdict(self.answer({"severity": "blocking", "title": "Drops rows", "detail": "d", "file": "a.py", "line": 3},
                                     {"severity": "advisory", "title": "Nit", "detail": "n"}))
        self.assertEqual(v["verdict"], "blocking")
        self.assertIn("1 blocking finding(s)", v["description"])
        self.assertIn("**Drops rows** (`a.py:3`)", v["comment"])

    def test_an_answer_in_the_reply_text_is_read_too(self):
        reply = 'Done.\n```json\n{"summary": "s", "findings": [{"severity": "blocking", "title": "t", "detail": "d"}]}\n```'
        self.assertEqual(self.verdict({"is_error": False, "result": reply})["verdict"], "blocking")

    def test_anything_unreadable_is_an_error_not_a_pass(self):
        for output in ("not json", {"is_error": True, "result": "API error"}, {"is_error": False, "result": "I approve."},
                       self.answer({"severity": "fine", "title": "t", "detail": "d"})):
            self.assertEqual(self.verdict(output)["verdict"], "error", output)

    def test_mentions_and_the_marker_are_defused(self):
        v = self.verdict(self.answer({"severity": "advisory", "title": "@someone <!-- agent-review -->", "detail": "d"}))
        self.assertNotIn("@someone", v["comment"])
        self.assertEqual(v["comment"].count(ar.MARKER), 1)

    def test_an_answer_carrying_the_api_key_isnt_posted(self):
        v = self.verdict(self.answer(summary="the key is sk-test-123"), key="sk-test-123")
        self.assertEqual((v["verdict"], v["comment"]), ("error", ""))

    def test_an_answer_carrying_the_subscription_s_token_isnt_posted(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-test"}):
            v = self.verdict(self.answer({"severity": "advisory", "title": "t", "detail": "sk-ant-oat01-test"}))
        self.assertEqual((v["verdict"], v["comment"]), ("error", ""))

    def test_outputs_are_one_line_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}), mock.patch("builtins.print"):
                ar.write_outputs({"verdict": "pass", "description": "ok", "comment": "line 1\nline 2\ncomment=injected"})
            lines = out.read_text().splitlines()
        self.assertEqual([ln.split("=", 1)[0] for ln in lines], ["verdict", "description", "comment"])
        self.assertEqual(base64.b64decode(lines[2].split("=", 1)[1]).decode(), "line 1\nline 2\ncomment=injected")


FAKE_CLAUDE = """#!/usr/bin/env bash
{ printf '%s\\n' "$@"; echo "KEY=${ANTHROPIC_API_KEY:-}"; echo "OAUTH=${CLAUDE_CODE_OAUTH_TOKEN:-}";
  echo "MDS=${CLAUDE_CODE_DISABLE_CLAUDE_MDS:-}"; } > "$RECORD"
echo '{"is_error": false, "structured_output": {"summary": "s", "findings": []}}'
"""


@unittest.skipUnless(Path("/bin/bash").exists(), "needs bash")
class Run(unittest.TestCase):

    def run_script(self, **secrets):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        (d / "prompt.md").write_text("Review it.")
        (d / "schema.json").write_text("{}")
        fake = d / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(0o755)
        env = {"PATH": os.environ.get("PATH", ""), "CLAUDE": str(fake), "MODEL": "some-model", "BUDGET": "5",
               "RECORD": str(d / "record"), **secrets}
        done = subprocess.run(["bash", str(ROOT / ".github/scripts/agent-review-run.sh")], cwd=d, env=env,
                              capture_output=True, text=True)
        record = (d / "record").read_text().splitlines() if (d / "record").exists() else []
        output = (d / "output.json").read_text() if (d / "output.json").exists() else ""
        return done, record, output

    def assert_isolated(self, args):
        i = args.index("--tools")
        self.assertEqual(args[i + 1], "Read,Grep,Glob")
        for flag in ("--restricted", "--safe-mode", "--strict-mcp-config", "--disable-slash-commands",
                     "--no-session-persistence", "MDS=1"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(args[args.index("--setting-sources") + 1], "")
        self.assertEqual(args[args.index("--model") + 1], "some-model")
        self.assertNotIn("--bare", args)

    def test_the_subscription_s_token_alone_is_used(self):
        done, args, output = self.run_script(CLAUDE_CODE_OAUTH_TOKEN="oat-token")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_isolated(args)
        self.assertIn("OAUTH=oat-token", args)
        self.assertIn("KEY=", args)
        self.assertIn("structured_output", output)
        self.assertNotIn("oat-token", done.stdout + done.stderr)

    def test_an_api_key_wins_and_the_token_isnt_passed_on(self):
        done, args, _ = self.run_script(ANTHROPIC_API_KEY="api-key", CLAUDE_CODE_OAUTH_TOKEN="oat-token")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_isolated(args)
        self.assertIn("KEY=api-key", args)
        self.assertIn("OAUTH=", args)
        self.assertNotIn("api-key", done.stdout + done.stderr)

    def test_no_secret_fails_without_starting_claude(self):
        done, args, _ = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("Neither an ANTHROPIC_API_KEY nor a CLAUDE_CODE_OAUTH_TOKEN", done.stdout)
        self.assertEqual(args, [])


if __name__ == "__main__":
    unittest.main()
