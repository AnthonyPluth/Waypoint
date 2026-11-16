<script lang="ts">
  import type { Snippet } from "svelte";
  import Plane from "@lucide/svelte/icons/plane";
  import type { FlightStatus, Segment } from "$lib/api-types";
  import { airportInfo } from "$lib/airport-zones";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { headline } from "$lib/trips";
  import { arcHeading, arcPoint, arcTravelled, flightCardView, type Stamp } from "$lib/flightcard";

  type Props = { segment: Segment; status?: FlightStatus; liveOn?: boolean; now?: number; online?: boolean; highlight?: boolean; level?: 2 | 3; footer?: Snippet };
  let { segment, status, liveOn = false, now = Date.now(), online = true, highlight = false, level = 2, footer }: Props = $props();

  let cities = $state<Record<string, string>>({});
  $effect(() => {
    const codes = [segment.origin, segment.destination, status?.destination].filter((c): c is string => !!c);
    let current = true;
    for (const code of codes) {
      void airportInfo(code).then((airport) => { if (current && airport) cities[code] = airport.city || airport.name; });
    }
    return () => { current = false; };
  });

  const view = $derived(flightCardView({ segment, status, liveOn, now, online, city: (code) => cities[code] || code }));
  let arcWidth = $state(0);
  const point = $derived(view.progress === null ? null : arcPoint(view.progress));
  const heading = $derived(view.progress === null ? 0 : arcHeading(view.progress, arcWidth || 160));
  const sideCity = $derived(cities[view.sideCode] ?? "");
</script>

{#snippet when(t: Stamp)}
  <span class="mt-1.5 whitespace-nowrap font-mono text-[17px] font-semibold desktop:text-[19px]" class:text-signal-ink={t.tone === "late"} class:text-muted-foreground={t.tone === "gone"} class:line-through={t.tone === "gone"} class:font-medium={t.tone === "gone"}>
    {#if t.original}<s class="block text-xs font-medium leading-tight text-muted-foreground"><span class="sr-only">Originally{" "}</span>{t.original}</s>{/if}<time datetime={t.local}>{t.time}</time>
  </span>
  <span class="font-mono text-[11px] text-muted-foreground">{t.zoneName}{#if t.later}<span>{" · "}{t.later}<span class="sr-only">, {t.laterWords}</span></span>{/if}</span>
{/snippet}

{#snippet source(kind: "live" | "booking")}
  {#if kind === "live"}<span role="img" aria-label="From live status" class="size-[7px] flex-none rounded-full bg-primary"></span>
  {:else}<span role="img" aria-label="From the booking" class="size-[7px] flex-none rounded-full border-[1.5px] border-muted-foreground"></span>{/if}
{/snippet}

<article class="@container flex scroll-mt-20 flex-col gap-3.5 rounded-[22px] border border-border bg-card p-4 shadow-card" class:ring-2={highlight} class:ring-ring={highlight} aria-label={view.name} data-kind="flight" data-state={view.state} data-progress={view.progress ?? undefined}>
  <svelte:element this={`h${level}`} class="sr-only">{headline(segment)}</svelte:element>
  <div class="flex items-center gap-2.5">
    <span class="grid size-[30px] flex-none place-items-center rounded-[9px] bg-avatar-1 text-[11px] font-bold tracking-[0.02em] text-avatar-1-ink" aria-hidden="true">{#if view.carrier}{view.carrier}{:else}<Plane class="size-4" />{/if}</span>
    <span class="min-w-0">
      <b class="block font-mono text-sm font-semibold">{view.number || "Flight"}</b>
      {#if view.provider}<span class="block truncate text-[13px] leading-[1.1] text-muted-foreground">{view.provider}</span>{/if}
    </span>
    {#if view.duration}
      <span class="ml-auto inline-flex items-center gap-1.5 font-mono text-[13px] text-muted-foreground"><Plane class="size-3.5" aria-hidden="true" />{view.duration}</span>
    {/if}
  </div>

  <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2.5">
    <div class="flex min-w-[78px] flex-col gap-0.5">
      <b class="text-[38px] font-[650] leading-none tracking-[-0.03em] desktop:text-[44px]" data-code="origin">{view.origin}</b>
      <span class="text-xs text-muted-foreground">{cities[view.origin] ?? ""}</span>
      {@render when(view.depart)}
    </div>
    <div class="relative mt-1.5 h-[60px]" bind:clientWidth={arcWidth} aria-hidden="true" data-arc>
      <svg class="absolute inset-x-0 top-0 h-[46px] w-full" viewBox="0 0 100 40" preserveAspectRatio="none">
        <path d="M2 38 Q50 -16 98 38" fill="none" class="stroke-map-border" stroke-width="2" stroke-linecap="round" stroke-dasharray="1 5" vector-effect="non-scaling-stroke" />
        {#if view.progress}<path d={arcTravelled(view.progress)} fill="none" class="stroke-map-route" stroke-width="2.5" stroke-linecap="round" vector-effect="non-scaling-stroke" />{/if}
      </svg>
      {#if point}
        <span class="absolute grid size-[22px] place-items-center text-map-route" style={`left: ${point.left}%; top: ${point.top}px; transform: translate(-50%, -50%) rotate(${45 + heading}deg)`} data-plane><Plane class="size-5 fill-current" /></span>
      {/if}
      {#if view.updated}<span class="absolute inset-x-0 bottom-0 text-center text-[11px] text-muted-foreground" data-updated>{view.updated}</span>{/if}
    </div>
    <div class="flex min-w-[78px] flex-col items-end gap-0.5 text-right">
      <b class="text-[38px] font-[650] leading-none tracking-[-0.03em] desktop:text-[44px]" data-code="destination">{view.destination}</b>
      <span class="text-xs text-muted-foreground">{cities[view.destination] ?? ""}</span>
      {@render when(view.arrive)}
    </div>
  </div>

  <div class="flex flex-wrap items-center gap-2.5">
    {#if view.pill}<StatusChip chip={view.pill} class="uppercase tracking-[0.04em]" />{/if}
    <p class="min-w-0 flex-[1_1_180px] text-sm" data-sentence>{view.sentence}</p>
  </div>

  <div class="flex flex-col gap-2 border-t border-border pt-3">
    <span class="eyebrow">{view.side}{sideCity ? ` · ${sideCity}` : ""}</span>
    <dl class="grid grid-cols-4 gap-2" data-facts>
      {#each view.facts as fact (fact.label)}
        <div class="min-w-0">
          <dt class="flex items-center gap-[5px] whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{@render source(fact.source)}{fact.label}</dt>
          {#if fact.value}
            <dd class="mt-0.5 break-words text-[22px] font-[650] tracking-[-0.02em]">
              {#if fact.abbreviated && fact.abbreviated !== fact.value}<span class="@[24rem]:hidden">{fact.abbreviated}</span><span class="hidden @[24rem]:inline">{fact.value}</span>{:else}{fact.value}{/if}
            </dd>
          {:else}
            <dd class="mt-0.5 text-[22px] font-medium tracking-[-0.02em] text-muted-foreground"><span aria-hidden="true">—</span><span class="sr-only">Not known yet</span></dd>
          {/if}
        </div>
      {/each}
    </dl>
  </div>

  {#if footer}<div class="flex flex-col gap-3 border-t border-border pt-3">{@render footer()}</div>{/if}
</article>
