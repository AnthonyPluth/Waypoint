<script lang="ts">
  import { untrack } from "svelte";
  import type { Stats, TripSummary } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import { distance } from "$lib/stats";

  let { tripId, revision = "" }: { tripId: number; revision?: string } = $props();

  type Loaded = { summary: TripSummary; unit: Stats["distance_unit"] | null } | null;
  let loaded = $state<Loaded>(null);
  let shownFor = 0;

  const US = "United States";
  const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;

  let latest = 0;
  async function load(id: number) {
    const mine = ++latest;
    if (shownFor !== id) loaded = null;
    try {
      const [summary, unit] = await Promise.all([
        apiCall<"GET /api/trips/{id}/summary">(`/api/trips/${id}/summary`),
        apiCall<"GET /api/distance-unit">("/api/distance-unit").then((u) => u.distance_unit, () => null),
      ]);
      if (mine !== latest) return;
      loaded = { summary, unit };
      shownFor = id;
    } catch {
      if (mine !== latest) return;
      loaded = null;
      shownFor = 0;
    }
  }

  $effect(() => {
    const id = tripId;
    void revision;
    untrack(() => void load(id));
  });

  const items = $derived.by(() => {
    if (!loaded) return [];
    const { summary: s, unit } = loaded;
    const out: { term: string; text: string; note?: string }[] = [];
    if (s.days > 0) out.push({ term: "Days", text: plural(s.days, "day") });
    if (s.nights > 0) out.push({ term: "Nights away", text: plural(s.nights, "night") });
    if (s.distance_km > 0 && unit) out.push({ term: "Distance", text: `${s.road_estimated ? "about " : ""}${distance(s.distance_km, unit)}` });
    const places = [...s.states, ...s.countries.filter((c) => s.states.length === 0 || c !== US)];
    if (places.length) out.push({ term: "Places", text: places.join(", ") });
    if (s.photos.total > 0) out.push({ term: "Photos", text: plural(s.photos.total, "photo"), note: s.photos.inferred > 0 ? `(${s.photos.inferred.toLocaleString()} placed from the itinerary)` : undefined });
    return out;
  });
</script>

{#if items.length}
  <dl class="-ml-[1.25em] mt-1 flex flex-wrap items-baseline gap-y-0.5 text-sm [clip-path:inset(0_0_0_1.25em)]" aria-label="Trip summary" data-testid="trip-summary">
    {#each items as item (item.term)}
      <div class="relative min-w-0 pl-[1.25em] before:absolute before:left-0 before:w-[1.25em] before:text-center before:text-muted-foreground before:[content:'·'_/_'']" data-summary-item>
        <dt class="sr-only">{item.term}</dt>
        <dd class="font-medium">{item.text}{#if item.note}{" "}<span class="font-normal text-muted-foreground">{item.note}</span>{/if}</dd>
      </div>
    {/each}
  </dl>
{/if}
