<script lang="ts">
  import { errMsg } from "$lib/act";
  import { app, route, setQuery } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { Person, Stats } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import type { Component } from "svelte";
  import TopList, { type Row } from "$lib/components/stats/TopList.svelte";
  import YearInReview from "$lib/components/YearInReview.svelte";
  import { reviewOffered } from "$lib/review";
  import { comparisons, count, countryName, distance, duration, monthLabel, parseSelection, selectionQuery, share, statsPath } from "$lib/stats";
  import { dateLabel } from "$lib/trips";

  // Travel stats for one person or everyone, in one year or all time. The choice lives in the address (#stats?who=2&year=2025).
  // What was loaded is kept with the choice it answers, so numbers for another choice are never drawn as current; a failed
  // load says so, leaves the pickers working and offers Try again.
  const me = $derived(app.state?.person_id ?? null);
  const sel = $derived(parseSelection(route.query, me));
  const key = $derived(`${sel.who}/${sel.year}`);

  let people = $state<Person[]>([]);
  let loaded = $state<{ key: string; stats: Stats } | null>(null);
  let years = $state<number[]>([]);   // the last years list the server gave, so the picker stays put while the next load runs
  let failed = $state<{ key: string; message: string } | null>(null);
  let attempt = 0;

  async function load(want: string, path: ReturnType<typeof statsPath>) {
    const mine = ++attempt;
    try {
      const s = await apiCall<"GET /api/stats">(path);
      if (mine !== attempt) return;
      loaded = { key: want, stats: s }; years = s.years; failed = null;
    } catch (err) { if (mine === attempt) { loaded = null; failed = { key: want, message: errMsg(err) }; } }
  }
  $effect(() => { void load(key, statsPath(sel)); });
  $effect(() => {
    // The names for the picker: if they don't load, Everyone and your own numbers still work.
    apiCall<"GET /api/people">("/api/people").then((p) => { people = p.people; }).catch(() => { people = []; });   // (the picker falls back to Everyone)
  });

  // The map's code and outlines are a separate download, fetched only once this page has something to draw on it.
  let TravelMap = $state<Component<{ flights: Stats["flights"]; stays: Stats["stays"]["pins"] }> | null>(null);
  let mapError = $state("");
  async function loadMap() {
    mapError = "";
    try { TravelMap = (await import("$lib/components/TravelMap.svelte")).default; } catch (err) { mapError = errMsg(err); }
  }
  $effect(() => { if (!TravelMap && !mapError) void loadMap(); });

  const current = $derived(loaded && loaded.key === key ? loaded.stats : null);
  const problem = $derived(failed && failed.key === key ? failed.message : "");
  const yearChoices = $derived(sel.year !== null && !years.includes(sel.year) ? [sel.year, ...years] : years);
  const pick = (who: number | "all", year: number | null) => setQuery(selectionQuery({ who, year }, me));
  const whoName = $derived(sel.who === "all" ? "Everyone" : people.find((p) => p.id === sel.who)?.display_name ?? "this person");
  const unit = $derived(current?.distance_unit ?? "mi");

  let reviewing = $state(false);
  const reviewable = $derived(reviewOffered(sel.year, new Date()));
  const reviewName = $derived(sel.who === "all" ? null : people.find((p) => p.id === sel.who)?.first_name ?? people.find((p) => p.id === sel.who)?.display_name ?? null);

  const f = $derived(current?.flights);
  const empty = $derived(!!current && current.flights.count === 0 && current.stays.nights === 0 && current.cars.days === 0 && current.cruises.count === 0);
  const plural = (n: number, one: string, many = `${one}s`) => `${count(n)} ${n === 1 ? one : many}`;
  type Tile = { label: string; value: string; note?: string[] };
  const flightTiles = $derived<Tile[]>(current && f && f.count ? [
    { label: "Flights taken", value: count(f.count) },
    { label: "Distance", value: distance(f.distance_km, unit), note: comparisons(f) },
    { label: "In the air", value: duration(f.air_seconds) },
    { label: "Airports", value: count(f.airports.length) },
    { label: "Airlines", value: count(f.airlines.length) },
  ] : []);
  const hotelTiles = $derived<Tile[]>(current && (current.stays.nights || current.stays.count) ? [
    { label: "Nights away", value: count(current.stays.nights) },
    ...(current.stays.count ? [
      { label: "Stays", value: count(current.stays.count) },
      { label: "Average stay", value: `${current.stays.average_nights.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${current.stays.average_nights === 1 ? "night" : "nights"}` },
      { label: "Different hotels", value: count(current.stays.hotels.length) },
    ] : []),
  ] : []);
  const carTiles = $derived<Tile[]>(current && current.cars.days ? [{ label: "Rental days", value: count(current.cars.days) }] : []);
  const cruiseTiles = $derived<Tile[]>(current && current.cruises.count ? [
    { label: "Cruises taken", value: count(current.cruises.count) },
    { label: "Nights at sea", value: count(current.cruises.nights) },
    { label: "Sea days", value: count(current.cruises.sea_days) },
    { label: "Ports of call", value: count(current.cruises.ports) },
  ] : []);

  const named = (rows: { name: string; count: number }[], unitWord: string): Row[] => rows.map((r) => ({ key: r.name, name: r.name, value: plural(r.count, unitWord) }));
  const flightLists = $derived<{ title: string; rows: Row[] }[]>(f ? [
    { title: "Routes", rows: f.routes.map((r) => ({ key: `${r.a}-${r.b}`, name: `${r.a} – ${r.b}`, sub: r.distance_km === null ? null : distance(r.distance_km, unit), value: plural(r.flights, "flight") })) },
    { title: "Airports", rows: f.airports.map((a) => ({ key: a.code, name: a.code, sub: [a.name === a.code ? null : a.name, a.city].filter(Boolean).join(", ") || null, value: plural(a.visits, "visit") })) },
    { title: "Airlines", rows: f.airlines.map((a) => ({ key: `${a.code}/${a.name}`, name: a.name, value: plural(a.flights, "flight") })) },
  ] : []);
  const placeLists = $derived<{ title: string; rows: Row[] }[]>(current ? [
    { title: "Countries", rows: current.places.countries.map((c) => ({ key: c.name, name: countryName(c.name), sub: `First visit ${dateLabel(c.first_visit)}`, value: plural(c.visits, "visit") })) },
  ] : []);
  const hotelLists = $derived<{ title: string; rows: Row[] }[]>(current ? [
    { title: "Hotels stayed at", rows: current.stays.hotels.map((h) => ({ key: h.name, name: h.name, sub: plural(h.stays, "stay"), value: plural(h.nights, "night") })) },
    { title: "Cities stayed in", rows: current.stays.cities_by_nights.map((c) => ({ key: c.name, name: c.name, sub: plural(c.stays, "stay"), value: plural(c.nights, "night") })) },
    { title: "Hotel chains", rows: named(current.stays.chains, "stay") },
  ] : []);
  const carLists = $derived<{ title: string; rows: Row[] }[]>(current ? [{ title: "Rental companies", rows: named(current.cars.companies, "rental") }] : []);
  const cruiseLists = $derived<{ title: string; rows: Row[] }[]>(current ? [{ title: "Cruise lines", rows: named(current.cruises.lines, "cruise") }] : []);

  const airportName = (code: string) => f?.airports.find((a) => a.code === code);
  const record = (r: NonNullable<Stats["flights"]["longest"]>) => ({ value: `${r.origin} – ${r.destination}`, detail: `${distance(r.distance_km, unit)} · ${dateLabel(r.start_local.slice(0, 10))}` });
  type Record_ = { label: string; value: string; detail: string };
  const hotelRecords = $derived<Record_[]>(current ? ((st) => [
    st.longest && { label: "Longest stay", value: [st.longest.hotel, st.longest.city].filter(Boolean).join(", ") || "A stay", detail: `${plural(st.longest.nights, "night")} · ${dateLabel(st.longest.start_local.slice(0, 10))}` },
    st.most_visited_hotel && { label: "Most-visited hotel", value: st.most_visited_hotel.name, detail: `${plural(st.most_visited_hotel.stays, "stay")} · ${plural(st.most_visited_hotel.nights, "night")}` },
    st.most_visited_city && { label: "Most-visited city", value: st.most_visited_city.name, detail: `${plural(st.most_visited_city.stays, "stay")} · ${plural(st.most_visited_city.nights, "night")}` },
    st.busiest_month && { label: "Most nights in a month", value: monthLabel(st.busiest_month), detail: "" },
  ].filter((r) => !!r) as Record_[])(current.stays) : []);
  const flightRecords = $derived<Record_[]>(f ? [
    f.longest && { label: "Longest flight", ...record(f.longest) },
    f.shortest && { label: "Shortest flight", ...record(f.shortest) },
    f.most_visited_airport && { label: "Most-visited airport", value: f.most_visited_airport, detail: airportName(f.most_visited_airport)?.name ?? "" },
    f.busiest_month && { label: "Busiest month", value: monthLabel(f.busiest_month), detail: "" },
  ].filter((r) => !!r) as Record_[] : []);

  const cabinTotal = $derived(f ? f.cabins.reduce((n, c) => n + c.count, 0) : 0);
  const seatTotal = $derived(f ? f.seat_positions.window + f.seat_positions.aisle + f.seat_positions.middle : 0);
  const seatBars = $derived(f ? [["Window", f.seat_positions.window], ["Aisle", f.seat_positions.aisle], ["Middle", f.seat_positions.middle]] as [string, number][] : []);
  const selectClass = "border-input bg-card dark:bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";
