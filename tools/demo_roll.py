from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "frontend" / "demo" / "data.json"
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$")
NAME = re.compile(r"^(.*) \((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}\)$")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def shift(value: str, days: int) -> str:
    match = DATE.match(value)
    if match is None:
        return value
    day = dt.date.fromisoformat(match.group(1)) + dt.timedelta(days=days)
    return day.isoformat() + (match.group(2) or "")


def walk(node, days: int):
    if isinstance(node, dict):
        return {key: walk(value, days) for key, value in node.items()}
    if isinstance(node, list):
        return [walk(value, days) for value in node]
    if isinstance(node, str):
        return shift(node, days)
    return node


def relabel_trips(trips: list[dict]) -> int:
    renamed = 0
    for trip in trips:
        match = NAME.match(trip["name"])
        if match is None:
            continue
        start = dt.date.fromisoformat(trip["start_date"])
        name = f"{match.group(1)} ({MONTHS[start.month - 1]} {start.year})"
        if name != trip["name"]:
            trip["name"] = name
            renamed += 1
    return renamed


def roll(data: dict, to: dt.date) -> tuple[dict, int, int]:
    as_of = dt.date.fromisoformat(data["asOf"])
    days = (to - as_of).days
    rolled = walk(data, days)
    renamed = relabel_trips(rolled["trips"])
    return rolled, days, renamed


def encode(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Move the static demo's pinned date forward and shift its data with it.")
    parser.add_argument("--to", type=dt.date.fromisoformat, default=dt.date.today(), help="the new asOf date, YYYY-MM-DD (default: today)")
    parser.add_argument("--data", type=Path, default=DATA, help="the demo data file")
    args = parser.parse_args(argv)

    raw = args.data.read_text(encoding="utf-8")
    data = json.loads(raw)
    as_of = dt.date.fromisoformat(data["asOf"])
    if args.to < as_of:
        print(f"demo_roll: {args.to} is before the current asOf {as_of}; the demo only moves forward", file=sys.stderr)
        return 2
    rolled, days, renamed = roll(data, args.to)
    assert rolled["asOf"] == args.to.isoformat()
    args.data.write_text(encode(rolled), encoding="utf-8")
    print(f"demo_roll: asOf {as_of} -> {args.to} ({days:+d} days); {renamed} trip name(s) relabelled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
