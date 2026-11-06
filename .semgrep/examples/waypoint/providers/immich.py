# waypoint/providers/immich.py: the one module that names Immich's endpoints and sends a library's API key.
# ok: waypoint-immich-hosts
SEARCH = "/api/search/metadata"
# ok: waypoint-immich-hosts
ASSETS = "/api/assets/"
# ok: waypoint-immich-hosts
headers = {"x-api-key": source.key, "User-Agent": "Waypoint/1"}