</script>

{#snippet bars(title: string, rows: [string, number][], whole: number)}
  <div class="space-y-2">
    <h4 class="text-sm font-medium">{title}</h4>
    <ul class="space-y-2">
      {#each rows as [name, n] (name)}
        <li>
          <div class="flex justify-between text-sm"><span>{name}</span><span class="tabular-nums text-muted-foreground">{share(n, whole)}% · {count(n)}</span></div>
          <div class="mt-1 h-2 rounded-full bg-muted" aria-hidden="true"><div class="h-2 rounded-full bg-primary" style:width="{share(n, whole)}%"></div></div>
        </li>
      {/each}
    </ul>
  </div>
{/snippet}

{#snippet tileGrid(tiles: Tile[])}
  <dl class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
    {#each tiles as t (t.label)}
      <div class="rounded-2xl border bg-card p-4 shadow-card {t.note ? 'col-span-2 sm:col-span-1' : ''}">
        <dt class="eyebrow">{t.label}</dt>
        <dd class="mt-1 break-words text-3xl font-bold tabular-nums tracking-tight">{t.value}</dd>
        {#if t.note}{#each t.note as line (line)}<dd class="text-sm text-muted-foreground">{line}</dd>{/each}{/if}
      </div>
    {/each}
  </dl>
{/snippet}

{#snippet recordList(title: string, items: Record_[])}
  {#if items.length}
    <div class="space-y-2">
      <h3 class="eyebrow px-1">{title}</h3>
      <dl class="rows">
        {#each items as r (r.label)}
            <div class="row"><dt class="text-muted-foreground">{r.label}</dt><dd class="text-right font-medium">{r.value}{#if r.detail}<span class="block text-sm font-normal text-muted-foreground">{r.detail}</span>{/if}</dd></div>
        {/each}
      </dl>
    </div>
  {/if}
{/snippet}

<h1 class="mb-6 text-4xl font-bold tracking-tight">Stats</h1>

<div class="mb-6 grid grid-cols-2 gap-3">
  <label class="space-y-1 text-sm font-medium">Who
    <select class={selectClass} value={String(sel.who)} onchange={(e) => pick(e.currentTarget.value === "all" ? "all" : Number(e.currentTarget.value), sel.year)}>
      <option value="all">Everyone</option>
      {#each people as p (p.id)}<option value={String(p.id)}>{p.id === me ? `${p.display_name} (you)` : p.display_name}</option>{/each}
      {#if typeof sel.who === "number" && !people.some((p) => p.id === sel.who)}<option value={String(sel.who)}>{whoName}</option>{/if}
    </select>
  </label>
  <label class="space-y-1 text-sm font-medium">When
    <select class={selectClass} value={String(sel.year ?? "all")} onchange={(e) => pick(sel.who, e.currentTarget.value === "all" ? null : Number(e.currentTarget.value))}>
      <option value="all">All time</option>
      {#each yearChoices as y (y)}<option value={String(y)}>{y}</option>{/each}
    </select>
  </label>
</div>

{#if problem}
  <Alert role="alert"><AlertDescription class="flex flex-wrap items-center justify-between gap-3"><span>Couldn’t load the stats: {problem}</span><Button variant="outline" size="sm" onclick={() => load(key, statsPath(sel))}>Try again</Button></AlertDescription></Alert>
{:else if !current}
  <div class="space-y-4" aria-busy="true" aria-label="Loading">
    <div class="h-28 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none"></div>
    <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none"></div>
  </div>
{:else if empty}
  <div class="rows" data-testid="stats-empty">
    <div class="row flex-col items-start gap-3 py-6">
      <p class="font-medium">{whoName === "Everyone" ? "Nothing finished" : `Nothing finished for ${whoName}`}{sel.year ? ` in ${sel.year}` : " yet"}.</p>
      <p class="text-sm text-muted-foreground">Stats count flights, stays, rentals and cruises once they’re over.</p>
      <div class="flex flex-wrap gap-2"><Button href="#trips">Add a trip</Button><Button variant="outline" href="#settings/travel">Import past flights</Button></div>
    </div>
  </div>
{:else if f}
  <div class="space-y-8">
    {#if reviewable && sel.year}
      <Button variant="outline" onclick={() => (reviewing = true)}>See your {sel.year} in review</Button>
    {/if}
    <section aria-labelledby="places-title" id="stats-map-slot" data-testid="stats-map-slot" class="scroll-mt-20 space-y-3">
      <h2 id="places-title" class="text-2xl font-bold tracking-tight">Where you’ve been</h2>
      {@render tileGrid([{ label: "Countries", value: count(current.places.countries.length) }])}
      {#if TravelMap}
        <TravelMap flights={f} stays={current?.stays.pins ?? []} />
      {:else if mapError}
        <p class="text-sm text-muted-foreground">The map couldn’t load: {mapError} <Button variant="outline" size="sm" onclick={loadMap}>Try again</Button></p>
      {:else}
        <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading the map"></div>
      {/if}
      {#each placeLists as l (l.title)}<TopList title={l.title} rows={l.rows} />{/each}
    </section>

    {#if flightTiles.length}
      <section aria-labelledby="flights-title" class="space-y-3">
        <h2 id="flights-title" class="text-2xl font-bold tracking-tight">Flights</h2>
        {@render tileGrid(flightTiles)}
        {#each flightLists as l (l.title)}<TopList title={l.title} rows={l.rows} />{/each}
        {@render recordList("Flight records", flightRecords)}
      {#if cabinTotal || seatTotal}
        <section aria-labelledby="seats-title" class="space-y-3">
          <h3 id="seats-title" class="eyebrow px-1">Seats</h3>
          <div class="rows"><div class="row flex-col items-stretch gap-5 py-4">
            {#if cabinTotal}{@render bars("Cabin", f.cabins.map((c) => [c.name, c.count]), cabinTotal)}{/if}
            {#if seatTotal}{@render bars("Where you sit", seatBars, seatTotal)}{/if}
            {#if f.top_seat}<p class="text-sm"><span class="text-muted-foreground">Top seat</span> <span class="font-medium">{f.top_seat}</span></p>{/if}
          </div></div>
        </section>
      {/if}
      </section>
    {/if}

    {#if hotelTiles.length}
      <section aria-labelledby="hotels-title" class="space-y-3">
        <h2 id="hotels-title" class="text-2xl font-bold tracking-tight">Hotels</h2>
        {@render tileGrid(hotelTiles)}
        {#each hotelLists as l (l.title)}<TopList title={l.title} rows={l.rows} />{/each}
        {@render recordList("Hotel records", hotelRecords)}
      </section>
    {/if}

    {#if carTiles.length}
      <section aria-labelledby="cars-title" class="space-y-3">
        <h2 id="cars-title" class="text-2xl font-bold tracking-tight">Cars</h2>
        {@render tileGrid(carTiles)}
        {#each carLists as l (l.title)}<TopList title={l.title} rows={l.rows} />{/each}
      </section>
    {/if}

    {#if cruiseTiles.length}
      <section aria-labelledby="cruises-title" class="space-y-3">
        <h2 id="cruises-title" class="text-2xl font-bold tracking-tight">Cruises</h2>
        {@render tileGrid(cruiseTiles)}
        {#each cruiseLists as l (l.title)}<TopList title={l.title} rows={l.rows} />{/each}
      </section>
    {/if}
  </div>
{/if}

{#if reviewing && current && sel.year}
  <YearInReview stats={current} person={sel.who} name={reviewName} onclose={() => (reviewing = false)} />
{/if}
