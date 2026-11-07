# waypoint/tls.py is the one place that opens a URL itself.
import urllib.request

# ok: waypoint-raw-urlopen
urllib.request.urlopen(req)
# ok: waypoint-raw-urlopen
urllib.request.build_opener()

# waypoint/tls.py is also the one place that opens an HTTP/2 or raw connection.
# ok: waypoint-raw-httpx
import httpx
# ok: waypoint-raw-httpx
import http.client
