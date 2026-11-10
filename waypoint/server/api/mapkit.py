from __future__ import annotations

import time

from ...domain import maps
from ..contract import MapkitToken


def api_mapkit_token(conn, _q, _b) -> MapkitToken:
    issued = maps.issue(time.time())
    if issued is None:
        return {"enabled": False}
    return {"enabled": True, "token": issued.token, "expires": issued.expires, "script": issued.script}
