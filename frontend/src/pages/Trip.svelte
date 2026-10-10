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
  import CopyCode from "$lib/components/CopyCode.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import { isMobile } from "$lib/platform";
  import { viewport } from "$lib/phone.svelte";
  import { Sheet } from "$lib/components/ui/sheet";
  import { loadFlightStatus } from "$lib/flightstatus.svelte";
  import { askAboutOffline, offline, refreshOffline, saveTripCopy } from "$lib/offline.svelte";
  import { hasSavedTrip, onLock } from "$lib/offline-vault";
  import LoyaltyNumber from "$lib/components/LoyaltyNumber.svelte";
  import MessageView from "$lib/components/MessageView.svelte";
  import OfflineSetup from "$lib/components/OfflineSetup.svelte";
  import PassCard from "$lib/components/PassCard.svelte";
  import SavedTripLock from "$lib/components/SavedTripLock.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import SegmentForm from "$lib/components/SegmentForm.svelte";
  import { blank, draftOf, KINDS, type Draft } from "$lib/segment-form";
  import { appWord, bookingCards, dateLabel, dayLabel, END_WORD, headline, membershipFor, START_WORD, untimed } from "$lib/trips";
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import { toast } from "svelte-sonner";

  let { tripId = null, onchanged = null }: { tripId?: number | null; onchanged?: ((movedTo?: number) => void) | null } = $props();

  let trip = $state<Trip | null>(null);
  let people = $state<Person[]>([]);
  let loyalty = $state<LoyaltyEntry[]>([]);
  let loadError = $state("");
  let form = $state<Draft | null>(null);
  let focus = $state("");
  let inSheet = $state(false);
  let renaming = $state<string | null>(null);
  let renameError = $state("");
  let saving = $state(false);
  let removing = $state<Segment | null>(null);
  let asking = $state(false);
  let askOffline = $state(false);
  let lockedCopy = $state(false);
  let savedCopy = $state<Trip | null>(null);

  const isTrip = (v: unknown): v is Trip => !!v && typeof v === "object" && Array.isArray((v as Trip).segments) && typeof (v as Trip).name === "string";
  $effect(() => onLock(() => { savedCopy = null; }));

  async function afterOnlineLoad(t: Trip) {
    await refreshOffline();
    if (offline.setUp) await saveTripCopy(t);
    else if (askAboutOffline()) askOffline = true;
  }

  async function offerSavedCopy() {
    lockedCopy = navigator.onLine === false && (await hasSavedTrip().catch(() => false));
  }

  type Mail = { state: "loading" } | { state: "ready"; emails: StoredEmail[] } | { state: "error"; message: string };
  let mails = $state<Record<number, Mail | undefined>>({});
  async function toggleMail(s: Segment) {
    if (mails[s.id]) { mails[s.id] = undefined; return; }
    mails[s.id] = { state: "loading" };
    try {
      mails[s.id] = { state: "ready", emails: (await apiCall<"GET /api/segments/{id}/emails">(`/api/segments/${s.id}/emails`)).emails };
    } catch (err) { mails[s.id] = { state: "error", message: errMsg(err) }; }
  }

  let now = $state(Date.now());
  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(tick);
  });

  const id = $derived(tripId === null ? route.sub : String(tripId));

  let latest = 0;
  async function load() {
    const mine = ++latest;
    loadError = "";
    lockedCopy = false;
    if (!/^\d+$/.test(id)) { trip = null; loadError = "No such trip"; return; }
    try {
      const [t, p, l] = await Promise.all([apiCall<"GET /api/trips/{id}">(`/api/trips/${id}`), apiCall<"GET /api/people">("/api/people"), apiCall<"GET /api/loyalty">("/api/loyalty")]);
      if (mine !== latest) return;
      trip = t; people = p.people; loyalty = l.loyalty;
      void loadFlightStatus();
      void afterOnlineLoad(t);
    } catch (err) {
      if (mine !== latest) return;
      trip = null; loadError = errMsg(err);
      await offerSavedCopy();
    }
  }
  $effect(() => { void id; form = null; renaming = null; savedCopy = null; void load(); });

  const wanted = $derived(new URLSearchParams(route.query).get("segment"));
  $effect(() => {
    if (!trip || !wanted) return;
    void cards;
    tick().then(() => document.getElementById(`segment-${wanted}`)?.scrollIntoView({ block: "start" }));
  });

  const cards = $derived(trip ? bookingCards(trip.segments) : []);
  const eyebrowOf = (s: Segment) => `${kindName(s)} · ${dayLabel(s.start_local)}`;
  const kindName = (s: Segment) => KINDS.find(([k]) => k === s.kind)?.[1] ?? s.kind;
  const dates = (t: Trip) => t.start_date && t.end_date ? (t.start_date === t.end_date ? dateLabel(t.start_date) : `${dateLabel(t.start_date)} – ${dateLabel(t.end_date)}`) : "No dates yet";

  function reveal(node: HTMLElement) {
    const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    node.scrollIntoView?.({ block: "nearest", behavior: calm ? "auto" : "smooth" });
  }

  function edit(s: Segment, field = "") {
    focus = field;
    inSheet = viewport.phone;
    form = draftOf(s);
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
      onchanged?.();
    }, { busy: (on) => (saving = on), onError: (m) => (renameError = m) });
  };

  async function saved(s: Segment) {
    form = null;
    toast.success("Saved");
    if (trip && s.trip_id !== trip.id) { if (onchanged) onchanged(s.trip_id); else location.hash = `#trip/${s.trip_id}`; return; }
    onchanged?.();
    await load();
  }

  const remove = (s: Segment) => act(async () => {
    await apiCall<"DELETE /api/segments/{id}">(`/api/segments/${s.id}`, { method: "DELETE" });
    toast.success("Removed");
    onchanged?.();
    if (trip && trip.segments.length === 1 && trip.auto) { if (!onchanged) location.hash = "#trips"; return; }
    await load();
  });
