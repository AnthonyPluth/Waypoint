<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import KindTile from "$lib/components/KindTile.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { bookingChip } from "$lib/status";
  import { bookingDetail, bookingGroups, bookingName, type Card } from "$lib/trips";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";

  type Props = { segments: Segment[]; grouped?: boolean; selected?: number | null; onopen: (segment: Segment, opener: HTMLElement) => void };
  let { segments, grouped = true, selected = null, onopen }: Props = $props();

  const uid = $props.id();
  const groups = $derived(bookingGroups(segments));
</script>

{#snippet row(card: Card)}
  {@const s = card.lead}
  <li>
    <button
      type="button"
      class={`flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left hover:bg-surface-3 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none ${selected === s.id ? "bg-surface-3" : ""}`}
      aria-haspopup="dialog"
      aria-current={selected === s.id ? "true" : undefined}
      data-booking={s.id}
      onclick={(e) => onopen(s, e.currentTarget)}
    >
      <KindTile kind={s.kind} decorative size={34} />
      <span class="flex min-w-0 flex-1 flex-col">
        <b class="truncate text-sm font-semibold">{bookingName(s)}</b>
        <span class="text-caption text-muted-foreground">{bookingDetail(card, !grouped)}</span>
      </span>
      {#if card.changed}<StatusChip chip={bookingChip("changed")} small />{/if}
      <ChevronRight class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    </button>
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
