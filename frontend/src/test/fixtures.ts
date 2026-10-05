import type { AppState } from "$lib/types";

/** GET /api/state, as a signed-in Waypoint answers it; `extra` changes what a test cares about. */
export const state = (extra: Partial<AppState> = {}): AppState => ({
  version: "1.2.3", database: "sqlite", user: { name: "Ada Lovelace", email: "ada@example.com" }, sentry: null, last_backup: null, ...extra,
});
