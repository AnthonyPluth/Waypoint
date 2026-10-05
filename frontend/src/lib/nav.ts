// The app's pages and how you reach them: the tab bar on a phone or tablet, the sidebar on a computer.
import type { Component } from "svelte";
import PlaneTakeoff from "@lucide/svelte/icons/plane-takeoff";
import Users from "@lucide/svelte/icons/users";
import Settings from "@lucide/svelte/icons/settings";

export type NavItem = { page: string; label: string; icon: Component<{ class?: string }> };

export const NAV: NavItem[] = [
  { page: "upcoming", label: "Upcoming", icon: PlaneTakeoff },
  { page: "people", label: "People", icon: Users },
  { page: "settings", label: "Settings", icon: Settings },
];

/** The page a route opens: anything that isn't one of ours (an old bookmark, a typo) opens Upcoming. */
export const pageFor = (route: string): string => NAV.find((n) => n.page === route)?.page ?? NAV[0].page;

/** Initials for the avatar: "Ada Lovelace" → "AL", "ada@example.com" → "AE". */
export const initials = (who: string): string =>
  who.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
