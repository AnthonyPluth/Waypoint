<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import PastBookings from "$lib/components/PastBookings.svelte";
  import { Sheet } from "$lib/components/ui/sheet";
  import { bookingCounts } from "$lib/trips";

  type Props = { open?: boolean; segments: Segment[]; onopen: (segment: Segment, opener: HTMLElement) => void };
  let { open = $bindable(false), segments, onopen }: Props = $props();

  const counts = $derived(bookingCounts({ segments }));
</script>

<Sheet bind:open title={`Bookings · ${counts.total}`} description={counts.words}>
  <PastBookings {segments} {onopen} />
</Sheet>
