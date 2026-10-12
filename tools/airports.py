from __future__ import annotations

import gzip
import sys
from pathlib import Path

RENAMED = {"Europe/Zaporozhye": "Europe/Kyiv", "Europe/Uzhgorod": "Europe/Kyiv", "Pacific/Enderbury": "Pacific/Kanton"}
COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "KR": "South Korea", "KP": "North Korea", "CD": "DR Congo", "CG": "Congo",
    "MM": "Myanmar", "SZ": "Eswatini", "AS": "American Samoa", "WS": "Samoa", "VG": "British Virgin Islands",
    "CC": "Cocos Islands", "MF": "Saint Martin", "SX": "Sint Maarten", "XK": "Kosovo", "VI": "U.S. Virgin Islands",
}
STORAGE = Path(__file__).resolve().parent.parent / "waypoint" / "storage"
OUT = STORAGE / "airports.tsv.gz"
REGIONS = STORAGE / "regions.tsv.gz"
ISO3166 = Path("/usr/share/zoneinfo/iso3166.tab")


def rows() -> list[tuple[str, str, str, str, str, str, str]]:
    import airportsdata
    found = airportsdata.load("IATA")
    return [(code, a["name"], a["city"], a["country"], RENAMED.get(a["tz"], a["tz"]), f"{a['lat']:.4f}", f"{a['lon']:.4f}")
            for code, a in sorted(found.items()) if len(code) == 3 and a["tz"]]


def state_rows() -> list[tuple[str, str, str]]:
    import airportsdata
    found = airportsdata.load("IATA")
    return [("A", code, a["subd"]) for code, a in sorted(found.items())
            if len(code) == 3 and a["tz"] and a["country"] == "US" and a["subd"]]


def country_rows(used: set[str]) -> list[tuple[str, str, str]]:
    names = dict(line.rstrip("\n").split("\t") for line in ISO3166.read_text(encoding="utf-8").splitlines() if line and line[0] != "#")
    names.update(COUNTRY_NAMES)
    return [("C", code, names[code]) for code in sorted(used) if code in names]


def write(path: Path, found: list[tuple[str, ...]]) -> None:
    lines = "".join("\t".join(r).replace("\n", " ") + "\n" for r in found)
    with path.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as z:
        z.write(lines.encode("utf-8"))


def main() -> int:
    found = rows()
    regions = [*state_rows(), *country_rows({r[3] for r in found})]
    write(OUT, list(found))
    write(REGIONS, list(regions))
    print(f"{len(found)} airports -> {OUT}; {len(regions)} regions -> {REGIONS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
