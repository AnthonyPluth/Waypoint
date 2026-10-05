# waypoint/providers/gmail.py: the one module that talks to Google's mail and OAuth services.
import datetime
from datetime import datetime as dt

# ok: waypoint-google-hosts
TOKEN_URL = "https://oauth2.googleapis.com/token"
# ok: waypoint-decrypt
token = secretbox.decrypt(row["refresh_token"])

# ruleid: waypoint-naive-now
expires = dt.now()
# ruleid: waypoint-naive-now
expires = datetime.datetime.fromtimestamp(stamp)
# ok: waypoint-naive-now
expires = dt.now(datetime.timezone.utc)
# ok: waypoint-naive-now
expires = dt.fromtimestamp(stamp, datetime.timezone.utc)
