<script lang="ts">
  import type { Maps } from "$lib/mapkit";
  import { createReplayMap, DEFAULT_PALETTE, type ReplayMap } from "$lib/replay-mapkit";
  import type { Stop } from "$lib/route-replay";

  let { maps, tripId, stops, width, height, progress, playing, calm, onfailure, onready = null, label = "Map of the route, stop by stop; the stops are listed below", decorative = false }: {
    maps: Maps; tripId?: number; stops: Stop[]; width: number; height: number; progress: number; playing: boolean; calm: boolean; onfailure: () => void; onready?: (() => void) | null; label?: string; decorative?: boolean;
  } = $props();

<<<<<<< Updated upstream
=======
  const moreKey = $derived(more.map((m) => `${m.latitude},${m.longitude}`).join(";"));
  // The map is rebuilt only when what it draws changes, not when the same route comes back as new objects.
  const shape = $derived(JSON.stringify([
    stops.map((s) => [s.latitude, s.longitude, s.kind, s.via]),
    roads.interstates.map((r) => [r.ref, r.points.length, r.points[0], r.points[r.points.length - 1]]),
    boundaries.map((b) => [b.points.length, b.points[0], b.points[b.points.length - 1]]),
  ]));
>>>>>>> Stashed changes
  let host = $state<HTMLElement | null>(null);
  let replay = $state.raw<ReplayMap | null>(null);

  $effect(() => {
    const element = host;
<<<<<<< Updated upstream
    if (!element) return;
    if (maps.failed()) {
      onfailure();
      return;
    }
    const css = getComputedStyle(document.documentElement);
    const color = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
    const palette = { route: color("--map-route", DEFAULT_PALETTE.route), stay: color("--map-stay", DEFAULT_PALETTE.stay) };
    let made: ReplayMap;
    try {
      made = createReplayMap(maps.mk, element, { stops, width, height, palette, scale: element.clientWidth / width || 1, onFailure: onfailure, tripId });
    } catch {
      onfailure();
      return;
    }
    const stop = maps.onFailure(onfailure);
    replay = made;
    onready?.();
    return () => { stop(); made.destroy(); replay = null; };
=======
    void moreKey;
    void shape;
    void width;
    void height;
    if (!element) return;
    return untrack(() => {
      const css = getComputedStyle(document.documentElement);
      const color = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
      const palette = { route: color("--map-route", DEFAULT_PALETTE.route), stay: color("--map-stay", DEFAULT_PALETTE.stay), border: color("--map-border", DEFAULT_PALETTE.border) };
      let made: ReplayMap;
      try {
        made = createReplayMap(maps.mk, element, { stops, roads, boundaries, width, height, palette, scale: element.clientWidth / width || 1, onFailure: onfailure, more, onView: onview });
      } catch {
        onfailure();
        return;
      }
      const stop = maps.onFailure(onfailure);
      replay = made;
      return () => { stop(); made.destroy(); replay = null; };
    });
>>>>>>> Stashed changes
  });

  $effect(() => { replay?.update({ progress, playing, calm }); });
</script>

<div bind:this={host} class="block h-full w-full" data-mapkit="true" data-zoomed="false" role={decorative ? undefined : "img"} aria-label={decorative ? undefined : label} aria-hidden={decorative ? "true" : undefined}></div>
