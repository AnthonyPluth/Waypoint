# waypoint/dates.py is where month arithmetic lives.
import calendar

from dateutil.relativedelta import relativedelta

# ok: waypoint-month-arithmetic
later = d + relativedelta(months=n)
# ok: waypoint-month-arithmetic
length = calendar.monthrange(d.year, d.month)[1]
# ok: waypoint-month-arithmetic
gap = (b.year - a.year) * 12 + b.month - a.month
