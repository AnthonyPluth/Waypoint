<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Segment } from "$lib/api-types";
  import BookingDetailBody from "$lib/components/BookingDetailBody.svelte";
  import KindTile from "$lib/components/KindTile.svelte";
  import { Button } from "$lib/components/ui/button";
  import { OptionsMenu } from "$lib/components/ui/options-menu";
  import { Sheet } from "$lib/components/ui/sheet";
  import { legName, moreItems } from "$lib/booking-menu";
  import { viewport } from "$lib/phone.svelte";
  import { bookingName, dayLabel, headline, placeOf, spanOf, type Card, type TripTraveller } from "$lib/trips";

  type Props = {
    card: Card; everyone: TripTraveller[]; canChange: boolean; onclose: () => void; onedit: (segment: Segment) => void;
    onmove: (segment: Segment) => void; onremove: (segment: Segment) => void; onCloseAutoFocus?: (event: Event) => void;
    above?: Snippet; below?: Snippet; withTimes?: boolean;
  };
  let { card, everyone, canChange, onclose, onedit, onmove, onremove, onCloseAutoFocus, above, below, withTimes = false }: Props = $props();

  const first = $derived(card.lead);
  const name = $derived(first.kind === "flight" || first.kind === "train" ? bookingName(first) : headline(first));
  const span = $derived(spanOf(first));
  const subtitle = $derived.by(() => {
    const s = first;
    const parts = s.kind === "flight" ? ["Flight", [s.provider, s.details.flight_number].filter(Boolean).join(" "), dayLabel(s.start_local)]
      : s.kind === "train" ? ["Train", s.provider, dayLabel(s.start_local)]
        : s.kind === "hotel" ? ["Stay", placeOf(s.details.address) || s.destination]
          : s.kind === "car" ? ["Car", s.provider, span]
            : s.kind === "cruise" ? ["Cruise", s.provider, span]
              : s.kind === "parking" ? ["Parking", span] : ["Visit", span];
    return parts.filter(Boolean).join(" · ");
  });

  const items = $derived(moreItems(card, { onedit, onmove, onremove }));
</script>

<Sheet bind:open={() => true, (v) => { if (!v) onclose(); }} title={name} description={subtitle} panel {onCloseAutoFocus}>
  {#snippet lead()}<KindTile kind={first.kind} size={viewport.phone ? 40 : 44} decorative outline />{/snippet}
  {#snippet actions()}
    {#if canChange}
      <Button variant="outline" size="sm" onclick={() => onedit(first)}>Edit</Button>
      <OptionsMenu size="sm" align="right" label={`More options for ${legName(card, first)}`} text="More" {items} />
    {/if}
  {/snippet}
  <BookingDetailBody {card} {everyone} {canChange} {onedit} {onmove} {onremove} {above} {below} {withTimes} />
</Sheet>
