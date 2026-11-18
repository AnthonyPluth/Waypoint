export const SHELL_STATES = ["saved", "one", "ten", "none", "off", "saving", "failed", "failed-none", "damaged", "old", "arrival-parking", "arrival-car", "arrival-hotel", "tap-parking", "tap-car", "tap-hotel"];

export function fakeShellScript(state) {
  const MINUTE = 60_000;
  const NAMES = ["Lisbon in June", "Denver offsite", "Kyoto in spring", "Oslo, long weekend", "Cape Town visit", "Lima and Cusco", "Berlin conference", "Hobart family trip", "Montreal in October", "Reykjavik stopover"];
  const SPECS = {
    saved: { count: 2, age: 12 * MINUTE },
    one: { count: 1, age: 0 },
    ten: { count: 10, age: 180 * MINUTE },
    none: { count: 0, age: 0 },
    off: { count: 0, age: 0, saving: false },
    saving: { count: 0, age: 0, syncing: true },
    failed: { count: 2, age: 120 * MINUTE, lastSaveFailed: true },
    "failed-none": { count: 0, age: 0, lastSaveFailed: true },
    damaged: { count: 0, age: 0, broken: true },
    "arrival-parking": { count: 2, age: 12 * MINUTE, here: "parking" },
    "arrival-car": { count: 2, age: 12 * MINUTE, here: "car" },
    "arrival-hotel": { count: 2, age: 12 * MINUTE, here: "hotel" },
    "tap-parking": { count: 2, age: 12 * MINUTE, tapped: "parking" },
    "tap-car": { count: 2, age: 12 * MINUTE, tapped: "car" },
    "tap-hotel": { count: 2, age: 12 * MINUTE, tapped: "hotel" },
  };
  if (state === "old") {
    globalThis.webkit = { messageHandlers: { waypointUnauthorized: { postMessage: () => {} } } };
    return;
  }
  const spec = SPECS[state];
  const savedAt = Date.now() - spec.age;
  let saving = spec.saving ?? true;
  let trips = NAMES.slice(0, spec.count).map((name, i) => ({ id: i + 1, name }));
  const status = () => (spec.broken
    ? { version: 9 }
    : { version: 1, saving, syncing: spec.syncing === true, lastSaveFailed: spec.lastSaveFailed === true, savedAt: trips.length ? savedAt : null, trips });
  const nobody = { version: 1, segmentId: null, tripId: null };
  const latest = async (kind) => {
    const { trips: found } = await (await fetch("/api/trips")).json();
    const wanted = found.flatMap((trip) => trip.segments.map((segment) => ({ tripId: trip.id, segment }))).filter(({ segment }) => segment.kind === kind && segment.status !== "cancelled" && (kind === "parking" ? segment.gate_code?.state === "ready" : !!segment.confirmation));
    wanted.sort((a, b) => b.segment.start_local.localeCompare(a.segment.start_local));
    return wanted.length ? { version: 1, segmentId: wanted[0].segment.id, tripId: wanted[0].tripId } : nobody;
  };
  let waiting = spec.tapped;
  const postMessage = async (message) => {
    if (message.type === "arrivalHere") return spec.here ? latest(spec.here) : nobody;
    if (message.type === "pendingArrival") {
      const kind = waiting;
      waiting = null;
      return kind ? latest(kind) : nobody;
    }
    if (message.type === "load") return { version: 1, trips: [] };
    if (message.type === "setSaving") {
      saving = message.on;
      if (!saving) trips = [];
      spec.broken = false;
      spec.syncing = false;
      spec.lastSaveFailed = false;
    }
    if (message.type === "remove") trips = [];
    return status();
  };
  globalThis.webkit = { messageHandlers: { waypointOffline: { postMessage } } };
}
