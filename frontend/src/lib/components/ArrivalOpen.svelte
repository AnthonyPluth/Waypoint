<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import { openable, pendingFor, settleTarget } from "$lib/arrival.svelte";
  import ArrivalCode from "$lib/components/ArrivalCode.svelte";

  type Props = { tripId: number; segments: Segment[]; now: number };
  let { tripId, segments, now }: Props = $props();

  let open = $state(false);
  let opened = $state<Segment | null>(null);

  $effect(() => {
    const wanted = pendingFor(tripId);
    if (wanted === null) return;
    const found = segments.find((s) => s.id === wanted);
    settleTarget();
    if (found && openable(found, now)) {
      opened = found;
      open = true;
    }
  });
</script>

{#if opened}<ArrivalCode segment={opened} {now} bind:open />{/if}
