<script lang="ts">
  import { tick, untrack } from "svelte";
  import { geoEqualEarth, geoPath } from "d3-geo";
  import RouteReplayMapKit from "$lib/components/RouteReplayMapKit.svelte";
  import { Button } from "$lib/components/ui/button";
  import { landFor } from "$lib/land.svelte";
  import type { Maps } from "$lib/mapkit";
  import { clusterCaption, clusterCount, clusterName, clusterTitle, thumbnailUrl, type ClusterInfo } from "$lib/photos";
  import { mercatorFor } from "$lib/replay-mapkit";
  import { viewport } from "$lib/phone.svelte";
  import { clock } from "$lib/trips";
  import { activeStop, boundariesShown, datesOf, PIN_TARGET, pinFraction, pinLit, pinsOf, spreadPins, boundaryShapes, cameraAt, inView, labelLit, LABEL_HOLD_MS, moverAt, NO_BOUNDARIES, NO_ROADS, roadShapes, roadsShown, SCRUB_STEPS, shieldsOf, legProgress, legsOf, positions, reached, replayMs, routeProjection, stopDates, stopLine, stopTitle, type Boundaries, type Box, type Roads, type Stop } from "$lib/route-replay";
  import Pause from "@lucide/svelte/icons/pause";
  import Play from "@lucide/svelte/icons/play";
  import X from "@lucide/svelte/icons/x";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";

  let { stops, year, roads = NO_ROADS, boundaries = NO_BOUNDARIES, still = null, autoplay = false, maps = null, infos = [], unlocated = 0, onshow }: { stops: Stop[]; year: number; roads?: Roads; boundaries?: Boundaries; still?: boolean | null; autoplay?: boolean; maps?: Maps | null; infos?: ClusterInfo[]; unlocated?: number; onshow?: (cluster: number) => void } = $props();
  const replayable = $derived(stops.length >= 2);
  const clusters = $derived(infos.map((i) => i.cluster));
  const away = $derived(new Set(infos.filter((i) => i.far > 0).map((i) => i.index)));
  const photoPlaces = $derived(infos.length > 0);
  const mapLabel = $derived(!replayable ? "Map of where this trip’s photos were taken" : photoPlaces ? "Map of the route, stop by stop, with photo places; the stops are listed below" : "Map of the route, stop by stop; the stops are listed below");
  let fellBack = $state(false);
  const onMapkit = $derived(maps !== null && !fellBack && replayable);

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
  const projection = $derived(routeProjection(stops, width, height, undefined, roads, geoEqualEarth, clusters));
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
  let touched = false;
  $effect(() => {
    if (!autoplay || calm || started || !replayable) return;
    started = true;
    if (touched) return;
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
    touched = true;
    if (progress >= 1) { progress = 0; tail = 0; playing = true; } else playing = !playing;
  }
  const scrub = (e: Event) => { touched = true; playing = false; tail = 0; progress = Number((e.currentTarget as HTMLInputElement).value) / SCRUB_STEPS; };

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
  let mapkitView = $state.raw<Box | null>(null);
  const showView = (view: Box) => { mapkitView = view; };
  const pinProjection = $derived(onMapkit ? mercatorFor(stops, width, height, roads, clusters) : projection);
  const pinBox = $derived(onMapkit ? (calm ? { x: 0, y: 0, w: width, h: height } : (mapkitView ?? { x: 0, y: 0, w: width, h: height })) : box);
  let mapWidth = $state(0);
  let mapHeight = $state(0);
  const pins = $derived.by(() => {
    const placed = pinsOf(clusters, pinProjection, away).map((pin) => ({ ...pin, ...pinFraction(pin, pinBox) }));
    if (mapWidth === 0 || mapHeight === 0) return placed;
    const spread = spreadPins(placed.map((p) => ({ index: p.index, x: (p.left * mapWidth) / 100, y: (p.top * mapHeight) / 100, reach: Math.max(p.size, PIN_TARGET) / 2 })));
    const at = new Map(spread.map((p) => [p.index, p]));
    return placed.map((p) => ({ ...p, left: (at.get(p.index)!.x / mapWidth) * 100, top: (at.get(p.index)!.y / mapHeight) * 100 }));
  });
  const infoOf = (index: number) => infos.find((i) => i.index === index);
  const litPin = (index: number) => calm || !replayable || pinLit(clusters[index], stops, progress);
  const lastLit = new Set<number>();
  let pinging = $state<number[]>([]);
  let named = $state<number | null>(null);
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const later = (run: () => void, ms: number) => {
    const timer = setTimeout(() => { timers.delete(timer); run(); }, ms);
    timers.add(timer);
  };
  $effect(() => () => timers.forEach(clearTimeout));
  $effect(() => {
    const lit = new Set(pins.filter((p) => litPin(p.index)).map((p) => p.index));
    const fresh = [...lit].filter((i) => !lastLit.has(i));
    lastLit.clear();
    lit.forEach((i) => lastLit.add(i));
    if (!playing || calm || !replayable || fresh.length === 0) return;
    untrack(() => {
      pinging = [...pinging, ...fresh];
      later(() => { pinging = pinging.filter((i) => !fresh.includes(i)); }, 1000);
      const latest = fresh[fresh.length - 1];
      named = latest;
      later(() => { if (named === latest) named = null; }, LABEL_HOLD_MS);
    });
  });
  $effect(() => { if (!playing) named = null; });
  let selected = $state<number | null>(null);
  const chosen = $derived(selected === null ? null : (infoOf(selected) ?? null));
  let cardBroken = $state(false);
  $effect(() => { void selected; cardBroken = false; });
  let mapBox = $state<HTMLElement | null>(null);
  function choose(index: number) { selected = selected === index ? null : index; }
  function release(back = true) {
    const was = selected;
    selected = null;
    if (back && was !== null) void tick().then(() => mapBox?.parentElement?.querySelector<HTMLElement>(`[data-pin="${was}"]`)?.focus());
  }
  const dismiss = (e: KeyboardEvent) => { if (e.key === "Escape" && selected !== null) { e.stopPropagation(); release(); } };
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

<div class="space-y-3" role="presentation" onkeydown={dismiss}>
  <div bind:this={mapBox} bind:clientWidth={mapWidth} bind:clientHeight={mapHeight} class="relative overflow-hidden rounded-2xl border border-border bg-map-sea" style="aspect-ratio: {width} / {height}" data-testid="replay-map">
    {#if onMapkit && maps}
      <RouteReplayMapKit {maps} {stops} {roads} {boundaries} {width} {height} {progress} {playing} {calm} more={clusters} onview={showView} label={mapLabel} onfailure={() => { fellBack = true; }} />
    {:else}
    <svg viewBox="{box.x} {box.y} {box.w} {box.h}" data-zoomed={zoomed} role="img" aria-label={mapLabel} class="block h-full w-full">
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
    {/if}
    {#if pins.length}
      <div class="pointer-events-none absolute inset-0" data-testid="photo-pins">
        {#each pins as p (p.index)}
          {@const info = infoOf(p.index)}
          {@const lit = litPin(p.index)}
          <button type="button" aria-label={info ? clusterName(info, year) : undefined} aria-pressed={selected === p.index} onclick={() => choose(p.index)}
            data-pin={p.index} data-count={p.count} data-size={p.size} data-hollow={p.inferred} data-far={p.far} data-lit={lit} style="left: {p.left}%; top: {p.top}%; --s: {Math.max(p.size, PIN_TARGET)}px; width: {Math.max(p.size, PIN_TARGET)}px; height: {Math.max(p.size, PIN_TARGET)}px"
            class={`pointer-events-auto absolute grid -translate-x-1/2 -translate-y-1/2 cursor-pointer place-items-center rounded-full p-0 outline-none transition-opacity duration-500 before:absolute before:inset-[min(0px,calc((var(--s)-44px)/2))] before:rounded-full before:content-[''] focus-visible:ring-[3px] focus-visible:ring-ring motion-reduce:transition-none ${lit ? "" : "opacity-45"}`}>
            <span class={`relative grid place-items-center rounded-full font-mono text-[11px] font-semibold shadow-[0_2px_8px_rgb(0_0_0/50%)] ${p.inferred ? "border-2 border-map-photo bg-map-sea text-map-photo shadow-[0_0_0_2px_var(--map-sea),0_2px_8px_rgb(0_0_0/50%)]" : "border-2 border-map-sea bg-map-photo text-map-sea"} ${selected === p.index ? "outline outline-[3px] outline-offset-[3px] outline-ring" : ""}`} style="width: {p.size}px; height: {p.size}px" data-disc>
              <span aria-hidden="true">{p.count}</span>
              {#if p.far}<span class="absolute -right-[3px] -top-[3px] size-[11px] rounded-full border-2 border-map-sea bg-signal" aria-hidden="true" data-far-dot></span>{/if}
              {#if pinging.includes(p.index)}<span class="pointer-events-none absolute -inset-[9px] animate-ping rounded-full border-2 border-map-photo opacity-60" aria-hidden="true" data-ping></span>{/if}
            </span>
          </button>
        {/each}
      </div>
    {/if}
    {#if named !== null && infoOf(named)}
      {@const info = infoOf(named)!}
      <div aria-hidden="true" class="pointer-events-none absolute bottom-2 left-2 flex max-w-[11rem] items-center gap-2 rounded-lg border border-border bg-card px-2 py-1 text-xs leading-tight shadow-elevation-1" data-testid="photo-label">
        <span class="size-2 shrink-0 rounded-full bg-map-photo"></span>
        <span><b class="block font-semibold text-foreground">{clusterCount(info)}</b><span class="text-muted-foreground">{datesOf(info.cluster.first, info.cluster.first, year, true)}, from {clock(info.cluster.first)}</span></span>
      </div>
    {/if}
    {#if chosen && !viewport.phone}{@render card(chosen, "absolute bottom-3 right-3 w-[300px] max-w-[calc(100%-1.5rem)]")}{/if}
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
  {#if chosen && viewport.phone}{@render card(chosen, "w-full")}{/if}
  <ul class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground" aria-label="Map key">
    {#if replayable}
    <li class="flex items-center gap-2"><span class="size-2.5 rounded-full bg-map-airport" aria-hidden="true"></span>Airport</li>
    {#if stops.some((s) => s.kind === "stay")}<li class="flex items-center gap-2"><span class="size-2.5 rotate-45 rounded-[2px] bg-map-stay" aria-hidden="true"></span>Stay</li>{/if}
    {#if stops.some((s) => s.kind === "home")}<li class="flex items-center gap-2"><svg viewBox="-9 -9 18 16" class="h-3 w-3.5" aria-hidden="true"><path d="M0 -8 L8 -1 L5.5 -1 L5.5 6 L-5.5 6 L-5.5 -1 L-8 -1 Z" class="fill-map-visited" /></svg>Home</li>{/if}
    {#if stops.some((s) => s.kind === "place")}<li class="flex items-center gap-2"><span class="size-2 rounded-full bg-map-visited" aria-hidden="true"></span>Other stop</li>{/if}
    <li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-route" aria-hidden="true"></span>Flight</li>
    {#if stateLines.length}<li class="flex items-center gap-2"><span class="w-4 border-t border-dashed border-map-border" aria-hidden="true"></span>State line</li>{/if}
    {#if roads.interstates.length}<li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-border" aria-hidden="true"></span>Highway</li>{/if}
    {#if legs.some((l) => !l.flight)}<li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-stay" aria-hidden="true"></span>Other travel</li>{/if}
    {/if}
    {#if pins.length}
      <li class="flex items-center gap-2"><span class="size-3 rounded-full bg-map-photo" aria-hidden="true"></span>Photos</li>
      {#if pins.some((p) => p.inferred)}<li class="flex items-center gap-2"><span class="size-3 rounded-full border-2 border-map-photo" aria-hidden="true"></span>Photos placed from the itinerary</li>{/if}
      {#if pins.some((p) => p.far)}<li class="flex items-center gap-2"><span class="size-2.5 rounded-full bg-signal" aria-hidden="true"></span>Far from every booking</li>{/if}
    {/if}
  </ul>
  {#if !replayable && unlocated > 0}
    <p class="text-caption text-muted-foreground" data-testid="unlocated">{unlocated === 1 ? "1 photo has no location and isn’t on the map." : `${unlocated} photos have no location and aren’t on the map.`}</p>
  {/if}
  {#if !calm && replayable}
    <div class="flex items-center gap-3">
      <Button variant="outline" onclick={toggle}>
        {#if progress >= 1}<RotateCcw />{:else if playing}<Pause />{:else}<Play />{/if}{buttonLabel}
      </Button>
      <Button variant="outline" size="sm" onclick={nextSpeed} aria-label="Playback speed {speed}×" class="tabular-nums">{speed}×</Button>
      <input type="range" min="0" max={SCRUB_STEPS} step="1" value={Math.round(progress * SCRUB_STEPS)} oninput={scrub} aria-label="Position along the route"
        aria-valuetext={stopLine(stops[now], year)} class="h-11 min-w-0 flex-1 accent-primary" />
    </div>
  {/if}
  {#if replayable}
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
  {/if}
</div>

{#snippet card(info: ClusterInfo, place: string)}
  <div role="group" aria-label={clusterTitle(info)} data-testid="pin-card" class={`flex flex-wrap items-center gap-3 rounded-[14px] border border-border bg-popover p-2.5 shadow-elevation-3 ${place}`}>
    <div class="size-14 shrink-0 overflow-hidden rounded-[10px] bg-surface-3" aria-hidden="true">
      {#if !cardBroken}<img class="size-full object-cover" src={thumbnailUrl(info.cluster.cover)} alt="" decoding="async" draggable="false" onerror={() => { cardBroken = true; }} />{/if}
    </div>
    <div class="flex min-w-0 flex-1 basis-40 flex-col gap-0.5">
      <p class="text-heading">{clusterCount(info)}</p>
      <p class="text-caption text-muted-foreground">{clusterCaption(info, year)}</p>
    </div>
    <div class="flex basis-full items-center justify-between gap-1">
      <Button size="sm" onclick={() => onshow?.(info.index)}>Show these photos</Button>
      <Button variant="ghost" size="icon" class="size-8" aria-label="Close" onclick={() => release()}><X /></Button>
    </div>
  </div>
{/snippet}
