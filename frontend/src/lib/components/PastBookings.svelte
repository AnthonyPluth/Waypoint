<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Segment } from "$lib/api-types";
  import KindTile from "$lib/components/KindTile.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { bookingChip } from "$lib/status";
  import { bookingDetail, bookingGroups, bookingName, type Card } from "$lib/trips";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";

  type Props = { segments: Segment[]; grouped?: boolean; expanded?: number | null; ontoggle: (segment: Segment) => void; detail?: Snippet<[Card]> };
  let { segments, grouped = true, expanded = null, ontoggle, detail }: Props = $props();

  const uid = $props.id();
  const groups = $derived(bookingGroups(segments));
</script>

{#snippet row(card: Card)}
  {@const s = card.lead}
  {@const open = expanded === s.id}
  <li id={`segment-${s.id}`} class="scroll-mt-20">
    <button
      type="button"
      class={`flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left hover:bg-surface-3 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none ${open ? "bg-surface-3" : ""}`}
      id={`${uid}-button-${s.id}`}
      aria-expanded={open}
      aria-controls={`${uid}-panel-${s.id}`}
      data-booking={s.id}
      onclick={() => ontoggle(s)}
    >
      <KindTile kind={s.kind} decorative size={34} />
      <span class="flex min-w-0 flex-1 flex-col">
        <b class="truncate text-sm font-semibold">{bookingName(s)}</b>
        <span class="text-caption text-muted-foreground">{bookingDetail(card, !grouped)}</span>
      </span>
      {#if card.changed}<StatusChip chip={bookingChip("changed")} small />{/if}
      <ChevronDown class={`size-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`} aria-hidden="true" />
    </button>
    <div id={`${uid}-panel-${s.id}`} role="region" aria-labelledby={`${uid}-button-${s.id}`} hidden={!open} class="border-t border-border px-4 py-3" data-booking-panel>
      {#if open}{@render detail?.(card)}{/if}
    </div>
  </li>
{/snippet}

{#if grouped}
  <div class="flex flex-col gap-1" data-testid="past-bookings">
    {#each groups as group (group.key)}
      <h3 id={`${uid}-${group.key}`} class="eyebrow mt-4 mb-1.5 px-1 text-muted-foreground first:mt-0">{group.heading}</h3>
      <ul class="divide-y divide-border overflow-hidden rounded-[18px] border border-border bg-card" aria-labelledby={`${uid}-${group.key}`}>
        {#each group.cards as card (card.id)}{@render row(card)}{/each}
      </ul>
    {/each}
  </div>
{:else}
  <ul class="divide-y divide-border overflow-hidden rounded-[18px] border border-border bg-card" aria-label="Bookings" data-testid="past-bookings">
    {#each groups as group (group.key)}{#each group.cards as card (card.id)}{@render row(card)}{/each}{/each}
  </ul>
{/if}
