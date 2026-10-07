<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import RouteLine from "$lib/components/RouteLine.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Button } from "$lib/components/ui/button";
  import { isMobile } from "$lib/platform";
  import { dayLabel, END_WORD, flightProgress, headline, headlineLine, START_WORD, untimed } from "$lib/trips";

  let { segment: s, now = Date.now() }: { segment: Segment; now?: number } = $props();

  const appWord = isMobile() ? "Open in app" : "Manage booking";
  const d = $derived(s.details);
  const line = $derived(headlineLine(s, now));
  const progress = $derived(flightProgress(s, now));
  const seat = $derived(s.travelers.length === 1 ? s.travelers[0].seat ?? d.seat : d.seat);
</script>

<article class="pass" data-testid="flight-pass-card" data-kind={s.kind}>
  <div class="flex flex-col gap-3 p-5 md:p-6">
    {#if line}<p class="eyebrow" data-testid="headline-line">{line}</p>{/if}
    <div>
      {#if s.confirmation}
        <CopyCode code={s.confirmation} class="text-4xl font-bold tracking-tight md:text-5xl" />
      {:else}
        <p class="text-2xl font-bold text-muted-foreground">No confirmation code</p>
      {/if}
    </div>
    {#if s.kind === "flight" || s.kind === "train"}
      <p class="text-lg font-semibold" data-testid="focal-facts">
        <span>{s.kind === "flight" ? d.flight_number ?? s.provider ?? "Flight" : s.provider ?? headline(s)}</span>
        <span class="text-muted-foreground"> · </span>{dayLabel(s.start_local)}
        <span class="text-muted-foreground"> · </span>{#if untimed(s)}<span class="text-muted-foreground">departs · time not recorded</span>{:else}departs <PlaceTime local={s.start_local} zone={s.start_zone} />{/if}
      </p>
    {:else}
      <p class="text-2xl font-bold tracking-tight" data-testid="focal-facts">{headline(s)}</p>
    {/if}
    <div class={s.kind === "flight" || s.kind === "train" ? "mt-1 text-sm" : "mt-1 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2"}
      title="The line is at the booked times, not the live ones." aria-label="The line is at the booked times, not the live ones." data-testid="booked-times">
      {#if s.kind === "flight" || s.kind === "train"}
        <RouteLine segment={s} progress={progress} />
        <div class="mt-2 flex items-end justify-between gap-4">
          {@render endAtBlock(s.kind === "flight" ? s.origin_city ?? s.origin ?? "" : s.origin ?? "", s.start_local, s.start_zone)}
          {@render endAtBlock(s.kind === "flight" ? s.destination_city ?? s.destination ?? "" : s.destination ?? "", s.end_local, s.end_zone, true)}
        </div>
      {:else}
        {@render endAtBlock(START_WORD[s.kind], s.start_local, s.start_zone)}
        {@render endAtBlock(END_WORD[s.kind], s.end_local, s.end_zone, true)}
      {/if}
    </div>
    {#if s.links.app}
      <div class="mt-1 flex">
        <Button variant="outline" size="sm" href={s.links.app} target="_blank" rel="noopener noreferrer">{appWord}</Button>
      </div>
    {/if}
  </div>
  <div class="pass-tear" aria-hidden="true"></div>
  <div class="flex flex-col gap-3 p-5 md:p-6">
    <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" data-testid="pass-facts">
      <StatusChip status={s.status} />
      {#if s.kind === "flight"}
        {@render fact("Terminal", d.terminal, "terminal")}
        {@render fact("Gate", d.gate, "gate")}
        {@render fact("Seat", seat, "seat")}
        {@render fact("Cabin", d.cabin, "cabin")}
      {:else if s.kind === "train"}
        {@render fact("Class", d.cabin, "cabin")}
        {@render fact("Seat", seat, "seat")}
      {:else if s.kind === "hotel"}
        {@render fact("Room", d.room, "room")}
        {@render fact("Phone", d.phone, "phone")}
      {:else if s.kind === "car"}
        {@render fact("Car", d.car_class, "car-class")}
        {@render fact("Phone", d.phone, "phone")}
      {:else}
        {@render fact("Ship", d.ship ?? s.provider, "ship")}
        {@render fact("Cabin", d.room ?? seat, "cabin")}
        {@render fact("Deck", d.deck, "deck")}
      {/if}
    </div>
    {#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}
  </div>
</article>

{#snippet endAtBlock(word: string, local: string, zone: string, right = false)}
  <div class={right ? "text-right" : ""}>
    <p class="eyebrow">{word}</p>
    <p class="mt-0.5 text-base font-medium">{#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime {local} {zone} />{/if}</p>
  </div>
{/snippet}

{#snippet fact(label: string, value: string | undefined | null, key: string)}
  {#if value}<span data-fact={key}><span class="eyebrow">{label} </span>{value}</span>{/if}
{/snippet}