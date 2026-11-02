import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/agent-review.yml"
BLOCK = re.compile(r"^      second-review-paths: \|\n((?:        \S.*\n)+)", re.MULTILINE)
READS_KEPT_MAIL = re.compile(r"\b(stored_mail|gate_codes|mailimages)\b")
ALWAYS_RISKY_DIRS = ("waypoint/domain/mail", "waypoint/server", "waypoint/providers")
NOT_YET_IN_THE_TREE = {"waypoint/domain/photos.py"}


def second_review_paths(text: str | None = None) -> list[str]:
    found = BLOCK.search(WORKFLOW.read_text(encoding="utf-8") if text is None else text)
    assert found, "agent-review.yml has no second-review-paths block"
    return [line.strip() for line in found.group(1).splitlines()]


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif pattern.startswith("**", i):
            out += ".*"; i += 2
        elif pattern[i] == "*":
            out += "[^/]*"; i += 1
        else:
            out += re.escape(pattern[i]); i += 1
    return re.compile(f"^{out}$")


def matches(path: str, patterns: list[str]) -> bool:
    return any(glob_to_regex(p).match(path) for p in patterns)


def backend_files() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "waypoint").rglob("*.py")
                  if "__pycache__" not in p.parts and "migrations" not in p.parts)


class SecondReviewPaths(unittest.TestCase):
    def test_the_block_is_read_from_the_workflow(self):
        paths = second_review_paths()
        self.assertIn("waypoint/oidc.py", paths)
        self.assertIn("waypoint/domain/mail/**", paths)
        self.assertTrue(all(paths))

    def test_globs_match_like_fleet_s(self):
        self.assertTrue(matches("waypoint/domain/mail/parsers/acme.py", ["waypoint/domain/mail/**"]))
        self.assertTrue(matches("waypoint/storage/stored_mail.py", ["waypoint/storage/*.py"]))
        self.assertFalse(matches("waypoint/storage/migrations/versions/0001_x.py", ["waypoint/storage/*.py"]))
        self.assertFalse(matches("waypoint/domain/mailbox.py", ["waypoint/domain/mail/**"]))
        self.assertTrue(matches("waypoint/server/mcp_server.py", ["waypoint/server/mcp_*.py"]))

    def test_every_file_that_reads_kept_mail_or_a_gate_code_is_risky(self):
        paths = second_review_paths()
        missing = [name for name in backend_files()
                   if READS_KEPT_MAIL.search((ROOT / name).read_text(encoding="utf-8")) and not matches(name, paths)]
        self.assertEqual(missing, [], "these read kept mail or gate codes but no second-review path covers them")

    def test_the_mail_server_and_provider_directories_are_risky_whole(self):
        paths = second_review_paths()
        missing = [name for name in backend_files()
                   if name.startswith(tuple(d + "/" for d in ALWAYS_RISKY_DIRS)) and not matches(name, paths)]
        self.assertEqual(missing, [])

    def test_the_file_entries_name_files_in_the_tree_or_ones_the_list_expects(self):
        for entry in second_review_paths():
            if "*" in entry or entry in NOT_YET_IN_THE_TREE:
                continue
            self.assertTrue((ROOT / entry).is_file(), f"{entry} is listed but isn't in the tree")

    def test_a_new_module_outside_the_list_that_reads_kept_mail_would_fail(self):
        text = WORKFLOW.read_text(encoding="utf-8").replace("        waypoint/domain/trips.py\n", "")
        paths = second_review_paths(text)
        self.assertFalse(matches("waypoint/domain/trips.py", paths))
        self.assertTrue(READS_KEPT_MAIL.search((ROOT / "waypoint/domain/trips.py").read_text(encoding="utf-8")))
