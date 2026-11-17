<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import BookingDetail from "./BookingDetail.svelte";
  import PastBookings from "./PastBookings.svelte";
  import { bookingCards, tripTravellers } from "$lib/trips";

  type Props = { segments: Segment[]; canChange?: boolean; onedit?: (s: Segment) => void; onmove?: (s: Segment) => void; onremove?: (s: Segment) => void };
  let { segments, canChange = true, onedit = () => {}, onmove = () => {}, onremove = () => {} }: Props = $props();

  let id = $state<number | null>(null);
  let opener: HTMLElement | null = null;
  const card = $derived(id === null ? null : (bookingCards(segments).find((c) => c.segments.some((s) => s.id === id)) ?? null));
  const afterClose = (e: Event) => {
    if (opener?.isConnected) { e.preventDefault(); opener.focus(); }
  };
</script>

<PastBookings {segments} grouped={false} onopen={(s, el) => { opener = el; id = s.id; }} />
{#if card}
  <BookingDetail {card} everyone={tripTravellers(segments)} {canChange} onclose={() => (id = null)} {onedit} {onmove} {onremove} onCloseAutoFocus={afterClose} />
{/if}
