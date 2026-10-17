<script lang="ts">
  import { onMount, tick } from "svelte";
  import { actGet } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Person, Segment } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { DiscardDialog } from "$lib/components/ui/discard-dialog";
  import { baseline, draftGuard, leave } from "$lib/drafts.svelte";
  import FlightLength from "$lib/components/FlightLength.svelte";
  import AirportField from "$lib/components/AirportField.svelte";
  import ZoneSelect from "$lib/components/ZoneSelect.svelte";
  import { airportInfo } from "$lib/airport-zones";
  import { countryChoices, usStateChoices } from "$lib/countries";
  import { ADDRESS_LIMIT, body, DETAILS, hasMore, inMore, issues, KINDS, MAX_PORTS, MAX_VISITS, nextVisitRow, visitBodies, visitRows, type VisitRow, SEAT_LIMIT, SEATED, FOR_EVERYONE, SAME_AS_PICKUP, seatKey, type Draft } from "$lib/segment-form";

  let { initial, people, onsaved, oncancel, focus = "", titled = true }: { initial: Draft; people: Person[]; onsaved: (s: Segment) => void; oncancel: () => void; focus?: string; titled?: boolean } = $props();
  // svelte-ignore state_referenced_locally
  let d = $state<Draft>({ ...initial, details: { ...initial.details }, people: [...initial.people], printed: [...initial.printed] });
  const uid = $props.id();
  let error = $state("");
  let attempted = $state(false);
  let saving = $state(false);
  let formEl: HTMLFormElement | null = $state(null);
  // svelte-ignore state_referenced_locally
  let moreOpen = $state(hasMore(initial));
  // svelte-ignore state_referenced_locally
  let zonesRequested = $state(initial.id !== null && !!(initial.start_zone || initial.end_zone));
  let unknownAirports = $state<string[]>([]);
  const unchanged = baseline(() => d);
  const guard = draftGuard({ dirty: unchanged.changed, saving: () => saving, discard: () => oncancel() });

  const addPort = () => (d.itinerary = [...d.itinerary, { name: "", zone: d.itinerary.at(-1)?.zone ?? d.start_zone, arrive: "", depart: "" }]);
  const movePort = (i: number, by: number) => {
    const next = [...d.itinerary];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    d.itinerary = next;
  };
  onMount(async () => {
    if (!focus) return;
    const target = document.getElementById(focus);
    if (target?.closest("details")) { moreOpen = true; await tick(); }
    target?.focus();
  });

  const rows = $derived(visitRows(d));
  const setState = (state: string | undefined) => {
    if (state) d.details.state = state;
    else delete d.details.state;
  };
  const setRow = (i: number, patch: Partial<VisitRow>) => {
    if (i === 0) {
      const { state, ...rest } = patch;
      Object.assign(d, rest);
      if (state !== undefined) setState(state);
    } else d.more = (d.more ?? []).map((r, n) => (n === i - 1 ? { ...r, ...patch } : r));
  };
  const addCountry = () => (d.more = [...(d.more ?? []), nextVisitRow(rows.at(-1) as VisitRow)]);
  const dropCountry = (i: number) => {
    const left = rows.filter((_, n) => n !== i);
    const { state, ...first } = left[0];
    Object.assign(d, first);
    setState(state);
    d.more = left.slice(1);
  };
  const localDay = (value: string) => (value ? `${value}T00:00` : "");

  const flight = $derived(d.kind === "flight");
  const editing = $derived(d.id !== null);
  const visit = $derived(d.kind === "visit");
  const countries = countryChoices();
  const usStates = usStateChoices();
  const day = (local: string) => local.slice(0, 10);
  const stay = $derived(d.kind === "hotel" || d.kind === "parking");
  const startBlank = $derived(flight ? "Work it out from the airport" : stay ? "Work it out from the address" : d.kind === "cruise" ? "Choose a time zone" : "Work it out from the airport or address");

  const found = $derived(attempted ? issues(d) : []);
  const shown = $derived(Object.fromEntries([...found].reverse().map((i) => [i.field, i.message])) as Record<string, string | undefined>);
  const zoneFailed = $derived(found.some((i) => i.field === "start_zone" || i.field === "end_zone"));
  const airportUnknown = $derived(flight && [d.origin, d.destination].some((c) => unknownAirports.includes(c.trim().toUpperCase())));
  const showZones = $derived(d.kind !== "cruise" && (zonesRequested || zoneFailed || airportUnknown || !!d.start_zone.trim() || !!d.end_zone.trim()));
  const fieldId = (field: string) => `${uid}-${field}`;
  const aria = (field: string) => (shown[field] ? { "aria-invalid": "true" as const, "aria-describedby": fieldId(field) } : {});

  $effect(() => {
    if (!flight) return;
    for (const raw of [d.origin, d.destination]) {
      const code = raw.trim().toUpperCase();
      if (/^[A-Z]{3}$/.test(code)) void airportInfo(code).then((a) => { if (!a && !unknownAirports.includes(code)) unknownAirports = [...unknownAirports, code]; });
    }
  });

  $effect(() => {
    if (found.some((i) => inMore(i.field, d.kind))) moreOpen = true;
  });

  async function focusFirstInvalid(list: { field: string }[]) {
    await tick();
    const targets = list.flatMap((i) => formEl?.querySelector<HTMLElement>(`[data-field="${i.field}"] :is(input, select, textarea)`) ?? []);
    const first = targets.sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))[0];
    first?.focus();
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    const list = issues(d);
    if (list.length) { attempted = true; error = ""; await focusFirstInvalid(list); return; }
    error = "";
    if (visit && !editing) { await saveVisits(); return; }
    const saved = await actGet(() => d.id === null
      ? apiCall<"POST /api/segments">("/api/segments", { method: "POST", body: { ...body(d), trip_id: d.tripId } })
      : apiCall<"POST /api/segments/{id}">(`/api/segments/${d.id}`, { method: "POST", body: body(d) }),
    { busy: (on) => (saving = on), onError: (m) => (error = m) });
    if (saved) onsaved(saved);
  }

  async function saveVisits() {
    const bodies = visitBodies(d);
    let first: Segment | null = null;
    saving = true;
    try {
      for (const [i, one] of bodies.entries()) {
        const saved = await actGet(() => apiCall<"POST /api/segments">("/api/segments", { method: "POST", body: { ...one, trip_id: first?.trip_id ?? d.tripId } }),
          { onError: (m) => (error = bodies.length > 1 ? `Country ${i + 1}: ${m}${first ? " The countries before it were saved." : ""}` : m) });
        if (!saved) {
          if (first) {
            const left = rows.slice(i);
            d.tripId = first.trip_id;
            Object.assign(d, left[0]);
            d.more = left.slice(1);
          }
          return;
        }
        first ??= saved;
      }
    } finally { saving = false; }
    if (first) onsaved(first);
  }

  const selectClass = "aria-invalid:border-destructive border-input bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";
  const label = "flex flex-col gap-1.5 text-sm";
  const group = "flex flex-col gap-4";
  const heading = "text-sm font-semibold text-muted-foreground";
