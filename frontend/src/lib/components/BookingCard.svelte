<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import GateCode from "$lib/components/GateCode.svelte";
  import KindTile from "$lib/components/KindTile.svelte";
  import { Button } from "$lib/components/ui/button";
  import { showsCode } from "$lib/gate-code";
  import { bookingName, cardFacts, dayLabel, endAt, headline, placeOf, type Card } from "$lib/trips";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";

  type Props = { card: Card; now: number; id?: string; highlight?: boolean; onopen: (segment: Segment, opener: HTMLElement) => void };
  let { card, now, id, highlight = false, onopen }: Props = $props();

  const s = $derived(card.lead);
  const KIND_WORD = { flight: "Flight", hotel: "Stay", car: "Car", train: "Train", cruise: "Cruise", parking: "Parking", visit: "Past visit" } as const;
  const name = $derived(s.kind === "train" ? bookingName(s) : headline(s));
  const where = $derived(s.kind === "hotel" ? placeOf(s.details.address) || s.destination : dayLabel(s.start_local));
  const subtitle = $derived([KIND_WORD[s.kind], where].filter(Boolean).join(" · "));
  const status = $derived(card.cancelled ? { word: "Cancelled", tone: "text-signal" } : card.changed ? { word: "Changed", tone: "text-signal" } : s.kind === "visit" ? null : { word: "Confirmed", tone: "text-success" });
  const facts = $derived(cardFacts(s));
  const struck = $derived(card.cancelled);
  const code = $derived(!card.cancelled && showsCode(s, endAt(s), now));
  let showing = $state(false);
  let showButton = $state<HTMLElement | null>(null);
  const lot = $derived(headline(s));
</script>

<li {id} class="scroll-mt-20 overflow-hidden rounded-3xl bg-card px-[18px] pb-4 text-card-foreground" class:ring-2={highlight} class:ring-ring={highlight} data-booking-card={s.kind} data-cancelled={struck ? "" : undefined}>
  <button
    type="button"
    class="flex min-h-16 w-full cursor-pointer items-center gap-3 rounded-xl text-left focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
    aria-haspopup="dialog"
    data-booking={s.id}
    onclick={(e) => onopen(s, e.currentTarget)}
  >
    <span class={struck ? "opacity-55" : ""}><KindTile kind={s.kind} outline /></span>
    <span class="flex min-w-0 flex-1 flex-col">
      <b class={`truncate text-[17px] font-bold ${struck ? "text-muted-foreground" : ""}`}>{name}</b>
      <span class="text-sm text-muted-foreground">{subtitle}{#if status}{" · "}<span class={`font-semibold ${status.tone}`}>{status.word}</span>{/if}</span>
    </span>
    <BrandLogo src={s.logo} size={32} />
    <ChevronRight class="size-[18px] shrink-0 text-muted-foreground" aria-hidden="true" />
  </button>
  <div class="mb-3 mt-1 h-px bg-border"></div>
  <dl class="grid grid-cols-3 gap-2.5">
    {#each facts as [label, value], i (label)}
    {@const shifted = /^(.*?) ([+−]\d+ days?)$/.exec(value)}
      <div class={`min-w-0 ${i === 1 ? "text-center" : i === 2 ? "text-right" : ""}`}>
        <dt class="eyebrow whitespace-nowrap">{label}</dt>
        <dd class={`mt-[3px] text-[17px] font-bold ${shifted ? "" : "truncate"} ${struck ? "text-label line-through" : ""} ${/\d:\d\d/.test(value) ? "mono" : ""}`}>{#if shifted}{shifted[1]}<span class="ml-1 text-xs font-medium text-label" data-shift>{shifted[2]}</span>{:else}{value}{/if}</dd>
      </div>
    {/each}
  </dl>
  {#if code}
    <Button bind:ref={showButton} class="mt-3.5 w-full" aria-label={`Show code for ${lot}`} onclick={() => (showing = true)}>Show code</Button>
  {/if}
  <GateCode segment={s} {now} buttons={false} returnFocus={showButton} bind:showing />
</li>