</script>

{#if tripId === null}
  <a class="mb-4 inline-flex items-center gap-1.5 phone:min-h-11 text-sm text-muted-foreground hover:text-foreground" href="#trips"><ArrowLeft class="size-4" /> Trips</a>
{/if}

{#if lockedCopy}
  {#if savedCopy}
    {@const copy = savedCopy}
    <div class="mb-6 space-y-1">
      <h1 class="break-words text-display">{copy.name}</h1>
      <p class="text-muted-foreground">{dates(copy)}{copy.destination ? ` · ${copy.destination}` : ""}</p>
      <p class="text-sm text-muted-foreground" role="note">Saved copy from this device. It locks again after 5 minutes without use.</p>
    </div>
    <ul class="flex flex-col gap-3" aria-label="Saved bookings">
      {#each copy.segments as s (s.id)}
        <li class="rounded-2xl border border-border bg-card p-4">
          <p class="eyebrow">{eyebrowOf(s)}</p>
          <p class="mt-1 break-words font-medium">{headline(s)}</p>
          {#if s.confirmation}<p class="mt-1 text-lg"><CopyCode code={s.confirmation} /></p>{/if}
        </li>
      {/each}
    </ul>
  {:else}
    <SavedTripLock onunlocked={(v) => { if (isTrip(v)) savedCopy = v; else throw new Error("unreadable"); }} onremoved={() => (lockedCopy = false)} />
  {/if}
{:else if loadError}
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
          <h1 class="break-words text-display">{t.name}</h1>
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
  <ul class="ml-2 flex flex-col gap-6 border-l-2 border-dashed border-border pl-4 sm:pl-6" aria-label="Bookings">
    {#each cards as card (card.id)}
      {@const s = card.lead}
      {#if card.segments.length === 1}
        <PassCard as="li" id={`segment-${s.id}`} highlight={wanted === String(s.id)} segment={s} {now} level={2} eyebrow={eyebrowOf(s)} showApp={false} omit={["Address"]}>
          {#snippet times()}<dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">{@render timeRows(s)}</dl>{/snippet}
          {#snippet details()}{@render ports(s)}{@render links(s)}{/snippet}
          {#snippet live()}{#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}{/snippet}
          {#snippet footer()}
            <div class="flex flex-col gap-3">
              <h3 class="eyebrow">Travellers</h3>
              {@render travellerList(s)}
              {@render buttons(s, headline(s))}
            </div>
          {/snippet}
        </PassCard>
      {:else}
        <PassCard as="li" id={`segment-${s.id}`} highlight={wanted === String(s.id)} segment={s} {now} level={2} eyebrow={eyebrowOf(s)} showCode={false} showApp={false}
          label={`${headline(s)}, on ${card.segments.length} bookings`}>
          {#snippet times()}
            {#if card.timesDiffer}
              <p class="text-sm font-medium" data-times-differ><Badge variant="secondary">Times differ between bookings</Badge> <span class="text-muted-foreground">Each booking’s times are below.</span></p>
            {:else}
              <dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">{@render timeRows(s)}</dl>
            {/if}
          {/snippet}
          {#snippet live()}{#if !card.cancelled && !untimed(s)}<FlightStatus segment={s} />{/if}{/snippet}
          {#snippet footer()}
            <div class="flex flex-col gap-4">
              <h3 class="eyebrow">Bookings</h3>
              <ul class="flex flex-col gap-4" aria-label={`Bookings of ${headline(s)}`}>
                {#each card.segments as b (b.id)}
                  {@const name = `${headline(b)} booking${b.confirmation ? ` ${b.confirmation}` : ""}`}
                  <li class="flex flex-col gap-3 rounded-2xl border border-border bg-surface-2 p-4" class:opacity-80={b.status === "cancelled"} data-booking>
                    <p class="flex flex-wrap items-center gap-2">
                      {#if b.confirmation}<span class="text-lg"><CopyCode code={b.confirmation} /></span>{:else}<span class="text-muted-foreground">No confirmation code</span>{/if}
                      {#if b.status !== "confirmed"}<Badge variant={b.status === "cancelled" ? "destructive" : "secondary"}>{b.status === "cancelled" ? "Cancelled" : "Changed"}</Badge>{/if}</p>
                    {#if card.timesDiffer && b.status !== "cancelled"}
                      <dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">{@render timeRows(b)}</dl>
                    {/if}
                    {@render links(b)}
                    <h4 class="eyebrow">Travellers</h4>
                    {@render travellerList(b)}
                    {@render buttons(b, name)}
                  </li>
                {/each}
              </ul>
            </div>
          {/snippet}
        </PassCard>
      {/if}
      {#if form && form.id !== null && !inSheet && card.segments.some((b) => b.id === form?.id)}
        <li use:reveal aria-label="Edit booking"><SegmentForm initial={form} {people} {focus} oncancel={() => (form = null)} onsaved={saved} /></li>
      {/if}
    {/each}
  </ul>
{/if}

<OfflineSetup bind:open={askOffline} onenabled={() => trip && void saveTripCopy(trip)} />

<Sheet bind:open={() => inSheet && form !== null && form.id !== null, (v) => { if (!v) form = null; }} title="Edit this booking">
  {#if form && form.id !== null}
    <SegmentForm initial={form} {people} {focus} titled={false} oncancel={() => (form = null)} onsaved={saved} />
  {/if}
</Sheet>

{#snippet timeRows(s: Segment)}
  <div><dt class="eyebrow">{START_WORD[s.kind]}</dt>
    <dd class="mt-1 text-base font-medium">{dayLabel(s.start_local)}, {#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.start_local} zone={s.start_zone} />{/if}</dd></div>
  <div><dt class="eyebrow">{END_WORD[s.kind]}</dt>
    <dd class="mt-1 text-base font-medium">{#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}{dayLabel(s.end_local)}, <PlaceTime local={s.end_local} zone={s.end_zone} />{/if}</dd></div>
  {#if s.kind === "hotel" && !untimed(s)}
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
      <p class="mt-2 text-sm"><button type="button" class="underline underline-offset-2 phone:min-h-11" onclick={() => edit(s, "segment-address")}
        aria-label={`Add address to ${headline(s)}`}>Add address</button></p>
    {/if}
  {/if}
  {#if s.links.app || (s.status !== "cancelled" && (s.links.directions || s.links.call))}
    <div class="mt-2 flex flex-wrap gap-2" role="group" aria-label={`Actions for ${headline(s)}`}>
      {#if s.links.app}<Button variant="outline" size="sm" href={s.links.app} target="_blank" rel="noopener noreferrer">{appWord(s, now, isMobile())}</Button>{/if}
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
              <MessageView subject={e.subject} text={e.text} html={e.html} truncated={e.truncated} original={e.original} images={e.images} imagesAt={`/api/segments/${s.id}/emails/${i}/images/`} />
            </div>
          {/each}
        {/if}
      </div>
    {/if}
  {/if}
{/snippet}

{#snippet ports(s: Segment)}
  {#if s.days.length}
    <div class="mt-2 text-sm" data-itinerary>
      <p class="eyebrow">Itinerary</p>
      <ol class="mt-1 flex flex-col gap-2">
        {#each s.days as d (d.day)}
          <li class="flex flex-wrap items-baseline justify-between gap-x-3" data-day={d.day}>
            <span class="break-words"><span class="text-muted-foreground">Day {d.day} · {dayLabel(`${d.date}T00:00`)}</span>{" "}<span class="font-medium">{#if d.sea}Sea day{:else}{d.stops.map((p) => p.name).join(", ")}{/if}</span></span>
            {#if !d.sea}
              <span class="text-muted-foreground">
                {#each d.stops as p, i (i)}
                  {#if i}<br />{/if}
                  {#if p.arrive_local}arrives <PlaceTime local={p.arrive_local} zone={p.zone} />{#if p.depart_local}, leaves <PlaceTime local={p.depart_local} zone={p.zone} />{/if}
                  {:else if p.depart_local}leaves <PlaceTime local={p.depart_local} zone={p.zone} />
                  {:else if p.recorded}In port
                  {:else}Time not recorded{/if}
                {/each}
              </span>
            {/if}
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
    <Button variant="outline" size="sm" aria-label={`Edit ${name}`} onclick={() => edit(s)}>Edit</Button>
    <Button variant="outline" size="sm" aria-label={`Remove ${name}`} onclick={() => { removing = s; asking = true; }}>Remove</Button>
  </div>
{/snippet}

<ConfirmDialog bind:open={asking} title={`Remove ${removing ? headline(removing) : "this booking"}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="It’s deleted from the trip. This can’t be undone."
  onconfirm={async () => { const s = removing; return s ? await remove(s) : true; }} />
