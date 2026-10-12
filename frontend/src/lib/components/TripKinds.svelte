<script lang="ts">
  import type { Trip } from "$lib/api-types";
  import { tripKinds } from "$lib/trips";
  import Building from "@lucide/svelte/icons/building";
  import Car from "@lucide/svelte/icons/car";
  import ParkingSquare from "@lucide/svelte/icons/square-parking";
  import Globe from "@lucide/svelte/icons/globe";
  import Plane from "@lucide/svelte/icons/plane";
  import Ship from "@lucide/svelte/icons/ship";
  import TrainFront from "@lucide/svelte/icons/train-front";

  let { trip }: { trip: Trip } = $props();
  const kinds = $derived(tripKinds(trip));
  const ICONS = { flight: Plane, hotel: Building, car: Car, train: TrainFront, cruise: Ship, parking: ParkingSquare, visit: Globe } as const;
  const NAMES = { flight: "flight", hotel: "stay", car: "rental car", train: "train", cruise: "cruise", parking: "parking", visit: "past visit" } as const;
</script>

{#if kinds.length}
  <span class="flex shrink-0 items-center gap-1.5 text-muted-foreground" role="img" aria-label={`Includes: ${kinds.map((k) => NAMES[k]).join(", ")}`} data-testid="trip-kinds">
    {#each kinds as kind (kind)}{@const Icon = ICONS[kind]}<Icon class="size-4" aria-hidden="true" />{/each}
  </span>
{/if}
