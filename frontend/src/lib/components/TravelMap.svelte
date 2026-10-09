<script lang="ts">
  import { geoContains, geoPath } from "d3-geo";
  import { errMsg } from "$lib/act";
  import type { StatsFlights, StatsMapTrip, StatsStayPin } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { clampPan, fitBox, flownBounds, IDENTITY, loadCountries, loadStates, MAP_HEIGHT, MAP_WIDTH, mapData, pins as stayPins, US_ID, visitedFeatureIds, visitedPoints, worldProjection, zoomAt, type Country, type Transform } from "$lib/map";
  import { dateLabel } from "$lib/trips";
  import Minus from "@lucide/svelte/icons/minus";
  import Plus from "@lucide/svelte/icons/plus";

  let { flights, stays = [] }: { flights: StatsFlights; stays?: StatsStayPin[] } = $props();

  let countries = $state<Country[] | null>(null);
  let states = $state<Country[]>([]);
  let loadError = $state("");

  async function loadOutlines() {
    loadError = "";
    try { countries = await loadCountries(); } catch (err) { loadError = errMsg(err); return; }
    try { states = await loadStates(); } catch { states = []; }
  }
  $effect(() => { void loadOutlines(); });

  const projection = worldProjection();
  const path = geoPath(projection);
  const world = $derived(mapData(flights, projection));
  const stayDots = $derived(stayPins(stays, projection));
  const places = $derived(visitedPoints(flights.airports, stays));
  const outlines = $derived((countries ?? []).map((c) => ({ id: c.id, name: c.properties?.name ?? "", d: path(c) ?? "" })));
  const visited = $derived(countries ? visitedFeatureIds(places, countries, (f, p) => geoContains(f, p)) : new Set<string | number>());
  const stateOutlines = $derived(states.map((c) => ({ id: c.id, name: c.properties?.name ?? "", d: path(c) ?? "" })));
  const visitedStates = $derived(states.length ? visitedFeatureIds(places, states, (f, p) => geoContains(f, p)) : new Set<string | number>());
  const byState = $derived(states.length > 0);
  const sphere = path({ type: "Sphere" }) ?? "";

  type Pick = { label: string; trips: StatsMapTrip[] };
  let picked = $state<Pick | null>(null);
  let hovered = $state<string | null>(null);
  const caption = $derived(hovered ?? picked?.label ?? null);
  const when = (t: StatsMapTrip) => (t.start === t.end ? dateLabel(t.start) : `${dateLabel(t.start)} – ${dateLabel(t.end)}`);

  const framed = $derived(fitBox(flownBounds(flights, projection, stays)));
  let t = $state<Transform>(IDENTITY);
  $effect(() => { t = framed; picked = null; });
  let svg = $state<SVGSVGElement>();
  const pointers = new Map<number, { x: number; y: number }>();
  let dragged = false;
  let pinch = 0;

  function inBox(e: { clientX: number; clientY: number }): { x: number; y: number } {
    const r = svg!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * MAP_WIDTH, y: ((e.clientY - r.top) / r.height) * MAP_HEIGHT };
  }
  const spread = () => { const [a, b] = [...pointers.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };

  function down(e: PointerEvent) {
    pointers.set(e.pointerId, inBox(e));
    dragged = false;
    if (pointers.size === 2) pinch = spread();
  }
  function move(e: PointerEvent) {
    const before = pointers.get(e.pointerId);
    if (!before) return;
    const now = inBox(e);
    pointers.set(e.pointerId, now);
    if (pointers.size === 2) {
      const s = spread();
      const [a, b] = [...pointers.values()];
      if (pinch) t = zoomAt(t, s / pinch, (a.x + b.x) / 2, (a.y + b.y) / 2);
      pinch = s; dragged = true;
    } else if (t.k > 1) {
      if (!dragged && Math.hypot(now.x - before.x, now.y - before.y) < 1.5) return;
      dragged = true;
      t = clampPan({ k: t.k, x: t.x + now.x - before.x, y: t.y + now.y - before.y });
    }
  }
  function up(e: PointerEvent) { pointers.delete(e.pointerId); pinch = 0; }
  function wheel(e: WheelEvent) {
    if (!e.ctrlKey && !e.metaKey && t.k === 1) return;
    e.preventDefault();
    const p = inBox(e);
    t = zoomAt(t, Math.exp(-e.deltaY / 300), p.x, p.y);
  }
  const zoomBy = (f: number) => (t = zoomAt(t, f, MAP_WIDTH / 2, MAP_HEIGHT / 2));
  const reset = () => { t = framed; picked = null; };
  const showWorld = () => { t = IDENTITY; picked = null; };

  $effect(() => {
    const el = svg;
    if (!el) return;
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  });

  const pick = (label: string, trips: StatsMapTrip[] = []) => { if (!dragged) picked = { label, trips }; };
  const key = (e: KeyboardEvent, label: string, trips: StatsMapTrip[] = []) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picked = { label, trips }; } };
