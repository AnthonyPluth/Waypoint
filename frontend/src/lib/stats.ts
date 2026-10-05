// What the Stats page works out from GET /api/stats: numbers as they read (units, large numbers, durations), the
// comparisons under the distance, and the pickers' choice as it's kept in the address (#stats?who=2&year=2025).
import type { Stats } from "./api-types";

type Unit = Stats["distance_unit"];
/** Whose numbers (a person's id, or "all" for the household) and which year (null: all time). */
export type Selection = { who: number | "all"; year: number | null };

const KM_PER_MILE = 1.609344;
const locale = () => (typeof navigator !== "undefined" && navigator.language) || "en-US";

/** A whole number with its thousands separators: 12,345. */
export const count = (n: number): string => Math.round(n).toLocaleString(locale());

/** A distance the server gives in kilometres, in the household's unit: "7,742 mi" or "12,459 km". */
export const distance = (km: number, unit: Unit): string => `${count(unit === "mi" ? km / KM_PER_MILE : km)} ${unit}`;

/** Time in the air, to the minute: "3 d 4 h", "5 h 20 min", "45 min". Days and hours only show what isn't zero. */
export function duration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds / 60));
  const days = Math.floor(total / 1440), hours = Math.floor((total % 1440) / 60), minutes = total % 60;
  if (days) return hours ? `${days} d ${hours} h` : `${days} d`;
  if (hours) return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
  return `${minutes} min`;
}

/** The two lines under the distance: "1.3× around the Earth", "4% of the way to the Moon". Nothing for no distance, and
 *  nothing for a figure that would read as zero. */
export function comparisons(f: Pick<Stats["flights"], "times_around_earth" | "moon_fraction">): string[] {
  const out: string[] = [];
  if (f.times_around_earth >= 0.05) out.push(`${f.times_around_earth.toFixed(1)}× around the Earth`);
  if (f.moon_fraction >= 1) out.push(`${f.moon_fraction.toFixed(1)}× the distance to the Moon`);
  else if (f.moon_fraction > 0) out.push(f.moon_fraction < 0.01 ? "Under 1% of the way to the Moon" : `${Math.round(f.moon_fraction * 100)}% of the way to the Moon`);
  return out;
}

/** A share of a whole, to the percent ("0%" when there is no whole). */
export const share = (n: number, whole: number): number => (whole > 0 ? Math.round((n / whole) * 100) : 0);

/** "2026-06" → "June 2026". */
export const monthLabel = (month: string): string => {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString(locale(), { timeZone: "UTC", month: "long", year: "numeric" });
};

/** A country's name from its ISO code ("NZ" → "New Zealand"); the code itself when the browser doesn't know it. */
export function countryName(code: string): string {
  try { return new Intl.DisplayNames([locale()], { type: "region" }).of(code) ?? code; } catch { return code; }   // (an invalid code throws)
}

/** The address's query for a choice. Your own numbers and all time are the defaults, so they leave no mark. */
export function selectionQuery(sel: Selection, me: number | null): string {
  const q = new URLSearchParams();
  if (sel.who !== (me ?? "all")) q.set("who", String(sel.who));
  if (sel.year !== null) q.set("year", String(sel.year));
  return q.toString();
}

/** The choice an address holds; whatever it doesn't say, or says wrongly, is the default. */
export function parseSelection(query: string, me: number | null): Selection {
  const q = new URLSearchParams(query);
  const who = q.get("who"), year = q.get("year");
  return {
    who: who === "all" ? "all" : who && /^\d{1,9}$/.test(who) ? Number(who) : me ?? "all",
    year: year && /^\d{4}$/.test(year) ? Number(year) : null,
  };
}

/** The request for a choice. */
export const statsPath = (sel: Selection): `/api/stats?${string}` => `/api/stats?person=${sel.who}&year=${sel.year ?? "all"}`;
