from __future__ import annotations

import gzip
import sys
from pathlib import Path

RENAMED = {"Europe/Zaporozhye": "Europe/Kyiv", "Europe/Uzhgorod": "Europe/Kyiv", "Pacific/Enderbury": "Pacific/Kanton"}
OUT = Path(__file__).resolve().parent.parent / "waypoint" / "storage" / "airports.tsv.gz"


def rows() -> list[tuple[str, str, str, str, str, str, str]]:
    import airportsdata
    found = airportsdata.load("IATA")
    return [(code, a["name"], a["city"], a["country"], RENAMED.get(a["tz"], a["tz"]), f"{a['lat']:.4f}", f"{a['lon']:.4f}")
            for code, a in sorted(found.items()) if len(code) == 3 and a["tz"]]


def main() -> int:
    lines = "".join("\t".join(r).replace("\n", " ") + "\n" for r in rows())
    with OUT.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as z:
        z.write(lines.encode("utf-8"))
    print(f"{len(lines.splitlines())} airports -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
