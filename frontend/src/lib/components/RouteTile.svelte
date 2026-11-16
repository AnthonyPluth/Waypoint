<script lang="ts">
  import { untrack } from "svelte";
  import type { Trip, TripPlaces } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import { limited } from "$lib/limit";
  import { stopsOf } from "$lib/route-replay";
  import RouteTileMap from "./RouteTileMap.svelte";
  import TripKinds from "./TripKinds.svelte";

  let { trip, locate }: { trip: Trip; locate: boolean } = $props();

  const lookup = limited(4);

  let places = $state<TripPlaces | null>(null);
  const stops = $derived(places ? stopsOf(trip, places) : []);

  let latest = 0;
  async function load(id: number) {
    const mine = ++latest;
    try {
      const found = await lookup(() => apiCall<"GET /api/trips/{id}/places">(`/api/trips/${id}/places`, { keep: true, background: true }), () => mine !== latest);
      if (mine !== latest) return;
      places = found && Array.isArray(found.airports) && Array.isArray(found.cities) ? found : null;
    } catch {
      if (mine === latest) places = null;
    }
  }
  $effect(() => {
    const id = trip.id;
    if (!locate) { places = null; return; }
    untrack(() => void load(id));
    return () => { latest++; };
  });
</script>

<span class="absolute inset-0 block bg-surface-3" data-testid="route-tile" data-drawn={stops.length >= 2}>
  {#if stops.length >= 2}
    <RouteTileMap {stops} />
  {:else}
    <span class="absolute top-3 right-3"><TripKinds {trip} /></span>
  {/if}
</span>
