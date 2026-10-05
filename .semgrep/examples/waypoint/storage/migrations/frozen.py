# Migrations are frozen as they ran: they keep the code they were written with.
from dateutil.relativedelta import relativedelta

# ok: waypoint-month-arithmetic
later = today + relativedelta(months=1)
