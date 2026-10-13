import type { Airport } from "$lib/api-types";
import { apiCall } from "$lib/contract";

const known = new Map<string, Promise<Airport | null>>();

export function forgetAirportZones(): void {
  known.clear();
}

export function airportInfo(raw: string): Promise<Airport | null> {
  const code = raw.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) return Promise.resolve(null);
  let found = known.get(code);
  if (!found) {
    found = apiCall<"GET /api/airports/{id}">(`/api/airports/${code}`, { keep: true }).then((a) => a, () => { known.delete(code); return null; });
    known.set(code, found);
  }
  return found;
}

export const airportZone = (raw: string): Promise<string | null> => airportInfo(raw).then((a) => a?.zone ?? null);

export const searchAirports = (text: string): Promise<Airport[]> =>
  text.trim().length < 2
    ? Promise.resolve([])
    : apiCall<"GET /api/airports">(`/api/airports?q=${encodeURIComponent(text.trim())}`).then((r) => r.airports, () => []);
