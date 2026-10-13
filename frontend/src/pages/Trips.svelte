<script lang="ts">
  import { errMsg } from "$lib/act";
  import { route, setQuery } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import { takeEarlyTrips } from "$lib/early";
  import type { Person, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import SegmentForm from "$lib/components/SegmentForm.svelte";
  import TripKinds from "$lib/components/TripKinds.svelte";
  import { dropDrafts, leave } from "$lib/drafts.svelte";
  import { panes } from "$lib/panes.svelte";
  import { blank } from "$lib/segment-form";
  import { dateLabel, dayIn, inYear, matchesText, splitTrips, tripYears, viewerZone, type TripWhen } from "$lib/trips";
  import TripPane from "./Trip.svelte";
  import Plus from "@lucide/svelte/icons/plus";

  let trips = $state<Trip[] | null>(null);
  let people = $state<Person[]>([]);
  let loadError = $state("");
  const addQuery = new URLSearchParams(route.query).get("add");
  let adding = $state<"booking" | "past" | null>(addQuery === "booking" || addQuery === "past" ? addQuery : null);
  const closeForm = () => { adding = null; if (addQuery) setQuery(""); };

  let latest = 0;
  async function load() {
    const mine = ++latest;
    loadError = "";
    try {
      const [t, p] = await Promise.all([takeEarlyTrips("trips") ?? apiCall<"GET /api/trips">("/api/trips"), apiCall<"GET /api/people">("/api/people")]);
      if (mine !== latest) return;
      trips = t.trips; people = p.people;
    } catch (err) { if (mine !== latest) return; trips = null; loadError = errMsg(err); }
  }
  $effect(() => { void load(); });

  const param = (key: string) => new URLSearchParams(route.query).get(key);
  const who = $derived(Number(param("who")) || null);
  const tripParam = $derived(Number(param("trip")) || null);
  const text = $derived((param("q") ?? "").trim());
  const when = $derived<TripWhen | null>(param("when") === "upcoming" || param("when") === "past" ? (param("when") as TripWhen) : null);
  const year = $derived(Number(param("year")) || null);
  const queryFor = (change: Record<string, string | number | null>) => {
    const next = { who, q: text, when, year, trip: tripParam, ...change };
    const q = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) if (value) q.set(key, String(value));
    return q.toString();
  };
  const refine = (change: Record<string, string | number | null>) => leave(() => setQuery(queryFor(change)));
  const pick = (key: string) => (e: Event) => {
    const field = e.currentTarget as HTMLSelectElement;
    const v = field.value;
    field.value = String(({ who, when, year } as Record<string, unknown>)[key] ?? "");
    refine({ [key]: v || null });
  };
  const search = (e: Event) => {
    const field = e.currentTarget as HTMLInputElement;
    const v = field.value;
    if (!refine({ q: v.trim() ? v : null })) field.value = text;
  };
  const clearFilters = () => refine({ who: null, q: null, when: null, year: null });
  const filtered = $derived(trips && trips.filter((t) => (!who || t.segments.some((s) => s.travelers.some((x) => x.person_id === who))) && matchesText(t, text) && (!year || inYear(t, year))));
  const count = (n: number) => `${n} ${n === 1 ? "trip" : "trips"}`;
  const years = $derived(trips ? tripYears(trips) : []);
  const filtering = $derived(!!(who || text || when || year));
  const shown = $derived.by(() => {
    if (!filtered) return null;
    const split = splitTrips(filtered, dayIn(Date.now(), viewerZone()));
    return { upcoming: when === "past" ? [] : split.upcoming, past: when === "upcoming" ? [] : split.past };
  });
  const everyTrip = $derived(shown ? [...shown.upcoming, ...shown.past] : []);
  const selected = $derived(everyTrip.find((t) => t.id === tripParam) ?? everyTrip[0] ?? null);
  const reloaded = (movedTo?: number) => { if (movedTo) setQuery(queryFor({ trip: movedTo })); void load(); };
  const choose = (e: MouseEvent, t: Trip) => {
    if (!panes.two || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    leave(() => setQuery(queryFor({ trip: t.id })));
  };
  const names = (t: Trip) => [...new Set(t.segments.flatMap((s) => s.travelers.map((x) => x.name)))].join(", ");
  const dates = (t: Trip) => t.start_date && t.end_date ? (t.start_date === t.end_date ? dateLabel(t.start_date) : `${dateLabel(t.start_date)} – ${dateLabel(t.end_date)}`) : "No dates yet";
  const selectClass = "border-input bg-secondary rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";
</script>

<div class="mb-6 flex flex-wrap items-center justify-between gap-3">
  <h1 class="text-4xl font-bold tracking-tight">Trips</h1>
  {#if trips && !adding}<div class="flex flex-wrap gap-2"><Button onclick={() => (adding = "booking")}><Plus /> Add a booking</Button><Button variant="outline" onclick={() => (adding = "past")}>Add a past trip</Button></div>{/if}
</div>

{#if adding && trips}
  <SegmentForm initial={adding === "past" ? { ...blank(), kind: "visit" } : blank()} {people} oncancel={closeForm} onsaved={(s) => { adding = null; dropDrafts(); location.hash = `#trip/${s.trip_id}`; }} />
{/if}

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if shown === null}
  <div class="h-40 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading"></div>
{:else}
  {#if trips && trips.length > 0}
    <form class="mb-6 flex flex-wrap items-end gap-3" role="search" aria-label="Find a trip" onsubmit={(e) => e.preventDefault()}>
      <label class="flex min-w-48 flex-1 flex-col gap-1.5 text-sm sm:max-w-sm"><span class="font-medium">Search</span>
        <Input type="search" value={text} oninput={search} placeholder="Name, destination or airline" autocomplete="off" /></label>
      <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Show</span>
        <select class={selectClass} value={when ?? ""} onchange={pick("when")}>
          <option value="">All trips</option><option value="upcoming">Upcoming</option><option value="past">Past</option>
        </select></label>
      {#if years.length > 1 || year}
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Year</span>
          <select class={selectClass} value={year ?? ""} onchange={pick("year")}>
            <option value="">Any year</option>
            {#each years as y (y)}<option value={y}>{y}</option>{/each}
          </select></label>
      {/if}
      {#if people.length > 1}
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Travelling</span>
          <select class={selectClass} value={who ?? ""} onchange={pick("who")}>
            <option value="">Everyone</option>
            {#each people as p (p.id)}<option value={p.id}>{p.display_name}</option>{/each}
          </select></label>
      {/if}
      {#if filtering}<Button type="button" variant="outline" onclick={clearFilters}>Clear filters</Button>{/if}
    </form>
    <p class="mb-4 text-sm text-muted-foreground" role="status" aria-live="polite">{filtering ? `${everyTrip.length} of ${count(trips.length)}` : count(trips.length)}</p>
  {/if}
  {#if shown.upcoming.length === 0 && shown.past.length === 0}
    <p class="text-muted-foreground">{filtering ? (who && !text && !when && !year ? "No trips with them." : "No trips match.") : "No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add a booking."}</p>
  {/if}
  {#snippet list()}
    {#each [["Upcoming", shown.upcoming], ["Past", shown.past]] as const as [title, group] (title)}
      {#if group.length}
        <section class="mb-8" aria-labelledby={`trips-${title}`}>
          <h2 id={`trips-${title}`} class="eyebrow mb-2">{title}</h2>
          <ul class={panes.two ? "flex flex-col gap-3" : "grid gap-3 md:grid-cols-2"} aria-label={`${title} trips`}>
            {#each group as t (t.id)}
              {@const current = panes.two && selected?.id === t.id}
              <li>
                <a class="block h-full rounded-2xl border bg-card p-4 shadow-card transition-colors hover:bg-surface-3 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none {current ? 'border-primary bg-surface-2' : 'border-border'}"
                  href={`#trip/${t.id}`} aria-current={current ? "true" : undefined} onclick={(e) => choose(e, t)}>
                  <span class="flex items-start justify-between gap-3">
                    <span class="min-w-0 break-words text-lg font-bold tracking-tight">{t.name}</span>
                    <TripKinds trip={t} />
                  </span>
                  <span class="eyebrow mt-1.5 block">{dates(t)}</span>
                  {#if t.destination}<span class="block text-sm text-muted-foreground">{t.destination}</span>{/if}
                  {#if names(t)}<span class="mt-2 block break-words text-sm text-muted-foreground">{names(t)}</span>{/if}
                </a>
              </li>
            {/each}
          </ul>
        </section>
      {/if}
    {/each}
  {/snippet}
  {#if panes.two && selected}
    <div class="grid grid-cols-[clamp(16rem,28%,24rem)_minmax(0,1fr)] items-start gap-8">
      <div class="sticky top-20 max-h-[calc(100dvh-6rem)] overflow-y-auto pr-1">{@render list()}</div>
      <div class="min-w-0" data-testid="trip-pane" aria-label="Selected trip" role="region">{#key selected.id}<TripPane tripId={selected.id} onchanged={reloaded} />{/key}</div>
    </div>
  {:else}
    {@render list()}
  {/if}
{/if}
