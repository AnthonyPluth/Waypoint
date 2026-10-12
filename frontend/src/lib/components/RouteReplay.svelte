<script lang="ts">
  import type { Trip, TripPlaces } from "$lib/api-types";
  import { act } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import RouteReplayMap from "$lib/components/RouteReplayMap.svelte";
  import { NO_BOUNDARIES, NO_ROADS, isRoadTrip, stopsOf, worthLocating } from "$lib/route-replay";
  import { dayIn, viewerZone } from "$lib/trips";

  let { trip, now, onchanged }: { trip: Trip; now: number; onchanged?: () => void } = $props();

  let places = $state<TripPlaces | null>(null);

  const today = $derived(dayIn(now, viewerZone()));
  const eligible = $derived(worthLocating(trip, today));
  const stops = $derived(eligible && places ? stopsOf(trip, places) : []);
  const offersHome = $derived(eligible && isRoadTrip(trip) && places?.home != null);
  let savingHome = $state(false);
  const setFromHome = (next: boolean) => act(async () => {
    await apiCall<"POST /api/trips/{id}">(`/api/trips/${trip.id}`, { method: "POST", body: { replay_from_home: next } });
    onchanged?.();
  }, { busy: (on) => (savingHome = on) });
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

{#if stops.length >= 2 || offersHome}
  <section class="mb-6 space-y-3" aria-label="Route replay">
    {#if stops.length >= 2}
      {#key trip.id}<RouteReplayMap {stops} {year} roads={places?.roads ?? NO_ROADS} boundaries={places?.boundaries ?? NO_BOUNDARIES} autoplay />{/key}
    {/if}
    {#if offersHome}
      <label class="flex min-h-11 items-center gap-3 text-sm">
        <input type="checkbox" class="size-5 shrink-0 accent-primary" checked={trip.replay_from_home} disabled={savingHome} onchange={(e) => setFromHome(e.currentTarget.checked)} />
        Start and end at home
      </label>
    {/if}
  </section>
{/if}
