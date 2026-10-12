from __future__ import annotations

import gzip
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "waypoint" / "storage" / "places.tsv.gz"


def _lines(archive: Path, member: str) -> list[list[str]]:
    with zipfile.ZipFile(archive) as z, z.open(member) as f:
        return [line.decode("utf-8").rstrip("\n").split("\t") for line in f if line.strip()]


def us_zips(archive: Path) -> list[tuple[str, ...]]:
    return [("Z", "US", r[0], f"{float(r[5]):.4f}", f"{float(r[6]):.4f}", "")
            for r in _lines(archive, "2023_Gaz_zcta_national.txt")[1:] if len(r) >= 7 and r[0].isdigit() and len(r[0]) == 5]


def postal(archive: Path, member: str, country: str) -> list[tuple[str, ...]]:
    sums: dict[str, list[float]] = {}
    for r in _lines(archive, member):
        if len(r) >= 11 and r[9] and r[10]:
            s = sums.setdefault(r[1].replace(" ", "").upper(), [0.0, 0.0, 0.0])
            s[0] += float(r[9])
            s[1] += float(r[10])
            s[2] += 1
    return [("Z", country, code, f"{s[0] / s[2]:.4f}", f"{s[1] / s[2]:.4f}", "") for code, s in sorted(sums.items())]


def cities(archive: Path) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for r in _lines(archive, "cities15000.txt"):
        if len(r) < 15 or not r[14].isdigit():
            continue
        state = r[10] if r[8] == "US" else ""
        for name in dict.fromkeys((r[1], r[2])):
            out.append(("C", r[8], name.replace("\t", " "), f"{float(r[4]):.4f}", f"{float(r[5]):.4f}", f"{state}|{r[14]}"))
    return sorted(out)


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print("usage: places.py 2023_Gaz_zcta_national.zip GB.zip CA.zip cities15000.zip", file=sys.stderr)
        return 2
    zcta, gb, ca, city = (Path(a) for a in argv[1:])
    rows = [*us_zips(zcta), *postal(gb, "GB.txt", "GB"), *postal(ca, "CA.txt", "CA"), *cities(city)]
    lines = "".join("\t".join(r) + "\n" for r in rows)
    with OUT.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as z:
        z.write(lines.encode("utf-8"))
    print(f"{len(rows)} places -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
