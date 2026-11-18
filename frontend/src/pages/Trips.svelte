<script lang="ts">
  import { tick, untrack } from "svelte";
  import { errMsg } from "$lib/act";
  import { app, currentEntry, route, setQuery } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import { takeEarlyTrips } from "$lib/early";
  import type { Person, Trip, TripCover } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import QuickTripForm from "$lib/components/QuickTripForm.svelte";
  import SegmentForm from "$lib/components/SegmentForm.svelte";
  import TravellerAvatars from "$lib/components/TravellerAvatars.svelte";
  import YearChips from "$lib/components/YearChips.svelte";
  import PastTripCard from "$lib/components/PastTripCard.svelte";
  import TripCard from "$lib/components/TripCard.svelte";
  import { OptionsMenu } from "$lib/components/ui/options-menu";
  import { Sheet } from "$lib/components/ui/sheet";
  import { viewport } from "$lib/phone.svelte";
  import { dropDrafts, leave } from "$lib/drafts.svelte";
  import { panes } from "$lib/panes.svelte";
  import { blankFor } from "$lib/segment-form";
  import { limited } from "$lib/limit";
  import { take, track } from "$lib/trips-position";
  import { distance as distanceText } from "$lib/stats";
  import { dayIn, inYear, isPast, matchesText, pastByYear, splitTrips, tripYears, viewerZone } from "$lib/trips";
  import TripPane from "./Trip.svelte";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";

  let trips = $state<Trip[] | null>(null);
  let people = $state<Person[]>([]);
  let loadError = $state("");
  const addQuery = new URLSearchParams(route.query).get("add");
  let adding = $state<"trip" | "booking" | "past" | null>(addQuery === "trip" || addQuery === "booking" || addQuery === "past" ? addQuery : null);
  let openedByQuery = $state(addQuery === "trip" || addQuery === "booking" || addQuery === "past");
  const closeForm = () => { adding = null; openedByQuery = false; if (param("add")) setQuery(queryFor({})); };

  let latest = 0;
  async function load() {
    const mine = ++latest;
    loadError = "";
    try {
      const [t, p] = await Promise.all([takeEarlyTrips("trips") ?? apiCall<"GET /api/trips">("/api/trips"), apiCall<"GET /api/people">("/api/people")]);
      if (mine !== latest) return;
      trips = t.trips; people = p.people;
      void loadCovers();
      resetDistances();
    } catch (err) { if (mine !== latest) return; trips = null; loadError = errMsg(err); }
  }
  $effect(() => { void load(); });

  let covers = $state<ReadonlyMap<number, TripCover>>(new Map());
  let coversKnown = $state(false);
  const withoutPhotos = $derived(!!app.state && (!app.state.user || app.state.user.local));
  let coversTicket = 0;
  async function loadCovers() {
    const mine = ++coversTicket;
    if (app.state && (!app.state.user || app.state.user.local)) { covers = new Map(); coversKnown = true; return; }
    try {
      const found = await apiCall<"GET /api/photos/trip-covers">("/api/photos/trip-covers", { keep: true, background: true });
      if (mine !== coversTicket) return;
      covers = new Map(found.trips.map((c) => [c.trip_id, c]));
      coversKnown = true;
    } catch {
      if (mine === coversTicket && !coversKnown) covers = new Map();
    }
  }

  const lookup = limited(4);
  let distances = $state<ReadonlyMap<number, number>>(new Map());
  let unit = $state<"mi" | "km" | null>(null);
  let resets = $state(0);
  let distanceGeneration = 0;
  const asked = new Set<number>();
  function resetDistances() { asked.clear(); distances = new Map(); distanceGeneration++; resets++; }
  async function loadDistances(ids: number[], generation: number) {
    const fresh = ids.filter((id) => !asked.has(id));
    if (!fresh.length) return;
    for (const id of fresh) asked.add(id);
    if (unit === null) {
      const found = await apiCall<"GET /api/distance-unit">("/api/distance-unit", { keep: true, background: true }).then((u) => u.distance_unit, () => null);
      if (generation !== distanceGeneration) return;
      unit = found;
    }
    await Promise.all(fresh.map((id) => lookup(
      () => apiCall<"GET /api/trips/{id}/summary">(`/api/trips/${id}/summary`, { keep: true, background: true }).then((s) => {
        if (generation === distanceGeneration && s.distance_km > 0) distances = new Map(distances).set(id, s.distance_km);
      }, () => {}),
      () => generation !== distanceGeneration,
    )));
  }
  $effect(() => () => { coversTicket++; distanceGeneration++; });

  const param = (key: string) => new URLSearchParams(route.query).get(key);
  $effect(() => {
    const wanted = param("add");    if (wanted === "trip" || wanted === "booking" || wanted === "past") { adding = wanted; openedByQuery = true; }
    else if (untrack(() => openedByQuery)) { adding = null; openedByQuery = false; }
  });
  const who = $derived(Number(param("who")) || null);
  const tripParam = $derived(Number(param("trip")) || null);
  const text = $derived((param("q") ?? "").trim());
  const year = $derived(Number(param("year")) || null);
  const queryFor = (change: Record<string, string | number | null>) => {
    const next = { who, q: text, year, trip: tripParam, add: openedByQuery ? adding : null, ...change };
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
  const clearFilters = () => refine({ who: null, q: null, year: null });
  const filtered = $derived(trips && trips.filter((t) => (!who || t.people.includes(who) || t.segments.some((s) => s.travelers.some((x) => x.person_id === who))) && matchesText(t, text) && (!year || inYear(t, year))));
  const count = (n: number) => `${n} ${n === 1 ? "trip" : "trips"}`;
  let filtersOpen = $state(false);
  const years = $derived(trips ? tripYears(trips) : []);
  const filtering = $derived(!!(who || text || year));
  let now = $state(Date.now());
  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(tick);
  });
  const today = () => dayIn(now, viewerZone());
  const comingUp = $derived(trips ? splitTrips(trips, today()).upcoming.length : 0);
  const shown = $derived.by(() => {
    if (!filtered) return null;
    const split = splitTrips(filtered, today());
    return split;
  });
  const everyTrip = $derived(shown ? [...shown.upcoming, ...shown.past] : []);
  const summary = $derived(trips ? (filtering ? `${everyTrip.length} of ${count(trips.length)}` : `${count(trips.length)}${comingUp ? ` · ${comingUp} coming up` : ""}`) : "");
  const selected = $derived(shown ? (shown.upcoming.find((t) => t.id === tripParam) ?? shown.upcoming[0] ?? null) : null);
  const photoCounts = $derived(new Map([...covers.values()].map((c) => [c.trip_id, c.count])));
  const pastGroups = $derived(shown ? pastByYear(shown.past, photoCounts) : []);
  const returning = take(currentEntry());
  let restoring = returning;
  let revealed = $state(returning?.revealed ?? 1);
  let scroller = $state<HTMLElement | null>(null);
  let loadingYear = $state<number | null>(null);
  let loadedNote = $state("");
  let sentinel = $state<HTMLElement | null>(null);
  const observes = typeof IntersectionObserver === "function";
  const visibleGroups = $derived(viewport.phone ? pastGroups.slice(0, revealed) : pastGroups);
  const visibleKey = $derived(visibleGroups.flatMap((g) => g.trips.map((t) => t.id)).join(","));
  function showNextYear() {
    if (loadingYear !== null || revealed >= pastGroups.length) return;
    loadingYear = pastGroups[revealed].year;
    revealed += 1;
  }
  function settleYear(year: number | null) {
    if (year === null || loadingYear !== year) return;
    const group = pastGroups.find((g) => g.year === loadingYear);
    loadedNote = group ? `Loaded ${group.year}, ${count(group.trips.length)}` : "";
    loadingYear = null;
  }
  $effect(() => {
    const key = visibleKey;
    void resets;
    if (key) untrack(() => {
      const year = loadingYear;
      void loadDistances(key.split(",").map(Number), distanceGeneration).then(() => settleYear(year));
    });
  });
  $effect(() => {
    const watched = sentinel;
    if (!watched || !observes || loadingYear !== null) return;
    const seen = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) untrack(showNextYear); }, { rootMargin: "600px 0px" });
    seen.observe(watched);
    return () => seen.disconnect();
  });
  $effect(() => {
    if (!restoring || shown === null) return;
    const target = restoring;
    restoring = null;
    void tick().then(() => {
      window.scrollTo(0, target.scroll);
      scroller?.scrollTo(0, target.inner);
    });
  });
  $effect(() => {
    const position = { scroll: restoring?.scroll ?? window.scrollY, inner: restoring?.inner ?? 0, revealed };
    track(position);
    const note = () => { position.scroll = window.scrollY; position.inner = scroller?.scrollTop ?? 0; };
    window.addEventListener("scroll", note, { capture: true, passive: true });
    return () => { window.removeEventListener("scroll", note, { capture: true }); track(null); };
  });
  const reloaded = (movedTo?: number) => {
    if (!movedTo) { void load(); return; }
    void load().then(() => {
      const found = trips?.find((t) => t.id === movedTo);
      if (found && !isPast(found, today())) setQuery(queryFor({ trip: movedTo }));
    });
  };
  const choose = (e: MouseEvent, t: Trip) => {
    if (!panes.two || isPast(t, today()) || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    leave(() => setQuery(queryFor({ trip: t.id })));
  };
  let paneRevision = $state(0);
</script>

<div class="mb-6 flex flex-wrap items-end justify-between gap-3">
  <div>
    {#if trips && trips.length > 0}<p class="eyebrow mb-1.5" role="status" aria-live="polite">{summary}</p>{/if}
    <h1 class="text-4xl font-bold tracking-tight">Trips</h1>
  </div>
  {#if trips && !adding}
    {#if viewport.phone}
      <OptionsMenu label="Add" text="Add" icon={Plus} iconOnly variant="default" items={[{ label: "Add a trip", onselect: () => (adding = "trip") }, { label: "Add a booking", onselect: () => (adding = "booking") }, { label: "Add a past trip", onselect: () => (adding = "past") }]} />
    {:else}
      <div class="flex flex-wrap gap-2"><Button variant="outline" onclick={() => (adding = "past")}>Add a past trip</Button><Button variant="outline" onclick={() => (adding = "booking")}>Add a booking</Button><Button onclick={() => (adding = "trip")}><Plus /> Add a trip</Button></div>
    {/if}
  {/if}
</div>

{#if adding === "trip" && trips}
  <QuickTripForm me={people.some((p) => p.id === app.state?.person_id) ? (app.state?.person_id ?? null) : null} oncancel={closeForm} oncreated={(t) => { adding = null; dropDrafts(); location.hash = `#trip/${t.id}`; }} />
{:else if adding && trips}
  <SegmentForm initial={adding === "past" ? { ...blankFor(people, app.state?.person_id), kind: "visit" } : blankFor(people, app.state?.person_id)} {people} oncancel={closeForm} onsaved={(s) => { adding = null; dropDrafts(); if (s.trip_id === selected?.id) paneRevision++; void load(); location.hash = `#trip/${s.trip_id}`; }} />
{/if}

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if shown === null}
  <div class="h-40 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" role="progressbar" aria-busy="true" aria-label="Loading"></div>
{:else}
  {#if trips && trips.length > 0}
    <form class="mb-6 flex flex-col gap-3 desktop:flex-row desktop:flex-wrap desktop:items-center desktop:gap-x-5 desktop:gap-y-3 desktop:rounded-[18px] desktop:border desktop:border-border desktop:bg-black/25 desktop:p-4" role="search" aria-label="Find a trip" onsubmit={(e) => e.preventDefault()}>
      <div class="flex items-center gap-2 desktop:contents">
        <div class="relative min-w-0 flex-1 desktop:max-w-sm desktop:min-w-56">
          <label for="trip-search" class="sr-only">Search trips</label>
          <Search class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input id="trip-search" type="search" class="pl-9 phone:h-11" value={text} oninput={search} placeholder="Name, destination or airline" autocomplete="off" />
        </div>
        {#if viewport.phone && (years.length > 1 || year || people.length > 1)}
          <Button type="button" variant="outline" size="icon" class="relative size-[46px] shrink-0" onclick={() => (filtersOpen = true)}>
            <SlidersHorizontal /><span class="sr-only">Filters{year || who ? ", in use" : ""}</span>
            {#if year || who}<span class="absolute top-2 right-2 size-2 rounded-full bg-primary" data-testid="filters-dot" aria-hidden="true"></span>{/if}
          </Button>
        {/if}
      </div>
      {#if !viewport.phone}
        {#if years.length > 1 || year}<YearChips {years} selected={year} onpick={(y) => refine({ year: y })} />{/if}
        {#if people.length > 1}<TravellerAvatars {people} selected={who} onpick={(id) => refine({ who: id })} />{/if}
      {/if}
      {#if filtering}<Button type="button" variant="outline" class="desktop:ml-auto" onclick={clearFilters}>Clear filters</Button>{/if}
    </form>
    {#if viewport.phone}
      <Sheet bind:open={filtersOpen} title="Filters">
        <div class="flex flex-col gap-5">
          {#if years.length > 1 || year}<YearChips {years} selected={year} onpick={(y) => refine({ year: y })} />{/if}
          {#if people.length > 1}<TravellerAvatars {people} selected={who} onpick={(id) => refine({ who: id })} />{/if}
        </div>
      </Sheet>
    {/if}
  {/if}
  {#if shown.upcoming.length === 0 && shown.past.length === 0}
    <p class="text-muted-foreground">{filtering ? (who && !text && !year ? "No trips with them." : "No trips match.") : "No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add a booking."}</p>
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
  {#snippet pastList()}
    {@const day = today()}
    {@const paneOpen = panes.two && selected !== null}
    {@const roomy = !viewport.phone && !paneOpen}
    <div class="flex flex-col gap-6">
      {#each visibleGroups as g (g.year)}
        <div class="flex flex-col gap-3.5">
          <div class="flex items-baseline justify-between gap-3 px-0.5">
            <h2 class="text-lg font-bold tracking-tight">{g.year}</h2>
            <span class="text-sm text-muted-foreground">{g.totals}</span>
          </div>
          <ul class={roomy ? "grid grid-cols-2 gap-[18px]" : "flex flex-col gap-3.5"} aria-label={`Past trips in ${g.year}`}>
            {#each g.trips as t (t.id)}
              {@const cover = covers.get(t.id)}
              {@const km = distances.get(t.id)}
              <li class="min-w-0"><PastTripCard trip={t} today={day} photos={cover?.count ?? 0} covers={cover?.covers ?? []} coversKnown={withoutPhotos || (coversKnown && covers.has(t.id))} distance={km && unit ? distanceText(km, unit) : ""} {roomy} /></li>
            {/each}
          </ul>
        </div>
      {/each}
      {#if viewport.phone}
        <p class="sr-only" role="status" aria-live="polite" aria-label="Past trips loaded">{loadedNote}</p>
        {#if loadingYear !== null}<p class="px-0.5 text-sm text-muted-foreground">Loading {loadingYear}…</p>{/if}
        {#if revealed < pastGroups.length}
          {#if observes}
            <div bind:this={sentinel} class="h-px" aria-hidden="true" data-testid="past-more"></div>
          {:else}
            <button type="button" class="self-start rounded-md px-1 py-2 text-sm font-medium text-primary outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" onclick={showNextYear}>Show more</button>
          {/if}
        {/if}
      {/if}
    </div>
  {/snippet}
  {#snippet list()}
    {#each [["Upcoming", shown.upcoming], ["Past", shown.past]] as const as [title, group] (title)}
      {#if group.length}
        <section class="mb-8" aria-labelledby={`trips-${title}`}>
          <h2 id={`trips-${title}`} class="eyebrow mb-2">{title}</h2>
          {#if title === "Upcoming"}{@render upcomingList(group)}{:else}{@render pastList()}{/if}
        </section>
      {/if}
    {/each}
  {/snippet}
  {#if panes.two && selected}
    <div class="grid grid-cols-[clamp(16rem,28%,24rem)_minmax(0,1fr)] items-start gap-8">
      <div bind:this={scroller} class="sticky top-20 max-h-[calc(100dvh-6rem)] overflow-y-auto pr-1">{@render list()}</div>
      <div class="min-w-0" data-testid="trip-pane" aria-label="Selected trip" role="region">{#key selected.id}<TripPane tripId={selected.id} onchanged={reloaded} revision={paneRevision} />{/key}</div>
    </div>
  {:else}
    {@render list()}
  {/if}
{/if}
