<script lang="ts">
  import type { Trip, TripPlaces } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import { Button } from "$lib/components/ui/button";
  import { Sheet } from "$lib/components/ui/sheet";
  import RouteReplayMap from "$lib/components/RouteReplayMap.svelte";
  import { stopsOf, worthLocating } from "$lib/route-replay";
  import { dayIn, viewerZone } from "$lib/trips";
  import Route from "@lucide/svelte/icons/route";

  let { trip, now }: { trip: Trip; now: number } = $props();

  let places = $state<TripPlaces | null>(null);
  let open = $state(false);

  const today = $derived(dayIn(now, viewerZone()));
  const eligible = $derived(worthLocating(trip, today));
  const stops = $derived(eligible && places ? stopsOf(trip, places) : []);
  const year = $derived(Number(today.slice(0, 4)));

  let latest = 0;
  $effect(() => {
    const mine = ++latest;
    const id = trip.id;
    void trip.segments;
    places = null;
    if (!eligible) return;
    apiCall<"GET /api/trips/{id}/places">(`/api/trips/${id}/places`).then(
      (found) => { if (mine === latest && Array.isArray(found?.airports) && Array.isArray(found?.cities)) places = found; },
      () => { if (mine === latest) places = null; },
    );
  });
</script>

{#if stops.length >= 2}
  <div class="mb-6">
    <Button variant="outline" onclick={() => (open = true)}><Route /> Replay the route</Button>
  </div>
  <Sheet bind:open title="Route replay" description={trip.name} wide>
    {#if open}<RouteReplayMap {stops} {year} />{/if}
  </Sheet>
{/if}
