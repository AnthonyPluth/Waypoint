# waypoint/providers/gmail.py: the one module that talks to Google's mail and OAuth services.
import datetime
from datetime import datetime as dt

# ok: waypoint-google-hosts
TOKEN_URL = "https://oauth2.googleapis.com/token"
# ok: waypoint-google-hosts
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# ok: waypoint-google-hosts
API = "https://gmail.googleapis.com/gmail/v1/users/me"
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

# The provider fetches a message and hands it over untouched; it doesn't look inside.
# ruleid: waypoint-message-body
text = message["raw"]
# ruleid: waypoint-message-body
text = base64.urlsafe_b64decode(message.get("raw", ""))
# ok: waypoint-message-body
found = _api("/messages/" + message_id, token, {"format": "raw"})
