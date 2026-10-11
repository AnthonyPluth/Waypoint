import { apiCall } from "$lib/contract";

const known = new Map<string, Promise<string | null>>();

export function forgetAirportZones(): void {
  known.clear();
}

export function airportZone(raw: string): Promise<string | null> {
  const code = raw.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) return Promise.resolve(null);
  let found = known.get(code);
  if (!found) {
    found = apiCall<"GET /api/airports/{id}">(`/api/airports/${code}`).then((a) => a.zone, () => { known.delete(code); return null; });
    known.set(code, found);
  }
  return found;
}
