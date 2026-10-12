<script lang="ts">
  import type { Trip, TripPlaces } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import RouteReplayMap from "$lib/components/RouteReplayMap.svelte";
  import { stopsOf, worthLocating } from "$lib/route-replay";
  import { dayIn, viewerZone } from "$lib/trips";

  let { trip, now }: { trip: Trip; now: number } = $props();

  let places = $state<TripPlaces | null>(null);

  const today = $derived(dayIn(now, viewerZone()));
  const eligible = $derived(worthLocating(trip, today));
  const stops = $derived(eligible && places ? stopsOf(trip, places) : []);
  const year = $derived(Number(today.slice(0, 4)));

  let latest = 0;
  let placesFor = 0;
  $effect(() => {
    const mine = ++latest;
    const id = trip.id;
    void trip.segments;
    if (!eligible || id !== placesFor) places = null;
    if (!eligible) return;
    placesFor = id;
    apiCall<"GET /api/trips/{id}/places">(`/api/trips/${id}/places`).then(
      (found) => { if (mine === latest && Array.isArray(found?.airports) && Array.isArray(found?.cities)) places = found; },
      () => { if (mine === latest) places = null; },
    );
  });
</script>

{#if stops.length >= 2}
  <section class="mb-6" aria-label="Route replay">
    {#key trip.id}<RouteReplayMap {stops} {year} autoplay />{/key}
  </section>
{/if}
