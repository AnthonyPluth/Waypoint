import type { State } from "./api-types";

export type AppState = State;
export type SignedIn = NonNullable<AppState["user"]>;
