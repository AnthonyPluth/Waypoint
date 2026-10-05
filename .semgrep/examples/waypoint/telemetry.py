# No error-reporting or analytics SDK anywhere in Waypoint.

# ruleid: waypoint-no-telemetry
import sentry_sdk
# ruleid: waypoint-no-telemetry
POSTHOG_HOST = "https://app.posthog.com"
# ok: waypoint-no-telemetry
monitoring.report(e, values=False)
