<script lang="ts">
  import { geoPath } from "d3-geo";
  import { Button } from "$lib/components/ui/button";
  import { loadCountries, type Country } from "$lib/map";
  import { viewport } from "$lib/phone.svelte";
  import { activeStop, labelLit, legProgress, legsOf, planeAt, positions, reached, replayMs, routeProjection, stopDates, stopLine, stopTitle, type Stop } from "$lib/route-replay";
  import Pause from "@lucide/svelte/icons/pause";
  import Play from "@lucide/svelte/icons/play";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";

  let { stops, year, still = null, autoplay = false }: { stops: Stop[]; year: number; still?: boolean | null; autoplay?: boolean } = $props();

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
  let started = false;
  $effect(() => {
    if (!autoplay || calm || started) return;
    started = true;
    progress = 0;
    playing = true;
  });
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
  const crowd = $derived(spots.map((p, i) => spots.slice(0, i).filter((q) => Math.hypot(p.x - q.x, p.y - q.y) < 40).length));
  const above = (i: number) => {
    const base = spots[i].y > height * 0.72 ? true : spots[i].y < height * 0.28 ? false : i % 2 === 0;
    return crowd[i] % 2 === 0 ? base : !base;
  };
  const shift = (i: number) => 12 + Math.floor(crowd[i] / 2) * 40;
  const edge = (x: number) => (x < width * 0.22 ? "0%" : x > width * 0.78 ? "-100%" : "-50%");
  const lit = (i: number) => calm || labelLit(i, stops.length, progress, !playing);
  const planeSize = 1.1;
  const planes = $derived(legs.flatMap((leg, i) => {
    if (!leg.flight) return [];
    const done = calm ? 1 : legProgress(i, stops.length, progress);
    if (done <= 0) return [];
    const flying = !calm && done < 1;
    return [{ i, flying, ...planeAt(leg, flying ? done : 0.5) }];
  }));
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
            <g data-stop={s.name} data-kind={s.kind}>
              {#if !calm && playing && i === now}<circle cx={spots[i].x} cy={spots[i].y} r="10" class="animate-ping fill-map-airport/60" style="transform-box: fill-box; transform-origin: center" />{/if}
              {#if s.kind === "stay"}
                <rect x={spots[i].x - 6} y={spots[i].y - 6} width="12" height="12" rx="2" transform="rotate(45 {spots[i].x} {spots[i].y})" class="fill-map-stay stroke-map-sea" stroke-width="2" />
              {:else if s.kind === "airport"}
                <circle cx={spots[i].x} cy={spots[i].y} r="6" class="fill-map-airport stroke-map-sea" stroke-width="2" />
              {:else}
                <circle cx={spots[i].x} cy={spots[i].y} r="4.5" class="fill-map-visited stroke-map-sea" stroke-width="2" />
              {/if}
            </g>
          {/if}
        {/each}
      </g>
      <g data-testid="planes" aria-hidden="true">
        {#each planes as p (p.i)}
          <g data-plane={p.i} data-flying={p.flying} transform="translate({p.x.toFixed(1)} {p.y.toFixed(1)}) rotate({p.angle.toFixed(1)}) scale({planeSize})">
            <path d="M12 0 L3 -2.5 L-2 -10 L-5 -10 L-3 -1.5 L-8 -1.5 L-10 -4 L-12.5 -4 L-10.5 0 L-12.5 4 L-10 4 L-8 1.5 L-3 1.5 L-5 10 L-2 10 L3 2.5 Z" class="fill-map-route stroke-map-sea" stroke-width="1.2" stroke-linejoin="round" />
          </g>
        {/each}
      </g>
    </svg>
    {#each stops as s, i (i)}
      <div aria-hidden="true" class="pointer-events-none absolute w-max max-w-[11rem] rounded-lg transition-opacity duration-500 motion-reduce:transition-none border border-border bg-card px-2 py-1 text-xs leading-tight shadow-elevation-1"
          style="left: {(spots[i].x / width) * 100}%; top: {(spots[i].y / height) * 100}%; transform: translate({edge(spots[i].x)}, {above(i) ? `calc(-100% - ${shift(i)}px)` : `${shift(i)}px`})"
          class:opacity-0={!lit(i)} data-visible={lit(i)} data-label={s.name}>
          <p class="break-words font-semibold text-foreground">{s.back ? "Back in " : ""}{stopTitle(s)}</p>
          <p class="text-muted-foreground">{stopDates(s, year)}</p>
        </div>
    {/each}
  </div>
  <ul class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground" aria-label="Map key">
    <li class="flex items-center gap-2"><span class="size-2.5 rounded-full bg-map-airport" aria-hidden="true"></span>Airport</li>
    {#if stops.some((s) => s.kind === "stay")}<li class="flex items-center gap-2"><span class="size-2.5 rotate-45 rounded-[2px] bg-map-stay" aria-hidden="true"></span>Stay</li>{/if}
    {#if stops.some((s) => s.kind === "place")}<li class="flex items-center gap-2"><span class="size-2 rounded-full bg-map-visited" aria-hidden="true"></span>Other stop</li>{/if}
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
