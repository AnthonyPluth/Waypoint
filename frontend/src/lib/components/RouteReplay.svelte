<script lang="ts">
  import { tick, untrack } from "svelte";
  import type { Trip, TripPlaces } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import RouteReplayMap from "$lib/components/RouteReplayMap.svelte";
  import { app } from "$lib/app.svelte";
  import { loadMapkit, type Maps } from "$lib/mapkit";
  import { stopsOf, worthLocating } from "$lib/route-replay";
  import { dayIn, viewerZone } from "$lib/trips";

<<<<<<< Updated upstream
  let { trip, now, shown = true, stopList = true, onstops, compact = false, onreplay = null, onended = null, wrapClass = "", wrapId = undefined, fallbackFocus = null, onmap }: { trip: Trip; now: number; shown?: boolean; stopList?: boolean; onstops?: (count: number) => void; compact?: boolean; onreplay?: (() => void) | null; onended?: (() => void) | null; wrapClass?: string; wrapId?: string; fallbackFocus?: (() => HTMLElement | null) | null; onmap?: (showing: boolean) => void } = $props();
=======
  let { trip, now, photos = null, photosSettled = true, onshow }: { trip: Trip; now: number; photos?: TripPhotos | null; photosSettled?: boolean; onshow?: (cluster: number) => void } = $props();
>>>>>>> Stashed changes

  let places = $state<TripPlaces | null>(null);

  const today = $derived(dayIn(now, viewerZone()));
  const eligible = $derived(worthLocating(trip, today));
  const stops = $derived(eligible && places ? stopsOf(trip, places) : []);
  const year = $derived(Number(today.slice(0, 4)));
  let connected = $state(typeof navigator === "undefined" || navigator.onLine !== false);
  $effect(() => {
    const set = () => {
      const held = holdsFocus();
      connected = navigator.onLine !== false;
      if (held && !connected) void restoreFocus();
    };
    set();
    window.addEventListener("online", set);
    window.addEventListener("offline", set);
    return () => { window.removeEventListener("online", set); window.removeEventListener("offline", set); };
  });
  const online = $derived(!app.offline && connected);
  const wanted = $derived(app.state?.mapkit === true && online && stops.length >= 2);

  let maps = $state<Maps | null | undefined>(undefined);
  let appeared = $state(false);
  let lost = $state(false);
  let section = $state<HTMLElement | null>(null);

  const available = $derived(maps != null && !lost);

  $effect(() => {
    const count = wanted && maps != null && !lost ? stops.length : 0;
    untrack(() => onstops?.(count));
  });

  $effect(() => {
    const on = shown && wanted && available && maps != null;
    untrack(() => onmap?.(on));
  });

  $effect(() => {
    const session = maps;
    if (!session || lost) return;
    return session.onFailure(() => void failed());
  });

  let askedFor: number | null = null;
  $effect(() => {
    const id = trip.id;
    if (!wanted) {
      askedFor = null;
      untrack(() => { maps = undefined; appeared = false; lost = false; });
      return;
    }
    if (askedFor === id) return;
    askedFor = id;
    untrack(() => { maps = undefined; appeared = false; lost = false; });
    loadMapkit().then((found) => { if (askedFor === id) maps = found && !found.failed() ? found : null; });
  });

  const holdsFocus = () => {
    const active = document.activeElement;
    return (!!section && section.contains(active)) || (!!wrapId && active?.getAttribute("aria-controls") === wrapId);
  };
  async function restoreFocus() {
    await tick();
    fallbackFocus?.()?.focus();
  }

  async function failed() {
    if (lost) return;
    const inside = holdsFocus();
    if (!appeared) {
      maps = null;
      if (inside) await restoreFocus();
      return;
    }
    lost = true;
    appeared = false;
    if (inside) await restoreFocus();
  }

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

<<<<<<< Updated upstream
{#if shown && wanted && (maps || lost)}
  <div id={wrapId} class={wrapClass || undefined}>
    {#if available && maps}
      <section bind:this={section} class={compact ? "" : "mb-6"} aria-label="Route replay">
        {#key trip.id}<RouteReplayMap {stops} {year} tripId={trip.id} autoplay={true} still={compact ? true : null} {compact} {onreplay} {onended} {maps} {stopList} onready={() => { appeared = true; }} onfailure={() => void failed()} />{/key}
      </section>
    {/if}
    <p role="status" aria-live="polite" class={lost ? "rounded-[14px] border border-dashed border-border px-3.5 py-3 text-sm text-muted-foreground" : "sr-only"}>{lost ? "The map couldn’t load" : ""}</p>
  </div>
=======
{#if stops.length >= 2 || photoOnly}
  <section class="mb-6" aria-label={stops.length >= 2 ? "Route replay" : "Trip photo map"}>
    {#key trip.id}<RouteReplayMap {stops} {year} roads={places?.roads ?? NO_ROADS} boundaries={places?.boundaries ?? NO_BOUNDARIES} autoplay={maps !== undefined && photosSettled} maps={stops.length >= 2 ? (maps ?? null) : null} {infos} unlocated={photos ? unlocated(photos.photos) : 0} {onshow} />{/key}
  </section>
>>>>>>> Stashed changes
{/if}
