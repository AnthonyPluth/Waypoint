<script lang="ts">
  import { errMsg } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Stats } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import type { Component } from "svelte";
  import type { StatsFlights } from "$lib/api-types";

  // The household's travel stats. A failed load leaves nothing drawn that could pass for current, with a Try again.
  let stats = $state<Stats | null>(null);
  let loadError = $state("");
  // The map's code and outlines are a separate download, fetched only when this page opens.
  let TravelMap = $state<Component<{ flights: StatsFlights }> | null>(null);

  async function load() {
    loadError = "";
    try {
      const [s, m] = await Promise.all([apiCall<"GET /api/stats">("/api/stats"), import("$lib/components/TravelMap.svelte")]);
      stats = s; TravelMap = m.default;
    } catch (err) { stats = null; loadError = errMsg(err); }
  }
  $effect(() => { void load(); });
</script>

<h1 class="mb-6 text-3xl font-semibold tracking-tight">Stats</h1>

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if !stats || !TravelMap}
  <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading"></div>
{:else}
  <!-- The map has its own section so the Stats page can put it where it belongs. -->
  <section aria-labelledby="map-heading" class="space-y-3">
    <h2 id="map-heading" class="text-lg font-semibold">Where you’ve been</h2>
    <TravelMap flights={stats.flights} />
  </section>
{/if}
