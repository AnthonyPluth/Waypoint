<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import PastBookingsSheet from "./PastBookingsSheet.svelte";

  let { segments, ontoggle }: { segments: Segment[]; ontoggle: (segment: Segment) => void } = $props();
  let open = $state(false);
</script>

<div>
  <button type="button" onclick={() => (open = true)}>Bookings row</button>
  <p>Page behind</p>
</div>
<PastBookingsSheet bind:open {segments} {ontoggle} />
