<script lang="ts">
  import type { Snippet } from "svelte";
  import Plane from "@lucide/svelte/icons/plane";
  import type { FlightStatus, FlightStatusPause, Segment } from "$lib/api-types";
  import { cityNames } from "$lib/cities.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { flightCardView, footerPlace, pausedWords, shortDay, zonesShown, type Stamp } from "$lib/flightcard";
  import { headline, viewerZone } from "$lib/trips";

  type Props = { segment: Segment; status?: FlightStatus; liveOn?: boolean; now?: number; online?: boolean; eyebrow: string; tripName: string; paused?: FlightStatusPause | null; footer?: Snippet; class?: string };
  let { segment, status, liveOn = false, now = Date.now(), online = true, eyebrow, tripName, paused = null, footer, class: cls = "" }: Props = $props();

  const PLANE = "M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z";
  const cities = cityNames(() => [segment.origin, segment.destination, status?.destination]);
  const view = $derived(flightCardView({ segment, status, liveOn, now, online, city: (code) => cities[code] || code }));
  const zones = $derived(zonesShown(view, viewerZone()));
  const planeAt = $derived(view.progress === null ? null : Math.min(94, Math.max(6, view.progress * 100)));
</script>

{#snippet when(t: Stamp, right: boolean)}
  <div class={`mt-1.5 font-mono text-[13px] font-semibold ${t.tone === "late" ? "text-signal-ink" : ""} ${right ? "text-right" : ""}`}>
    <time datetime={t.local}>{t.time}</time>{#if zones && t.zoneName}<span class="ml-1 text-[11px] font-normal text-muted-foreground">{t.zoneName}</span>{/if}{#if t.later}<span class="ml-1 text-[11px] font-normal text-muted-foreground" data-later>{t.later}<span class="sr-only">, {t.laterWords}</span></span>{/if}
  </div>
{/snippet}

<section class={cls} data-flight-home>
  <p class="eyebrow mb-2">{eyebrow}</p>
  <h2 class="sr-only">{headline(segment)}</h2>
  <article class="relative flex flex-col gap-2.5 rounded-[22px] border border-border bg-card p-4 shadow-card" data-state={view.state} data-progress={view.progress ?? undefined}>
    <a class="absolute inset-0 z-[1] rounded-[22px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60" href={`#trip/${segment.trip_id}/flight/${segment.id}`} aria-label={view.name} data-live-link></a>
    <div class="flex items-center gap-2.5">
      <span class="grid size-[30px] flex-none place-items-center rounded-[9px] bg-avatar-1 text-[11px] font-bold tracking-[0.02em] text-avatar-1-ink" aria-hidden="true">{#if view.carrier}{view.carrier}{:else}<Plane class="size-4" />{/if}</span>
      <span class="min-w-0">
        <b class="block font-mono text-sm font-semibold">{view.number || "Flight"}</b>
        <span class="block truncate text-[13px] leading-[1.1] text-muted-foreground">{shortDay(view.depart.local)}{tripName ? ` · ${tripName}` : ""}</span>
      </span>
      {#if view.pill}<StatusChip chip={view.pill} class="ml-auto py-[3px]! font-bold! uppercase tracking-[0.04em]" />{/if}
    </div>
    <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5">
      <div><b class="text-2xl font-[650] leading-none tracking-[-0.025em]">{view.origin}</b>{@render when(view.depart, false)}</div>
      <div class="relative h-4" aria-hidden="true">
        <span class="absolute inset-x-0 top-1/2 border-t-2 border-dotted border-map-border"></span>
        {#if planeAt !== null}<span class="absolute top-1/2 grid size-[18px] -translate-x-1/2 -translate-y-1/2 place-items-center text-map-route" style={`left: ${planeAt}%`} data-plane><svg class="size-4" viewBox="0 0 24 24" fill="currentColor"><path d={PLANE} style="transform: rotate(90deg); transform-origin: 12px 12px" /></svg></span>{/if}
      </div>
      <div class="text-right"><b class="text-2xl font-[650] leading-none tracking-[-0.025em]">{view.destination}</b>{@render when(view.arrive, true)}</div>
    </div>
    <div class="flex items-center justify-between gap-2.5 border-t border-border pt-2.5 text-caption text-muted-foreground">
      <span data-place>{footerPlace(view)}</span>
      {#if view.updated}<span data-updated>{view.updated}</span>{/if}
    </div>
    {#if paused}<p class="text-xs text-muted-foreground" role="status" data-paused>{pausedWords(paused)}</p>{/if}
    {#if footer}<div class="relative z-10 flex flex-wrap items-center gap-2 border-t border-border pt-2.5">{@render footer()}</div>{/if}
  </article>
</section>
