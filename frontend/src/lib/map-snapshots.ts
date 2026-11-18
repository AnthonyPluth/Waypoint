import { ignoreFailure } from "./act";
import { apiCall } from "./contract";
import type { MapSnapshot } from "./api-types";

export type Snapshot = Omit<MapSnapshot, "trip_id">;

export const CARD_TRIPS = 12;
export const CARD_WAIT_MS = 40;

export const KEEP_MS = 12 * 60 * 60 * 1000;

const asked = new Map<string, { job: Promise<Snapshot | null>; at: number }>();
const queued: { trip: number; width: number; height: number; resolve: (snapshot: Snapshot | null) => void }[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;
let generation = 0;

const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

function isSnapshot(s: unknown): s is MapSnapshot {
  const c = s as MapSnapshot | null;
  return typeof c === "object" && c !== null && finite(c.trip_id) && typeof c.url === "string" && c.url.startsWith("https://")
    && typeof c.center === "object" && c.center !== null && finite(c.center.latitude) && finite(c.center.longitude)
    && finite(c.zoom) && finite(c.width) && c.width > 0 && finite(c.height) && c.height > 0;
}

export function clearSnapshots(): void {
  generation++;
  asked.clear();
  clearTimeout(timer);
  for (const waiting of queued.splice(0)) waiting.resolve(null);
}

async function flush(batch: typeof queued, born: number): Promise<void> {
  const bySize = new Map<string, typeof queued>();
  for (const waiting of batch) {
    const key = `${waiting.width}x${waiting.height}`;
    bySize.set(key, [...(bySize.get(key) ?? []), waiting]);
  }
  for (const group of bySize.values()) {
    for (let i = 0; i < group.length; i += CARD_TRIPS) {
      const chunk = group.slice(i, i + CARD_TRIPS);
      const wanted = new Set(chunk.map((c) => c.trip));
      const got = new Map<number, Snapshot>();
      try {
        const query = [...[...wanted].map((t) => `trip=${t}`), `w=${chunk[0].width}`, `h=${chunk[0].height}`, `lang=${encodeURIComponent(navigator.language || "en-US")}`].join("&");
        const reply = await apiCall<"GET /api/map-snapshots">(`/api/map-snapshots?${query}`, { keep: true, background: true });
        if (Array.isArray(reply?.snapshots)) {
          for (const { trip_id, ...snapshot } of reply.snapshots.filter(isSnapshot)) if (wanted.has(trip_id)) got.set(trip_id, snapshot);
        }
      } catch {
        ignoreFailure();
      }
      for (const waiting of chunk) waiting.resolve(born === generation ? (got.get(waiting.trip) ?? null) : null);
    }
  }
}

export function snapshotFor(trip: number, width: number, height: number, revision = ""): Promise<Snapshot | null> {
  const key = `${trip}:${width}x${height}:${revision}`;
  const have = asked.get(key);
  if (have && Date.now() - have.at < KEEP_MS) return have.job;
  const born = generation;
  const job = new Promise<Snapshot | null>((resolve) => {
    queued.push({ trip, width, height, resolve });
    clearTimeout(timer);
    timer = setTimeout(() => void flush(queued.splice(0), born), CARD_WAIT_MS);
  });
  asked.set(key, { job, at: Date.now() });
  return job;
}
