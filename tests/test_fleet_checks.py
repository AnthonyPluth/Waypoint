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


if __name__ == "__main__":
    unittest.main()
