# Examples for .semgrep/waypoint.yml. Each `# ruleid: <id>` comment says the next line must be flagged by that rule, each
# `# ok: <id>` that it must not be; `make semgrep` (.semgrep/check_examples.py) checks both, and that nothing else
# is flagged. Nothing here runs; it is only parsed. The path matters: a rule only looks where its `paths` say, so the
# files beside this one (server/api/body.py, domain/mail/scan.py, providers/, tls.py, dates.py, migrations/) cover those.
import calendar
import datetime
import urllib.request
from datetime import date
from datetime import datetime as dt

import sqlalchemy as sa
from dateutil.relativedelta import relativedelta
from sqlalchemy import text

# ruleid: waypoint-raw-urlopen
urllib.request.urlopen(req, timeout=5)
# ruleid: waypoint-raw-urlopen
urllib.request.build_opener()
# ok: waypoint-raw-urlopen
tls.urlopen(req, timeout=5)

# ruleid: waypoint-sql-from-string
sa.text(f"SELECT * FROM {name}")
# ruleid: waypoint-sql-from-string
text("SELECT * FROM " + name)
# ruleid: waypoint-sql-from-string
text("SELECT * FROM %s" % name)
# ruleid: waypoint-sql-from-string
text("SELECT * FROM {}".format(name))
# ruleid: waypoint-sql-from-string
conn.exec_driver_sql(f"SELECT * FROM {name}")
# ruleid: waypoint-sql-from-string
conn.execute(f"SELECT * FROM {name}")
# ok: waypoint-sql-from-string
text("SELECT * FROM accounts WHERE id = :id")
# ok: waypoint-sql-from-string
conn.execute(text("SELECT * FROM accounts WHERE id = :id"), {"id": 1})

# ok: waypoint-today-in-jobs
start = date.today()   # only background jobs and provider modules (see domain/mail/scan.py)

# ruleid: waypoint-utcnow
stamp = dt.utcnow()
# ruleid: waypoint-utcnow
stamp = datetime.datetime.utcnow()
# ok: waypoint-utcnow
stamp = datetime.datetime.now(datetime.timezone.utc)

# ruleid: waypoint-month-arithmetic
later = today + relativedelta(months=1)
# ruleid: waypoint-month-arithmetic
later = today + relativedelta(years=1, months=2)
# ruleid: waypoint-month-arithmetic
length = calendar.monthrange(today.year, today.month)[1]
# ruleid: waypoint-month-arithmetic
gap = (a.year - b.year) * 12
# ruleid: waypoint-month-arithmetic
prev = today.month - 1
# ruleid: waypoint-month-arithmetic
following = today.month + 1
# ok: waypoint-month-arithmetic
later = dates.add_months(today, 1)
# ok: waypoint-month-arithmetic
later = today + relativedelta(days=7)

# ruleid: waypoint-print
print(f"scanned {message_id}")
# ok: waypoint-print
monitoring.log("Scanned the mailbox.")

# ruleid: waypoint-google-hosts
TOKEN_URL = "https://oauth2.googleapis.com/token"
# ruleid: waypoint-google-hosts
LIST = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
# ruleid: waypoint-google-hosts
REVOKE = "https://oauth2.googleapis.com/revoke"
# ruleid: waypoint-google-hosts
CONSENT = "https://accounts.google.com/o/oauth2/v2/auth"
# ok: waypoint-google-hosts
gmail.list_messages(conn, mailbox, query)

# ruleid: waypoint-flightstatus-hosts
STATUS_URL = "https://aerodatabox.p.rapidapi.com/flights/number/EX101/2026-11-20"
# ruleid: waypoint-flightstatus-hosts
HEADERS = {"X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"}
# ruleid: waypoint-flightstatus-hosts
OTHER = "https://example-api.rapidapi.com/status"
# ok: waypoint-flightstatus-hosts
flightstatus.fetch("EX101", "2026-11-20")

# ruleid: waypoint-logodev-hosts
LOGO_URL = "https://img.logo.dev/name/Example%20Hotels?token=pk_example"
# ruleid: waypoint-logodev-hosts
LOGO_SEARCH = "https://api.logo.dev/search?q=Example"
# ok: waypoint-logodev-hosts
logos.fetch_due(conn, now)

# ruleid: waypoint-ai-hosts
URL = "https://openrouter.ai/api/v1/chat/completions"
# ruleid: waypoint-ai-hosts
LOCAL = "http://127.0.0.1:11434/api/chat"
# ok: waypoint-ai-hosts
suggestion = ai.suggest(conn, item)

# ruleid: waypoint-decrypt
number = secretbox.decrypt(row["number"])
# ruleid: waypoint-decrypt
open_it = secretbox.decrypt
# ruleid: waypoint-decrypt
from .storage.secretbox import decrypt
# ruleid: waypoint-decrypt
from waypoint.storage.secretbox import encrypt, decrypt as reveal
# ok: waypoint-decrypt
from .storage.secretbox import encrypt
# ok: waypoint-decrypt
number = loyalty.reveal(conn, person, loyalty_id)
