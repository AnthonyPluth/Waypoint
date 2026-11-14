<script lang="ts">
  import { untrack } from "svelte";
  import type { Maps } from "$lib/mapkit";
  import { createReplayMap, DEFAULT_PALETTE, type ReplayMap } from "$lib/replay-mapkit";
  import type { Boundaries, Box, Roads, Stop } from "$lib/route-replay";

  let { maps, stops, roads, boundaries, width, height, progress, playing, calm, onfailure, more = [], onview, label = "Map of the route, stop by stop; the stops are listed below" }: {
    maps: Maps; stops: Stop[]; roads: Roads; boundaries: Boundaries; width: number; height: number; progress: number; playing: boolean; calm: boolean; onfailure: () => void;
    more?: Pick<Stop, "latitude" | "longitude">[]; onview?: (box: Box) => void; label?: string;
  } = $props();

  const moreKey = $derived(more.map((m) => `${m.latitude},${m.longitude}`).join(";"));
  let host = $state<HTMLElement | null>(null);
  let replay = $state.raw<ReplayMap | null>(null);

  $effect(() => {
    const element = host;
    void moreKey;
    if (!element) return;
    const css = getComputedStyle(document.documentElement);
    const color = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
    const palette = { route: color("--map-route", DEFAULT_PALETTE.route), stay: color("--map-stay", DEFAULT_PALETTE.stay), border: color("--map-border", DEFAULT_PALETTE.border) };
    let made: ReplayMap;
    try {
      made = createReplayMap(maps.mk, element, { stops, roads, boundaries, width, height, palette, scale: element.clientWidth / width || 1, onFailure: onfailure, more: untrack(() => more), onView: untrack(() => onview) });
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
