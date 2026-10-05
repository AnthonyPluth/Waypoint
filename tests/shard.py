"""Which test modules one CI shard runs: `python tests/shard.py 2/3` prints unittest -k arguments for the second of three
shards (e.g. `-k tests.test_forecast. -k tests.test_notify.`).

The Postgres tests are split across runners, each with its own Postgres, because on one runner they mostly wait on each
other (one shared schema, the settings lock in tests/shared.py): four workers there ran only 1.8× faster than one.
Modules are spread greedily by file size, which tracks their running time closely, so a new or growing module finds its
own place without a table of timings to keep up to date. Every module lands in exactly one shard.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def modules() -> list[str]:
    return sorted(f[:-3] for f in os.listdir(HERE) if f.startswith("test") and f.endswith(".py"))


def shards(count: int) -> list[list[str]]:
    """The modules split into `count` shards of about the same total size, largest modules placed first."""
    out: list[list[str]] = [[] for _ in range(count)]
    load = [0] * count
    for name in sorted(modules(), key=lambda m: (-os.path.getsize(os.path.join(HERE, m + ".py")), m)):
        i = load.index(min(load))
        out[i].append(name)
        load[i] += os.path.getsize(os.path.join(HERE, name + ".py"))
    return [sorted(s) for s in out]


def main(arg: str) -> str:
    index, _, count = arg.partition("/")
    if not (index.isdigit() and count.isdigit() and 1 <= int(index) <= int(count)):
        raise SystemExit(f"Give a shard as N/COUNT, like 2/3 (not {arg!r}).")
    return " ".join(f"-k tests.{m}." for m in shards(int(count))[int(index) - 1])


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else ""))
