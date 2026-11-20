<script lang="ts">
  import type { Snippet } from "svelte";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Plane from "@lucide/svelte/icons/plane";
  import type { FlightStatusPause, Segment } from "$lib/api-types";
  import FlightArc from "$lib/components/FlightArc.svelte";
  import { pausedWords, type FlightCardView, type Stamp } from "$lib/flightcard";
  import { heroView } from "$lib/flighthero";
  import { headline } from "$lib/trips";

  type Props = {
    segment: Segment; view: FlightCardView; cities: Record<string, string>; now: number; paused?: FlightStatusPause | null; href?: string; linkLabel: string;
    highlight?: boolean; level?: 2 | 3; travellers?: boolean; ondetail?: (from: HTMLElement) => void; footer?: Snippet;
  };
  let { segment, view, cities, now, paused = null, href, linkLabel, highlight = false, level = 2, travellers = false, ondetail, footer }: Props = $props();

  const hero = $derived(heroView(view, segment, (code) => cities[code] || code, now, travellers));
  const TONE = { primary: "text-primary", success: "text-success", signal: "text-signal-ink" } as const;
  const ALIGN = ["text-left", "text-center", "text-right"] as const;
</script>

{#snippet when(t: Stamp, side: "origin" | "destination")}
  <span class={`mt-1.5 flex flex-col font-mono text-[15px] font-semibold tabular-nums @[32rem]:text-[17px] ${side === "destination" ? "items-end text-right" : ""} ${t.tone === "late" ? "text-signal-ink" : t.tone === "gone" ? "font-medium text-label line-through" : ""}`} data-when={side}>
    {#if t.original}<s class="block text-xs font-medium leading-[1.2] text-label"><span class="sr-only">Originally{" "}</span>{t.original.toUpperCase()}</s>{/if}
    <span><time datetime={t.local}>{t.time.toUpperCase()}</time>{#if t.later}<span class="ml-1 text-xs font-medium text-label" data-later>{t.later}<span class="sr-only">, {t.laterWords}</span></span>{/if}</span>
  </span>
  {#if t.zoneName}<span class="font-mono text-[11px] tracking-[0.04em] text-label" data-zone={side}>{t.zoneName}</span>{/if}
{/snippet}

<article class="@container relative flex scroll-mt-20 flex-col rounded-hero border border-border bg-card p-5 shadow-card @[32rem]:p-7" class:ring-2={highlight} class:ring-ring={highlight} aria-label={view.name} data-kind="flight" data-state={view.state} data-progress={view.progress ?? undefined} data-hero>
  <svelte:element this={`h${level}`} class="sr-only">{headline(segment)}</svelte:element>
  {#if href}<a {href} class="absolute inset-0 z-[1] rounded-hero outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60" aria-label={linkLabel} data-live-link></a>{/if}

  <div class="flex min-h-6 items-center justify-between gap-3 text-sm">
    <span class="min-w-0 truncate font-semibold text-muted-foreground" data-carrier>{hero.carrierLine}</span>
    {#if hero.top}
      <span class={`inline-flex flex-none items-center gap-1.5 font-bold ${hero.top.pill ? "rounded-full bg-signal px-2.5 py-1 text-xs uppercase tracking-[0.04em] text-signal-foreground" : TONE[hero.top.tone]}`} data-top data-tone={hero.top.tone}>
        {#if hero.top.dot}<i class="size-2 rounded-full bg-primary shadow-[0_0_0_4px_color-mix(in_srgb,var(--primary)_25%,transparent)]" aria-hidden="true"></i>{/if}{#if hero.top.plane}<Plane class="size-4" aria-hidden="true" />{/if}{hero.top.text}
      </span>
    {/if}
  </div>

  <p class="mt-4 text-[17px] font-semibold text-muted-foreground @[32rem]:text-xl" data-sentence>{hero.sentence}</p>
  <p class="mt-0.5 text-hero-fact @[32rem]:text-hero-fact-lg" data-big>{#if hero.bigTime}{hero.big.slice(0, hero.big.length - hero.bigTime.length)}<span class="font-mono font-bold tracking-[-0.04em]">{hero.bigTime}</span>{:else}{hero.big}{/if}</p>
  <p class="mt-2 text-sm text-muted-foreground @[32rem]:text-[15px]" data-quiet>
    {#if hero.quiet.late}<span class="font-semibold text-signal-ink">{hero.quiet.late}</span>{#if hero.quiet.struck}{" · was "}<s class="font-mono text-label"><span class="sr-only">Originally{" "}</span>{hero.quiet.struck}</s>{/if}{/if}
    {#if hero.quiet.text}<span data-updated={hero.quiet.text.startsWith("Updated") ? "" : undefined}>{hero.quiet.text}</span>{/if}
    {#if hero.quiet.onTime}<span class="font-semibold text-success" data-on-time>{" · on time"}</span>{/if}
  </p>

  <div class="mt-5 grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2">
    <div class="flex min-w-[74px] flex-col gap-[3px]">
      <b class={`text-airport @[32rem]:text-airport-lg tabular-nums ${hero.cancelled ? "text-label" : ""}`} data-code="origin">{view.origin}</b>
      {@render when(view.depart, "origin")}
    </div>
    <FlightArc progress={view.progress} class="mt-1" hero landed={hero.landed} />
    <div class="flex min-w-[74px] flex-col items-end gap-[3px] text-right">
      {#if hero.was}<span class="text-xs font-semibold text-label line-through" data-was><span class="sr-only">Booked for </span>{hero.was}</span>{/if}
      <b class={`text-airport @[32rem]:text-airport-lg tabular-nums ${hero.cancelled ? "text-label" : ""}`} data-code="destination">{view.destination}</b>
      {@render when(view.arrive, "destination")}
    </div>
  </div>

  {#if paused}<p class="mt-3 text-xs text-muted-foreground" role="status" data-paused>{pausedWords(paused)}</p>{/if}

  <dl class="mt-[18px] grid grid-cols-3 gap-2.5 border-t border-border pt-4" data-facts>
    {#each hero.facts as fact, i (fact.label)}
      <div class={`min-w-0 ${ALIGN[i]}`}>
        <dt class="whitespace-nowrap text-[11px] font-semibold uppercase tracking-[0.09em] text-label">{fact.label}</dt>
        {#if fact.value}
          <dd class={`mt-[3px] break-words text-fact @[32rem]:text-fact-lg ${fact.mono ? "font-mono" : ""}`}>{fact.value}</dd>
        {:else}
          <dd class="mt-[3px] text-fact font-medium text-label @[32rem]:text-fact-lg"><span aria-hidden="true">—</span><span class="sr-only">Not known yet</span></dd>
        {/if}
      </div>
    {/each}
  </dl>

  {#if hero.nobody}<p class="mt-3.5 text-sm text-muted-foreground" data-nobody>Nobody is listed on this booking.</p>{/if}
  {#if hero.seats.length > 1 || hero.seats.some((s) => s.unmatched)}
    <ul class="mt-3.5 flex flex-wrap gap-x-4 gap-y-2" data-seats>
      {#each hero.seats as s, i (i)}
        <li class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground"><i class="grid size-6 place-items-center rounded-full bg-secondary text-[10px] font-bold not-italic text-secondary-foreground" aria-hidden="true">{s.initials}</i>{s.name}{#if s.seat}<span class="font-mono text-[15px] font-semibold text-foreground">{s.seat}</span>{/if}{#if s.unmatched}<span class="basis-full pl-8 text-xs text-muted-foreground" data-unmatched>Not matched to a person in <a class="relative z-10 underline" href="#people">People</a></span>{/if}</li>
      {/each}
    </ul>
  {/if}

  {#if ondetail}
    <button type="button" class="relative z-10 mt-3 flex min-h-11 w-full items-center justify-between gap-3 rounded-lg border-t border-border pt-2.5 text-left text-sm font-semibold text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60" onclick={(e) => ondetail(e.currentTarget)} data-detail>
      Confirmation, travellers and price<ChevronRight class="size-4 flex-none text-label" aria-hidden="true" />
    </button>
  {/if}

  {#if footer}<div class="relative z-10 mt-3 flex flex-col gap-3 border-t border-border pt-3">{@render footer()}</div>{/if}
</article>