</script>

<div>
  <div class="relative overflow-hidden rounded-3xl border border-border bg-map-sea shadow-elevation-1">
    {#if loadError}
      <p class="p-6 text-sm text-muted-foreground">The map couldn’t be drawn: {loadError} <Button variant="outline" size="sm" onclick={loadOutlines}>Try again</Button></p>
    {:else}
      <svg
        bind:this={svg} viewBox="0 0 {MAP_WIDTH} {MAP_HEIGHT}" role="group" aria-label="Map of the airports, routes and stays you’ve been to"
        class="block h-auto w-full touch-pan-y select-none {t.k > 1 ? 'cursor-grab touch-none' : ''}"
        onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onpointerleave={(e) => { if (e.pointerType === "mouse") up(e); }}
      >
        <path d={sphere} class="fill-map-sea" />
        <g transform="translate({t.x} {t.y}) scale({t.k})" data-testid="map-layer">
          <g role="presentation" class="stroke-map-border" stroke-width="0.5" vector-effect="non-scaling-stroke" onclick={() => { if (!dragged) picked = null; }}>
            {#each outlines as c (c.id ?? c.name)}
              {@const shaded = visited.has(c.id ?? "") && !(byState && c.id === US_ID)}
              <path d={c.d} class={shaded ? "fill-map-visited" : "fill-map-land"} data-visited={shaded ? "true" : undefined}><title>{c.name}</title></path>
            {/each}
            {#each stateOutlines as c (c.id ?? c.name)}
              <path d={c.d} class={visitedStates.has(c.id ?? "") ? "fill-map-visited" : "fill-map-land"} data-state={c.name} data-visited={visitedStates.has(c.id ?? "") ? "true" : undefined}><title>{c.name}</title></path>
            {/each}
          </g>
          <g fill="none" stroke-linecap="round" class="stroke-map-route" data-testid="arcs">
            {#each world.arcs as a (a.key)}
              <g role="button" tabindex="0" aria-label={a.label} onclick={() => pick(a.label, a.trips)} onkeydown={(e) => key(e, a.label, a.trips)}
                onpointerenter={(e) => { if (e.pointerType === "mouse") hovered = a.label; }} onpointerleave={() => (hovered = null)} onfocus={() => (picked = { label: a.label, trips: a.trips })} class="cursor-pointer outline-none focus-visible:[&>path:last-child]:stroke-foreground">
                <path d={a.d} stroke="transparent" stroke-width="14" vector-effect="non-scaling-stroke" />
                <path d={a.d} stroke-width={a.width} stroke-opacity="0.85" vector-effect="non-scaling-stroke" data-arc={a.key} />
              </g>
            {/each}
          </g>
          <g data-testid="stays">
            {#each stayDots as p (p.key)}
              <g role="button" tabindex="0" aria-label={p.label} onclick={() => pick(p.label, p.trips)} onkeydown={(e) => key(e, p.label, p.trips)}
                onpointerenter={(e) => { if (e.pointerType === "mouse") hovered = p.label; }} onpointerleave={() => (hovered = null)} onfocus={() => (picked = { label: p.label, trips: p.trips })} class="cursor-pointer outline-none [&:focus-visible>rect:last-child]:stroke-foreground">
                <circle cx={p.x} cy={p.y} r={9 / t.k} fill="transparent" />
                <rect x={p.x - 4 / t.k} y={p.y - 4 / t.k} width={8 / t.k} height={8 / t.k} transform="rotate(45 {p.x} {p.y})" class="fill-map-stay stroke-map-sea" stroke-width={1.5 / t.k} data-stay={p.city} />
              </g>
            {/each}
          </g>
          <g data-testid="dots">
            {#each world.dots as d (d.code)}
              <g role="button" tabindex="0" aria-label={d.label} onclick={() => pick(d.label)} onkeydown={(e) => key(e, d.label)}
                onpointerenter={(e) => { if (e.pointerType === "mouse") hovered = d.label; }} onpointerleave={() => (hovered = null)} onfocus={() => (picked = { label: d.label, trips: [] })} class="cursor-pointer outline-none [&:focus-visible>circle:last-child]:stroke-foreground">
                <circle cx={d.x} cy={d.y} r={Math.max(d.r / t.k, 9 / t.k)} fill="transparent" />
                <circle cx={d.x} cy={d.y} r={d.r / t.k} class="fill-map-airport stroke-map-sea" stroke-width={1.5 / t.k} data-dot={d.code} />
              </g>
            {/each}
          </g>
        </g>
      </svg>
    {/if}
  </div>
  {#if !loadError && (world.dots.length || stayDots.length)}
    <ul class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground" aria-label="Map key" data-testid="map-key">
      {#if world.dots.length}<li class="flex items-center gap-2"><span class="size-2.5 rounded-full bg-map-airport" aria-hidden="true"></span>Airport</li>{/if}
      {#if world.arcs.length}<li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-route" aria-hidden="true"></span>Route</li>{/if}
      {#if stayDots.length}<li class="flex items-center gap-2"><span class="size-2.5 rotate-45 bg-map-stay" aria-hidden="true"></span>Stay</li>{/if}
      <li class="flex items-center gap-2"><span class="size-2.5 rounded-sm bg-map-visited" aria-hidden="true"></span>Visited</li>
    </ul>
  {/if}
  <div class="mt-2 flex items-start justify-between gap-3">
    <p class="min-h-5 text-sm text-muted-foreground" aria-live="polite">
      {#if caption}<span class="font-medium text-foreground">{caption}</span>
      {:else if world.dots.length === 0 && stayDots.length === 0}No airports or stays to show on the map yet.
      {:else}Tap an airport, a route or a stay for its name and count, and for the trips there.{/if}
    </p>
    {#if !loadError}
      <div class="flex shrink-0 gap-1">
        <Button variant="outline" size="icon" aria-label="Zoom in" disabled={t.k >= 8} onclick={() => zoomBy(1.6)}><Plus /></Button>
        <Button variant="outline" size="icon" aria-label="Zoom out" disabled={t.k <= 1} onclick={() => zoomBy(1 / 1.6)}><Minus /></Button>
        <Button variant="outline" size="sm" disabled={t.k === framed.k && t.x === framed.x && t.y === framed.y} onclick={reset}>Reset</Button>
        <Button variant="outline" size="sm" disabled={t.k === 1} onclick={showWorld}>World</Button>
      </div>
    {/if}
  </div>
  {#if picked && picked.trips.length}
    <div class="mt-3 rounded-2xl border border-border bg-card p-4 text-sm shadow-elevation-1" data-testid="map-trips">
      <ul class="space-y-1">
        {#each picked.trips as tr, i (`${tr.trip_id}-${tr.start}-${i}`)}
          <li class="flex flex-wrap items-baseline justify-between gap-x-3"><a href={`#trip/${tr.trip_id}`} class="font-medium underline underline-offset-2">{tr.name}</a><span class="text-muted-foreground">{when(tr)}</span></li>
        {/each}
      </ul>
    </div>
  {/if}
</div>
