<script lang="ts">
  import Plane from "@lucide/svelte/icons/plane";
  import type { FlightStatus, FlightStatusPause, Segment } from "$lib/api-types";
  import { cityNames } from "$lib/cities.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { bookingTimes, flightCardView, pausedWords } from "$lib/flightcard";
  import { viewerZone } from "$lib/trips";

  type Props = { segment: Segment; status?: FlightStatus; liveOn?: boolean; now?: number; online?: boolean; paused?: FlightStatusPause | null; showTimes?: boolean; onopen?: () => void };
  let { segment, status, liveOn = false, now = Date.now(), online = true, paused = null, showTimes = true, onopen }: Props = $props();

  const cities = cityNames(() => [segment.origin, segment.destination, status?.destination]);
  const view = $derived(flightCardView({ segment, status, liveOn, now, online, city: (code) => cities[code] || code }));
  const times = $derived(bookingTimes(view, viewerZone()));
  const percent = $derived(Math.round((view.progress ?? 0) * 100));
</script>

<div class="relative rounded-[18px] border border-border bg-surface-1 p-3.5" data-flight-booking data-state={view.state}>
  <a class="absolute inset-0 z-[1] rounded-[18px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60" href={`#trip/${segment.trip_id}/flight/${segment.id}`} aria-label={view.name} onclick={() => onopen?.()}></a>
  <div class="mb-2.5 flex items-center gap-2.5" aria-hidden="true">
    <span class="grid size-[30px] flex-none place-items-center rounded-[9px] bg-avatar-1 text-[11px] font-bold tracking-[0.02em] text-avatar-1-ink">{#if view.carrier}{view.carrier}{:else}<Plane class="size-4" />{/if}</span>
    <span class="min-w-0">
      <b class="block font-mono text-sm font-semibold">{view.number || "Flight"}</b>
      <span class="block text-[13px] leading-[1.1] text-muted-foreground">{view.origin} to {view.destination}</span>
    </span>
    {#if view.pill}<StatusChip chip={view.pill} class="ml-auto py-[3px]! font-bold! uppercase tracking-[0.04em]" />{/if}
  </div>
  <div class="h-1.5 overflow-hidden rounded-md bg-surface-3" role="progressbar" aria-label="Flight progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow={percent}>
    <div class="h-full bg-map-route" style={`width: ${percent}%`}></div>
  </div>
  {#if showTimes}
    <div class="mt-2 flex justify-between gap-3">
      <span class="text-caption text-muted-foreground">{times.left}</span>
      <b class="text-sm">{times.right}</b>
    </div>
  {/if}
  {#if paused}<p class="mt-2 text-xs text-muted-foreground" role="status" data-paused>{pausedWords(paused)}</p>{/if}
</div>
