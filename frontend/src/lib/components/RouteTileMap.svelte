<script lang="ts">
  import { geoPath } from "d3-geo";
  import { landFor } from "$lib/land.svelte";
  import { legsOf, NO_ROADS, positions, routeProjection, type Roads, type Stop } from "$lib/route-replay";

  let { stops, roads = NO_ROADS }: { stops: Stop[]; roads?: Roads } = $props();

  const WIDTH = 400;
  const HEIGHT = 200;

  const projection = $derived(routeProjection(stops, WIDTH, HEIGHT, { x: 44, y: 44 }, roads));
  const path = $derived(geoPath(projection));
  const legs = $derived(legsOf(stops, projection, roads));
  const spots = $derived(positions(stops, projection));
  const terrain = landFor(() => ({ projection, width: WIDTH, height: HEIGHT }));
  const land = $derived(terrain.features.map((c) => path(c) ?? ""));
  const sphere = $derived(path({ type: "Sphere" }) ?? "");
</script>

<svg viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="xMidYMid slice" class="block size-full" aria-hidden="true">
  <path d={sphere} class="fill-map-sea" />
  <g class="fill-map-land stroke-map-border" stroke-width="0.5" vector-effect="non-scaling-stroke">
    {#each land as d, i (i)}<path {d} />{/each}
  </g>
  <g fill="none" stroke-linecap="round" stroke-linejoin="round">
    {#each legs as leg, i (i)}<path d={leg.d} stroke-width={leg.flight ? 2 : 1.6} class={leg.flight ? "stroke-map-route" : "stroke-map-stay"} />{/each}
  </g>
  {#each stops as s, i (i)}
    <circle cx={spots[i].x} cy={spots[i].y} r={s.kind === "airport" ? 3.5 : 3} class={s.kind === "airport" ? "fill-map-airport stroke-map-sea" : s.kind === "stay" ? "fill-map-stay stroke-map-sea" : "fill-map-visited stroke-map-sea"} stroke-width="1.5" />
  {/each}
</svg>
