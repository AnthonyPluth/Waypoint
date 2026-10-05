// The shapes of Waypoint's API replies that the pages use. GET /api/state is the contract's State (api-types.ts), with
// its Sentry settings spelled out.
import type { State } from "./api-types";

/** Where the web app sends its error reports, when Waypoint is set up for them. */
export interface SentryConfig {
  dsn: string; environment: string; release: string;
  /** Who's signed in, as a code that doesn't say who, so reports count the people they affect. */
  user_id?: string | null;
}

export type AppState = Omit<State, "sentry"> & { sentry: SentryConfig | null };
export type SignedIn = NonNullable<AppState["user"]>;
