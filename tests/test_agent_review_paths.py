import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/agent-review.yml"
BLOCK = re.compile(r"^      second-review-paths: \|\n((?:        \S.*\n)+)", re.MULTILINE)


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


def tree_files() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                  if p.is_file() and not {".git", "node_modules", "__pycache__"} & set(p.parts))


class SecondReviewPaths(unittest.TestCase):
    def test_the_block_is_read_from_the_workflow(self):
        paths = second_review_paths()
        self.assertIn("waypoint/oidc.py", paths)
        self.assertIn("frontend/src/lib/offline-vault.ts", paths)
        self.assertTrue(all(paths))

    def test_the_photo_access_files_are_risky(self):
        paths = second_review_paths()
        for name in ("photos.py", "photogrants.py", "photoproxy.py"):
            self.assertIn(f"waypoint/domain/{name}", paths)

    def test_globs_match_like_fleet_s(self):
        self.assertTrue(glob_to_regex(".semgrep/**").match(".semgrep/waypoint.yml"))
        self.assertTrue(glob_to_regex("Dockerfile*").match("Dockerfile"))
        self.assertFalse(glob_to_regex("Dockerfile*").match("docs/Dockerfile"))

    def test_each_file_entry_is_in_the_tree(self):
        for entry in second_review_paths():
            if "*" in entry:
                continue
            self.assertTrue((ROOT / entry).is_file(), f"{entry} is listed but isn't in the tree")

    def test_each_pattern_entry_matches_a_file_in_the_tree(self):
        files = tree_files()
        for entry in second_review_paths():
            if "*" not in entry:
                continue
            pattern = glob_to_regex(entry)
            self.assertTrue(any(pattern.match(name) for name in files), f"{entry} matches nothing in the tree")
