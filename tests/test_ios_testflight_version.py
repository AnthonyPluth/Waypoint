import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/ios-testflight.yml"
STEP = re.compile(
    r"      - name: Find the latest release version\n(?:        .*\n)*?        run: \|\n((?:          .*\n|\n)+)"
)


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def version_script() -> str:
    found = STEP.search(workflow_text())
    assert found, "ios-testflight.yml has no 'Find the latest release version' step"
    return "".join(line[10:] for line in found.group(1).splitlines(keepends=True))


def run_step(gh_body: str) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "gh"
        fake.write_text(f"#!/usr/bin/env bash\n{gh_body}\n", encoding="utf-8")
        fake.chmod(0o755)
        output = Path(tmp) / "output"
        output.write_text("", encoding="utf-8")
        env = {
            "PATH": f"{tmp}:{os.environ['PATH']}",
            "REPO": "owner/repo",
            "GITHUB_OUTPUT": str(output),
            "GITHUB_RUN_NUMBER": "87",
        }
        done = subprocess.run(
            ["bash", "-eo", "pipefail", "-c", version_script()], env=env, capture_output=True, text=True, check=False
        )
        return done.returncode, output.read_text(encoding="utf-8"), done.stdout + done.stderr


class IosTestflightVersion(unittest.TestCase):
    def test_the_version_is_the_latest_release_without_the_v(self):
        code, output, _ = run_step("echo v3.49.0")
        self.assertEqual(code, 0)
        self.assertEqual(output, "version=3.49.0\n")

    def test_it_reads_the_latest_release_of_this_repository(self):
        code, output, _ = run_step('[ "$1 $2" = "api repos/owner/repo/releases/latest" ] && echo v10.0.12')
        self.assertEqual(code, 0)
        self.assertEqual(output, "version=10.0.12\n")

    def test_anything_but_vx_y_z_stops_the_build(self):
        for tag in ["", "v3.49", "3.49.0", "v3.49.0-rc1", "v3.49.0.1", "vx.y.z", "v3.49.0 "]:
            with self.subTest(tag=tag):
                code, output, text = run_step(f"echo '{tag}'")
                self.assertNotEqual(code, 0)
                self.assertEqual(output, "")
                self.assertIn("::error::", text)
                self.assertNotIn("0.1.0", text)

    def test_a_failed_call_stops_the_build(self):
        code, output, text = run_step("echo 'HTTP 404' >&2; exit 1")
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("::error::Could not read the latest GitHub Release", text)

    def test_the_archive_passes_the_version_found_by_the_step_before_it(self):
        text = workflow_text()
        find = text.index("- name: Find the latest release version")
        archive = text.index("- name: Archive the app")
        self.assertLess(find, archive)
        archive_step = text[archive : text.index("- name: Export the .ipa")]
        self.assertIn("MARKETING_VERSION: ${{ steps.version.outputs.version }}", archive_step)
        self.assertIn('MARKETING_VERSION="$MARKETING_VERSION"', archive_step)
        self.assertIn('CURRENT_PROJECT_VERSION="$BUILD_NUMBER"', archive_step)

    def test_nothing_commits_a_version_back_and_the_token_stays_read_only(self):
        text = workflow_text()
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("git push", text)


if __name__ == "__main__":
    unittest.main()
