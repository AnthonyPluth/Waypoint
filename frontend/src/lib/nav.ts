import type { Component } from "svelte";
import PlaneTakeoff from "@lucide/svelte/icons/plane-takeoff";
import Luggage from "@lucide/svelte/icons/luggage";
import ChartColumn from "@lucide/svelte/icons/chart-column";
import Users from "@lucide/svelte/icons/users";
import Inbox from "@lucide/svelte/icons/inbox";
import Ellipsis from "@lucide/svelte/icons/ellipsis";
import Settings from "@lucide/svelte/icons/settings";
import type { AppState } from "./types";

export type NavItem = { page: string; label: string; icon: Component<{ class?: string }>; badge?: (s: AppState) => number };

export const NAV: NavItem[] = [
  { page: "upcoming", label: "Upcoming", icon: PlaneTakeoff },
  { page: "trips", label: "Trips", icon: Luggage },
  { page: "stats", label: "Stats", icon: ChartColumn },
  { page: "people", label: "People", icon: Users },
  { page: "review", label: "Review", icon: Inbox, badge: (s) => s.review_count },
  { page: "settings", label: "Settings", icon: Settings },
];

const TAB_PAGES = ["upcoming", "trips", "stats", "review"];
const MORE_PAGES = ["people", "settings"];

const only = (pages: string[]): NavItem[] => NAV.filter((n) => pages.includes(n.page));

export const TABS: NavItem[] = only(TAB_PAGES);
export const MORE: NavItem[] = only(MORE_PAGES);
export const MORE_TAB = { label: "More", icon: Ellipsis };

export const inMore = (page: string): boolean => MORE_PAGES.includes(page);

const INSIDE: Record<string, string> = { trip: "trips", design: "settings" };

export const pageFor = (route: string): string => (route in INSIDE ? route : NAV.find((n) => n.page === route)?.page ?? NAV[0].page);

export const navFor = (route: string): string => INSIDE[pageFor(route)] ?? pageFor(route);

export const initials = (who: string): string =>
  who.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
