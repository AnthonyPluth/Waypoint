from __future__ import annotations

from collections.abc import Callable

from ..booking import Parsed
from . import disneycruise, southwest


Parser = Callable[[str, str], Parsed]

PARSERS: dict[str, Parser] = {
    "southwest.com": southwest.parse,
    "familyvacations-disneycruise.com": disneycruise.parse,
}


def for_sender(domain: str | None) -> Parser | None:
    if not domain:
        return None
    for key, parser in PARSERS.items():
        if domain == key or domain.endswith("." + key):
            return parser
    return None
