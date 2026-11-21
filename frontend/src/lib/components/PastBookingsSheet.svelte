<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Segment } from "$lib/api-types";
  import PastBookings from "$lib/components/PastBookings.svelte";
  import { Sheet } from "$lib/components/ui/sheet";
  import { bookingCounts, type Card } from "$lib/trips";

  type Props = { open?: boolean; segments: Segment[]; expanded?: number | null; ontoggle: (segment: Segment) => void; detail?: Snippet<[Card]> };
  let { open = $bindable(false), segments, expanded = null, ontoggle, detail }: Props = $props();

  const counts = $derived(bookingCounts({ segments }));
</script>

<Sheet bind:open title={`Bookings · ${counts.total}`} description={counts.words}>
  <PastBookings {segments} {expanded} {ontoggle} {detail} />
</Sheet>
