import type { OfflineTrip } from "./api-types";
import { inShell, shellLoad } from "./offline-shell";

export type SavedCode = { picture: string | null };

export async function savedCodeFor(segmentId: number): Promise<SavedCode | null> {
  if (!inShell()) return null;
  try {
    for (const copy of (await shellLoad()) as Partial<OfflineTrip>[]) {
      const hit = Array.isArray(copy?.codes) ? copy.codes.find((c) => c.segment_id === segmentId) : undefined;
      if (hit && typeof hit.type === "string" && typeof hit.data === "string") return { picture: `data:${hit.type};base64,${hit.data}` };
    }
  } catch { return { picture: null }; }
  return { picture: null };
}
