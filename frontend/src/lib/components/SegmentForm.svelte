<script lang="ts">
  import { onMount } from "svelte";
  import { actGet } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Person, Segment } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import FlightLength from "$lib/components/FlightLength.svelte";
  import ZoneSelect from "$lib/components/ZoneSelect.svelte";
  import { countryChoices } from "$lib/countries";
  import { ADDRESS_LIMIT, body, DETAILS, KINDS, MAX_PORTS, problem, SEAT_LIMIT, SEATED, FOR_EVERYONE, seatKey, type Draft } from "$lib/segment-form";

  let { initial, people, onsaved, oncancel, focus = "", titled = true }: { initial: Draft; people: Person[]; onsaved: (s: Segment) => void; oncancel: () => void; focus?: string; titled?: boolean } = $props();
  // svelte-ignore state_referenced_locally
  let d = $state<Draft>({ ...initial, details: { ...initial.details }, people: [...initial.people], printed: [...initial.printed] });
  let error = $state("");
  let saving = $state(false);

  const addPort = () => (d.itinerary = [...d.itinerary, { name: "", zone: d.itinerary.at(-1)?.zone ?? d.start_zone, arrive: "", depart: "" }]);
  const movePort = (i: number, by: number) => {
    const next = [...d.itinerary];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    d.itinerary = next;
  };
  onMount(() => { if (focus) document.getElementById(focus)?.focus(); });

  const flight = $derived(d.kind === "flight");
  const editing = $derived(d.id !== null);
  const visit = $derived(d.kind === "visit");
  const countries = countryChoices();
  const day = (local: string) => local.slice(0, 10);
  const stay = $derived(d.kind === "hotel" || d.kind === "parking");
  const startBlank = $derived(flight ? "Work it out from the airport" : stay ? "Work it out from the address" : d.kind === "cruise" ? "Choose a time zone" : "Work it out from the airport or address");

  async function save(e: SubmitEvent) {
    e.preventDefault();
    const msg = problem(d);
    if (msg) { error = msg; return; }
    error = "";
    const saved = await actGet(() => d.id === null
      ? apiCall<"POST /api/segments">("/api/segments", { method: "POST", body: { ...body(d), trip_id: d.tripId } })
      : apiCall<"POST /api/segments/{id}">(`/api/segments/${d.id}`, { method: "POST", body: body(d) }),
    { busy: (on) => (saving = on), onError: (m) => (error = m) });
    if (saved) onsaved(saved);
  }

  const selectClass = "border-input bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";
  const label = "flex flex-col gap-1.5 text-sm";
</script>

