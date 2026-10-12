import argparse
import json
from collections import defaultdict
from pathlib import Path


def load(directory: Path) -> tuple[list[dict], dict[str, float]]:
    timed: list[dict] = []
    phases: dict[str, float] = defaultdict(float)
    for p in sorted(directory.glob("*.json")):
        data = json.loads(p.read_text())
        timed.extend(data["tests"])
        for name, seconds in data["phases"].items():
            phases[name] += seconds
    return timed, phases


def report(timed: list[dict], phases: dict[str, float], top: int) -> str:
    total = sum(t["seconds"] for t in timed)
    classes: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for t in timed:
        entry = classes[f"{t['module']}.{t['class']}"]
        entry[0] += t["seconds"]
        entry[1] += 1
    lines = [f"{len(timed)} tests, {total:.1f}s of test time summed over all workers",
             "Time spent in the database set-up and clean-up, summed over all workers (set-up and clean-up a whole class shares are included):"]
    for name, seconds in sorted(phases.items()):
        lines.append(f"  {name}: {seconds:.1f}s")
    lines.append("")
    lines.append(f"Slowest {top} tests")
    for t in sorted(timed, key=lambda t: -t["seconds"])[:top]:
        extra = " ".join(f"{k}={v:.2f}" for k, v in t["phases"].items())
        lines.append(f"  {t['seconds']:7.2f}s  {t['module']}.{t['class']}.{t['test']}  {extra}".rstrip())
    lines.append("")
    lines.append(f"Slowest {top} classes (sum of their tests)")
    for name, (seconds, count) in sorted(classes.items(), key=lambda kv: -kv[1][0])[:top]:
        lines.append(f"  {seconds:7.1f}s  {count:4d} tests  {name}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize the timings tests.timing_result.TimingResult wrote")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()
    timed, phases = load(args.directory)
    print(report(timed, phases, args.top))


if __name__ == "__main__":
    main()
