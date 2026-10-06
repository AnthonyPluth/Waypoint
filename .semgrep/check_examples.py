from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "examples"
MARK = re.compile(r"(?:#|//)\s*(ruleid|ok):\s*(\S+)")


def expected() -> tuple[set[tuple[str, int, str]], set[tuple[str, int, str]]]:
    flagged: set[tuple[str, int, str]] = set()
    clean: set[tuple[str, int, str]] = set()
    for path in sorted(p for p in EXAMPLES.rglob("*") if p.suffix in (".py", ".ts")):
        rel = str(path.relative_to(EXAMPLES))
        for n, line in enumerate(path.read_text().split("\n"), 1):
            m = MARK.match(line.strip())
            if m:
                (flagged if m.group(1) == "ruleid" else clean).add((rel, n + 1, m.group(2)))
    return flagged, clean


def found(semgrep: list[str]) -> set[tuple[str, int, str]]:
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(EXAMPLES, tmp, dirs_exist_ok=True)
        run = subprocess.run([*semgrep, "scan", "--metrics=off", "--disable-version-check", "--quiet", "--json",
                              "--config", str(HERE / "waypoint.yml"), "."], cwd=tmp, capture_output=True, text=True)
    if run.returncode not in (0, 1):
        sys.exit(f"semgrep failed ({run.returncode}):\n{run.stderr}")
    out = json.loads(run.stdout)
    if out["errors"]:
        sys.exit("semgrep reported errors:\n" + json.dumps(out["errors"], indent=2))
    return {(r["path"], r["start"]["line"], r["check_id"].rsplit(".", 1)[-1]) for r in out["results"]}


def main(semgrep: list[str]) -> int:
    flagged, clean = expected()
    seen = found(semgrep)
    problems = [f"{p}:{n}: {rule} should flag this line" for p, n, rule in sorted(flagged - seen)]
    problems += [f"{p}:{n}: {rule} flags a line marked ok" for p, n, rule in sorted(clean & seen)]
    problems += [f"{p}:{n}: {rule} flags a line no example expects it on" for p, n, rule in sorted(seen - flagged - clean)]
    rules = {m.group(1) for m in re.finditer(r"^  - id: (\S+)", (HERE / "waypoint.yml").read_text(), re.M)}
    for rule in sorted(rules):
        if not any(r == rule for _, _, r in flagged):
            problems.append(f"{rule} has no failing example")
        if not any(r == rule for _, _, r in clean):
            problems.append(f"{rule} has no passing example")
    if problems:
        print("\n".join(problems))
        return 1
    print(f"{len(flagged)} failing and {len(clean)} passing examples across {len(rules)} rules agree with Semgrep.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["semgrep"]))
