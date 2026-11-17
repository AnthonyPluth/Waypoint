<script lang="ts">
  import type { Snippet } from "svelte";
  import Plane from "@lucide/svelte/icons/plane";
  import type { FlightStatus, FlightStatusPause, Segment } from "$lib/api-types";
  import { cityNames } from "$lib/cities.svelte";
  import SourceDot from "$lib/components/SourceDot.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { headline } from "$lib/trips";
  import FlightArc from "$lib/components/FlightArc.svelte";
  import { flightCardView, pausedWords, type Stamp } from "$lib/flightcard";

  type Props = { segment: Segment; status?: FlightStatus; liveOn?: boolean; now?: number; online?: boolean; highlight?: boolean; level?: 2 | 3; paused?: FlightStatusPause | null; href?: string; footer?: Snippet };
  let { segment, status, liveOn = false, now = Date.now(), online = true, highlight = false, level = 2, paused = null, href, footer }: Props = $props();

  const PLANE = "M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z";
  const cities = cityNames(() => [segment.origin, segment.destination, status?.destination]);

  const view = $derived(flightCardView({ segment, status, liveOn, now, online, city: (code) => cities[code] || code }));
  const sideCity = $derived(cities[view.sideCode] ?? "");
</script>

{#snippet when(t: Stamp)}
  <span class="mt-1.5 whitespace-nowrap font-mono text-[17px] font-semibold @[24rem]:text-[19px]" class:text-signal-ink={t.tone === "late"} class:text-muted-foreground={t.tone === "gone"} class:line-through={t.tone === "gone"} class:font-medium={t.tone === "gone"}>
    {#if t.original}<s class="block text-xs font-medium leading-[1.2] text-muted-foreground"><span class="sr-only">Originally{" "}</span>{t.original}</s>{/if}<time datetime={t.local}>{t.time}</time>
  </span>
  <span class="font-mono text-[11px] text-muted-foreground">{t.zoneName}{#if t.later}<span>{" · "}{t.later}<span class="sr-only">, {t.laterWords}</span></span>{/if}</span>
{/snippet}

<article class="@container relative flex scroll-mt-20 flex-col gap-3.5 rounded-[22px] border border-border bg-card p-4 shadow-card" class:ring-2={highlight} class:ring-ring={highlight} aria-label={view.name} data-kind="flight" data-state={view.state} data-progress={view.progress ?? undefined}>
  <svelte:element this={`h${level}`} class="sr-only">{headline(segment)}</svelte:element>
  {#if href}<a {href} class="absolute inset-0 z-[1] rounded-[22px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60" aria-label={`${view.name}, open live status`} data-live-link></a>{/if}
  <div class="flex items-center gap-2.5">
    <span class="grid size-[30px] flex-none place-items-center rounded-[9px] bg-avatar-1 text-[11px] font-bold tracking-[0.02em] text-avatar-1-ink" aria-hidden="true">{#if view.carrier}{view.carrier}{:else}<Plane class="size-4" />{/if}</span>
    <span class="min-w-0">
      <b class="block font-mono text-sm font-semibold">{view.number || "Flight"}</b>
      {#if view.provider}<span class="block truncate text-[13px] leading-[1.1] text-muted-foreground">{view.provider}</span>{/if}
    </span>
    {#if view.duration}
      <span class="ml-auto inline-flex items-center gap-1.5 font-mono text-[13px] text-muted-foreground"><svg class="size-3.5 flex-none" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d={PLANE} style="transform: rotate(90deg); transform-origin: 12px 12px" /></svg>{view.duration}</span>
    {/if}
  </div>

  <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2.5">
    <div class="flex min-w-[78px] flex-col gap-0.5">
      <b class="text-[38px] font-[650] leading-none tracking-[-0.03em] @[24rem]:text-[44px]" data-code="origin">{view.origin}</b>
      <span class="text-xs text-muted-foreground">{cities[view.origin] ?? ""}</span>
      {@render when(view.depart)}
    </div>
    <FlightArc progress={view.progress} class="mt-1.5">
      {#if view.updated}<span class="absolute inset-x-0 bottom-0 text-center text-[11px] text-muted-foreground" data-updated>{view.updated}</span>{/if}
    </FlightArc>
    <div class="flex min-w-[78px] flex-col items-end gap-0.5 text-right">
      <b class="text-[38px] font-[650] leading-none tracking-[-0.03em] @[24rem]:text-[44px]" data-code="destination">{view.destination}</b>
      <span class="text-xs text-muted-foreground">{cities[view.destination] ?? ""}</span>
      {@render when(view.arrive)}
    </div>
  </div>

  <div class="flex flex-wrap items-center gap-2.5">
    {#if view.pill}<StatusChip chip={view.pill} class="py-[3px]! font-bold! uppercase tracking-[0.04em]" />{/if}
    {#if view.sentence}<p class="min-w-0 flex-[1_1_180px] text-sm" data-sentence>{view.sentence}</p>{/if}
  </div>

  {#if paused}<p class="text-xs text-muted-foreground" role="status" data-paused>{pausedWords(paused)}</p>{/if}

  <div class="flex flex-col gap-2 border-t border-border pt-3">
    <span class="eyebrow">{view.side}{sideCity ? ` · ${sideCity}` : ""}{view.sideDay ? ` · ${view.sideDay}` : ""}</span>
    <dl class="flex flex-wrap gap-x-2 gap-y-2" data-facts>
      {#each view.facts as fact (fact.label)}
        <div class="min-w-min flex-[1_1_0]">
          <dt class="flex items-center gap-[5px] whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"><SourceDot kind={fact.source} />{fact.label}</dt>
          {#if fact.value}
            <dd class="mt-0.5 break-words text-[22px] font-[650] tracking-[-0.02em]">{fact.value}</dd>
          {:else}
            <dd class="mt-0.5 text-[22px] font-medium tracking-[-0.02em] text-muted-foreground"><span aria-hidden="true">—</span><span class="sr-only">Not known yet</span></dd>
          {/if}
        </div>
      {/each}
    </dl>
  </div>

  {#if footer}<div class="relative z-10 flex flex-col gap-3 border-t border-border pt-3">{@render footer()}</div>{/if}
</article>
