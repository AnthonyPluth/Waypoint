from __future__ import annotations

import csv
import gzip
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "waypoint" / "storage" / "airlines.tsv.gz"
IATA = re.compile(r"[A-Z0-9]{2}")
ICAO = re.compile(r"[A-Z0-9]{3}")


def rows(source: Path) -> list[tuple[str, str, str, str]]:
    best: dict[str, tuple[bool, int, tuple[str, str, str, str]]] = {}
    with source.open(encoding="utf-8", newline="") as f:
        for line in csv.reader(f):
            if len(line) < 8:
                continue
            ident, name, _alias, iata, icao, _callsign, country, active = line[:8]
            iata = iata.strip().upper()
            if not IATA.fullmatch(iata) or not name.strip() or name.strip() in ("Unknown", "Private flight"):
                continue
            icao = icao.strip().upper()
            row = (iata, icao if ICAO.fullmatch(icao) else "", name.strip(), "" if country == "\\N" else country.strip())
            key = (active == "Y", -int(ident))
            if iata not in best or key > best[iata][:2]:
                best[iata] = (key[0], key[1], row)
    return [best[code][2] for code in sorted(best)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 tools/airlines.py /path/to/airlines.dat")
        return 2
    found = rows(Path(argv[1]))
    lines = "".join("\t".join(r).replace("\n", " ") + "\n" for r in found)
    with OUT.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as z:
        z.write(lines.encode("utf-8"))
    print(f"{len(found)} airlines -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
