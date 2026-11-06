from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .. import tls


class Gone(Exception):
    pass


def wake(base: str, device_id: str, secret: str, collapse_id: str | None = None, timeout: float = 10) -> None:
    body: dict[str, str] = {"kind": "alert"}
    if collapse_id:
        body["collapse_id"] = collapse_id
    req = urllib.request.Request(
        f"{base.rstrip('/')}/v1/devices/{urllib.parse.quote(device_id, safe='')}/wake", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}", "User-Agent": "Waypoint/0.1"})
    try:
        with tls.urlopen(req, timeout=timeout) as r:
            r.read(1024)
    except urllib.error.HTTPError as e:
        if e.code in (401, 404, 410):
            raise Gone(device_id) from e
        raise RuntimeError(f"the push relay said {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError("couldn't reach the push relay") from e
