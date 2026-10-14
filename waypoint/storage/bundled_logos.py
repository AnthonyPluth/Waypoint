from __future__ import annotations

import json
import re
import unicodedata
from functools import cache
from pathlib import Path

ROOT = Path(__file__).with_name("logos")
ALIASES = {
    "delta airlines": "delta air lines",
    "delta": "delta air lines",
    "united": "united airlines",
    "american": "american airlines",
    "southwest": "southwest airlines",
    "jetblue": "jetblue airways",
    "allegiant": "allegiant air",
    "swiss": "swiss international air lines",
    "ana": "all nippon airways",
    "latam": "latam airlines",
    "sas scandinavian airlines": "sas",
    "scandinavian airlines": "sas",
    "ihg": "ihg hotels resorts",
    "wyndham": "wyndham hotels resorts",
    "radisson": "radisson hotel group",
    "enterprise rent a car": "enterprise",
    "enterprise car rental": "enterprise",
    "national car rental": "national",
    "alamo rent a car": "alamo",
    "budget rent a car": "budget",
    "hertz rent a car": "hertz",
    "avis rent a car": "avis",
    "dollar rent a car": "dollar",
    "thrifty car rental": "thrifty",
    "sixt rent a car": "sixt",
    "carnival": "carnival cruise line",
    "carnival cruises": "carnival cruise line",
    "royal caribbean international": "royal caribbean",
    "norwegian": "norwegian cruise line",
    "ncl": "norwegian cruise line",
    "princess": "princess cruises",
    "celebrity": "celebrity cruises",
    "msc": "msc cruises",
    "holland america": "holland america line",
    "viking cruises": "viking",
    "viking river cruises": "viking",
    "seabourn cruise line": "seabourn",
}


def normalize(name: str | None) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


@cache
def catalog() -> dict[str, str]:
    entries = json.loads((ROOT / "manifest.json").read_text())
    return {normalize(entry["name"]): entry["file"] for entry in entries}


def filename(name: str | None) -> str | None:
    key = normalize(name)
    return catalog().get(ALIASES.get(key, key))


def has(name: str | None) -> bool:
    return filename(name) is not None


def read(name: str | None) -> tuple[bytes, str] | None:
    file = filename(name)
    if file is None:
        return None
    content_type = "image/svg+xml" if file.endswith(".svg") else "image/png"
    return (ROOT / file).read_bytes(), content_type
