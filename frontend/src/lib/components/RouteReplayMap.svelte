<script lang="ts">
  import { geoPath } from "d3-geo";
  import { Button } from "$lib/components/ui/button";
  import { loadCountries, type Country } from "$lib/map";
  import { viewport } from "$lib/phone.svelte";
  import { activeStop, legProgress, legsOf, positions, reached, replayMs, routeProjection, stopDates, stopLine, type Stop } from "$lib/route-replay";
  import Pause from "@lucide/svelte/icons/pause";
  import Play from "@lucide/svelte/icons/play";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";

  let { stops, year, still = null }: { stops: Stop[]; year: number; still?: boolean | null } = $props();

  const query = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  let observed = $state(query?.matches ?? false);
  const calm = $derived(still ?? observed);
  $effect(() => {
    if (!query) return;
    const change = (e: MediaQueryListEvent) => { observed = e.matches; };
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  });

  const width = $derived(viewport.phone ? 600 : 960);
  const height = $derived(viewport.phone ? 640 : 520);
  const projection = $derived(routeProjection(stops, width, height));
  const path = $derived(geoPath(projection));
  const legs = $derived(legsOf(stops, projection));
  const spots = $derived(positions(stops, projection));
  const sphere = $derived(path({ type: "Sphere" }) ?? "");
  let countries = $state<Country[]>([]);
  const land = $derived(countries.map((c) => ({ id: c.id ?? c.properties?.name ?? "", d: path(c) ?? "" })));
  $effect(() => { loadCountries().then((c) => { countries = c; }, () => { countries = []; }); });

  let progress = $state(0);
  let playing = $state(false);
  $effect(() => { if (calm) { progress = 1; playing = false; } });
  const duration = $derived(replayMs(stops.length));
  const now = $derived(calm ? stops.length - 1 : activeStop(stops.length, progress));

  $effect(() => {
    if (!playing) return;
    let frame = 0;
    let last = performance.now();
    const step = (at: number) => {
      progress = Math.min(1, progress + (at - last) / duration);
      last = at;
      if (progress >= 1) { playing = false; return; }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  });

  function toggle() {
    if (progress >= 1) { progress = 0; playing = true; } else playing = !playing;
  }
  const scrub = (e: Event) => { playing = false; progress = Number((e.currentTarget as HTMLInputElement).value) / 1000; };

  const showing = (i: number) => calm || reached(i, stops.length, progress);
  const alone = $derived(spots.map((p, i) => spots.slice(0, i).every((q) => Math.hypot(p.x - q.x, p.y - q.y) > 40)));
  const above = (i: number) => (spots[i].y > height * 0.72 ? true : spots[i].y < height * 0.28 ? false : i % 2 === 0);
  const edge = (x: number) => (x < width * 0.22 ? "0%" : x > width * 0.78 ? "-100%" : "-50%");
  const buttonLabel = $derived(progress >= 1 ? "Replay" : playing ? "Pause" : progress > 0 ? "Resume" : "Play");
</script>

<div class="space-y-3">
  <div class="relative overflow-hidden rounded-2xl border border-border bg-map-sea" style="aspect-ratio: {width} / {height}" data-testid="replay-map">
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="Map of the route, stop by stop; the stops are listed below" class="block h-full w-full">
      <path d={sphere} class="fill-map-sea" />
      <g class="fill-map-land stroke-map-border" stroke-width="0.5" vector-effect="non-scaling-stroke">
        {#each land as c (c.id)}<path d={c.d} />{/each}
      </g>
      <g fill="none" stroke-linecap="round" data-testid="legs">
        {#each legs as leg, i (i)}
          {@const done = calm ? 1 : legProgress(i, stops.length, progress)}
          {#if done > 0}
            <path d={leg.d} pathLength="1" stroke-dasharray="1" stroke-dashoffset={1 - done} stroke-width={leg.flight ? 2.5 : 2}
              class={leg.flight ? "stroke-map-route" : "stroke-map-stay"} data-leg={leg.flight ? "flight" : "ground"} />
          {/if}
        {/each}
      </g>
      <g data-testid="stops">
        {#each stops as s, i (i)}
          {#if showing(i)}
            <g data-stop={s.name}>
              {#if !calm && playing && i === now}<circle cx={spots[i].x} cy={spots[i].y} r="9" class="animate-ping fill-map-airport/60" style="transform-box: fill-box; transform-origin: center" />{/if}
              <circle cx={spots[i].x} cy={spots[i].y} r="6" class="fill-map-airport stroke-map-sea" stroke-width="2" />
            </g>
          {/if}
        {/each}
      </g>
    </svg>
    {#each stops as s, i (i)}
      {#if showing(i) && alone[i]}
        <div class="pointer-events-none absolute w-max max-w-[11rem] rounded-lg border border-border bg-card px-2 py-1 text-xs leading-tight shadow-elevation-1"
          style="left: {(spots[i].x / width) * 100}%; top: {(spots[i].y / height) * 100}%; transform: translate({edge(spots[i].x)}, {above(i) ? 'calc(-100% - 12px)' : '12px'})"
          data-label={s.name}>
          <p class="break-words font-semibold text-foreground">{s.name}</p>
          <p class="text-muted-foreground">{stopDates(s, year)}</p>
        </div>
      {/if}
    {/each}
  </div>
  <ul class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground" aria-label="Map key">
    <li class="flex items-center gap-2"><span class="size-2.5 rounded-full bg-map-airport" aria-hidden="true"></span>Stop</li>
    <li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-route" aria-hidden="true"></span>Flight</li>
    {#if legs.some((l) => !l.flight)}<li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-stay" aria-hidden="true"></span>Other travel</li>{/if}
  </ul>
  {#if !calm}
    <div class="flex items-center gap-3">
      <Button variant="outline" onclick={toggle}>
        {#if progress >= 1}<RotateCcw />{:else if playing}<Pause />{:else}<Play />{/if}{buttonLabel}
      </Button>
      <input type="range" min="0" max="1000" step="1" value={Math.round(progress * 1000)} oninput={scrub} aria-label="Position along the route"
        aria-valuetext={stopLine(stops[now], year)} class="h-11 min-w-0 flex-1 accent-primary" />
    </div>
  {/if}
  <ol class="space-y-1 text-sm" aria-label="Stops in order" data-testid="stop-list">
    {#each stops as s, i (i)}
      <li class="flex gap-2"><span class="w-5 shrink-0 text-right text-muted-foreground" aria-hidden="true">{i + 1}.</span><span class="min-w-0 break-words">{stopLine(s, year)}</span></li>
    {/each}
  </ol>
</div>
