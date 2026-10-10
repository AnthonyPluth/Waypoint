# Background jobs (the mail scan) and provider modules take the day they're given.
import datetime
from datetime import date

# ruleid: waypoint-today-in-jobs
start = date.today()
# ruleid: waypoint-today-in-jobs
start = datetime.date.today()
# ok: waypoint-today-in-jobs
today = today or date.today()
# ok: waypoint-today-in-jobs
start = today

# ruleid: waypoint-naive-now
scanned_at = datetime.datetime.now()
# ok: waypoint-naive-now
scanned_at = datetime.datetime.now(datetime.timezone.utc)

# Only extract.py reads what a message holds: the scan passes the message on and keeps the booking fields that come back.
# ruleid: waypoint-message-body
body = message["raw"]
# ruleid: waypoint-message-body
body = message.get("payload")
# ruleid: waypoint-message-body
body = message["payload"]["parts"][0]
# ruleid: waypoint-message-body
text = base64.urlsafe_b64decode(data)
# ruleid: waypoint-message-body
parsed = email.message_from_string(text)
# ruleid: waypoint-message-body
text = part.get_payload(decode=True)
# ok: waypoint-message-body
found = extract.read(message)
# ok: waypoint-message-body
sender = found.sender_domain

# The scan is the one caller of the image provider, and it calls it when a message is kept.
# ok: waypoint-image-callers
from ...providers import gmail, images
