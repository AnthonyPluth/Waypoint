// The app's pages and how you reach them: the tab bar on a phone or tablet, the sidebar on a computer.
import type { Component } from "svelte";
import PlaneTakeoff from "@lucide/svelte/icons/plane-takeoff";
import Luggage from "@lucide/svelte/icons/luggage";
import Users from "@lucide/svelte/icons/users";
import Settings from "@lucide/svelte/icons/settings";

export type NavItem = { page: string; label: string; icon: Component<{ class?: string }> };

export const NAV: NavItem[] = [
  { page: "upcoming", label: "Upcoming", icon: PlaneTakeoff },
  { page: "trips", label: "Trips", icon: Luggage },
  { page: "people", label: "People", icon: Users },
  { page: "settings", label: "Settings", icon: Settings },
];

/** Pages with no link of their own: a trip (#trip/<id>) is opened from Trips, which stays lit while you're on it. */
const INSIDE: Record<string, string> = { trip: "trips" };

/** The page a route opens: anything that isn't one of ours (an old bookmark, a typo) opens Upcoming. */
export const pageFor = (route: string): string => (route in INSIDE ? route : NAV.find((n) => n.page === route)?.page ?? NAV[0].page);

/** The link in the tab bar or sidebar that's lit for a route. */
export const navFor = (route: string): string => INSIDE[pageFor(route)] ?? pageFor(route);

/** Initials for the avatar: "Ada Lovelace" → "AL", "ada@example.com" → "AE". */
export const initials = (who: string): string =>
  who.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
