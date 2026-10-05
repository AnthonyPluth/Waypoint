// The shapes of Waypoint's API replies that the pages use: GET /api/state is the contract's State (api-types.ts).
import type { State } from "./api-types";

export type AppState = State;
export type SignedIn = NonNullable<AppState["user"]>;
