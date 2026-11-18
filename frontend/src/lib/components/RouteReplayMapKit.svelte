<script lang="ts">
  import type { Maps } from "$lib/mapkit";
  import { createReplayMap, DEFAULT_PALETTE, type ReplayMap } from "$lib/replay-mapkit";
  import type { Roads, Stop } from "$lib/route-replay";

  let { maps, tripId, stops, roads, width, height, progress, playing, calm, onfailure, label = "Map of the route, stop by stop; the stops are listed below" }: {
    maps: Maps; tripId?: number; stops: Stop[]; roads: Roads; width: number; height: number; progress: number; playing: boolean; calm: boolean; onfailure: () => void; label?: string;
  } = $props();

  let host = $state<HTMLElement | null>(null);
  let replay = $state.raw<ReplayMap | null>(null);

  $effect(() => {
    const element = host;
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
      made = createReplayMap(maps.mk, element, { stops, roads, width, height, palette, scale: element.clientWidth / width || 1, onFailure: onfailure, tripId });
    } catch {
      onfailure();
      return;
    }
    const stop = maps.onFailure(onfailure);
    replay = made;
    return () => { stop(); made.destroy(); replay = null; };
  });

  $effect(() => { replay?.update({ progress, playing, calm }); });
</script>

<div bind:this={host} class="block h-full w-full" data-mapkit="true" data-zoomed="false" role="img" aria-label={label}></div>
