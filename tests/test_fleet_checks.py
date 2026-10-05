"""tools/fleet_checks.py: the checks that replaced instructions (one migration head, migrations tested, agents' commit
trailers, workflow conventions), each passing on the repository as it is and failing on the mistake it is for."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("fleet_checks", ROOT / "tools" / "fleet_checks.py")
assert _spec and _spec.loader
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

MIGRATION = "revision = {rev!r}\ndown_revision = {down!r}\n\ndef upgrade():\n    pass\n"


class Migrations(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        # A repository that started the rule at 0036 (Waypoint's own starts at 0001), so the one before needs no test.
        patch = mock.patch.object(fc, "TESTED_FROM", "0036")
        patch.start()
        self.addCleanup(patch.stop)
        self.write("0035_a.py", "0035", None)
        self.write("0036_b.py", "0036", "0035")

    def write(self, name, rev, down):
        (self.dir / name).write_text(MIGRATION.format(rev=rev, down=down))

    def problems(self, tests="def test_0036_b(self): ...\ndef test_0037_c(self): ...\ndef test_0038_d(self): ...\n"):
        return fc.check_migrations(fc.migrations(self.dir), tests)

    def test_the_repository_passes(self):
        self.assertEqual(fc.check_migrations(fc.migrations(), fc.MIGRATION_TESTS.read_text()), [])

    def test_a_chain_with_tests_passes(self):
        self.write("0037_c.py", "0037", "0036")
        self.assertEqual(self.problems(), [])

    def test_two_branches_each_adding_the_next_number_leave_two_heads(self):
        # What nearly merged: two pull requests both added a migration after the same parent.
        self.write("0037_c.py", "0037", "0036")
        self.write("0038_d.py", "0038", "0036")
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("more than one Alembic head (0037, 0038)", problems[0])

    def test_the_same_number_twice_is_caught(self):
        self.write("0037_c.py", "0037", "0036")
        self.write("0037_d.py", "0037", "0036")
        self.assertTrue(any("'0037' is used more than once (0037_c.py, 0037_d.py)" in p for p in self.problems()))

    def test_a_new_migration_without_its_own_test_fails(self):
        self.write("0037_c.py", "0037", "0036")
        problems = self.problems(tests="def test_0036_b(self): ...\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("0037_c.py: no test of its own", problems[0])

    def test_migrations_before_the_rule_need_no_test(self):
        self.assertEqual(self.problems(tests="def test_0036_b(self): ...\n"), [])

    def test_a_parent_that_isnt_there_and_a_misnamed_file_fail(self):
        self.write("0037_c.py", "0037", "0099")
        self.write("c_0038.py", "0038", "0037")
        problems = self.problems()
        self.assertTrue(any("down_revision '0099' is no migration here" in p for p in problems))
        self.assertTrue(any("c_0038.py: the file name should start with its revision" in p for p in problems))

    def test_a_merge_migration_follows_both_heads(self):
        self.write("0037_c.py", "0037", "0036")
        self.write("0038_d.py", "0038", "0036")
        (self.dir / "0039_merge.py").write_text("revision = '0039'\ndown_revision = ('0037', '0038')\n")
        self.assertEqual(self.problems(tests="def test_0036_b(self): ...\ndef test_0037_c(self): ...\n"
                                             "def test_0038_d(self): ...\ndef test_0039_m(self): ...\n"), [])


class Commits(unittest.TestCase):
    SESSION = "Claude-Session: https://claude.ai/code/session_x"

    def test_a_person_s_commit_needs_nothing(self):
        self.assertEqual(fc.check_commit("a" * 40, "fix: something\n\nWhy it changed."), [])

    def test_an_agent_s_commit_naming_its_model_passes(self):
        for model in ("Opus 4.5", "Sonnet 4", "Haiku 4.5"):
            msg = f"fix: x\n\nCo-Authored-By: Claude {model} <noreply@anthropic.com>\n{self.SESSION}\n"
            self.assertEqual(fc.check_commit("a" * 40, msg), [], model)

    def test_an_agent_s_commit_without_the_trailer_fails(self):
        problems = fc.check_commit("a" * 40, f"fix: x\n\n{self.SESSION}\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("needs a 'Co-Authored-By: Claude", problems[0])

    def test_a_trailer_that_doesnt_name_the_model_fails(self):
        for trailer in ("Claude <noreply@anthropic.com>", "Claude Opus <noreply@anthropic.com>",
                        "Claude Opus 4.5 <claude@example.com>", "claude-opus-4-5 <noreply@anthropic.com>"):
            problems = fc.check_commit("a" * 40, f"fix: x\n\nCo-authored-by: {trailer}\n")
            self.assertEqual(len(problems), 1, trailer)
            self.assertIn("should name the model", problems[0])

    def test_two_claude_trailers_fail(self):
        msg = ("fix: x\n\nCo-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>\n"
               "Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>\n")
        self.assertIn("more than one", fc.check_commit("a" * 40, msg)[0])

    def test_another_person_as_co_author_is_left_alone(self):
        self.assertEqual(fc.check_commit("a" * 40, "fix: x\n\nCo-Authored-By: Pat Doe <pat@example.com>\n"), [])


class Workflows(unittest.TestCase):
    GOOD = ("name: X\non: push\ndefaults:\n  run:\n    shell: bash\njobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout@" + "a" * 40 + "   # v7.0.1\n"
            "      - uses: ./.github/actions/local\n"
            "      - run: gh api --paginate \"repos/$R/pulls?per_page=100\"\n")

    def test_the_repository_passes(self):
        self.assertEqual(fc.check_workflows(), [])

    def test_a_workflow_following_the_rules_passes(self):
        self.assertEqual(fc.check_workflow("x.yml", self.GOOD), [])

    def test_no_bash_default_fails(self):
        text = self.GOOD.replace("defaults:\n  run:\n    shell: bash\n", "")
        self.assertIn("no top-level `defaults: run: shell: bash`", fc.check_workflow("x.yml", text)[0])

    def test_an_unpinned_action_or_a_pin_without_its_version_fails(self):
        self.assertIn("isn't pinned", fc.check_workflow("x.yml", self.GOOD.replace("@" + "a" * 40, "@v7"))[0])
        self.assertIn("no version in a comment", fc.check_workflow("x.yml", self.GOOD.replace("   # v7.0.1", ""))[0])

    def test_a_list_read_without_paginate_fails(self):
        self.assertIn("without --paginate", fc.check_workflow("x.yml", self.GOOD.replace("--paginate ", ""))[0])



class Tests(unittest.TestCase):
    """A test that's removed or skipped needs a trailer saying why."""

    def test_names_python_and_vitest(self):
        py = "class A(unittest.TestCase):\n    def test_one(self):\n        pass\n\n\ndef test_free():\n    pass\n"
        self.assertEqual(fc.test_names("tests/test_x.py", py), {"tests/test_x.py::A.test_one", "tests/test_x.py::test_free"})
        ts = 'describe("x", () => {\n  it("shows a trip", () => {});\n  test(`keeps ${a}`, () => {});\n});\n'
        self.assertEqual(fc.test_names("frontend/src/a.test.ts", ts),
                         {"frontend/src/a.test.ts::shows a trip", "frontend/src/a.test.ts::keeps ${a}"})

    def test_which_files_hold_tests(self):
        self.assertTrue(fc.is_test_file("tests/test_backup.py"))
        self.assertTrue(fc.is_test_file("frontend/src/lib/api.test.ts"))
        self.assertFalse(fc.is_test_file("tests/shared.py"))
        self.assertFalse(fc.is_test_file("waypoint/server/handler.py"))

    def test_skips_are_recognised(self):
        for line in ("@unittest.skip('later')", "self.skipTest('flaky')", "it.skip('x', () => {})", "describe.only('x')",
                     "xit('x')", "@unittest.skipUnless(db.using_postgres(), 'Postgres only')"):
            with self.subTest(line=line):
                self.assertTrue(fc.SKIP.search(line))
        for line in ("def test_skips_nothing(self):", "it('skips a cancelled leg', () => {})", "only = 1"):
            with self.subTest(line=line):
                self.assertFalse(fc.SKIP.search(line))

    def check(self, removed=(), skipped=(), messages=()):
        with mock.patch.object(fc, "removed_tests", return_value=list(removed)), \
                mock.patch.object(fc, "added_skips", return_value=list(skipped)):
            return fc.check_tests("base", list(messages))

    def test_nothing_removed_passes(self):
        self.assertEqual(self.check(), [])

    def test_a_removed_test_needs_a_trailer_naming_it(self):
        gone = "tests/test_trips.py::TripTests.test_hidden_trip_is_404"
        self.assertIn("Removes-Test: TripTests.test_hidden_trip_is_404", self.check(removed=[gone])[0])
        for trailer in ("TripTests.test_hidden_trip_is_404 — covered by test_every_route now",
                        "test_hidden_trip_is_404 — covered by test_every_route now", f"{gone} — moved"):
            with self.subTest(trailer=trailer):
                self.assertEqual(self.check(removed=[gone], messages=[f"refactor: x\n\nRemoves-Test: {trailer}\n"]), [])
        other = "refactor: x\n\nRemoves-Test: test_hidden_trip — a different test whose name is part of this one's\n"
        self.assertTrue(self.check(removed=[gone], messages=[other]))

    def test_a_vitest_title_is_named_up_to_the_dash(self):
        gone = "frontend/src/lib/app.test.ts::shows a trip, then its legs"
        self.assertEqual(self.check(removed=[gone], messages=["x\n\nRemoves-Test: shows a trip, then its legs — merged into one\n"]), [])
        self.assertTrue(self.check(removed=[gone], messages=["x\n\nRemoves-Test: shows — merged\n"]))

    def test_each_skip_needs_its_own_trailer(self):
        added = [("tests/test_trips.py", "test_a", "@unittest.skip('later')"),
                 ("tests/test_trips.py", "test_b", "self.skipTest('flaky')")]
        found = self.check(skipped=added, messages=["x\n\nSkips-Test: test_a — needs Postgres\n"])
        self.assertEqual(len(found), 1)
        self.assertIn("Skips-Test: test_b", found[0])
        self.assertEqual(self.check(skipped=added, messages=["x\n\nSkips-Test: test_a — needs Postgres\nSkips-Test: test_b — a reason\n"]), [])

    def test_which_test_a_skip_belongs_to(self):
        py = ["class T(unittest.TestCase):", "    @unittest.skip('later')", "    def test_decorated(self):",
              "        pass", "", "    def test_inside(self):", "        self.skipTest('x')"]
        self.assertEqual(fc.skipped_name("tests/test_t.py", py, 1), "test_decorated")
        self.assertEqual(fc.skipped_name("tests/test_t.py", py, 6), "test_inside")
        self.assertEqual(fc.skipped_name("frontend/src/a.test.ts", ['  it.skip("shows a trip", () => {});'], 0), "shows a trip")

    def test_the_repository_passes_against_main(self):
        base = fc._git("rev-parse", "--verify", "--quiet", "origin/main").strip() if fc._git(
            "branch", "-r", "--list", "origin/main").strip() else ""
        if not base:
            self.skipTest("no origin/main here to compare with")
        found = fc.commits(f"{base}..HEAD")
        self.assertEqual(fc.check_tests(fc._git("merge-base", base, "HEAD").strip(), [m for _, m in found]), [])


class ManageLinks(unittest.TestCase):
    def test_a_provider_needs_a_test_and_a_bare_host(self):
        table = {"example air": ("www.example.com", "/m?c={code}")}
        self.assertEqual(fc.check_manage_links(table, 'x("example air")'), [])
        self.assertIn("has no test", fc.check_manage_links(table, "")[0])
        self.assertIn("isn't a bare host", fc.check_manage_links({"a": ("evil.com/x", "/")}, '"a"')[0])
        self.assertEqual(fc.check_manage_links({}, ""), [])


if __name__ == "__main__":
    unittest.main()
