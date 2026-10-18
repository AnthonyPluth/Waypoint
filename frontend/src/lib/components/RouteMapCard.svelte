<script lang="ts">
  import { geoPath } from "d3-geo";
  import { landFor } from "$lib/land.svelte";
  import { legsOf, NO_ROADS, positions, routeProjection, type Roads, type Stop } from "$lib/route-replay";
  import { routeDescription } from "$lib/side-column";

  let { tripId, stops, roads = NO_ROADS }: { tripId: number; stops: Stop[]; roads?: Roads } = $props();

  const WIDTH = 340;
  const HEIGHT = 180;
  const projection = $derived(routeProjection(stops, WIDTH, HEIGHT, { x: 34, y: 28 }, roads));
  const path = $derived(geoPath(projection));
  const legs = $derived(legsOf(stops, projection, roads));
  const spots = $derived(positions(stops, projection));
  const sphere = $derived(path({ type: "Sphere" }) ?? "");
  const terrain = landFor(() => ({ projection, width: WIDTH, height: HEIGHT }));
  const land = $derived(terrain.features.map((c) => ({ id: c.id ?? c.properties?.name ?? "", d: path(c) ?? "" })));
  const label = (s: Stop): string => s.code ?? s.city;
</script>

<a href={`#trip/${tripId}`} class="block overflow-hidden rounded-2xl border border-border bg-map-sea" data-testid="route-map">
  <svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label={routeDescription(stops)} class="block h-[180px] w-full">
    <path d={sphere} class="fill-map-sea" />
    <g class="fill-map-land stroke-map-border" stroke-width="0.5" vector-effect="non-scaling-stroke">
      {#each land as c, i (i)}<path d={c.d} />{/each}
    </g>
    <g fill="none" stroke-linecap="round" stroke-linejoin="round">
      {#each legs as leg, i (i)}
        <path d={leg.d} stroke-width="1.8" class={leg.flight ? "stroke-map-route" : "stroke-map-stay"} stroke-dasharray={leg.flight ? "4 3" : undefined} data-leg={leg.flight ? "flight" : "ground"} />
      {/each}
    </g>
    {#each stops as s, i (i)}
      <g data-stop={s.name} transform="translate({spots[i].x} {spots[i].y})">
        <circle r="3.5" class="fill-map-airport stroke-map-sea" stroke-width="1.5" />
        <text x={spots[i].x > WIDTH * 0.7 ? -6 : 6} y="-5" text-anchor={spots[i].x > WIDTH * 0.7 ? "end" : "start"} font-size="9" class="mono fill-foreground" paint-order="stroke" stroke-width="2.5" stroke-linejoin="round" style="stroke: var(--map-sea)">{label(s)}</text>
      </g>
    {/each}
  </svg>
</a>
