from __future__ import annotations

from collections.abc import Callable, Sequence

TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
MAX_IMAGE = 1_000_000
MAX_TOTAL = 5_000_000
MAX_COUNT = 30

Fetched = tuple[str, bytes]
Fetch = Callable[[Sequence[str], int], dict[str, Fetched]]


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
