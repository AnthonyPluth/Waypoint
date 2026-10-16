<script lang="ts">
  import type { Trip } from "$lib/api-types";
  import { tripKinds } from "$lib/trips";
  import KindTile from "./KindTile.svelte";

  let { trip }: { trip: Trip } = $props();
  const kinds = $derived(tripKinds(trip));
  const NAMES = { flight: "flight", hotel: "stay", car: "rental car", train: "train", cruise: "cruise", parking: "parking", visit: "past visit" } as const;
</script>

{#if kinds.length}
  <span class="flex shrink-0 items-center gap-1.5" role="img" aria-label={`Includes: ${kinds.map((k) => NAMES[k]).join(", ")}`} data-testid="trip-kinds">
    {#each kinds as kind (kind)}<KindTile {kind} decorative />{/each}
  </span>
{/if}
