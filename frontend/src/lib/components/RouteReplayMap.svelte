<script lang="ts">
  import { geoPath } from "d3-geo";
  import { Button } from "$lib/components/ui/button";
  import { landFor } from "$lib/land.svelte";
  import { viewport } from "$lib/phone.svelte";
  import { activeStop, boundariesShown, boundaryShapes, cameraAt, inView, labelLit, LABEL_HOLD_MS, moverAt, NO_BOUNDARIES, NO_ROADS, roadShapes, roadsShown, SCRUB_STEPS, shieldsOf, legProgress, legsOf, positions, reached, replayMs, routeProjection, stopDates, stopLine, stopTitle, type Boundaries, type Roads, type Stop } from "$lib/route-replay";
  import Pause from "@lucide/svelte/icons/pause";
  import Play from "@lucide/svelte/icons/play";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";

  let { stops, year, roads = NO_ROADS, boundaries = NO_BOUNDARIES, still = null, autoplay = false }: { stops: Stop[]; year: number; roads?: Roads; boundaries?: Boundaries; still?: boolean | null; autoplay?: boolean } = $props();

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
  const projection = $derived(routeProjection(stops, width, height, undefined, roads));
  const path = $derived(geoPath(projection));
  const legs = $derived(legsOf(stops, projection, roads));
  const shapes = $derived(roadShapes(roads.interstates, projection));
  const lines = $derived(boundaryShapes(boundaries, projection));
  const spots = $derived(positions(stops, projection));
  const sphere = $derived(path({ type: "Sphere" }) ?? "");

  let progress = $state(0);
  let playing = $state(false);
  let tail = $state(0);
  const SPEEDS = [1, 2, 4];
  let speed = $state(1);
  const nextSpeed = () => { speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]; };
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
      const elapsed = (at - last) * speed;
      if (progress < 1) progress = Math.min(1, progress + elapsed / duration);
      else tail += elapsed;
      last = at;
      if (progress >= 1 && tail >= LABEL_HOLD_MS + 500) { playing = false; return; }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  });

  function toggle() {
    if (progress >= 1) { progress = 0; tail = 0; playing = true; } else playing = !playing;
  }
  const scrub = (e: Event) => { playing = false; tail = 0; progress = Number((e.currentTarget as HTMLInputElement).value) / SCRUB_STEPS; };

  const showing = (i: number) => calm || reached(i, stops.length, progress);
  const lit = (i: number) => calm || (i === stops.length - 1 ? progress >= 1 && playing && tail < LABEL_HOLD_MS : labelLit(i, stops.length, progress, !playing));
  const box = $derived(calm ? { x: 0, y: 0, w: width, h: height } : cameraAt(stops, spots, width, height, progress, legs));
  const terrain = landFor(() => ({ projection, width, height, box, zoom: width / box.w }));
  const land = $derived(terrain.features.map((c, i) => ({ id: i, d: path(c) ?? "" })));
  const zoom = $derived(box.w / width);
  const drawn = $derived(roadsShown(projection, zoom) ? shapes.filter((r) => inView(r, box)) : []);
  const stateLines = $derived(boundariesShown(projection, zoom) ? lines.filter((l) => inView(l, box)) : []);
  const shields = $derived(shieldsOf(drawn, box, zoom));
  const zoomed = $derived(box.w < width - 0.5);
  const movers = $derived(legs.flatMap((leg, i) => {
    const done = calm ? 1 : legProgress(i, stops.length, progress);
    if (done <= 0 || done >= 1) return [];
    return [{ i, moving: true, vehicle: leg.vehicle, ...moverAt(leg, done) }];
  }));
  const RING: Record<Stop["kind"], string> = { airport: "border-map-airport", stay: "border-map-stay", home: "border-map-visited", place: "border-map-visited" };
  const following = $derived(!calm && (playing || progress > 0));
  let listBox = $state<HTMLElement | null>(null);
  let quietUntil = 0;
  const QUIET_MS = 4000;
  const handsOff = () => { quietUntil = performance.now() + QUIET_MS; };
  function quiet(node: HTMLElement) {
    const events = ["wheel", "touchmove", "pointerdown", "keydown"];
    events.forEach((e) => node.addEventListener(e, handsOff, { passive: true }));
    return { destroy: () => events.forEach((e) => node.removeEventListener(e, handsOff)) };
  }
  $effect(() => {
    const index = now;
    const box = listBox;
    if (!following || !box) return;
    const centre = () => {
      const item = box.querySelector<HTMLElement>(`[data-stop-item="${index}"]`);
      if (item) box.scrollTo({ top: Math.max(0, item.offsetTop - (box.clientHeight - item.offsetHeight) / 2), behavior: "smooth" });
    };
    const wait = quietUntil - performance.now();
    if (wait <= 0) { centre(); return; }
    const timer = setTimeout(centre, wait);
    return () => clearTimeout(timer);
  });
  const buttonLabel = $derived(progress >= 1 ? "Replay" : playing ? "Pause" : progress > 0 ? "Resume" : "Play");
