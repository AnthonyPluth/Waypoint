from __future__ import annotations

import threading
from typing import Literal, TypedDict

from .. import monitoring
from ..providers import protomaps
from ..storage import mapfile

State = Literal["ready", "downloading", "waiting", "failed", "off", "missing"]
_lock = threading.Lock()
_running = False
_progress = (0, 0)
_failure: str | None = None


class Status(TypedDict):
    state: State
    bytes: int
    total: int | None
    error: str | None


def status() -> Status:
    if mapfile.usable():
        return {"state": "ready", "bytes": mapfile.size() or 0, "total": None, "error": None}
    with _lock:
        running, (done, total), failure = _running, _progress, _failure
    if running:
        return {"state": "downloading", "bytes": done, "total": total or None, "error": None}
    if mapfile.own_file():
        return {"state": "missing", "bytes": 0, "total": None, "error": None}
    if not mapfile.downloads():
        return {"state": "off", "bytes": 0, "total": None, "error": None}
    if failure:
        return {"state": "failed", "bytes": 0, "total": None, "error": failure}
    return {"state": "waiting", "bytes": 0, "total": None, "error": None}


def _report(done: int, total: int) -> None:
    global _progress
    with _lock:
        _progress = (done, total)


def ensure() -> bool:
    global _running, _failure
    if mapfile.usable() or not mapfile.downloads():
        return False
    with _lock:
        if _running:
            return False
        _running = True
        _failure = None
    try:
        monitoring.log("Downloading the detailed trip map from Protomaps' public build (about 2 GB, once). Nothing about your trips is sent.")
        dest = mapfile.path()
        key_file = dest.with_name(dest.name + ".build")
        try:
            key = key_file.read_text().strip()
            url = protomaps.build_url(key)
        except (OSError, protomaps.Unavailable):
            key = protomaps.latest_build()
            url = protomaps.build_url(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.with_name(dest.name + ".part").unlink(missing_ok=True)
            key_file.write_text(key)
        protomaps.extract(url, dest, _report)
        key_file.unlink(missing_ok=True)
        monitoring.log("The detailed trip map is ready.")
        return True
    except (protomaps.Unavailable, OSError) as e:
        reason = str(e) if isinstance(e, protomaps.Unavailable) else "The map file couldn't be written to the data folder (is the disk full?)"
        with _lock:
            _failure = reason
        monitoring.log(f"The detailed trip map couldn't be downloaded: {reason}. Waypoint tries again later and uses the bundled map meanwhile.")
        return False
    finally:
        with _lock:
            _running = False
