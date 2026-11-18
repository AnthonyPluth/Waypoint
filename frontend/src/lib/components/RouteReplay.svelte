<script lang="ts">
  import { untrack } from "svelte";
  import type { Trip, TripPlaces } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import RouteReplayMap from "$lib/components/RouteReplayMap.svelte";
  import { app } from "$lib/app.svelte";
  import { loadMapkit, type Maps } from "$lib/mapkit";
  import { NO_BOUNDARIES, NO_ROADS, stopsOf, worthLocating } from "$lib/route-replay";
  import { dayIn, viewerZone } from "$lib/trips";

  let { trip, now, shown = true, stopList = true, onstops, compact = false, onreplay = null, onended = null }: { trip: Trip; now: number; shown?: boolean; stopList?: boolean; onstops?: (count: number) => void; compact?: boolean; onreplay?: (() => void) | null; onended?: (() => void) | null } = $props();

  let places = $state<TripPlaces | null>(null);

  const today = $derived(dayIn(now, viewerZone()));
  const eligible = $derived(worthLocating(trip, today));
  const stops = $derived(eligible && places ? stopsOf(trip, places) : []);
  const year = $derived(Number(today.slice(0, 4)));

  $effect(() => {
    const count = stops.length;
    untrack(() => onstops?.(count));
  });

  let maps = $state<Maps | null | undefined>(undefined);
  let askedFor: number | null = null;
  $effect(() => {
    const id = trip.id;
    if (stops.length < 2 || !shown || compact) {
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
    if (!eligible || id !== placesFor) places = null;
    if (!eligible) return;
    placesFor = id;
    apiCall<"GET /api/trips/{id}/places">(`/api/trips/${id}/places`).then(
      (found) => { if (mine === latest && Array.isArray(found?.airports) && Array.isArray(found?.cities)) places = found; },
      () => { if (mine === latest) places = null; },
    );
  });
</script>

{#if shown && stops.length >= 2}
  <section class={compact ? "" : "mb-6"} aria-label="Route replay">
    {#key trip.id}<RouteReplayMap {stops} {year} tripId={trip.id} roads={places?.roads ?? NO_ROADS} boundaries={places?.boundaries ?? NO_BOUNDARIES} autoplay={maps !== undefined} still={compact ? true : null} {compact} {onreplay} {onended} maps={compact ? null : (maps ?? null)} {stopList} />{/key}
  </section>
{/if}
