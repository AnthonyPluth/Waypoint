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
