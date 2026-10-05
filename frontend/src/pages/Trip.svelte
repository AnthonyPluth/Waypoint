<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { route } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { LoyaltyEntry, Person, Segment, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import { isIOS } from "$lib/platform";
  import { loadFlightStatus } from "$lib/flightstatus.svelte";
  import LoyaltyNumber from "$lib/components/LoyaltyNumber.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import SegmentForm from "$lib/components/SegmentForm.svelte";
  import { blank, draftOf, KINDS, type Draft } from "$lib/segment-form";
  import { dateLabel, dayLabel, END_WORD, headline, membershipFor, START_WORD, subline } from "$lib/trips";
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import Plus from "@lucide/svelte/icons/plus";
  import { toast } from "svelte-sonner";

  // One trip: each booking as a card, with its local times, travellers and the number each would use. A failed load leaves
  // nothing drawn that could pass for current, with a Try again.
  let trip = $state<Trip | null>(null);
  let people = $state<Person[]>([]);
  let loyalty = $state<LoyaltyEntry[]>([]);
  let loadError = $state("");
  let form = $state<Draft | null>(null);
  let removing = $state<Segment | null>(null);
  let asking = $state(false);

  const id = $derived(route.sub);
  const ios = isIOS();

  let latest = 0;   // the newest load: an earlier, slower one finishing later must not put its trip on screen
  async function load() {
    const mine = ++latest;
    loadError = "";
    if (!/^\d+$/.test(id)) { trip = null; loadError = "No such trip"; return; }
    try {
      const [t, p, l] = await Promise.all([apiCall<"GET /api/trips/{id}">(`/api/trips/${id}`), apiCall<"GET /api/people">("/api/people"), apiCall<"GET /api/loyalty">("/api/loyalty")]);
      if (mine !== latest) return;
      trip = t; people = p.people; loyalty = l.loyalty;
      void loadFlightStatus();   // (the flights' live status shows beside their times once it arrives)
    } catch (err) { if (mine !== latest) return; trip = null; loadError = errMsg(err); }
  }
  $effect(() => { void id; form = null; void load(); });

  const kindName = (s: Segment) => KINDS.find(([k]) => k === s.kind)?.[1] ?? s.kind;
  const dates = (t: Trip) => t.start_date && t.end_date ? (t.start_date === t.end_date ? dateLabel(t.start_date) : `${dateLabel(t.start_date)} – ${dateLabel(t.end_date)}`) : "No dates yet";

  async function saved(s: Segment) {
    form = null;
    toast.success("Saved");
    if (trip && s.trip_id !== trip.id) { location.hash = `#trip/${s.trip_id}`; return; }
    await load();
  }

  const remove = (s: Segment) => act(async () => {
    await apiCall<"DELETE /api/segments/{id}">(`/api/segments/${s.id}`, { method: "DELETE" });
    toast.success("Removed");
    // A grouped trip left with no bookings goes too.
    if (trip && trip.segments.length === 1 && trip.auto) { location.hash = "#trips"; return; }
    await load();
  });
</script>

<a class="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground" href="#trips"><ArrowLeft class="size-4" /> Trips</a>

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if trip === null}
  <div class="h-40 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading"></div>
{:else}
  {@const t = trip}
  <div class="mb-6 flex flex-wrap items-start justify-between gap-3">
    <div class="min-w-0">
      <h1 class="break-words text-3xl font-semibold tracking-tight">{t.name}</h1>
      <p class="text-muted-foreground">{dates(t)}{t.destination ? ` · ${t.destination}` : ""}</p>
      {#if t.notes}<p class="mt-2 whitespace-pre-line break-words text-sm">{t.notes}</p>{/if}
    </div>
    {#if !form}<Button onclick={() => (form = blank(t.id))}><Plus /> Add a booking</Button>{/if}
  </div>

  {#if form}
    {#key form.id ?? "new"}<SegmentForm initial={form} {people} oncancel={() => (form = null)} onsaved={saved} />{/key}
  {/if}

  {#if t.segments.length === 0}
    <p class="text-muted-foreground">Nothing booked on this trip yet.</p>
  {/if}
  <ul class="flex flex-col gap-4" aria-label="Bookings">
    {#each t.segments as s (s.id)}
      {@const live = s.status !== "cancelled"}
      <li class="pass" class:opacity-70={s.status === "cancelled"}>
        <div class="flex flex-col gap-2 p-5 md:p-6">
          <p class="flex flex-wrap items-center gap-2"><span class="eyebrow">{kindName(s)}</span>
            {#if s.status !== "confirmed"}<Badge variant={s.status === "cancelled" ? "destructive" : "secondary"}>{s.status === "cancelled" ? "Cancelled" : "Changed"}</Badge>{/if}
            {#if s.locked_fields.length}<Badge variant="outline" title="A later email won’t change what you edited">Edited by you</Badge>{/if}</p>
          <h2 class="break-words text-xl font-semibold tracking-tight" class:line-through={s.status === "cancelled"}>{headline(s)}</h2>
          {#if subline(s)}<p class="break-words text-sm text-muted-foreground">{subline(s)}</p>{/if}
          {#if s.kind === "flight" && s.status !== "cancelled"}<FlightStatus segment={s} />{/if}
          <dl class="mt-2 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div><dt class="eyebrow">{START_WORD[s.kind]}</dt>
              <dd class="mt-1 text-base font-medium">{dayLabel(s.start_local)}, <PlaceTime local={s.start_local} zone={s.start_zone} /></dd></div>
            <div><dt class="eyebrow">{END_WORD[s.kind]}</dt>
              <dd class="mt-1 text-base font-medium">{dayLabel(s.end_local)}, <PlaceTime local={s.end_local} zone={s.end_zone} /></dd></div>
            {#if s.confirmation}<div><dt class="eyebrow">Confirmation</dt><dd class="mt-1 text-lg"><CopyCode code={s.confirmation} /></dd></div>{/if}
          </dl>
          {#if s.links.app || (live && (s.links.directions || s.links.call || ios))}
            <div class="mt-2 flex flex-wrap gap-2" role="group" aria-label={`Actions for ${headline(s)}`}>
              {#if s.links.app}<Button variant="outline" size="sm" href={s.links.app} target="_blank" rel="noopener noreferrer">Open in app</Button>{/if}
              {#if live && ios}<Button variant="outline" size="sm" href="shoebox://">Wallet</Button>{/if}
              {#if live && s.links.directions}<Button variant="outline" size="sm" href={s.links.directions} target="_blank" rel="noopener noreferrer">Directions</Button>{/if}
              {#if live && s.links.call}<Button variant="outline" size="sm" href={s.links.call}>Call</Button>{/if}
            </div>
          {/if}
        </div>
        <div class="pass-tear" aria-hidden="true"></div>
        <div class="flex flex-col gap-3 p-5 md:p-6">
          <h3 class="eyebrow">Travellers</h3>
          {#if s.travelers.length === 0}<p class="text-sm text-muted-foreground">Nobody is listed on this booking.</p>{/if}
          <ul class="flex flex-col gap-2">
            {#each s.travelers as who (who.id)}
              {@const m = membershipFor(s, who, loyalty)}
              <li class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
                <span class="break-words font-medium">{who.name}</span>
                <span class="text-muted-foreground">
                  {#if m?.state === "found"}{m.entry.program} <LoyaltyNumber entry={m.entry} />
                  {:else if m?.state === "none"}No {m.program} number yet · <a class="underline" href="#people">add one in People</a>
                  {:else if m?.state === "unmatched"}Not matched to a person in <a class="underline" href="#people">People</a>{/if}
                </span>
              </li>
            {/each}
          </ul>
          <div class="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" aria-label={`Edit ${headline(s)}`} onclick={() => (form = draftOf(s))}>Edit</Button>
            <Button variant="outline" size="sm" aria-label={`Remove ${headline(s)}`} onclick={() => { removing = s; asking = true; }}>Remove</Button>
          </div>
        </div>
      </li>
    {/each}
  </ul>
{/if}

<ConfirmDialog bind:open={asking} title={`Remove ${removing ? headline(removing) : "this booking"}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="It’s deleted from the trip. This can’t be undone."
  onconfirm={async () => { const s = removing; return s ? await remove(s) : true; }} />
