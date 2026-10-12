import { COMMON_NAMES } from "$lib/zone-names";

export const MAX_SHOWN = 10;

export type ZoneEntry = {
  zone: string;
  label: string;
  city: string;
  region: string;
  generic: string;
  common: string[];
  abbreviations: string[];
  long: string[];
};

export function normalize(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

export function zoneLabel(zone: string): string {
  return zone.replaceAll("_", " ");
}

export function supportedZones(): string[] | null {
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    return zones.length ? zones : null;
  } catch {
    return null;
  }
}

function zoneName(zone: string, style: "short" | "long" | "longGeneric", at: Date): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: style }).formatToParts(at);
    return parts.find((part) => part.type === "timeZoneName")?.value ?? "";
  } catch {
    return "";
  }
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

export function zoneEntry(zone: string, now: Date = new Date()): ZoneEntry {
  const parts = zone.split("/");
  const year = now.getUTCFullYear();
  const dates = [new Date(Date.UTC(year, 0, 15)), new Date(Date.UTC(year, 6, 15))];
  const abbreviations = unique(dates.map((at) => zoneName(zone, "short", at)).filter((name) => !/^(GMT|UTC)[+\-−]/.test(name)));
  return {
    zone,
    label: zoneLabel(zone),
    city: parts[parts.length - 1] ?? zone,
    region: parts.length > 1 ? (parts[0] ?? "") : "",
    generic: zoneName(zone, "longGeneric", now),
    common: COMMON_NAMES[zone] ?? [],
    abbreviations,
    long: unique(dates.map((at) => zoneName(zone, "long", at))),
  };
}

export function buildIndex(zones: string[], now: Date = new Date()): ZoneEntry[] {
  return zones.map((zone) => zoneEntry(zone, now));
}

function rank(entry: ZoneEntry, query: string): number {
  const city = normalize(entry.city);
  if (city === query) return 0;
  if (city.startsWith(query)) return 1;
  const named = [normalize(entry.region), ...entry.common.map(normalize)];
  if (named.some((name) => name === query || name.startsWith(query))) return 2;
  const abbreviations = entry.abbreviations.map(normalize);
  if (abbreviations.some((name) => name === query || name.startsWith(query))) return 3;
  const everything = [normalize(entry.zone), ...named, ...abbreviations, ...entry.long.map(normalize)];
  if (everything.some((name) => name.includes(query))) return 4;
  return -1;
}

export function searchZones(index: ZoneEntry[], text: string, limit: number = MAX_SHOWN): ZoneEntry[] {
  const query = normalize(text);
  if (!query) return index.slice(0, limit);
  return index
    .map((entry) => ({ entry, rank: rank(entry, query) }))
    .filter((hit) => hit.rank >= 0)
    .sort((a, b) => a.rank - b.rank || a.entry.zone.localeCompare(b.entry.zone))
    .slice(0, limit)
    .map((hit) => hit.entry);
}

export function describeZone(entry: ZoneEntry): string {
  return entry.generic && !entry.generic.startsWith("GMT") ? `${entry.label}, ${entry.generic}` : entry.label;
}
