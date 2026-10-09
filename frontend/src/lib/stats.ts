import type { Stats } from "./api-types";

type Unit = Stats["distance_unit"];
export type Selection = { who: number | "all"; year: number | null };

const KM_PER_MILE = 1.609344;
const locale = () => (typeof navigator !== "undefined" && navigator.language) || "en-US";

export const count = (n: number): string => Math.round(n).toLocaleString(locale());

export const distance = (km: number, unit: Unit): string => `${count(unit === "mi" ? km / KM_PER_MILE : km)} ${unit}`;

export const compact = (n: number): string => n.toLocaleString(locale(), { notation: "compact", maximumFractionDigits: 1 });

export const compactDistance = (km: number, unit: Unit): string => `${compact(unit === "mi" ? km / KM_PER_MILE : km)} ${unit}`;

export function duration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds / 60));
  const days = Math.floor(total / 1440), hours = Math.floor((total % 1440) / 60), minutes = total % 60;
  if (days) return hours ? `${days} d ${hours} h` : `${days} d`;
  if (hours) return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
  return `${minutes} min`;
}

export function comparisons(f: Pick<Stats["flights"], "times_around_earth" | "moon_fraction">): string[] {
  const out: string[] = [];
  if (f.times_around_earth >= 0.05) out.push(`${f.times_around_earth.toFixed(1)}× around the Earth`);
  if (f.moon_fraction >= 1) out.push(`${f.moon_fraction.toFixed(1)}× the distance to the Moon`);
  else if (f.moon_fraction > 0) out.push(f.moon_fraction < 0.01 ? "Under 1% of the way to the Moon" : `${Math.round(f.moon_fraction * 100)}% of the way to the Moon`);
  return out;
}

export const share = (n: number, whole: number): number => (whole > 0 ? Math.round((n / whole) * 100) : 0);

export const monthLabel = (month: string): string => {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString(locale(), { timeZone: "UTC", month: "long", year: "numeric" });
};

export function countryName(code: string): string {
  try { return new Intl.DisplayNames([locale()], { type: "region" }).of(code) ?? code; } catch { return code; }
}

export function selectionQuery(sel: Selection, me: number | null): string {
  const q = new URLSearchParams();
  if (sel.who !== (me ?? "all")) q.set("who", String(sel.who));
  if (sel.year !== null) q.set("year", String(sel.year));
  return q.toString();
}

export function parseSelection(query: string, me: number | null): Selection {
  const q = new URLSearchParams(query);
  const who = q.get("who"), year = q.get("year");
  return {
    who: who === "all" ? "all" : who && /^\d{1,9}$/.test(who) ? Number(who) : me ?? "all",
    year: year && /^\d{4}$/.test(year) ? Number(year) : null,
  };
}

export const statsPath = (sel: Selection): `/api/stats?${string}` => `/api/stats?person=${sel.who}&year=${sel.year ?? "all"}`;
