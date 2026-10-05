# waypoint/providers/flightstatus.py: the one module that talks to the flight status service (RapidAPI's AeroDataBox).
# ok: waypoint-flightstatus-hosts
HOST = "aerodatabox.p.rapidapi.com"
# ok: waypoint-flightstatus-hosts
BASE = f"https://{HOST}"
# ok: waypoint-flightstatus-hosts
headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"}
