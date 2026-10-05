// No error-reporting or analytics SDK in the web app either.

// ruleid: waypoint-no-telemetry
import * as Sentry from "@sentry/browser";
// ruleid: waypoint-no-telemetry
window.gtag("event", "trip_opened");
// ok: waypoint-no-telemetry
console.error(err);