</script>

<form class="rows mb-6" data-editor novalidate bind:this={formEl} onsubmit={save} aria-labelledby={titled ? "segment-form-title" : undefined} aria-label={titled ? undefined : editing ? "Edit this booking" : "Add a booking"}>
  <div class="row items-stretch">
    <div class="flex w-full flex-col gap-6">
      {#if titled}<h2 id="segment-form-title" class="font-medium">{editing ? "Edit this booking" : "Add a booking"}</h2>{/if}
      {#if editing}<p class="text-sm text-muted-foreground">Anything you change here is kept: a later email won’t put it back.</p>{/if}
      <section class={group} aria-labelledby={fieldId("booking")}>
        <h3 id={fieldId("booking")} class={heading}>Booking</h3>
        <label class={label}><span class="font-medium">What is it</span>
          <select bind:value={d.kind} disabled={editing} class={selectClass}>
            {#each KINDS as [key, name] (key)}<option value={key}>{name}</option>{/each}
          </select></label>
        {#if !visit && !flight}{@render providerFields()}{/if}
      </section>

      <section class={group} aria-labelledby={fieldId("where")}>
        <h3 id={fieldId("where")} class={heading}>When and where</h3>
        {#if visit}
          <p class="text-sm text-muted-foreground">For a trip you remember only by country and dates. Add flights or hotels to it later if you find them.</p>
          {#each rows as row, i (i)}
            {@const named = rows.length > 1 ? ` ${i + 1}` : ""}
            <div class="flex flex-col gap-3" class:rounded-xl={rows.length > 1} class:border={rows.length > 1} class:border-border={rows.length > 1} class:p-3={rows.length > 1} data-country>
              <div data-field={`country-${i}`} class="flex flex-col gap-1.5">
                <label class={label}><span class="font-medium">Country{named}</span>
                  <select value={row.destination} onchange={(e) => setRow(i, { destination: e.currentTarget.value })} class={selectClass} {...aria(`country-${i}`)}>
                    <option value="">Choose a country</option>
                    {#each countries as [code, name] (code)}<option value={code}>{name}</option>{/each}
                  </select></label>
                {@render fieldError(`country-${i}`)}
              </div>
              {#if row.destination === "US"}
                <div data-field={`state-${i}`} class="flex flex-col gap-1.5">
                  <label class={label}><span class="font-medium">State{named} (optional)</span>
                    <select value={row.state ?? ""} onchange={(e) => setRow(i, { state: e.currentTarget.value })} class={selectClass} {...aria(`state-${i}`)}>
                      <option value="">Any state</option>
                      {#each usStates as [code, name] (code)}<option value={code}>{name}</option>{/each}
                    </select></label>
                  {@render fieldError(`state-${i}`)}
                </div>
              {/if}
              <div class="grid grid-cols-2 gap-3">
                <div data-field={`first-${i}`} class="flex flex-col gap-1.5">
                  <label class={label}><span class="font-medium">First day{named}</span>
                    <Input type="date" value={day(row.start_local)} oninput={(e) => setRow(i, { start_local: localDay(e.currentTarget.value) })} autocomplete="off" {...aria(`first-${i}`)} /></label>
                  {@render fieldError(`first-${i}`)}
                </div>
                <div data-field={`last-${i}`} class="flex flex-col gap-1.5">
                  <label class={label}><span class="font-medium">Last day{named}</span>
                    <Input type="date" value={day(row.end_local)} oninput={(e) => setRow(i, { end_local: localDay(e.currentTarget.value) })} autocomplete="off" {...aria(`last-${i}`)} /></label>
                  {@render fieldError(`last-${i}`)}
                </div>
              </div>
              {#if rows.length > 1}
                <div><Button type="button" variant="outline" size="sm" aria-label={`Remove country ${i + 1}`} onclick={() => dropCountry(i)}>Remove</Button></div>
              {/if}
            </div>
          {/each}
          {@render fieldError("visits")}
          {#if !editing}
            <div><Button type="button" variant="outline" size="sm" disabled={rows.length >= MAX_VISITS} onclick={addCountry}>Add another country</Button></div>
          {/if}
        {:else}
          {#if flight}
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div class="flex flex-col gap-1.5">
                <label class={label}><span class="font-medium">From (airport)</span>
                  <AirportField bind:value={d.origin} placeholder="JFK, or a city or airport name" field="origin" invalid={!!shown.origin} describedby={shown.origin ? fieldId("origin") : undefined} /></label>
                {@render fieldError("origin")}
              </div>
              <div class="flex flex-col gap-1.5">
                <label class={label}><span class="font-medium">To (airport)</span>
                  <AirportField bind:value={d.destination} placeholder="LHR, or a city or airport name" field="destination" invalid={!!shown.destination} describedby={shown.destination ? fieldId("destination") : undefined} /></label>
                {@render fieldError("destination")}
              </div>
            </div>
          {:else}
            <div data-field="origin" class="flex flex-col gap-1.5">
              <label class={label}><span class="font-medium">{d.kind === "hotel" ? "Hotel name" : d.kind === "parking" ? "Lot name" : d.kind === "car" ? "Pick-up place" : d.kind === "cruise" ? "Embark port" : "From"}</span>
                <Input bind:value={d.origin} maxlength={100} autocomplete="off" {...aria("origin")} /></label>
              {@render fieldError("origin")}
            </div>
            {#if !stay}
              <label class={label}><span class="font-medium">{d.kind === "car" ? "Drop-off place" : d.kind === "cruise" ? "Disembark port" : "To"}</span>
                <Input bind:value={d.destination} maxlength={100} autocomplete="off" placeholder={d.kind === "car" ? SAME_AS_PICKUP : ""} /></label>
            {/if}
          {/if}
          <div data-field="start" class="flex flex-col gap-1.5">
            <label class={label}><span class="font-medium">{d.kind === "hotel" ? "Check-in" : d.kind === "parking" ? "Entry" : d.kind === "car" ? "Pick-up" : d.kind === "cruise" ? "Embarks" : "Departs"}</span>
              <Input type="datetime-local" bind:value={d.start_local} autocomplete="off" {...aria("start")} />
              <span class="text-muted-foreground">The local time at the place.</span></label>
            {@render fieldError("start")}
          </div>
          <div data-field="end" class="flex flex-col gap-1.5">
            <label class={label}><span class="font-medium">{d.kind === "hotel" ? "Check-out" : d.kind === "parking" ? "Exit" : d.kind === "car" ? "Drop-off" : d.kind === "cruise" ? "Disembarks" : "Arrives"}</span>
              <Input type="datetime-local" bind:value={d.end_local} autocomplete="off" {...aria("end")} />
              <span class="text-muted-foreground">The local time at the place it ends.</span></label>
            {@render fieldError("end")}
          </div>
          {#if flight}<FlightLength origin={d.origin} destination={d.destination} start={d.start_local} end={d.end_local} />{/if}
          {#if stay}
            <div data-field="address" class="flex flex-col gap-1.5">
              <label class={label}><span class="font-medium">Address</span>
                <textarea id="segment-address" rows="3" maxlength={ADDRESS_LIMIT} value={d.details.address ?? ""} oninput={(e) => (d.details.address = e.currentTarget.value)}
                  autocomplete="off" class={selectClass} {...aria("address")}></textarea></label>
              {@render fieldError("address")}
            </div>
          {/if}
          {#if d.kind === "cruise" || showZones}
            <div data-field="start_zone" class="flex flex-col gap-1.5">
              <label class={label}><span class="font-medium">{flight ? "Departure time zone (only if the airport isn’t known)" : "Time zone"}</span>
                <ZoneSelect bind:value={d.start_zone} blank={startBlank} invalid={!!shown.start_zone} describedby={shown.start_zone ? fieldId("start_zone") : undefined} /></label>
              {@render fieldError("start_zone")}
            </div>
            {#if !stay}
              <div data-field="end_zone" class="flex flex-col gap-1.5">
                <label class={label}><span class="font-medium">{flight ? "Arrival time zone (only if the airport isn’t known)" : "Time zone at the end (if different)"}</span>
                  <ZoneSelect bind:value={d.end_zone} blank={flight ? "Work it out from the airport" : d.kind === "cruise" ? "Same as where it starts" : "Same as where it starts, or work it out from the airport"} invalid={!!shown.end_zone} describedby={shown.end_zone ? fieldId("end_zone") : undefined} /></label>
                {@render fieldError("end_zone")}
              </div>
            {/if}
          {:else}
            <div><Button type="button" variant="outline" size="sm" onclick={() => (zonesRequested = true)}>Set the time zone by hand</Button></div>
          {/if}
          {#if d.kind === "cruise"}
            <fieldset class="flex flex-col gap-3" data-itinerary>
              <legend class="mb-1.5 text-sm font-medium">Ports of call</legend>
              <p class="text-sm text-muted-foreground">In the order the ship calls at them. Times are local to each port; leave them empty if you don’t have them.</p>
              {@render fieldError("ports")}
              {#each d.itinerary as port, i (i)}
                <div class="flex flex-col gap-3 rounded-xl border border-border p-3" data-port>
                  <div data-field={`port-${i}-name`} class="flex flex-col gap-1.5">
                    <label class={label}><span class="font-medium">Port {i + 1}</span>
                      <Input bind:value={port.name} maxlength={100} autocomplete="off" aria-label={`Port ${i + 1} name`} {...aria(`port-${i}-name`)} /></label>
                    {@render fieldError(`port-${i}-name`)}
                  </div>
                  <div data-field={`port-${i}-zone`} class="flex flex-col gap-1.5">
                    <label class={label}><span class="font-medium">Time zone</span>
                      <ZoneSelect bind:value={port.zone} blank="Choose a time zone" label={`Port ${i + 1} time zone`} invalid={!!shown[`port-${i}-zone`]} describedby={shown[`port-${i}-zone`] ? fieldId(`port-${i}-zone`) : undefined} /></label>
                    {@render fieldError(`port-${i}-zone`)}
                  </div>
                  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div data-field={`port-${i}-arrive`} class="flex flex-col gap-1.5">
                      <label class={label}><span class="font-medium">Arrives</span>
                        <Input type="datetime-local" bind:value={port.arrive} autocomplete="off" aria-label={`Port ${i + 1} arrival`} {...aria(`port-${i}-arrive`)} /></label>
                      {@render fieldError(`port-${i}-arrive`)}
                    </div>
                    <div data-field={`port-${i}-depart`} class="flex flex-col gap-1.5">
                      <label class={label}><span class="font-medium">Leaves</span>
                        <Input type="datetime-local" bind:value={port.depart} autocomplete="off" aria-label={`Port ${i + 1} departure`} {...aria(`port-${i}-depart`)} /></label>
                      {@render fieldError(`port-${i}-depart`)}
                    </div>
                  </div>
                  <div class="flex flex-wrap gap-2">
                    <Button type="button" variant="outline" size="sm" disabled={i === 0} aria-label={`Move port ${i + 1} up`} onclick={() => movePort(i, -1)}>Up</Button>
                    <Button type="button" variant="outline" size="sm" disabled={i === d.itinerary.length - 1} aria-label={`Move port ${i + 1} down`} onclick={() => movePort(i, 1)}>Down</Button>
                    <Button type="button" variant="outline" size="sm" aria-label={`Remove port ${i + 1}`} onclick={() => (d.itinerary = d.itinerary.filter((_, n) => n !== i))}>Remove</Button>
                  </div>
                </div>
              {/each}
              <div><Button type="button" variant="outline" size="sm" disabled={d.itinerary.length >= MAX_PORTS} onclick={addPort}>Add a port</Button></div>
            </fieldset>
          {/if}
        {/if}
      </section>

      {#if !FOR_EVERYONE.includes(d.kind)}
        <section class={group} aria-labelledby={fieldId("travelers")}>
          <h3 id={fieldId("travelers")} class={heading}>Travelers</h3>
          <fieldset class="flex flex-col gap-2 text-sm" data-field="travelers">
            <legend class="mb-1.5 font-medium">Who’s travelling</legend>
            {#each people as p (p.id)}
              <label class="flex items-center gap-2"><input type="checkbox" value={p.id} bind:group={d.people} class="size-4" {...aria("travelers")} /> {p.display_name}</label>
              {@render seat(seatKey(p.id), p.display_name, d.people.includes(p.id))}
            {/each}
            {#each d.printed as name (name)}
              <label class="flex items-center gap-2"><input type="checkbox" checked onchange={() => (d.printed = d.printed.filter((n) => n !== name))} class="size-4" {...aria("travelers")} /> {name} <span class="text-muted-foreground">(name as printed, not in People)</span></label>
              {@render seat(seatKey(name), name, true)}
            {/each}
            {@render fieldError("travelers")}
          </fieldset>
        </section>
      {/if}

      {#if !visit}
        <details class="rounded-xl border border-border" bind:open={moreOpen} data-more>
          <summary class="cursor-pointer px-3 py-2.5 text-sm font-medium">More details</summary>
          <div class="flex flex-col gap-4 p-3 pt-1">
            {#if flight}{@render providerFields()}{/if}
            <label class={label}><span class="font-medium">Status</span>
              <select bind:value={d.status} class={selectClass}>
                <option value="confirmed">Confirmed</option><option value="changed">Changed</option><option value="cancelled">Cancelled</option>
              </select></label>
            {#each DETAILS[d.kind].filter(([key]) => !(key === "address" && stay)) as [key, name] (key)}
              <div data-field={key} class="flex flex-col gap-1.5">
                <label class={label}><span class="font-medium">{name}</span>
                  {#if key === "address"}
                    <textarea id="segment-address" rows="3" maxlength={ADDRESS_LIMIT} value={d.details[key] ?? ""} oninput={(e) => (d.details[key] = e.currentTarget.value)}
                      autocomplete="off" class={selectClass} {...aria("address")}></textarea>
                  {:else}
                    <Input value={d.details[key] ?? ""} oninput={(e) => (d.details[key] = e.currentTarget.value)} maxlength={200} autocomplete="off" />
                  {/if}</label>
                {#if key === "address"}{@render fieldError("address")}{/if}
              </div>
            {/each}
            {#if d.kind === "car" && d.addressField}
              <div data-field="address" class="flex flex-col gap-1.5">
                <label class={label}><span class="font-medium">Pick-up address</span>
                  <textarea id="segment-address" rows="3" maxlength={ADDRESS_LIMIT} value={d.details.address ?? ""} oninput={(e) => (d.details.address = e.currentTarget.value)}
                    autocomplete="off" class={selectClass} {...aria("address")}></textarea>
                  <span class="text-muted-foreground">Leave it empty to use the pick-up place.</span></label>
                {@render fieldError("address")}
              </div>
            {/if}
            <div data-field="manage_url" class="flex flex-col gap-1.5">
              <label class={label}><span class="font-medium">Manage link</span>
                <Input bind:value={d.manage_url} maxlength={500} autocomplete="off" spellcheck={false} placeholder="https://" {...aria("manage_url")} /></label>
              {@render fieldError("manage_url")}
            </div>
            <fieldset class="flex flex-col gap-1.5 text-sm" data-cost>
              <legend class="mb-1.5 font-medium">Cost</legend>
              <div class="flex gap-3">
                <span data-field="cost" class="contents"><Input class="min-w-0 flex-1" bind:value={d.cost} inputmode="decimal" autocomplete="off" spellcheck={false} placeholder="1,240.00" aria-label="Cost amount" {...aria("cost")} /></span>
                <span data-field="currency" class="contents"><Input class="w-24 uppercase" bind:value={d.currency} maxlength={3} autocomplete="off" spellcheck={false} placeholder="USD" aria-label="Cost currency" {...aria("currency")} /></span>
              </div>
              {@render fieldError("cost")}
              {@render fieldError("currency")}
              <span class="text-muted-foreground">{d.costSource === "email" ? "Read from an email. Change it and your amount is kept: a later email won’t replace it. " : ""}The total for this booking, in its own currency (nothing is converted). Clear it to remove the cost.</span>
            </fieldset>
          </div>
        </details>
      {/if}
      {#if error}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{error}</p>{/if}
      {#if found.length}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{found.length === 1 ? "One thing needs fixing before this can be saved. It is marked above." : `${found.length} things need fixing before this can be saved. They are marked above.`}</p>{/if}
      <div class="flex flex-wrap gap-2">
        <Button type="submit" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Add booking"}</Button>
        <Button type="button" variant="outline" disabled={saving} onclick={() => leave(oncancel, [guard])}>Cancel</Button>
      </div>
    </div>
  </div>
</form>

<DiscardDialog {guard} />

{#snippet providerFields()}
  <label class={label}><span class="font-medium">{d.kind === "hotel" ? "Hotel chain or booking site" : d.kind === "car" ? "Rental company" : d.kind === "train" ? "Railway" : d.kind === "cruise" ? "Cruise line" : d.kind === "parking" ? "Parking operator" : "Airline"}</span>
    <Input bind:value={d.provider} maxlength={100} autocomplete="off" placeholder={d.kind === "flight" ? "American Airlines" : d.kind === "hotel" ? "Marriott" : ""} /></label>
  <label class={label}><span class="font-medium">Confirmation code</span>
    <Input bind:value={d.confirmation} maxlength={50} autocomplete="off" spellcheck={false} /></label>
{/snippet}

{#snippet fieldError(field: string)}
  {#if shown[field]}<p id={fieldId(field)} class="text-sm text-signal-ink" data-error>{shown[field]}</p>{/if}
{/snippet}

{#snippet seat(key: string, name: string, ticked: boolean)}
  {#if ticked && SEATED.includes(d.kind)}
    <div data-field={`seat-${key}`} class="ml-6 flex flex-col gap-1.5">
      <label class="flex items-center gap-2"><span class="text-muted-foreground">Seat</span>
        <Input class="w-28" bind:value={d.seats[key]} maxlength={SEAT_LIMIT} autocomplete="off" spellcheck={false} aria-label={`Seat of ${name}`} {...aria(`seat-${key}`)} /></label>
      {@render fieldError(`seat-${key}`)}
    </div>
  {/if}
{/snippet}
