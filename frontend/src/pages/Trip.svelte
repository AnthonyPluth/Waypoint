<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { route } from "$lib/app.svelte";
  import { tick } from "svelte";
  import { apiCall } from "$lib/contract";
  import type { LoyaltyEntry, Person, Segment, StoredEmail, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import { isMobile } from "$lib/platform";
  import { loadFlightStatus } from "$lib/flightstatus.svelte";
  import LoyaltyNumber from "$lib/components/LoyaltyNumber.svelte";
  import MessageView from "$lib/components/MessageView.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import SegmentForm from "$lib/components/SegmentForm.svelte";
  import { blank, draftOf, KINDS, type Draft } from "$lib/segment-form";
  import { bookingCards, dateLabel, dayLabel, END_WORD, headline, membershipFor, START_WORD, subline, untimed } from "$lib/trips";
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import { toast } from "svelte-sonner";

  // One trip: each booking as a card (a flight on two bookings is one card, with a block for each booking), with its local times,
  // travellers and the number each would use. A failed load leaves
  // nothing drawn that could pass for current, with a Try again.
  let trip = $state<Trip | null>(null);
  let people = $state<Person[]>([]);
  let loyalty = $state<LoyaltyEntry[]>([]);
  let loadError = $state("");
  let form = $state<Draft | null>(null);
  let focus = $state("");   // the form field to put the cursor in (Add address)
  let renaming = $state<string | null>(null);   // the trip's name while it's being changed (null: not renaming)
  let renameError = $state("");
  let saving = $state(false);
  let removing = $state<Segment | null>(null);
  let asking = $state(false);

  // The email a booking was made from, read in place: the copy the server kept, fetched when asked and held only while it's open.
  type Mail = { state: "loading" } | { state: "ready"; emails: StoredEmail[] } | { state: "error"; message: string };
  let mails = $state<Record<number, Mail | undefined>>({});
  async function toggleMail(s: Segment) {
    if (mails[s.id]) { mails[s.id] = undefined; return; }
    mails[s.id] = { state: "loading" };
    try {
      mails[s.id] = { state: "ready", emails: (await apiCall<"GET /api/segments/{id}/emails">(`/api/segments/${s.id}/emails`)).emails };
    } catch (err) { mails[s.id] = { state: "error", message: errMsg(err) }; }
  }

  const id = $derived(route.sub);
  const appWord = isMobile() ? "Open in app" : "Manage booking";   // (a desktop browser has no app to open: it gets the provider’s website)

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
  $effect(() => { void id; form = null; renaming = null; void load(); });

  // A link to one booking (#trip/<id>?segment=<its card's first segment>): once the trip is on screen, scroll to that card and mark it.
  const wanted = $derived(new URLSearchParams(route.query).get("segment"));
  $effect(() => {
    if (!trip || !wanted) return;
    void cards;
    tick().then(() => document.getElementById(`segment-${wanted}`)?.scrollIntoView({ block: "start" }));
  });

  const cards = $derived(trip ? bookingCards(trip.segments) : []);
  const kindName = (s: Segment) => KINDS.find(([k]) => k === s.kind)?.[1] ?? s.kind;
  const dates = (t: Trip) => t.start_date && t.end_date ? (t.start_date === t.end_date ? dateLabel(t.start_date) : `${dateLabel(t.start_date)} – ${dateLabel(t.end_date)}`) : "No dates yet";

  // A form that opens below a card the reader may have scrolled to: bring it into view (reduced motion jumps instead of gliding).
  function reveal(node: HTMLElement) {
    const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    node.scrollIntoView?.({ block: "nearest", behavior: calm ? "auto" : "smooth" });
  }

  const rename = (e: SubmitEvent) => {
    e.preventDefault();
    const name = (renaming ?? "").trim();
    if (!trip || !name) { renameError = "Enter a name for the trip"; return; }
    return act(async () => {
      if (!trip) return;
      trip = await apiCall<"POST /api/trips/{id}">(`/api/trips/${trip.id}`, { method: "POST", body: { name } });
      renaming = null; renameError = "";
      toast.success("Saved");
    }, { busy: (on) => (saving = on), onError: (m) => (renameError = m) });
  };

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
      {#if renaming !== null}
        <form class="flex flex-col gap-2 sm:flex-row sm:items-center" onsubmit={rename} aria-label="Rename trip">
          <Input class="sm:w-80" aria-label="Trip name" bind:value={renaming} maxlength={100} autocomplete="off" autofocus />
          <div class="flex gap-2">
            <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
            <Button type="button" variant="outline" disabled={saving} onclick={() => { renaming = null; renameError = ""; }}>Cancel</Button>
          </div>
        </form>
        {#if renameError}<p class="mt-2 rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{renameError}</p>{/if}
      {:else}
        <div class="flex items-start gap-2">
          <h1 class="break-words text-4xl font-bold tracking-tight">{t.name}</h1>
          <Button variant="ghost" size="icon" class="mt-1 shrink-0" aria-label="Rename trip" onclick={() => { renaming = t.name; renameError = ""; }}><Pencil /></Button>
        </div>
      {/if}
      <p class="text-muted-foreground">{dates(t)}{t.destination ? ` · ${t.destination}` : ""}</p>
      {#if t.notes}<p class="mt-2 whitespace-pre-line break-words text-sm">{t.notes}</p>{/if}
    </div>
    {#if !form}<Button onclick={() => { focus = ""; form = blank(t.id); }}><Plus /> Add a booking</Button>{/if}
  </div>

  {#if form && form.id === null}
    <SegmentForm initial={form} {people} {focus} oncancel={() => (form = null)} onsaved={saved} />
  {/if}

  {#if t.segments.length === 0}
    <p class="text-muted-foreground">Nothing booked on this trip yet.</p>
  {/if}
  <ul class="flex flex-col gap-4" aria-label="Bookings">
    {#each cards as card (card.id)}
      {@const s = card.lead}
      {@const live = !card.cancelled}
      {#if card.segments.length === 1}
        <li class="pass scroll-mt-20" id={`segment-${s.id}`} class:ring-2={wanted === String(s.id)} class:ring-ring={wanted === String(s.id)} class:opacity-70={s.status === "cancelled"}>
          <div class="flex flex-col gap-2 p-5 md:p-6">
            {@render heading(s)}
            {#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}
            <dl class="mt-2 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
              {@render times(s)}
              {#if s.confirmation}<div><dt class="eyebrow">Confirmation</dt><dd class="mt-1 text-lg"><CopyCode code={s.confirmation} /></dd></div>{/if}
            </dl>
            {@render ports(s)}
            {@render links(s)}
          </div>
          <div class="pass-tear" aria-hidden="true"></div>
          <div class="flex flex-col gap-3 p-5 md:p-6">
            <h3 class="eyebrow">Travellers</h3>
            {@render travellerList(s)}
            {@render buttons(s, headline(s))}
          </div>
        </li>
      {:else}
        <!-- One flight on several bookings: the flight once, then a block for each booking. -->
        <li class="pass scroll-mt-20" id={`segment-${s.id}`} class:ring-2={wanted === String(s.id)} class:ring-ring={wanted === String(s.id)} class:opacity-70={card.cancelled} aria-label={`${headline(s)}, on ${card.segments.length} bookings`}>
          <div class="flex flex-col gap-2 p-5 md:p-6">
            {@render heading(s, card.cancelled)}
            {#if live && !untimed(s)}<FlightStatus segment={s} />{/if}
            {#if card.timesDiffer}
              <p class="mt-2 text-sm font-medium" data-times-differ><Badge variant="secondary">Times differ between bookings</Badge> <span class="text-muted-foreground">Each booking’s times are below.</span></p>
            {:else}
              <dl class="mt-2 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">{@render times(s)}</dl>
            {/if}
          </div>
          <div class="pass-tear" aria-hidden="true"></div>
          <div class="flex flex-col gap-4 p-5 md:p-6">
            <h3 class="eyebrow">Bookings</h3>
            <ul class="flex flex-col gap-4" aria-label={`Bookings of ${headline(s)}`}>
              {#each card.segments as b (b.id)}
                {@const name = `${headline(b)} booking${b.confirmation ? ` ${b.confirmation}` : ""}`}
                <li class="flex flex-col gap-3 rounded-2xl border border-border bg-background/40 p-4" class:opacity-70={b.status === "cancelled"} data-booking>
                  <p class="flex flex-wrap items-center gap-2">
                    {#if b.confirmation}<span class="text-lg"><CopyCode code={b.confirmation} /></span>{:else}<span class="text-muted-foreground">No confirmation code</span>{/if}
                    {#if b.status !== "confirmed"}<Badge variant={b.status === "cancelled" ? "destructive" : "secondary"}>{b.status === "cancelled" ? "Cancelled" : "Changed"}</Badge>{/if}
                    {#if b.locked_fields.length}<Badge variant="outline" title="A later email won’t change what you edited">Edited by you</Badge>{/if}</p>
                  {#if card.timesDiffer && b.status !== "cancelled"}
                    <dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">{@render times(b)}</dl>
                  {/if}
                  {@render links(b)}
                  <h4 class="eyebrow">Travellers</h4>
                  {@render travellerList(b)}
                  {@render buttons(b, name)}
                </li>
              {/each}
            </ul>
          </div>
        </li>
      {/if}
      <!-- Editing a booking opens its form right under it, where the reader is, not up at the trip's title. -->
      {#if form && form.id !== null && card.segments.some((b) => b.id === form?.id)}
        <li use:reveal aria-label="Edit booking"><SegmentForm initial={form} {people} {focus} oncancel={() => (form = null)} onsaved={saved} /></li>
      {/if}
    {/each}
  </ul>
{/if}

{#snippet heading(s: Segment, cancelled: boolean = s.status === "cancelled")}
  <p class="flex flex-wrap items-center gap-2"><span class="eyebrow">{kindName(s)}</span>
    {#if cancelled}<Badge variant="destructive">Cancelled</Badge>{:else if s.status !== "confirmed"}<Badge variant="secondary">Changed</Badge>{/if}
    {#if s.locked_fields.length}<Badge variant="outline" title="A later email won’t change what you edited">Edited by you</Badge>{/if}</p>
  <div class="flex items-center gap-3">
    <BrandLogo src={s.logo} label={s.logo_label} size={40} />
    <div class="min-w-0">
      <h2 class="break-words text-2xl font-bold tracking-tight" class:line-through={cancelled}>{headline(s)}</h2>
      {#if subline(s)}<p class="break-words text-sm text-muted-foreground">{subline(s)}</p>{/if}
    </div>
  </div>
{/snippet}

{#snippet times(s: Segment)}
  <div><dt class="eyebrow">{START_WORD[s.kind]}</dt>
    <dd class="mt-1 text-base font-medium">{dayLabel(s.start_local)}, {#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.start_local} zone={s.start_zone} />{/if}</dd></div>
  <div><dt class="eyebrow">{END_WORD[s.kind]}</dt>
    <dd class="mt-1 text-base font-medium">{#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}{dayLabel(s.end_local)}, <PlaceTime local={s.end_local} zone={s.end_zone} />{/if}</dd></div>
  {#if s.kind === "hotel" && !untimed(s)}
    <!-- A stay's zone may have been worked out from its address: say which, so a wrong one is caught. -->
    <div><dt class="eyebrow">Time zone</dt><dd class="mt-1 text-sm text-muted-foreground" data-testid="stay-zone">{s.start_zone.replaceAll("_", " ")}</dd></div>
  {/if}
{/snippet}

{#snippet links(s: Segment)}
  {#if s.check_times}<p class="text-sm text-signal-ink" role="note">Check the times: the email gave them in UTC and Waypoint couldn’t tell which clock they mean. Edit the booking to correct or confirm them.</p>{/if}
  {#if s.kind === "hotel" || s.kind === "car" || s.kind === "cruise"}
    {#if s.details.address}
      <div class="mt-2 text-sm"><p class="eyebrow">{s.kind === "car" ? "Pick-up address" : s.kind === "cruise" ? "Terminal address" : "Address"}</p>
        <CopyCode code={s.details.address} label="address" multiline class="mt-1 text-base font-medium" /></div>
    {:else if s.status !== "cancelled"}
      <p class="mt-2 text-sm"><button type="button" class="underline underline-offset-2" onclick={() => { focus = "segment-address"; form = draftOf(s); }}
        aria-label={`Add address to ${headline(s)}`}>Add address</button></p>
    {/if}
  {/if}
  {#if s.links.app || (s.status !== "cancelled" && (s.links.directions || s.links.call))}
    <div class="mt-2 flex flex-wrap gap-2" role="group" aria-label={`Actions for ${headline(s)}`}>
      {#if s.links.app}<Button variant="outline" size="sm" href={s.links.app} target="_blank" rel="noopener noreferrer">{appWord}</Button>{/if}
      {#if s.status !== "cancelled" && s.links.directions}<Button variant="outline" size="sm" href={s.links.directions} target="_blank" rel="noopener noreferrer">Directions</Button>{/if}
      {#if s.status !== "cancelled" && s.links.call}<Button variant="outline" size="sm" href={s.links.call}>Call</Button>{/if}
    </div>
  {/if}
  {#if s.has_email}
    {@const mail = mails[s.id]}
    <div class="mt-2">
      <Button variant="outline" size="sm" aria-expanded={!!mail} aria-label={`${mail ? "Hide" : "View"} the email for ${headline(s)}`} onclick={() => toggleMail(s)}>{mail ? "Hide email" : "View email"}</Button>
    </div>
    {#if mail}
      <div class="mt-2 space-y-4" role="region" aria-label={`The email for ${headline(s)}`}>
        {#if mail.state === "loading"}<p class="text-sm text-muted-foreground" role="status">Opening the email…</p>
        {:else if mail.state === "error"}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{mail.message}</p>
        {:else if !mail.emails.length}<p class="text-sm text-muted-foreground">This email isn’t kept any more.</p>
        {:else}
          {#each mail.emails as e, i (i)}
            <div>
              {#if e.received || e.sender_domain}<p class="mb-1 text-sm text-muted-foreground">{[e.sender_domain, e.received && `sent ${e.received}`].filter(Boolean).join(" · ")}</p>{/if}
              <MessageView subject={e.subject} text={e.text} html={e.html} truncated={e.truncated} />
            </div>
          {/each}
        {/if}
      </div>
    {/if}
  {/if}
{/snippet}

{#snippet ports(s: Segment)}
  {#if s.itinerary.length}
    <div class="mt-2 text-sm" data-itinerary>
      <p class="eyebrow">Ports of call</p>
      <ol class="mt-1 flex flex-col gap-2">
        {#each s.itinerary as p, i (i)}
          <li class="flex flex-wrap items-baseline justify-between gap-x-3">
            <span class="break-words font-medium">{p.name}</span>
            <span class="text-muted-foreground">
              {#if p.arrive_local}{dayLabel(p.arrive_local)}, arrives <PlaceTime local={p.arrive_local} zone={p.zone} />{#if p.depart_local}, leaves <PlaceTime local={p.depart_local} zone={p.zone} />{/if}
              {:else if p.depart_local}{dayLabel(p.depart_local)}, leaves <PlaceTime local={p.depart_local} zone={p.zone} />
              {:else}Time not recorded{/if}
            </span>
          </li>
        {/each}
      </ol>
    </div>
  {/if}
{/snippet}

{#snippet travellerList(s: Segment)}
  {#if s.travelers.length === 0}<p class="text-sm text-muted-foreground">Nobody is listed on this booking.</p>{/if}
  <ul class="flex flex-col gap-2">
    {#each s.travelers as who (who.id)}
      {@const m = membershipFor(s, who, loyalty)}
      <li class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
        <span class="break-words font-medium">{who.name}{#if who.seat}{" "}<span class="font-normal text-muted-foreground">· Seat {who.seat}</span>{/if}</span>
        <span class="text-muted-foreground">
          {#if m?.state === "found"}{m.entry.program} <LoyaltyNumber entry={m.entry} />
          {:else if m?.state === "none"}No {m.program} number yet · <a class="underline" href="#people">add one in People</a>
          {:else if m?.state === "unmatched"}Not matched to a person in <a class="underline" href="#people">People</a>{/if}
        </span>
      </li>
    {/each}
  </ul>
{/snippet}

{#snippet buttons(s: Segment, name: string)}
  <div class="flex flex-wrap gap-2">
    <Button variant="outline" size="sm" aria-label={`Edit ${name}`} onclick={() => { focus = ""; form = draftOf(s); }}>Edit</Button>
    <Button variant="outline" size="sm" aria-label={`Remove ${name}`} onclick={() => { removing = s; asking = true; }}>Remove</Button>
  </div>
{/snippet}

<ConfirmDialog bind:open={asking} title={`Remove ${removing ? headline(removing) : "this booking"}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="It’s deleted from the trip. This can’t be undone."
  onconfirm={async () => { const s = removing; return s ? await remove(s) : true; }} />
