from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

from waypoint.domain import app_links

INTERNAL = re.compile(r"(^|[._-])(dev|alpha|beta|gamma|qa\d*|uat|stage|staging|nonprod|preprod|test|inhouse|featureqa\d*|poc\w*|mq\d)([._-]|$)", re.IGNORECASE)


def claimed(document: object) -> list[tuple[str, list[str]]]:
    details = document.get("applinks", {}).get("details", []) if isinstance(document, dict) else []
    if isinstance(details, dict):
        details = [{"appIDs": [app], "paths": value.get("paths", [])} for app, value in details.items() if isinstance(value, dict)]
    found: list[tuple[str, list[str]]] = []
    for entry in details if isinstance(details, list) else []:
        if not isinstance(entry, dict):
            continue
        apps = [*entry.get("appIDs", []), *([entry["appID"]] if entry.get("appID") else [])]
        paths = [*entry.get("paths", []), *(c["/"] for c in entry.get("components", []) if isinstance(c, dict) and "/" in c and not c.get("exclude"))]
        for app in dict.fromkeys(apps):
            if isinstance(app, str) and not INTERNAL.search(app.split(".", 1)[-1]):
                found.append((app, list(dict.fromkeys(p for p in paths if isinstance(p, str)))))
    return found


def fetch(host: str, name: str) -> object:
    url = f"https://{host}/.well-known/{name}"
    request = urllib.request.Request(url, headers={"User-Agent": "Waypoint link check", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read(2_000_000))


def main(argv: list[str]) -> int:
    domains = argv[1:] or sorted(app_links.BY_DOMAIN)
    for domain in domains:
        for host in (f"www.{domain}", domain):
            try:
                document = fetch(host, "apple-app-site-association")
            except (urllib.error.URLError, ValueError, OSError) as e:
                print(f"{host}: no file ({type(e).__name__})")
                continue
            apps = claimed(document)
            print(f"{host}: {len(apps)} production app(s)")
            for app, paths in apps:
                print(f"  {app}")
                for path in paths:
                    print(f"    {path}")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
