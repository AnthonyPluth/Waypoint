"""Writes waypoint/storage/airports.tsv.gz, the airports Waypoint knows by IATA code (the seed of migration 0005's
`airports` table): code, name, city, country, IANA time zone, latitude and longitude, one per line, sorted by code.

    python3 -m venv /tmp/airports && /tmp/airports/bin/pip install airportsdata && /tmp/airports/bin/python tools/airports.py

The rows come from the `airportsdata` package, which is built from OurAirports' public-domain data with each airport's
IANA zone added (OurAirports has none). It's needed only to regenerate the file, so it isn't one of Waypoint's
dependencies. A changed file ships with a migration that updates the table, never by editing 0005's seed."""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

# Zone names tzdata has since retired, by the ones that replaced them (a system without the old names can't read them).
RENAMED = {"Europe/Zaporozhye": "Europe/Kyiv", "Europe/Uzhgorod": "Europe/Kyiv", "Pacific/Enderbury": "Pacific/Kanton"}
OUT = Path(__file__).resolve().parent.parent / "waypoint" / "storage" / "airports.tsv.gz"


def rows() -> list[tuple[str, str, str, str, str, str, str]]:
    import airportsdata   # (only here: the script's own dependency)
    found = airportsdata.load("IATA")
    return [(code, a["name"], a["city"], a["country"], RENAMED.get(a["tz"], a["tz"]), f"{a['lat']:.4f}", f"{a['lon']:.4f}")
            for code, a in sorted(found.items()) if len(code) == 3 and a["tz"]]


def main() -> int:
    lines = "".join("\t".join(r).replace("\n", " ") + "\n" for r in rows())
    with OUT.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as z:   # (mtime 0: the same bytes each run)
        z.write(lines.encode("utf-8"))
    print(f"{len(lines.splitlines())} airports -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
