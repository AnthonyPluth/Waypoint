<script lang="ts">
  import { geoContains, geoPath } from "d3-geo";
  import { errMsg } from "$lib/act";
  import type { StatsFlights } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { clampPan, IDENTITY, loadCountries, MAP_HEIGHT, MAP_WIDTH, mapData, visitedFeatureIds, worldProjection, zoomAt, type Country, type Transform } from "$lib/map";
  import Minus from "@lucide/svelte/icons/minus";
  import Plus from "@lucide/svelte/icons/plus";

  // Everywhere you've flown, drawn here from the outlines bundled with the app (Natural Earth through world-atlas): no tiles,
  // no map host, nothing sent anywhere. Takes the stats' flights as a prop. Tap or hover an airport or an arc for its name
  // and count; drag, pinch or use the buttons to zoom, and Reset to see the whole world again.
  let { flights }: { flights: StatsFlights } = $props();

  let countries = $state<Country[] | null>(null);
  let loadError = $state("");

  async function loadOutlines() {
    loadError = "";
    try { countries = await loadCountries(); } catch (err) { loadError = errMsg(err); }
  }
  $effect(() => { void loadOutlines(); });

  const projection = worldProjection();
  const path = geoPath(projection);
  const world = $derived(mapData(flights, projection));
  const outlines = $derived((countries ?? []).map((c) => ({ id: c.id, name: c.properties?.name ?? "", d: path(c) ?? "" })));
  const visited = $derived(countries ? visitedFeatureIds(flights.airports, countries, (f, p) => geoContains(f, p)) : new Set<string | number>());
  const sphere = path({ type: "Sphere" }) ?? "";

  // What's picked (tap, focus) or pointed at (hover): its label shows under the map, so a finger isn't covering it.
  let picked = $state<string | null>(null);
  let hovered = $state<string | null>(null);
  const caption = $derived(hovered ?? picked);

  // Zoom and pan: a transform on the drawing, kept so the world always covers the map's box.
  let t = $state<Transform>(IDENTITY);
  let svg = $state<SVGSVGElement>();
  const pointers = new Map<number, { x: number; y: number }>();
  let dragged = false;
  let pinch = 0;

  /** A pointer's place in the map's own box (viewBox units), however wide the map is on screen. */
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
    if (!e.ctrlKey && !e.metaKey && t.k === 1) return;   // a plain scroll past the map keeps scrolling the page
    e.preventDefault();
    const p = inBox(e);
    t = zoomAt(t, Math.exp(-e.deltaY / 300), p.x, p.y);
  }
  const zoomBy = (f: number) => (t = zoomAt(t, f, MAP_WIDTH / 2, MAP_HEIGHT / 2));
  const reset = () => { t = IDENTITY; picked = null; };

  // A wheel listener has to be non-passive to stop the page scrolling under a zoom.
  $effect(() => {
    const el = svg;
    if (!el) return;
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  });

  const pick = (label: string) => { if (!dragged) picked = label; };
  const key = (e: KeyboardEvent, label: string) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picked = label; } };
</script>

<div>
  <div class="relative overflow-hidden rounded-2xl border border-border bg-card">
    {#if loadError}
      <p class="p-6 text-sm text-muted-foreground">The map couldn’t be drawn: {loadError} <Button variant="outline" size="sm" onclick={loadOutlines}>Try again</Button></p>
    {:else}
      <svg
        bind:this={svg} viewBox="0 0 {MAP_WIDTH} {MAP_HEIGHT}" role="group" aria-label="Map of the airports and routes you’ve flown"
        class="block h-auto w-full touch-pan-y select-none {t.k > 1 ? 'cursor-grab touch-none' : ''}"
        onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onpointerleave={(e) => { if (e.pointerType === "mouse") up(e); }}
      >
        <path d={sphere} class="fill-muted/60" />
        <g transform="translate({t.x} {t.y}) scale({t.k})" data-testid="map-layer">
          <g role="presentation" class="stroke-border" stroke-width="0.5" vector-effect="non-scaling-stroke" onclick={() => { if (!dragged) picked = null; }}>
            {#each outlines as c (c.id ?? c.name)}
              <path d={c.d} class={visited.has(c.id ?? "") ? "fill-primary/35" : "fill-card"} data-visited={visited.has(c.id ?? "") ? "true" : undefined}><title>{c.name}</title></path>
            {/each}
          </g>
          <g fill="none" stroke-linecap="round" class="stroke-primary" data-testid="arcs">
            {#each world.arcs as a (a.key)}
              <!-- A wide, invisible stroke under each arc, so a thin one is easy to hit with a finger. -->
              <g role="button" tabindex="0" aria-label={a.label} onclick={() => pick(a.label)} onkeydown={(e) => key(e, a.label)}
                onpointerenter={(e) => { if (e.pointerType === "mouse") hovered = a.label; }} onpointerleave={() => (hovered = null)} onfocus={() => (picked = a.label)} class="cursor-pointer outline-none focus-visible:[&>path:last-child]:stroke-signal">
                <path d={a.d} stroke="transparent" stroke-width="14" vector-effect="non-scaling-stroke" />
                <path d={a.d} stroke-width={a.width} stroke-opacity="0.7" vector-effect="non-scaling-stroke" data-arc={a.key} />
              </g>
            {/each}
          </g>
          <g data-testid="dots">
            {#each world.dots as d (d.code)}
              <g role="button" tabindex="0" aria-label={d.label} onclick={() => pick(d.label)} onkeydown={(e) => key(e, d.label)}
                onpointerenter={(e) => { if (e.pointerType === "mouse") hovered = d.label; }} onpointerleave={() => (hovered = null)} onfocus={() => (picked = d.label)} class="cursor-pointer outline-none [&:focus-visible>circle:last-child]:stroke-foreground">
                <circle cx={d.x} cy={d.y} r={Math.max(d.r / t.k, 9 / t.k)} fill="transparent" />
                <circle cx={d.x} cy={d.y} r={d.r / t.k} class="fill-signal stroke-card" stroke-width={1.5 / t.k} data-dot={d.code} />
              </g>
            {/each}
          </g>
        </g>
      </svg>
    {/if}
  </div>
  <div class="mt-2 flex items-start justify-between gap-3">
    <p class="min-h-5 text-sm text-muted-foreground" aria-live="polite">
      {#if caption}<span class="font-medium text-foreground">{caption}</span>
      {:else if world.dots.length === 0}No airports to show on the map yet.
      {:else}Tap an airport or a route for its name and count.{/if}
    </p>
    {#if !loadError}
      <div class="flex shrink-0 gap-1">
        <Button variant="outline" size="icon" aria-label="Zoom in" disabled={t.k >= 8} onclick={() => zoomBy(1.6)}><Plus /></Button>
        <Button variant="outline" size="icon" aria-label="Zoom out" disabled={t.k <= 1} onclick={() => zoomBy(1 / 1.6)}><Minus /></Button>
        <Button variant="outline" size="sm" disabled={t.k === 1} onclick={reset}>Reset</Button>
      </div>
    {/if}
  </div>
</div>
