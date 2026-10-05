"""Writes waypoint/storage/airlines.tsv.gz, the airlines Waypoint knows by IATA code (the seed of migration 0008's
`airlines` table): IATA code, ICAO code, name and country, one per line, sorted by IATA code.

    curl -sSLo /tmp/airlines.dat https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat
    python3 tools/airlines.py /tmp/airlines.dat

The rows come from OpenFlights' `airlines.dat`, which is under the Open Database License (ODbL 1.0): see NOTICE and the
"Data sources" docs page. Several airlines, mostly defunct ones, share an IATA code; the active one wins, then the
lowest OpenFlights id. A changed file ships with a migration that updates the table, never by editing 0008's seed."""
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
    """(IATA, ICAO or "", name, country) for each IATA code, from airlines.dat's id, name, alias, IATA, ICAO, callsign,
    country, active columns (`\\N` and "-" are OpenFlights' blanks)."""
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
        print(__doc__)
        return 2
    found = rows(Path(argv[1]))
    lines = "".join("\t".join(r).replace("\n", " ") + "\n" for r in found)
    with OUT.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as z:   # (mtime 0: the same bytes each run)
        z.write(lines.encode("utf-8"))
    print(f"{len(found)} airlines -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