</script>

<div class="space-y-3">
  <div class="relative overflow-hidden rounded-2xl border border-border bg-map-sea" style="aspect-ratio: {width} / {height}" data-testid="replay-map">
    <svg viewBox="{box.x} {box.y} {box.w} {box.h}" data-zoomed={zoomed} role="img" aria-label="Map of the route, stop by stop; the stops are listed below" class="block h-full w-full">
      <path d={sphere} class="fill-map-sea" />
      <g class="fill-map-land stroke-map-border" stroke-width="0.5" vector-effect="non-scaling-stroke">
        {#each land as c, i (i)}<path d={c.d} />{/each}
      </g>
      {#if stateLines.length}
        <g aria-hidden="true" fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="4 3" opacity="0.8" data-testid="state-lines">
          {#each stateLines as l, i (i)}<path d={l.d} class="stroke-map-border" stroke-width="1" vector-effect="non-scaling-stroke" />{/each}
        </g>
      {/if}
      {#if drawn.length}
        <g aria-hidden="true" fill="none" stroke-linecap="round" stroke-linejoin="round" data-testid="interstates">
          {#each drawn as r, i (i)}<path d={r.d} data-road={r.ref} class="stroke-map-border" stroke-width={1.6 * zoom} />{/each}
        </g>
      {/if}
      <g fill="none" stroke-linecap="round" stroke-linejoin="round" data-testid="legs">
        {#each legs as leg, i (i)}
          {@const done = calm ? 1 : legProgress(i, stops.length, progress)}
          {#if done > 0}
            <path d={leg.d} pathLength="1" stroke-dasharray="1" stroke-dashoffset={1 - done} stroke-width={(leg.flight ? 2.5 : 2) * zoom}
              class={leg.flight ? "stroke-map-route" : "stroke-map-stay"} data-leg={leg.flight ? "flight" : "ground"} data-road-leg={leg.road ? leg.refs.join(" ") : undefined} />
          {/if}
        {/each}
      </g>
      <g data-testid="stops">
        {#each stops as s, i (i)}
          {#if showing(i)}
            <g data-stop={s.name} data-kind={s.kind} transform="translate({spots[i].x} {spots[i].y}) scale({zoom})">
              {#if !calm && playing && i === now}<circle r="10" class="animate-ping fill-map-airport/60" style="transform-box: fill-box; transform-origin: center" />{/if}
              {#if s.kind === "stay"}
                <rect x="-6" y="-6" width="12" height="12" rx="2" transform="rotate(45)" class="fill-map-stay stroke-map-sea" stroke-width="2" />
              {:else if s.kind === "home"}
                <path d="M0 -8 L8 -1 L5.5 -1 L5.5 6 L-5.5 6 L-5.5 -1 L-8 -1 Z" class="fill-map-visited stroke-map-sea" stroke-width="2" stroke-linejoin="round" data-house />
              {:else if s.kind === "airport"}
                <circle r="6" class="fill-map-airport stroke-map-sea" stroke-width="2" />
              {:else}
                <circle r="4.5" class="fill-map-visited stroke-map-sea" stroke-width="2" />
              {/if}
            </g>
          {/if}
        {/each}
      </g>
      {#if shields.length}
        <g aria-hidden="true" data-testid="shields">
          {#each shields as sh (sh.ref + sh.x)}
            <g data-shield={sh.ref} transform="translate({sh.x.toFixed(1)} {sh.y.toFixed(1)}) scale({zoom})">
              <rect x={-(sh.ref.length * 3 + 4)} y="-8" width={sh.ref.length * 6 + 8} height="16" rx="4" class="fill-card stroke-map-border" stroke-width="1" />
              <text text-anchor="middle" dy="3.5" font-size="10" font-weight="600" class="fill-muted-foreground">{sh.ref}</text>
            </g>
          {/each}
        </g>
      {/if}
      <g data-testid="movers" aria-hidden="true">
        {#each movers as m (m.i)}
          <g data-mover={m.i} data-vehicle={m.vehicle} data-plane={m.vehicle === "plane" ? m.i : undefined} data-car={m.vehicle === "car" ? m.i : undefined} data-boat={m.vehicle === "boat" ? m.i : undefined}
            data-flying={m.moving} transform="translate({m.x.toFixed(1)} {m.y.toFixed(1)}) rotate({m.angle.toFixed(1)}) scale({1.1 * zoom})">
            {#if m.vehicle === "plane"}
              <path d="M12 0 L3 -2.5 L-2 -10 L-5 -10 L-3 -1.5 L-8 -1.5 L-10 -4 L-12.5 -4 L-10.5 0 L-12.5 4 L-10 4 L-8 1.5 L-3 1.5 L-5 10 L-2 10 L3 2.5 Z" class="fill-map-route stroke-map-sea" stroke-width="1.2" stroke-linejoin="round" />
            {:else if m.vehicle === "car"}
              <rect x="-9" y="-5" width="18" height="10" rx="3" class="fill-map-stay stroke-map-sea" stroke-width="1.2" />
              <rect x="1" y="-3.5" width="4" height="7" rx="1" class="fill-map-sea" />
            {:else}
              <path d="M12 0 L6 6 L-10 6 L-8 0 L-10 -6 L6 -6 Z" class="fill-map-visited stroke-map-sea" stroke-width="1.2" stroke-linejoin="round" />
            {/if}
          </g>
        {/each}
      </g>
    </svg>
    <div aria-hidden="true" class="pointer-events-none absolute left-2 top-2 grid max-w-[11rem]">
      {#each stops as s, i (i)}
        <div class="col-start-1 row-start-1 w-max max-w-[11rem] self-start rounded-lg transition-opacity duration-500 motion-reduce:transition-none border border-border bg-card px-2 py-1 text-xs leading-tight shadow-elevation-1"
            class:opacity-0={!lit(i)} data-visible={lit(i)} data-label={s.name}>
          <p class="break-words font-semibold text-foreground">{stopTitle(s)}</p>
          <p class="text-muted-foreground">{stopDates(s, year)}</p>
        </div>
      {/each}
    </div>
  </div>
  <ul class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground" aria-label="Map key">
    <li class="flex items-center gap-2"><span class="size-2.5 rounded-full bg-map-airport" aria-hidden="true"></span>Airport</li>
    {#if stops.some((s) => s.kind === "stay")}<li class="flex items-center gap-2"><span class="size-2.5 rotate-45 rounded-[2px] bg-map-stay" aria-hidden="true"></span>Stay</li>{/if}
    {#if stops.some((s) => s.kind === "home")}<li class="flex items-center gap-2"><svg viewBox="-9 -9 18 16" class="h-3 w-3.5" aria-hidden="true"><path d="M0 -8 L8 -1 L5.5 -1 L5.5 6 L-5.5 6 L-5.5 -1 L-8 -1 Z" class="fill-map-visited" /></svg>Home</li>{/if}
    {#if stops.some((s) => s.kind === "place")}<li class="flex items-center gap-2"><span class="size-2 rounded-full bg-map-visited" aria-hidden="true"></span>Other stop</li>{/if}
    <li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-route" aria-hidden="true"></span>Flight</li>
    {#if stateLines.length}<li class="flex items-center gap-2"><span class="w-4 border-t border-dashed border-map-border" aria-hidden="true"></span>State line</li>{/if}
    {#if roads.interstates.length}<li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-border" aria-hidden="true"></span>Highway</li>{/if}
    {#if legs.some((l) => !l.flight)}<li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-stay" aria-hidden="true"></span>Other travel</li>{/if}
  </ul>
  {#if !calm}
    <div class="flex items-center gap-3">
      <Button variant="outline" onclick={toggle}>
        {#if progress >= 1}<RotateCcw />{:else if playing}<Pause />{:else}<Play />{/if}{buttonLabel}
      </Button>
      <Button variant="outline" size="sm" onclick={nextSpeed} aria-label="Playback speed {speed}×" class="tabular-nums">{speed}×</Button>
      <input type="range" min="0" max={SCRUB_STEPS} step="1" value={Math.round(progress * SCRUB_STEPS)} oninput={scrub} aria-label="Position along the route"
        aria-valuetext={stopLine(stops[now], year)} class="h-11 min-w-0 flex-1 accent-primary" />
    </div>
  {/if}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div bind:this={listBox} use:quiet class="relative max-h-[24rem] overflow-y-auto overscroll-contain rounded-xl" tabindex="0" role="region" aria-label="Stops list">
    <ol class="text-sm" aria-label="Stops in order" data-testid="stop-list">
      {#each stops as s, i (i)}
        {@const current = following && i === now}
        <li class="relative flex gap-3 rounded-xl px-2 py-2 transition-colors duration-300 motion-reduce:transition-none" class:bg-secondary={current} aria-current={current ? "step" : undefined} data-stop-item={i} data-current={current}>
          {#if i < stops.length - 1}<span class="absolute -bottom-2 left-5 top-8 w-px -translate-x-1/2 bg-border" aria-hidden="true"></span>{/if}
          <span class={`z-10 flex size-6 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold tabular-nums ${RING[s.kind]} ${current ? "bg-foreground text-background" : "bg-card text-foreground"}`} aria-hidden="true">{i + 1}</span>
          <div class="min-w-0 pt-0.5">
            <p class="break-words font-medium text-foreground">{stopTitle(s)}<span class="sr-only">, </span></p>
            <p class="text-muted-foreground">{stopDates(s, year)}</p>
          </div>
        </li>
      {/each}
    </ol>
  </div>
</div>
