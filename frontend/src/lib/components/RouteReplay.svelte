<script lang="ts">
  import { untrack } from "svelte";
  import type { Trip, TripPhotos, TripPlaces } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import RouteReplayMap from "$lib/components/RouteReplayMap.svelte";
  import { app } from "$lib/app.svelte";
  import { loadMapkit, type Maps } from "$lib/mapkit";
  import { clusterInfos, unlocated } from "$lib/photos";
  import { NO_BOUNDARIES, NO_ROADS, stopsOf, worthLocating } from "$lib/route-replay";
  import { dayIn, viewerZone } from "$lib/trips";

  let { trip, now, photos = null, onshow }: { trip: Trip; now: number; photos?: TripPhotos | null; onshow?: (cluster: number) => void } = $props();

  let places = $state<TripPlaces | null>(null);
  let settled = $state(false);

  const today = $derived(dayIn(now, viewerZone()));
  const eligible = $derived(worthLocating(trip, today));
  const stops = $derived(eligible && places ? stopsOf(trip, places) : []);
  const year = $derived(Number(today.slice(0, 4)));
  const infos = $derived(photos ? clusterInfos(photos.photos, photos.clusters, new Map(trip.segments.map((s) => [s.id, s]))) : []);
  const photoOnly = $derived(stops.length < 2 && infos.length > 0 && (!eligible || settled));

  let maps = $state<Maps | null | undefined>(undefined);
  let askedFor: number | null = null;
  $effect(() => {
    const id = trip.id;
    if (stops.length < 2) {
      askedFor = null;
      untrack(() => { maps = undefined; });
      return;
    }
    if (askedFor === id) return;
    askedFor = id;
    untrack(() => { if (maps === null) maps = undefined; });
    if (app.state?.mapkit === false) { maps = null; return; }
    loadMapkit().then((found) => { if (askedFor === id) maps = found; });
  });

  let latest = 0;
  let placesFor = 0;
  $effect(() => {
    const mine = ++latest;
    const id = trip.id;
    void trip.segments;
    if (!eligible || id !== placesFor) { places = null; settled = false; }
    if (!eligible) return;
    placesFor = id;
    apiCall<"GET /api/trips/{id}/places">(`/api/trips/${id}/places`).then(
      (found) => { if (mine === latest) { if (Array.isArray(found?.airports) && Array.isArray(found?.cities)) places = found; settled = true; } },
      () => { if (mine === latest) { places = null; settled = true; } },
    );
  });
</script>

{#if stops.length >= 2 || photoOnly}
  <section class="mb-6" aria-label={stops.length >= 2 ? "Route replay" : "Trip photo map"}>
    {#key trip.id}<RouteReplayMap {stops} {year} roads={places?.roads ?? NO_ROADS} boundaries={places?.boundaries ?? NO_BOUNDARIES} autoplay={maps !== undefined} maps={stops.length >= 2 ? (maps ?? null) : null} {infos} unlocated={photos ? unlocated(photos.photos) : 0} {onshow} />{/key}
  </section>
{/if}
