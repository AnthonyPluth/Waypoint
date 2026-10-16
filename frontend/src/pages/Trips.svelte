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
  import AvatarStack from "$lib/components/AvatarStack.svelte";
  import TripCard from "$lib/components/TripCard.svelte";
  import TripKinds from "$lib/components/TripKinds.svelte";
  import { avatarTone } from "$lib/avatar";
  import { OptionsMenu } from "$lib/components/ui/options-menu";
  import { Sheet } from "$lib/components/ui/sheet";
  import { initials } from "$lib/nav";
  import { viewport } from "$lib/phone.svelte";
  import { dropDrafts, leave } from "$lib/drafts.svelte";
  import { panes } from "$lib/panes.svelte";
  import { blank } from "$lib/segment-form";
  import { dayIn, inYear, matchesText, pastByYear, rangeLabel, splitTrips, tripPeople, tripYears, viewerZone, type TripWhen } from "$lib/trips";
  import TripPane from "./Trip.svelte";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";

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
  const search = (e: Event) => {
    const field = e.currentTarget as HTMLInputElement;
    const v = field.value;
    if (!refine({ q: v.trim() ? v : null })) field.value = text;
  };
  const clearFilters = () => refine({ who: null, q: null, when: null, year: null });
  const filtered = $derived(trips && trips.filter((t) => (!who || t.segments.some((s) => s.travelers.some((x) => x.person_id === who))) && matchesText(t, text) && (!year || inYear(t, year))));
  const count = (n: number) => `${n} ${n === 1 ? "trip" : "trips"}`;
  let filtersOpen = $state(false);
  const years = $derived(trips ? tripYears(trips) : []);
  const filtering = $derived(!!(who || text || when || year));
  const today = () => dayIn(Date.now(), viewerZone());
  const comingUp = $derived(trips ? splitTrips(trips, today()).upcoming.length : 0);
  const shown = $derived.by(() => {
    if (!filtered) return null;
    const split = splitTrips(filtered, today());
    return { upcoming: when === "past" ? [] : split.upcoming, past: when === "upcoming" ? [] : split.past };
  });
  const everyTrip = $derived(shown ? [...shown.upcoming, ...shown.past] : []);
  const summary = $derived(trips ? (filtering ? `${everyTrip.length} of ${count(trips.length)}` : `${count(trips.length)}${comingUp ? ` · ${comingUp} coming up` : ""}`) : "");
  const selected = $derived(everyTrip.find((t) => t.id === tripParam) ?? everyTrip[0] ?? null);
  const reloaded = (movedTo?: number) => { if (movedTo) setQuery(queryFor({ trip: movedTo })); void load(); };
  const choose = (e: MouseEvent, t: Trip) => {
    if (!panes.two || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    leave(() => setQuery(queryFor({ trip: t.id })));
  };
  let revealed = $state(1);
  const chipClass = (on: boolean) => `inline-flex min-h-10 phone:min-h-11 items-center rounded-full border px-4 text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 ${on ? "border-primary bg-primary/15 text-primary" : "border-input bg-secondary hover:bg-input/60"}`;
</script>

{#snippet yearChips()}
  {#if years.length > 1 || year}
    <div class="flex flex-col gap-2 md:flex-row md:items-center md:gap-3">
      <span class="eyebrow" aria-hidden="true">Year</span>
      <div class="flex flex-wrap gap-2" role="group" aria-label="Year">
        {#each years as y (y)}
          <button type="button" class={chipClass(year === y)} aria-pressed={year === y} onclick={() => refine({ year: year === y ? null : y })}>{y}</button>
        {/each}
      </div>
    </div>
  {/if}
{/snippet}

{#snippet travellers()}
  {#if people.length > 1}
    <div class="flex flex-col gap-2 md:flex-row md:items-center md:gap-3">
      <span class="eyebrow" aria-hidden="true">Travelling</span>
      <div class="flex flex-wrap gap-2" role="group" aria-label="Travelling">
        {#each people as p (p.id)}
          {@const on = who === p.id}
          <button type="button" class={`inline-flex size-10 phone:size-11 items-center justify-center rounded-full text-sm font-semibold outline-none before:content-[attr(data-initials)] transition-opacity focus-visible:ring-[3px] focus-visible:ring-ring/50 ${avatarTone({ id: p.id, name: p.display_name })} ${on ? "ring-2 ring-primary" : who ? "opacity-60" : ""}`}
            aria-label={p.display_name} data-initials={initials(p.display_name)} aria-pressed={on} onclick={() => refine({ who: on ? null : p.id })}></button>
        {/each}
      </div>
    </div>
  {/if}
{/snippet}

<div class="mb-6 flex flex-wrap items-end justify-between gap-3">
  <div>
    {#if trips && trips.length > 0}<p class="eyebrow mb-1.5" role="status" aria-live="polite">{summary}</p>{/if}
    <h1 class="text-4xl font-bold tracking-tight">Trips</h1>
  </div>
  {#if trips && !adding}
    {#if viewport.phone}
      <OptionsMenu label="Add a booking" text="Add" icon={Plus} iconOnly variant="default" items={[{ label: "Add a booking", onselect: () => (adding = "booking") }, { label: "Add a past trip", onselect: () => (adding = "past") }]} />
    {:else}
      <div class="flex flex-wrap gap-2"><Button variant="outline" onclick={() => (adding = "past")}>Add a past trip</Button><Button onclick={() => (adding = "booking")}><Plus /> Add a booking</Button></div>
    {/if}
  {/if}
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
    <form class="mb-6 flex flex-col gap-3 rounded-[18px] border border-border bg-black/25 p-3 md:flex-row md:flex-wrap md:items-center md:gap-x-5 md:gap-y-3 md:p-4" role="search" aria-label="Find a trip" onsubmit={(e) => e.preventDefault()}>
      <div class="relative w-full md:max-w-sm md:min-w-56 md:flex-1">
        <label for="trip-search" class="sr-only">Search trips</label>
        <Search class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input id="trip-search" type="search" class="pl-9 phone:h-11" value={text} oninput={search} placeholder="Name, destination or airline" autocomplete="off" />
      </div>
      <div class="flex items-center gap-2 md:gap-3">
        <span class="eyebrow hidden md:inline" aria-hidden="true">Show</span>
        <div class="flex flex-1 overflow-hidden rounded-xl border border-input bg-secondary" role="group" aria-label="Show">
          {#each [["All", null], ["Upcoming", "upcoming"], ["Past", "past"]] as const as [label, value] (label)}
            <button type="button" class={`min-h-10 phone:min-h-11 flex-1 px-4 text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:ring-inset ${when === value ? "bg-primary text-primary-foreground" : "hover:bg-input/60"}`}
              aria-pressed={when === value} onclick={() => refine({ when: value })}>{label}</button>
          {/each}
        </div>
        {#if viewport.phone && (years.length > 1 || year || people.length > 1)}
          <Button type="button" variant="outline" size="icon" class="relative size-[46px]" onclick={() => (filtersOpen = true)}>
            <SlidersHorizontal /><span class="sr-only">Filters{year || who ? ", in use" : ""}</span>
            {#if year || who}<span class="absolute top-2 right-2 size-2 rounded-full bg-primary" data-testid="filters-dot" aria-hidden="true"></span>{/if}
          </Button>
        {/if}
      </div>
      {#if !viewport.phone}
        {@render yearChips()}
        {@render travellers()}
      {/if}
      {#if filtering}<Button type="button" variant="outline" class="md:ml-auto" onclick={clearFilters}>Clear filters</Button>{/if}
    </form>
    {#if viewport.phone}
      <Sheet bind:open={filtersOpen} title="Filters">
        <div class="flex flex-col gap-5">
          {@render yearChips()}
          {@render travellers()}
        </div>
      </Sheet>
    {/if}
  {/if}
  {#if shown.upcoming.length === 0 && shown.past.length === 0}
    <p class="text-muted-foreground">{filtering ? (who && !text && !when && !year ? "No trips with them." : "No trips match.") : "No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add a booking."}</p>
  {/if}
  {#snippet upcomingList(group: Trip[])}
    {@const day = today()}
    {@const phoneList = viewport.phone && !panes.two}
    {@const featuredId = !panes.two && group[0]?.start_date ? group[0].id : null}
    <ul class={panes.two ? "flex flex-col gap-2" : phoneList ? "flex flex-col gap-2.5" : "grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-[14px]"} aria-label="Upcoming trips">
      {#each group as t, i (t.id)}
        <li><TripCard trip={t} today={day} form={panes.two ? "row" : phoneList ? (i === 0 ? "hero" : "row") : "card"} featured={t.id === featuredId || (phoneList && i === 0 && !!t.start_date)} current={panes.two && selected?.id === t.id} onclick={(e) => choose(e, t)} /></li>
      {/each}
    </ul>
  {/snippet}
  {#snippet pastList(group: Trip[])}
    {@const groups = pastByYear(group)}
    {@const compact = viewport.phone || panes.two}
    {@const visible = viewport.phone ? groups.slice(0, revealed) : groups}
    <div class="flex flex-col gap-4">
      {#each visible as g (g.year)}
        <div class="overflow-hidden rounded-2xl border border-border bg-card shadow-card">
          <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border px-4 py-3">
            <h3 class="text-lg font-bold tracking-tight">{g.year}</h3>
            <span class="text-sm text-muted-foreground">{g.totals}</span>
          </div>
          <ul aria-label={`Past trips in ${g.year}`}>
            {#each g.trips as t (t.id)}
              {@const current = panes.two && selected?.id === t.id}
              <li class="border-b border-border last:border-b-0">
                <a class="group flex items-center gap-4 px-4 py-3 transition-colors hover:bg-surface-3 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none focus-visible:ring-inset {current ? 'bg-surface-2 ring-1 ring-primary ring-inset' : ''}"
                  href={`#trip/${t.id}`} aria-current={current ? "true" : undefined} onclick={(e) => choose(e, t)}>
                  {#if compact}
                    <span class="min-w-0 flex-1">
                      <span class="block truncate font-semibold">{t.name}</span>
                      <span class="block truncate text-sm text-muted-foreground">{[rangeLabel(t), t.destination].filter(Boolean).join(" · ")}</span>
                    </span>
                  {:else}
                    <span class="mono w-32 shrink-0 text-sm text-muted-foreground">{rangeLabel(t)}</span>
                    <span class="min-w-0 flex-1">
                      <span class="block truncate font-semibold">{t.name}</span>
                      {#if t.destination}<span class="block truncate text-sm text-muted-foreground">{t.destination}</span>{/if}
                    </span>
                    <TripKinds trip={t} />
                    <AvatarStack people={tripPeople(t)} />
                  {/if}
                  <ChevronRight class="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" aria-hidden="true" />
                </a>
              </li>
            {/each}
          </ul>
        </div>
      {/each}
      {#if viewport.phone && revealed < groups.length}
        <button type="button" class="self-start rounded-md px-1 py-2 text-sm font-medium text-primary outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" onclick={() => (revealed += 1)}>Show {groups[revealed].year}</button>
      {/if}
    </div>
  {/snippet}
  {#snippet list()}
    {#each [["Upcoming", shown.upcoming], ["Past", shown.past]] as const as [title, group] (title)}
      {#if group.length}
        <section class="mb-8" aria-labelledby={`trips-${title}`}>
          <h2 id={`trips-${title}`} class="eyebrow mb-2">{title}</h2>
          {#if title === "Upcoming"}{@render upcomingList(group)}{:else}{@render pastList(group)}{/if}
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
