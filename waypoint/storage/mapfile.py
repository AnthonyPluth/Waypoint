from __future__ import annotations

import os
from pathlib import Path

from .. import pmtiles
from . import db

FILENAME = "map.pmtiles"
OFF_WORDS = {"0", "false", "no", "off"}


def own_file() -> str | None:
    return (os.environ.get("WAYPOINT_MAP_FILE") or "").strip() or None


def path() -> Path:
    return Path(own_file() or os.path.join(db.data_dir(), FILENAME))


def downloads() -> bool:
    return own_file() is None and (os.environ.get("WAYPOINT_MAP_DOWNLOAD") or "").strip().lower() not in OFF_WORDS


def size() -> int | None:
    try:
        return path().stat().st_size
    except OSError:
        return None


def version() -> str | None:
    try:
        stat = path().stat()
    except OSError:
        return None
    return f"{stat.st_size:x}-{int(stat.st_mtime):x}"


def usable() -> bool:
    try:
        with path().open("rb") as f:
            pmtiles.parse_header(f.read(pmtiles.HEADER_LENGTH))
        return True
    except (OSError, pmtiles.FormatError):
        return False


def read(start: int, length: int) -> bytes:
    with path().open("rb") as f:
        f.seek(start)
        return f.read(length)
