from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "waypoint/storage/migrations/versions"
MIGRATION_TESTS = ROOT / "tests/test_migrations.py"
PARSERS = ROOT / "waypoint/domain/mail/parsers"
MAIL_FIXTURES = ROOT / "tests/fixtures/mail"
TESTS = ROOT / "tests"
WORKFLOWS = ROOT / ".github/workflows"
ACTIONS = ROOT / ".github/actions"

TESTED_FROM = "0001"

REVISION = re.compile(r"^\d{4}$")
MODEL_FAMILIES = ("Opus", "Sonnet", "Haiku")
CO_AUTHOR = re.compile(r"^co-authored-by:\s*(.*)$", re.IGNORECASE | re.MULTILINE)
SESSION = re.compile(r"^claude-session:\s*\S", re.IGNORECASE | re.MULTILINE)
GOOD_CO_AUTHOR = re.compile(r"^Claude (" + "|".join(MODEL_FAMILIES) + r") \d+(\.\d+)* <noreply@anthropic\.com>$")
CLAUDE = re.compile(r"\bclaude\b|anthropic\.com", re.IGNORECASE)


def _assigned(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(getattr(t, "id", None) == name for t in targets) and getattr(node, "value", None) is not None:
            return ast.literal_eval(node.value)  # type: ignore[arg-type]
    return ...


def migrations(directory: Path = MIGRATIONS) -> list[dict]:
    found = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("__"):
            continue
        tree = ast.parse(path.read_text(), str(path))
        revision, down = _assigned(tree, "revision"), _assigned(tree, "down_revision")
        downs = () if down is None or down is ... else tuple(down) if isinstance(down, (list, tuple)) else (down,)
        found.append({"file": path.name, "revision": revision, "down": downs})
    return found


def check_migrations(found: list[dict], tests_text: str) -> list[str]:
    problems = []
    revisions = [m["revision"] for m in found]
    for m in found:
        rev = m["revision"]
        if not isinstance(rev, str) or not REVISION.match(rev):
            problems.append(f"{m['file']}: revision should be four digits, like '0041' (it is {rev!r})")
        elif not m["file"].startswith(rev + "_"):
            problems.append(f"{m['file']}: the file name should start with its revision, {rev}_")
        if revisions.count(rev) > 1 and m is next(x for x in found if x["revision"] == rev):
            files = ", ".join(x["file"] for x in found if x["revision"] == rev)
            problems.append(f"revision {rev!r} is used more than once ({files}): renumber yours after main's newest")
        for d in m["down"]:
            if d not in revisions:
                problems.append(f"{m['file']}: down_revision {d!r} is no migration here")
    followed = {d for m in found for d in m["down"]}
    heads = sorted({m["revision"] for m in found if m["revision"] not in followed}, key=str)
    if len(heads) > 1:
        problems.append(f"more than one Alembic head ({', '.join(map(str, heads))}): another branch added a migration "
                        "with the same parent; merge main and make yours follow its newest")
    if len(heads) == 0 and found:
        problems.append("no Alembic head: the migrations go round in a loop")
    tested = set(re.findall(r"^\s*def test_(\d{4})_", tests_text, re.MULTILINE))
    for m in found:
        rev = m["revision"]
        if isinstance(rev, str) and REVISION.match(rev) and rev >= TESTED_FROM and rev not in tested:
            problems.append(f"{m['file']}: no test of its own in tests/test_migrations.py (a method named test_{rev}_...); "
                            "downgrade to the revision before it, write the data it changes, upgrade and check the result")
    return problems


def check_commit(sha: str, message: str) -> list[str]:
    co_authors = [c.strip() for c in CO_AUTHOR.findall(message)]
    claude = [c for c in co_authors if CLAUDE.search(c)]
    if not SESSION.search(message) and not claude:
        return []
    subject = message.strip().splitlines()[0] if message.strip() else ""
    where = f"commit {sha[:10]} ({subject[:60]})"
    if not claude:
        return [f"{where}: an agent's commit (it has a Claude-Session trailer) needs a "
                "'Co-Authored-By: Claude <Model> <version> <noreply@anthropic.com>' trailer for the model that wrote it"]
    if len(claude) > 1:
        return [f"{where}: more than one Claude Co-Authored-By trailer; keep the one for the model that wrote it"]
    if not GOOD_CO_AUTHOR.match(claude[0]):
        return [f"{where}: 'Co-Authored-By: {claude[0]}' should name the model, as "
                f"'Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>' (one of {', '.join(MODEL_FAMILIES)})"]
    return []


def commits(revision_range: str) -> list[tuple[str, str]]:
    out = subprocess.run(["git", "log", "--format=%H%x00%B%x1e", revision_range, "--"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    return [tuple(rec.strip("\n").split("\0", 1)) for rec in out.split("\x1e") if rec.strip()]  # type: ignore[misc]


PY_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(", re.MULTILINE)
PY_CLASS = re.compile(r"^class\s+(\w+)", re.MULTILINE)
TS_TEST = re.compile(r"""\b(?:it|test)\(\s*(["'`])((?:(?!\1).)+)\1""")
SKIP = re.compile(r"\b(?:unittest\.skip(?:If|Unless)?\b|skipTest\(|(?:it|test|describe)\.(?:skip|only|todo)\b|xit\(|xdescribe\()")
REMOVES = re.compile(r"^removes-test:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
SKIPS = re.compile(r"^skips-test:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def is_test_file(path: str) -> bool:
    return (path.startswith("tests/") and path.endswith(".py") and Path(path).name.startswith("test_")) or \
        (path.startswith("frontend/") and re.search(r"\.test\.(ts|mjs|js)$", path) is not None)


def test_names(path: str, text: str) -> set[str]:
    if path.endswith(".py"):
        names = set()
        cls = ""
        for line in text.splitlines():
            if m := PY_CLASS.match(line):
                cls = m.group(1)
            elif m := PY_TEST.match(line):
                names.add(f"{path}::{cls + '.' if cls and line.startswith(' ') else ''}{m.group(1)}")
        return names
    return {f"{path}::{m.group(2)}" for m in TS_TEST.finditer(text)}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def removed_tests(base: str) -> list[str]:
    gone = []
    for path in _git("ls-tree", "-r", "--name-only", base).splitlines():
        if not is_test_file(path):
            continue
        before = test_names(path, _git("show", f"{base}:{path}"))
        now_file = ROOT / path
        now = test_names(path, now_file.read_text()) if now_file.exists() else set()
        gone += sorted(before - now)
    return gone


STRING = re.compile(r"""(["'`])(?:\\.|(?!\1).)*\1""")


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")


def skipped_name(path: str, lines: list[str], index: int) -> str:
    if path.endswith(".py"):
        here = lines[index].lstrip()
        steps = range(index + 1, len(lines)) if here.startswith("@") else range(index, -1, -1)
        for k in steps:
            if m := PY_DEF.match(lines[k]):
                return m.group(1)
        return ""
    m = TS_TEST.search(lines[index].replace(".skip(", "(").replace(".only(", "(").replace(".todo(", "("))
    return m.group(2) if m else ""


def added_skips(base: str) -> list[tuple[str, str, str]]:
    out = []
    diff = _git("diff", "--unified=0", f"{base}", "--", "tests", "frontend")
    path, line_no = "", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif m := HUNK.match(line):
            line_no = int(m.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            if path and is_test_file(path) and SKIP.search(STRING.sub("", line)):
                lines = (ROOT / path).read_text().splitlines()
                out.append((path, skipped_name(path, lines, line_no - 1), line[1:].strip()[:100]))
            line_no += 1
    return out


def _names(declared: list[str]) -> set[str]:
    out = set()
    for d in (d.strip() for d in declared):
        if d:
            parts = re.split(r"\s+[—–]\s+", d, maxsplit=1)
            out.add(parts[0].strip() if len(parts) == 2 else d.split()[0])
    return out


def check_tests(base: str, messages: list[str]) -> list[str]:
    removals = _names([r for m in messages for r in REMOVES.findall(m)])
    skips = _names([r for m in messages for r in SKIPS.findall(m)])
    problems = []
    for name in removed_tests(base):
        short = name.split("::", 1)[1]
        if not {name, short, short.rsplit(".", 1)[-1]} & removals:
            problems.append(f"the test {name} is gone: keep it, or say why on a commit with a "
                            f"'Removes-Test: {short} — <why>' trailer")
    for path, test, text in added_skips(base):
        names = {f"{path}::{test}", test} if test else {path, Path(path).name}
        if not names & skips:
            problems.append(f"a test is skipped or narrowed ({path}: {text}): say why on a commit with a "
                            f"'Skips-Test: {test or Path(path).name} — <why>' trailer")
    return problems


PARSER_FIXTURES = ("booking", "change", "cancellation")


def parser_vendors(directory: Path = PARSERS) -> list[str]:
    return sorted(p.stem for p in directory.glob("*.py") if not p.stem.startswith("_"))


def check_parsers(vendors: list[str], registry: str, fixtures: Path = MAIL_FIXTURES, tests: Path = TESTS) -> list[str]:
    problems = []
    for vendor in vendors:
        where = f"waypoint/domain/mail/parsers/{vendor}.py"
        if not re.search(rf"\b{re.escape(vendor)}\.parse\b", registry):
            problems.append(f"{where}: not registered in PARSERS in parsers/__init__.py (a parser nothing runs)")
        for name in PARSER_FIXTURES:
            if not (fixtures / vendor / f"{name}.eml").is_file():
                problems.append(f"{where}: no synthetic fixture tests/fixtures/mail/{vendor}/{name}.eml")
        test = tests / f"test_mail_parser_{vendor}.py"
        if not test.is_file():
            problems.append(f"{where}: no test in tests/test_mail_parser_{vendor}.py that uses the fixtures")
            continue
        text = test.read_text()
        if not re.search(rf"""fixtures/mail/{re.escape(vendor)}\b|"fixtures"\s*/\s*"mail"\s*/\s*"{re.escape(vendor)}\"""", text):
            problems.append(f"{test.name}: doesn't name the fixtures directory tests/fixtures/mail/{vendor}/")
        for name in PARSER_FIXTURES:
            if not re.search(rf"""["']{name}["']""", text):
                problems.append(f"{test.name}: never uses the {name} fixture")
    return problems


USES = re.compile(r"^[ \t]*(?:-[ \t]*)?uses:[ \t]*([^\s#]+)(.*)$", re.MULTILINE)
PINNED = re.compile(r"@[0-9a-f]{40}$")
BASH_DEFAULT = re.compile(r"^defaults:[ \t]*\n[ \t]+run:[ \t]*\n(?:[ \t]{4,}\S.*\n)*?[ \t]{4,}shell:[ \t]*bash[ \t]*(?:#.*)?$",
                          re.MULTILINE)
GH_API_LIST = re.compile(r"\bgh api\b[^\n]*per_page=")
RUNS_ON = ("runs-on: ${{ fromJSON(vars.RUNS_ON != '' && github.actor != 'dependabot[bot]' && "
           "(!github.event.pull_request || github.event.pull_request.head.repo.full_name == github.repository && "
           "github.event.pull_request.user.login != 'dependabot[bot]') && vars.RUNS_ON || '\"ubuntu-latest\"') }}")
RUNS_ON_LINE = re.compile(r"^[ \t]*runs-on:.*$", re.MULTILINE)
HOSTED = re.compile(r"^runs-on: ubuntu-latest[ \t]+# hosted: \S")


def check_workflow(name: str, text: str, workflow: bool = True) -> list[str]:
    problems = []
    if workflow and not BASH_DEFAULT.search(text):
        problems.append(f"{name}: no top-level `defaults: run: shell: bash` (steps then run without -o pipefail)")
    for m in USES.finditer(text):
        target, rest = m.group(1), m.group(2)
        if target.startswith("./") or target.startswith("docker://"):
            continue
        if not PINNED.search(target):
            problems.append(f"{name}: {target} isn't pinned by its commit SHA")
        elif not re.search(r"#\s*v?\d", rest):
            problems.append(f"{name}: {target} has no version in a comment (`# v1.2.3`)")
    for line in text.splitlines():
        if GH_API_LIST.search(line) and "--paginate" not in line:
            problems.append(f"{name}: `gh api ... per_page=` without --paginate reads only the first page: {line.strip()[:80]}")
    for m in RUNS_ON_LINE.finditer(text):
        line = m.group(0).strip()
        if line != RUNS_ON and not HOSTED.match(line):
            problems.append(f"{name}: `{line[:60]}` should be fleet_checks.RUNS_ON, or `runs-on: ubuntu-latest   # hosted: <why>`")
    return problems


def check_workflows() -> list[str]:
    problems = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        problems += check_workflow(str(path.relative_to(ROOT)), path.read_text())
    for path in sorted(ACTIONS.glob("*/action.y*ml")):
        problems += check_workflow(str(path.relative_to(ROOT)), path.read_text(), workflow=False)
    return problems


def check_manage_links(table: dict, tests_text: str) -> list[str]:
    problems = []
    for provider, (host, _path) in table.items():
        if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", host):
            problems.append(f"manage link for {provider!r}: {host!r} isn't a bare host")
        if f'"{provider}"' not in tests_text and f"'{provider}'" not in tests_text:
            problems.append(f"manage link for {provider!r} has no test in tests/test_links.py")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commits", metavar="BASE..HEAD", help="also check these commits' trailers (a pull request's)")
    args = ap.parse_args(argv)
    problems = check_migrations(migrations(), MIGRATION_TESTS.read_text())
    problems += check_parsers(parser_vendors(), (PARSERS / "__init__.py").read_text())
    problems += check_workflows()
    sys.path.insert(0, str(ROOT))
    from waypoint.domain import links
    problems += check_manage_links(links.MANAGE, (ROOT / "tests/test_links.py").read_text())
    if args.commits:
        found = commits(args.commits)
        for sha, message in found:
            problems += check_commit(sha, message)
        base = _git("merge-base", *args.commits.split("..", 1)).strip() if ".." in args.commits else args.commits
        problems += check_tests(base, [message for _, message in found])
    for p in problems:
        print(f"::error::{p}" if "GITHUB_ACTIONS" in os.environ else p, file=sys.stderr)
    if not problems:
        print("Fleet checks passed: one migration head, migrations tested, mail parsers registered with fixtures and a test"
              + (", commit trailers, no test removed or skipped without a reason" if args.commits else "")
              + ", workflow conventions, manage links tested.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