<form class="rows mb-6" data-editor novalidate onsubmit={save} aria-labelledby={titled ? "segment-form-title" : undefined} aria-label={titled ? undefined : editing ? "Edit this booking" : "Add a booking"}>
  <div class="row items-stretch">
    <div class="flex w-full flex-col gap-4">
      {#if titled}<h2 id="segment-form-title" class="font-medium">{editing ? "Edit this booking" : "Add a booking"}</h2>{/if}
      {#if editing}<p class="text-sm text-muted-foreground">Anything you change here is kept: a later email won’t put it back.</p>{/if}
      <label class={label}><span class="font-medium">What is it</span>
        <select bind:value={d.kind} disabled={editing} class={selectClass}>
          {#each KINDS as [key, name] (key)}<option value={key}>{name}</option>{/each}
        </select></label>
      {#if visit}
        <p class="text-sm text-muted-foreground">For a trip you remember only by country and dates. Add flights or hotels to it later if you find them.</p>
        <label class={label}><span class="font-medium">Country</span>
          <select bind:value={d.destination} class={selectClass}>
            <option value="">Choose a country</option>
            {#each countries as [code, name] (code)}<option value={code}>{name}</option>{/each}
          </select></label>
        <div class="grid grid-cols-2 gap-3">
          <label class={label}><span class="font-medium">First day</span>
            <Input type="date" value={day(d.start_local)} oninput={(e) => { d.start_local = e.currentTarget.value ? `${e.currentTarget.value}T00:00` : ""; }} autocomplete="off" /></label>
          <label class={label}><span class="font-medium">Last day</span>
            <Input type="date" value={day(d.end_local)} oninput={(e) => { d.end_local = e.currentTarget.value ? `${e.currentTarget.value}T00:00` : ""; }} autocomplete="off" /></label>
        </div>
      {:else}
      <label class={label}><span class="font-medium">Status</span>
        <select bind:value={d.status} class={selectClass}>
          <option value="confirmed">Confirmed</option><option value="changed">Changed</option><option value="cancelled">Cancelled</option>
        </select></label>
      <label class={label}><span class="font-medium">{d.kind === "hotel" ? "Hotel chain or booking site" : d.kind === "car" ? "Rental company" : d.kind === "train" ? "Railway" : d.kind === "cruise" ? "Cruise line" : d.kind === "parking" ? "Parking operator" : "Airline"}</span>
        <Input bind:value={d.provider} maxlength={100} autocomplete="off" placeholder={d.kind === "flight" ? "American Airlines" : d.kind === "hotel" ? "Marriott" : ""} /></label>
      <label class={label}><span class="font-medium">Confirmation code</span>
        <Input bind:value={d.confirmation} maxlength={50} autocomplete="off" spellcheck={false} /></label>
      {#if flight}
        <div class="grid grid-cols-2 gap-3">
          <label class={label}><span class="font-medium">From (airport)</span>
            <Input bind:value={d.origin} maxlength={3} autocomplete="off" spellcheck={false} placeholder="JFK" /></label>
          <label class={label}><span class="font-medium">To (airport)</span>
            <Input bind:value={d.destination} maxlength={3} autocomplete="off" spellcheck={false} placeholder="LHR" /></label>
        </div>
      {:else}
        <label class={label}><span class="font-medium">{d.kind === "hotel" ? "Hotel name" : d.kind === "parking" ? "Lot name" : d.kind === "car" ? "Pick-up place" : d.kind === "cruise" ? "Embark port" : "From"}</span>
          <Input bind:value={d.origin} maxlength={100} autocomplete="off" /></label>
        {#if !stay}
          <label class={label}><span class="font-medium">{d.kind === "car" ? "Drop-off place" : d.kind === "cruise" ? "Disembark port" : "To"}</span>
            <Input bind:value={d.destination} maxlength={100} autocomplete="off" /></label>
        {/if}
      {/if}
      <label class={label}><span class="font-medium">{d.kind === "hotel" ? "Check-in" : d.kind === "parking" ? "Entry" : d.kind === "car" ? "Pick-up" : d.kind === "cruise" ? "Embarks" : "Departs"}</span>
        <Input type="datetime-local" bind:value={d.start_local} autocomplete="off" />
        <span class="text-muted-foreground">The local time at the place.</span></label>
      <label class={label}><span class="font-medium">{d.kind === "hotel" ? "Check-out" : d.kind === "parking" ? "Exit" : d.kind === "car" ? "Drop-off" : d.kind === "cruise" ? "Disembarks" : "Arrives"}</span>
        <Input type="datetime-local" bind:value={d.end_local} autocomplete="off" />
        <span class="text-muted-foreground">The local time at the place it ends.</span></label>
      {#if flight}<FlightLength origin={d.origin} destination={d.destination} start={d.start_local} end={d.end_local} />{/if}
      <label class={label}><span class="font-medium">{flight ? "Departure time zone (only if the airport isn’t known)" : "Time zone"}</span>
        <ZoneSelect bind:value={d.start_zone} blank={startBlank} /></label>
      {#if !stay}
        <label class={label}><span class="font-medium">{flight ? "Arrival time zone (only if the airport isn’t known)" : "Time zone at the end (if different)"}</span>
          <ZoneSelect bind:value={d.end_zone} blank={flight ? "Work it out from the airport" : d.kind === "cruise" ? "Same as where it starts" : "Same as where it starts, or work it out from the airport"} /></label>
      {/if}
      {#each DETAILS[d.kind] as [key, name] (key)}
        <label class={label}><span class="font-medium">{name}</span>
          {#if key === "address"}
            <textarea id="segment-address" rows="3" maxlength={ADDRESS_LIMIT} value={d.details[key] ?? ""} oninput={(e) => (d.details[key] = e.currentTarget.value)}
              autocomplete="off" class={selectClass}></textarea>
          {:else}
            <Input value={d.details[key] ?? ""} oninput={(e) => (d.details[key] = e.currentTarget.value)} maxlength={200} autocomplete="off" />
          {/if}</label>
      {/each}
      {#if d.kind === "cruise"}
        <fieldset class="flex flex-col gap-3" data-itinerary>
          <legend class="mb-1.5 text-sm font-medium">Ports of call</legend>
          <p class="text-sm text-muted-foreground">In the order the ship calls at them. Times are local to each port; leave them empty if you don’t have them.</p>
          {#each d.itinerary as port, i (i)}
            <div class="flex flex-col gap-3 rounded-xl border border-border p-3" data-port>
              <label class={label}><span class="font-medium">Port {i + 1}</span>
                <Input bind:value={port.name} maxlength={100} autocomplete="off" aria-label={`Port ${i + 1} name`} /></label>
              <label class={label}><span class="font-medium">Time zone</span>
                <ZoneSelect bind:value={port.zone} blank="Choose a time zone" label={`Port ${i + 1} time zone`} /></label>
              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label class={label}><span class="font-medium">Arrives</span>
                  <Input type="datetime-local" bind:value={port.arrive} autocomplete="off" aria-label={`Port ${i + 1} arrival`} /></label>
                <label class={label}><span class="font-medium">Leaves</span>
                  <Input type="datetime-local" bind:value={port.depart} autocomplete="off" aria-label={`Port ${i + 1} departure`} /></label>
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
      <label class={label}><span class="font-medium">Manage link</span>
        <Input bind:value={d.manage_url} maxlength={500} autocomplete="off" spellcheck={false} placeholder="https://" /></label>
      <fieldset class="flex flex-col gap-1.5 text-sm" data-cost>
        <legend class="mb-1.5 font-medium">Cost</legend>
        <div class="flex gap-3">
          <Input class="min-w-0 flex-1" bind:value={d.cost} inputmode="decimal" autocomplete="off" spellcheck={false} placeholder="1,240.00" aria-label="Cost amount" />
          <Input class="w-24 uppercase" bind:value={d.currency} maxlength={3} autocomplete="off" spellcheck={false} placeholder="USD" aria-label="Cost currency" />
        </div>
        <span class="text-muted-foreground">{d.costSource === "email" ? "Read from an email. Change it and your amount is kept: a later email won’t replace it. " : ""}The total for this booking, in its own currency (nothing is converted). Clear it to remove the cost.</span>
      </fieldset>
      {/if}
      {#if !FOR_EVERYONE.includes(d.kind)}
      <fieldset class="flex flex-col gap-2 text-sm">
        <legend class="mb-1.5 font-medium">Who’s travelling</legend>
        {#each people as p (p.id)}
          <label class="flex items-center gap-2"><input type="checkbox" value={p.id} bind:group={d.people} class="size-4" /> {p.display_name}</label>
          {@render seat(seatKey(p.id), p.display_name, d.people.includes(p.id))}
        {/each}
        {#each d.printed as name (name)}
          <label class="flex items-center gap-2"><input type="checkbox" checked onchange={() => (d.printed = d.printed.filter((n) => n !== name))} class="size-4" /> {name} <span class="text-muted-foreground">(name as printed, not in People)</span></label>
          {@render seat(seatKey(name), name, true)}
        {/each}
      </fieldset>
      {/if}
      {#if error}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{error}</p>{/if}
      <div class="flex flex-wrap gap-2">
        <Button type="submit" disabled={saving}>{saving ? "Saving…" : editing ? "Save" : "Add"}</Button>
        <Button type="button" variant="outline" disabled={saving} onclick={oncancel}>Cancel</Button>
      </div>
    </div>
  </div>
</form>

{#snippet seat(key: string, name: string, ticked: boolean)}
  {#if ticked && SEATED.includes(d.kind)}
    <label class="ml-6 flex items-center gap-2"><span class="text-muted-foreground">Seat</span>
      <Input class="w-28" bind:value={d.seats[key]} maxlength={SEAT_LIMIT} autocomplete="off" spellcheck={false} aria-label={`Seat of ${name}`} /></label>
  {/if}
{/snippet}
