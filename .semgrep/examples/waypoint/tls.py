# waypoint/tls.py is the one place that opens a URL itself.
import urllib.request

# ok: waypoint-raw-urlopen
urllib.request.urlopen(req)
# ok: waypoint-raw-urlopen
urllib.request.build_opener()
