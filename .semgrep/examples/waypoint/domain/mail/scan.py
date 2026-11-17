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

# scan._read is the one caller of ai.suggest: nothing else in scan.py, and no other name for it.
def _read(cfg, text, timeout):
    try:
        # ok: waypoint-ai-suggest-caller
        reading = ai.suggest(cfg, text, timeout)
    except ai.AiError:
        reading = None
    return reading


def _ask(cfg, text):
    # ruleid: waypoint-ai-suggest-caller
    return ai.suggest(cfg, text)


def _fill_gaps(cfg, text):
    # ruleid: waypoint-ai-suggest-caller
    reading = ai.suggest(cfg, text, 5)
    return _read(cfg, text, 5) or reading


# ruleid: waypoint-ai-suggest-caller
from .ai import suggest
# ruleid: waypoint-ai-suggest-caller
from . import ai as mail_ai
# ok: waypoint-ai-suggest-caller
from . import ai
