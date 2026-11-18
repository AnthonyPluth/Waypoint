<script lang="ts">
  import { untrack } from "svelte";
  import { geoContains } from "d3-geo";
  import type { StatsFlights, StatsMapTrip, StatsPlacePoint, StatsStayPin, StatsVisit } from "$lib/api-types";
  import { loadDetailedCountries, loadStates, type Country } from "$lib/map";
  import { loadMapkit, type Maps } from "$lib/mapkit";
  import { viewport } from "$lib/phone.svelte";
  import { createStatsMap, DEFAULT_PALETTE, type Pick, type StatsMap } from "$lib/stats-mapkit";
  import { dateLabel } from "$lib/trips";

  let { flights, stays = [], visits = [], points = [], onfailure }: { flights: StatsFlights; stays?: StatsStayPin[]; visits?: StatsVisit[]; points?: StatsPlacePoint[]; onfailure: () => void } = $props();

  let maps = $state<Maps | null>(null);
  let countries = $state<Country[] | null>(null);
  let settled = $state(false);
  let host = $state<HTMLElement | null>(null);
  let drawn = $state.raw<StatsMap | null>(null);
  let picked = $state<Pick | null>(null);
  let gone = false;

  $effect(() => {
    gone = false;
    void (async () => {
      const found = await loadMapkit();
      if (gone) return;
      if (!found || found.failed()) { onfailure(); return; }
      maps = found;
      try { countries = await loadDetailedCountries(); } catch { countries = null; }
      if (!gone) settled = true;
    })();
    return () => { gone = true; };
  });

  $effect(() => {
    const session = maps;
    if (!session) return;
    return session.onFailure(onfailure);
  });

  $effect(() => {
    const element = host;
    const session = maps;
    if (!element || !session || !settled) return;
    const css = getComputedStyle(document.documentElement);
    const color = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
    let made: StatsMap;
    try {
      made = untrack(() => createStatsMap(session.mk, element, {
        palette: { visited: color("--map-visited", DEFAULT_PALETTE.visited), route: color("--map-route", DEFAULT_PALETTE.route), airport: color("--map-airport", DEFAULT_PALETTE.airport), stay: color("--map-stay", DEFAULT_PALETTE.stay), sea: color("--map-sea", DEFAULT_PALETTE.sea) },
        countries, loadStates, contains: (f, p) => geoContains(f, p), phone: viewport.phone, onpick: (p) => { picked = p; }, onfailure,
      }));
    } catch {
      onfailure();
      return;
    }
    drawn = made;
    return () => { made.destroy(); drawn = null; };
  });

  $effect(() => { drawn?.show({ flights, stays, visits, points }); });

  const when = (t: StatsMapTrip) => (t.start === t.end ? dateLabel(t.start) : `${dateLabel(t.start)} – ${dateLabel(t.end)}`);
</script>

{#if !settled}
  <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading the map"></div>
{:else}
  <div>
    <div bind:this={host} class="relative h-[260px] overflow-hidden rounded-[18px] border border-border bg-map-sea shadow-elevation-1 md:h-[500px]" data-mapkit="true" role="img" aria-label="Map of the visited countries and states, flights, airports and stays"></div>
    <p class="mt-2 min-h-5 text-sm text-muted-foreground" aria-live="polite">
      {#if picked}<span class="font-medium text-foreground">{picked.label}</span>
      {:else}Tap a country, state, airport, route or stay to see its trips.{/if}
    </p>
    {#if picked && picked.trips.length}
      <div class="mt-3 rounded-2xl border border-border bg-card p-4 text-sm shadow-elevation-1" data-testid="map-trips">
        <ul class="space-y-1">
          {#each picked.trips as tr, i (`${tr.trip_id}-${tr.start}-${i}`)}
            <li class="flex flex-wrap items-baseline justify-between gap-x-3"><a href={`#trip/${tr.trip_id}`} class="inline-flex items-center phone:min-h-11 font-medium underline underline-offset-2">{tr.name}</a><span class="text-muted-foreground">{when(tr)}</span></li>
          {/each}
        </ul>
      </div>
    {/if}
  </div>
{/if}
