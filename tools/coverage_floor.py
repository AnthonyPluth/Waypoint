from __future__ import annotations

import json
import sys
from pathlib import Path

TOTAL = 85.0
EACH = 90.0
DIRS = ("waypoint/domain/", "waypoint/providers/", "waypoint/server/api/")


def problems(report: dict) -> list[str]:
    out = []
    total = report["totals"]["percent_covered"]
    if total < TOTAL:
        out.append(f"the tests cover {total:.1f}% of the backend; the floor is {TOTAL:.0f}%")
    for name, f in sorted(report["files"].items()):
        pct, statements = f["summary"]["percent_covered"], f["summary"]["num_statements"]
        if name.startswith(DIRS) and statements and pct < EACH:
            out.append(f"{name}: the tests cover {pct:.1f}%; modules in {', '.join(DIRS)} need {EACH:.0f}% (add tests that run it)")
    return out


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    found = problems(json.loads(path.read_text()))
    for p in found:
        print(f"coverage: {p}", file=sys.stderr)
    if not found:
        print(f"Coverage floor met: {TOTAL:.0f}% overall, {EACH:.0f}% for each module in {', '.join(DIRS)}.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
