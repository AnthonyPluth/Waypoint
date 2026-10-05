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
