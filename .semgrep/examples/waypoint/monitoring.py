# waypoint/monitoring.py is where the log is written.
import sys

# ok: waypoint-print
print(scrub(message), file=sys.stderr, flush=True)
