<script module lang="ts">
  import { limited } from "$lib/limit";

  const lookup = limited(4);
</script>

<script lang="ts">
  import { untrack } from "svelte";
  import type { Trip, TripPlaces } from "$lib/api-types";
  import { app } from "$lib/app.svelte";
  import { cardLegs, cardSpots } from "$lib/card-map";
  import { apiCall } from "$lib/contract";
  import { hasDrive, savedRoutes, type SavedRoutes } from "$lib/driving-routes";
  import { snapshotFor, type Snapshot } from "$lib/map-snapshots";
  import { stopsOf } from "$lib/route-replay";
  import TripKinds from "./TripKinds.svelte";

  let { trip, locate }: { trip: Trip; locate: boolean } = $props();

  const SIDES = { width: { step: 16, max: 640 }, height: { step: 8, max: 640 } };
  const MIN_SIDE = 50;

  let places = $state<TripPlaces | null>(null);
  let looked = $state(false);
  let snapshot = $state<Snapshot | null | undefined>(undefined);
  let image = $state<"loading" | "loaded" | "failed">("loading");
  let roads = $state<SavedRoutes>(new Map());
  let clientWidth = $state(0);
  let clientHeight = $state(0);

  const tripId = $derived(trip.id);
  const wanted = $derived(locate && app.state?.mapkit === true && !app.offline);
  const stops = $derived(places ? stopsOf(trip, places) : []);
  const size = $derived(clientWidth >= MIN_SIDE && clientHeight >= MIN_SIDE
    ? { width: Math.min(SIDES.width.max, Math.floor(clientWidth / SIDES.width.step) * SIDES.width.step), height: Math.min(SIDES.height.max, Math.floor(clientHeight / SIDES.height.step) * SIDES.height.step) }
    : null);
  const loaded = $derived(snapshot != null && image === "loaded");
  const pending = $derived(wanted && (!looked || (stops.length >= 2 && snapshot === undefined) || (snapshot != null && image === "loading")));
  const frame = $derived(snapshot ? { center: snapshot.center, zoom: snapshot.zoom, width: snapshot.width, height: snapshot.height } : null);
  const spots = $derived(frame ? cardSpots(stops, frame) : []);
  const ratio = $derived(snapshot && clientWidth > 0 ? snapshot.width / clientWidth : 1);
  const legs = $derived(frame ? cardLegs(stops, spots, roads, frame) : []);

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
    if (mine === latest) looked = true;
  }
  $effect(() => {
    const id = tripId;
    places = null; looked = false; snapshot = undefined; image = "loading"; roads = new Map();
    if (!wanted) return;
    untrack(() => void load(id));
    return () => { latest++; };
  });

  $effect(() => {
    const id = tripId;
    if (!wanted || stops.length < 2 || !size) return;
    const { width, height } = size;
    const revision = stops.map((s) => `${s.latitude.toFixed(4)},${s.longitude.toFixed(4)}`).join(";");
    let live = true;
    untrack(() => void snapshotFor(id, width, height, revision).then((found) => {
      if (!live) return;
      if (found?.url !== snapshot?.url) image = "loading";
      snapshot = found;
    }));
    return () => { live = false; };
  });

  $effect(() => {
    const id = tripId;
    if (!snapshot || !hasDrive(stops)) return;
    let live = true;
    untrack(() => void savedRoutes(id).then((found) => { if (live) roads = found; }));
    return () => { live = false; };
  });
</script>

<span class="absolute inset-0 block bg-surface-3" data-testid="route-tile" data-drawn={loaded} bind:clientWidth bind:clientHeight>
  {#if !loaded}
    <span class={`absolute top-3 right-3 transition-opacity ${pending ? "opacity-50" : ""}`} data-testid="kinds-tile" data-pending={pending}><TripKinds {trip} /></span>
  {/if}
  {#if snapshot && image !== "failed"}
    <span class={`absolute inset-0 block transition-opacity duration-200 motion-reduce:transition-none ${loaded ? "opacity-100" : "opacity-0"}`}>
      <img class="absolute inset-0 size-full" src={snapshot.url} alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" draggable="false" onload={() => (image = "loaded")} onerror={() => (image = "failed")} />
      {#if loaded && frame}
        <svg viewBox="0 0 {frame.width} {frame.height}" preserveAspectRatio="none" class="absolute inset-0 size-full" aria-hidden="true" data-testid="route-overlay">
          <g fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width={2.2 * ratio}>
            {#each legs as leg, i (i)}<path d={leg.d} class={leg.flight ? "stroke-map-route" : "stroke-map-stay"} />{/each}
          </g>
          {#each stops as s, i (i)}
            <circle cx={spots[i].x} cy={spots[i].y} r={4 * ratio} class={s.kind === "airport" ? "fill-map-airport stroke-map-sea" : "fill-map-stay stroke-map-sea"} stroke-width={2 * ratio} />
          {/each}
        </svg>
      {/if}
    </span>
  {/if}
</span>
