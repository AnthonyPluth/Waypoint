from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Position = Literal["window", "aisle", "middle"]
Cabin = Literal["economy"]


@dataclass(frozen=True)
class Layout:
    window: str
    aisle: str
    middle: str

    def position(self, letter: str) -> Position | None:
        if letter in self.window:
            return "window"
        if letter in self.aisle:
            return "aisle"
        return "middle" if letter in self.middle else None

    def letters(self) -> str:
        return self.window + self.aisle + self.middle


NARROWBODY_3_3 = Layout(window="AF", aisle="CD", middle="BE")
A220_2_3 = Layout(window="AF", aisle="CD", middle="B")
WIDEBODY_3_4_3 = Layout(window="AK", aisle="CDGH", middle="BEFJ")
WIDEBODY_3_3_3 = Layout(window="AK", aisle="CDFG", middle="BEH")

LAYOUTS: dict[str, dict[Cabin, Layout]] = {
    "Airbus A220": {"economy": A220_2_3},
    "Airbus A320 family": {"economy": NARROWBODY_3_3},
    "Boeing 737": {"economy": NARROWBODY_3_3},
    "Boeing 757": {"economy": NARROWBODY_3_3},
    "Boeing 777": {"economy": WIDEBODY_3_4_3},
    "Boeing 787": {"economy": WIDEBODY_3_3_3},
    "Airbus A350": {"economy": WIDEBODY_3_3_3},
}

FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = tuple((name, re.compile(pattern)) for name, pattern in (
    ("Airbus A220", r"\ba220|\bbcs[13]\b|\bcs[13]00\b"),
    ("Airbus A320 family", r"\ba3(?:18|19|20|21)|\ba(?:19|20|21)n\b"),
    ("Airbus A330", r"\ba330|\ba33[2389]\b"),
    ("Airbus A350", r"\ba350|\ba359\b|\ba35k\b"),
    ("Airbus A380", r"\ba380|\ba388\b"),
    ("Boeing 737", r"\bb?737|\bb73[1-9]\b|\bb3[789]m\b"),
    ("Boeing 757", r"\bb?757|\bb75[23]\b"),
    ("Boeing 767", r"\bb?767|\bb76[2-4]\b"),
    ("Boeing 777", r"\bb?777|\bb77[23lw]\b"),
    ("Boeing 787", r"\bb?787|\bb78[89x]\b"),
    ("Embraer E170", r"\be170\b"),
    ("Embraer E175", r"\be175\b|\be75[sl]\b"),
    ("Embraer E190", r"\be190\b"),
    ("Bombardier CRJ", r"\bcrj|\bcanadair regional jet"),
))


def family(text: str | None) -> str | None:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).strip()
    return next((name for name, pattern in FAMILIES if pattern.search(cleaned)), None)


def position(aircraft: str | None, cabin: Cabin, letter: str) -> Position | None:
    layout = LAYOUTS.get(family(aircraft) or "", {}).get(cabin)
    return layout.position(letter.upper()) if layout else None
