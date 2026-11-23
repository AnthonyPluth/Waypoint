<script lang="ts">
  import { untrack } from "svelte";
  import RouteReplayMapKit from "$lib/components/RouteReplayMapKit.svelte";
  import { Button } from "$lib/components/ui/button";
  import type { Maps } from "$lib/mapkit";
  import { viewport } from "$lib/phone.svelte";
  import { activeStop, labelLit, LABEL_HOLD_MS, SCRUB_STEPS, replayMs, stopDates, stopLine, stopTitle, type Stop } from "$lib/route-replay";
  import Pause from "@lucide/svelte/icons/pause";
  import Play from "@lucide/svelte/icons/play";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";

  let { stops, year, maps, still = null, autoplay = false, stopList = true, tripId, compact = false, onreplay = null, onended = null, onready = null, onfailure = null }: { stops: Stop[]; year: number; maps: Maps; tripId?: number; still?: boolean | null; autoplay?: boolean; stopList?: boolean; compact?: boolean; onreplay?: (() => void) | null; onended?: (() => void) | null; onready?: (() => void) | null; onfailure?: (() => void) | null } = $props();
  const replayable = $derived(stops.length >= 1);
  const single = $derived(stops.length === 1);
  const COMPACT_LABEL = "Trip map";
  const mapLabel = $derived(single ? "Map of the stay" : stopList ? "Map of the route, stop by stop; the stops are listed below" : "Map of the route, stop by stop");

  const query = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  let observed = $state(query?.matches ?? false);
  const calm = $derived(still ?? observed);
  $effect(() => {
    if (!query) return;
    const change = (e: MediaQueryListEvent) => { observed = e.matches; };
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  });

  const width = $derived(compact ? 600 : viewport.phone ? 600 : 960);
  const height = $derived(compact ? 405 : viewport.phone ? 640 : 520);
  const otherTravel = $derived(stops.some((s, i) => i > 0 && s.via !== "flight"));

  let progress = $state(0);
  let playing = $state(false);
  let tail = $state(0);
  const SPEEDS = [1, 2, 4];
  let speed = $state(1);
  const nextSpeed = () => { speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]; };
  let started = false;
  let touched = false;
  $effect(() => { if (calm) { progress = 1; playing = false; started = false; touched = false; } });
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
  let ran = $state(false);
  $effect(() => { if (playing) ran = true; });
  $effect(() => {
    if (!ran || playing || progress < 1 || compact) return;
    untrack(() => { ran = false; onended?.(); });
  });
  const scrub = (e: Event) => { ran = true; touched = true; playing = false; tail = 0; progress = Number((e.currentTarget as HTMLInputElement).value) / SCRUB_STEPS; };

  const lit = (i: number) => calm || (i === stops.length - 1 ? progress >= 1 && playing && tail < LABEL_HOLD_MS : labelLit(i, stops.length, progress, !playing));
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
  <div role={compact ? "group" : undefined} aria-label={compact ? COMPACT_LABEL : undefined} class="relative overflow-hidden rounded-2xl border border-border bg-map-sea" style="aspect-ratio: {width} / {height}" data-testid="replay-map">
    {#if replayable}
    <RouteReplayMapKit {maps} {tripId} {stops} {width} {height} {progress} {playing} {calm} label={compact ? undefined : mapLabel} decorative={compact} {onready} onfailure={() => onfailure?.()} />
    {/if}
    {#if compact && onreplay && replayable && !observed}
      <Button class="absolute bottom-3 left-3" variant="secondary" size="sm" aria-label="Replay trip" aria-expanded="false" onclick={onreplay}><Play class="size-3.5" aria-hidden="true" /> Replay trip</Button>
    {/if}
    {#if !compact}
    <div aria-hidden="true" class="pointer-events-none absolute left-2 top-2 grid max-w-[11rem]">
      {#each stops as s, i (i)}
        <div class="col-start-1 row-start-1 w-max max-w-[11rem] self-start rounded-lg transition-opacity duration-500 motion-reduce:transition-none border border-border bg-card px-2 py-1 text-xs leading-tight shadow-elevation-1"
            class:opacity-0={!lit(i)} data-visible={lit(i)} data-label={s.name}>
          <p class="break-words font-semibold text-foreground">{stopTitle(s)}</p>
          <p class="text-muted-foreground">{stopDates(s, year)}</p>
        </div>
      {/each}
    </div>
    {/if}
  </div>
  {#if !compact}
  <ul class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground" aria-label="Map key">
    {#if replayable}
    {#if !single || stops[0].kind === "airport"}<li class="flex items-center gap-2"><span class="size-2.5 rounded-full bg-map-airport" aria-hidden="true"></span>Airport</li>{/if}
    {#if stops.some((s) => s.kind === "stay")}<li class="flex items-center gap-2"><span class="size-2.5 rotate-45 rounded-[2px] bg-map-stay" aria-hidden="true"></span>Stay</li>{/if}
    {#if stops.some((s) => s.kind === "home")}<li class="flex items-center gap-2"><svg viewBox="-9 -9 18 16" class="h-3 w-3.5" aria-hidden="true"><path d="M0 -8 L8 -1 L5.5 -1 L5.5 6 L-5.5 6 L-5.5 -1 L-8 -1 Z" class="fill-map-visited" /></svg>Home</li>{/if}
    {#if stops.some((s) => s.kind === "place")}<li class="flex items-center gap-2"><span class="size-2 rounded-full bg-map-visited" aria-hidden="true"></span>Other stop</li>{/if}
    {#if !single}<li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-route" aria-hidden="true"></span>Flight</li>{/if}
    {#if otherTravel}<li class="flex items-center gap-2"><span class="h-0.5 w-4 rounded-full bg-map-stay" aria-hidden="true"></span>Other travel</li>{/if}
    {/if}
  </ul>
  {/if}
  {#if !calm && replayable && !compact}
    <div class="flex items-center gap-3">
      <Button variant="outline" onclick={toggle}>
        {#if progress >= 1}<RotateCcw />{:else if playing}<Pause />{:else}<Play />{/if}{buttonLabel}
      </Button>
      <Button variant="outline" size="sm" onclick={nextSpeed} aria-label="Playback speed {speed}×" class="tabular-nums">{speed}×</Button>
      <input type="range" min="0" max={SCRUB_STEPS} step="1" value={Math.round(progress * SCRUB_STEPS)} oninput={scrub} aria-label="Position along the route"
        aria-valuetext={stopLine(stops[now], year)} class="h-11 min-w-0 flex-1 accent-primary" />
    </div>
  {/if}
  {#if stopList && replayable && !compact}
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
