<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { app, layout, route } from "$lib/app.svelte";
  import { tick, untrack } from "svelte";
  import { apiCall } from "$lib/contract";
  import type { LoyaltyEntry, Person, Segment, StoredEmail, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { OptionsMenu } from "$lib/components/ui/options-menu";
  import BookingCard from "$lib/components/BookingCard.svelte";
  import BookingDetailBody from "$lib/components/BookingDetailBody.svelte";
  import { viewport } from "$lib/phone.svelte";
  import PastBookings from "$lib/components/PastBookings.svelte";
  import PastBookingsSheet from "$lib/components/PastBookingsSheet.svelte";
  import ArrivalOpen from "$lib/components/ArrivalOpen.svelte";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import FlightCard from "$lib/components/FlightCard.svelte";
  import GateCode from "$lib/components/GateCode.svelte";
  import { isMobile } from "$lib/platform";
  import { Sheet } from "$lib/components/ui/sheet";
  import { dropDrafts, leave } from "$lib/drafts.svelte";
  import { flightStatus, loadFlightStatus, followFlightStatus, statusFor } from "$lib/flightstatus.svelte";
  import { expiryOf, isSavedCopy, type SavedCopy } from "$lib/offline";
  import { inShell, shellLoad } from "$lib/offline-shell";
  import OfflineTrip from "$lib/components/OfflineTrip.svelte";
  import { askAboutOffline, offline, refreshOffline, saveTripCopy } from "$lib/offline.svelte";
  import { hasSavedTrip, onLock } from "$lib/offline-vault";
  import LoyaltyNumber from "$lib/components/LoyaltyNumber.svelte";
  import MessageView from "$lib/components/MessageView.svelte";
  import OfflineSetup from "$lib/components/OfflineSetup.svelte";
  import PastTrip from "$lib/components/PastTrip.svelte";
  import SavedTripLock from "$lib/components/SavedTripLock.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import RouteReplay from "$lib/components/RouteReplay.svelte";
  import SegmentForm from "$lib/components/SegmentForm.svelte";
  import TripDetails from "$lib/components/TripDetails.svelte";
  import TripDone from "$lib/components/TripDone.svelte";
  import TripPeopleSheet from "$lib/components/TripPeopleSheet.svelte";
  import TripPhotos from "$lib/components/TripPhotos.svelte";
  import TripSummary from "$lib/components/TripSummary.svelte";
  import { countNote, formatMoney, formatTotals } from "$lib/money";
  import { blankFor, draftOf, KINDS, type Draft } from "$lib/segment-form";
  import { appWord, bookingCards, bookingCounts, dateLabel, dayIn, dayLabel, headline, isPast, loyaltyNumbers, nextUp, showBookingTravellers, showTripTravellers, tripPeople, tripTravellers, untimed, vendorLink, viewerZone, type Card } from "$lib/trips";
  import AvatarStack from "$lib/components/AvatarStack.svelte";
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import GitMerge from "@lucide/svelte/icons/git-merge";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import Users from "@lucide/svelte/icons/users";
  import { toast } from "svelte-sonner";

  const staticDemo = import.meta.env.MODE === "demo";

  let { tripId = null, onchanged = null, revision = 0 }: { tripId?: number | null; onchanged?: ((movedTo?: number) => void) | null; revision?: number } = $props();

  let trip = $state<Trip | null>(null);
  let loads = $state(0);
  let photoChanges = $state(0);
  const replace = (next: Trip) => { trip = next; loads++; };
  let people = $state<Person[]>([]);
  let loyalty = $state<LoyaltyEntry[]>([]);
  let loadError = $state("");
  let form = $state<Draft | null>(null);
  let editingTrip = $state(false);
  let focus = $state("");
  let details = $state<{ open: () => Promise<void> } | null>(null);
  let editButton = $state<HTMLElement | null>(null);
  let bookingsOpen = $state(false);
  let peopleOpen = $state(false);
  let expandedId = $state<number | null>(null);
  let removing = $state<Segment | null>(null);
  let asking = $state(false);
  let askOffline = $state(false);
  let lockedCopy = $state(false);
  let savedCopy = $state<Trip | null>(null);
  let savedTrips = $state<Trip[]>([]);
  let shellCopy = $state<SavedCopy | null>(null);
  let deleting = $state(false);
  let others = $state<Trip[]>([]);
  let merging = $state(false);
  let mergeWith = $state("");
  let confirmMergeOpen = $state(false);
  let newlySeeThisTrip = $state<string[]>([]);
  let newlySeeOtherTrip = $state<string[]>([]);
  let moveOpen = $state(false);
  let moving = $state<Segment | null>(null);
  let moveTo = $state("");
  let confirmMoveOpen = $state(false);
  let newlySeeBooking = $state<string[]>([]);
  let newlySeeTrip = $state<string[]>([]);
  const moveChoices = $derived([...others].sort((a, b) => (b.start_date ?? "").localeCompare(a.start_date ?? "") || b.id - a.id));
  const namesOf = (v: unknown): string[] => (Array.isArray(v) ? v.map((p) => String((p as { name?: unknown }).name ?? "")).filter(Boolean) : []);

  const pick = "border-input bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";
  const isTrip = (v: unknown): v is Trip => !!v && typeof v === "object" && Array.isArray((v as Trip).segments) && typeof (v as Trip).name === "string";
  $effect(() => onLock(() => { savedCopy = null; savedTrips = []; }));

  function openSaved(values: unknown) {
    const found = (Array.isArray(values) ? values : []).map((v) => (isSavedCopy(v) ? v.trip : v)).filter(isTrip);
    if (found.length === 0) throw new Error("unreadable");
    savedTrips = found;
    savedCopy = found.find((t) => String(t.id) === id) ?? null;
  }

  async function afterOnlineLoad(t: Trip) {
    if (isPast(t, dayIn(now, viewerZone()))) return;
    await refreshOffline();
    if (offline.setUp) await saveTripCopy(t);
    else if (askAboutOffline()) askOffline = true;
  }

  const unreachable = (err: unknown) => !(err && typeof err === "object" && "status" in err && typeof err.status === "number" && err.status > 0 && ![502, 503, 504].includes(err.status));

  const copyLive = (copy: SavedCopy) => { const expires = expiryOf(copy); return expires === null || Date.now() < expires; };

  function dropExpiredShellCopy(held: SavedCopy) {
    if (shellCopy !== held || copyLive(held)) return;
    shellCopy = null;
    void load();
  }

  $effect(() => {
    const held = shellCopy;
    if (!held) return;
    const expires = expiryOf(held);
    let timer: ReturnType<typeof setTimeout> | null = null;
    const arm = () => {
      if (expires === null) return;
      timer = setTimeout(() => { dropExpiredShellCopy(held); if (shellCopy === held) arm(); }, Math.min(Math.max(0, expires - Date.now()), 2 ** 31 - 1));
    };
    arm();
    const foreground = () => { if (document.visibilityState !== "hidden") dropExpiredShellCopy(held); };
    document.addEventListener("visibilitychange", foreground);
    window.addEventListener("focus", foreground);
    return () => {
      if (timer !== null) clearTimeout(timer);
      document.removeEventListener("visibilitychange", foreground);
      window.removeEventListener("focus", foreground);
    };
  });

  async function offerShellCopy(err: unknown, mine: number): Promise<boolean> {
    if (!inShell() || !unreachable(err)) return false;
    try {
      const found = (await shellLoad()).filter(isSavedCopy).find((c) => String(c.trip.id) === id);
      if (!found || mine !== latest || !copyLive(found)) return false;
      shellCopy = found;
      return true;
    } catch { return false; }
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
  followFlightStatus(() => trip?.segments ?? [], () => app.sessionExpired);

  const id = $derived(tripId === null ? route.sub : String(tripId));

  let latest = 0;
  async function load() {
    const mine = ++latest;
    loadError = "";
    lockedCopy = false;
    shellCopy = null;
    if (!/^\d+$/.test(id)) { trip = null; loadError = "No such trip"; return; }
    try {
      const [t, p, l] = await Promise.all([apiCall<"GET /api/trips/{id}">(`/api/trips/${id}`), apiCall<"GET /api/people">("/api/people"), apiCall<"GET /api/loyalty">("/api/loyalty")]);
      if (mine !== latest) return;
      replace(t); people = p.people; loyalty = l.loyalty;
      void loadFlightStatus();
      void afterOnlineLoad(t);
    } catch (err) {
      if (mine !== latest) return;
      trip = null; loadError = errMsg(err);
      if (await offerShellCopy(err, mine)) { if (mine === latest) loadError = ""; return; }
      await offerSavedCopy();
    }
  }
  let seenRevision = untrack(() => revision);
  $effect(() => { if (revision !== seenRevision) { seenRevision = revision; void load(); } });
  $effect(() => { void id; form = null; editingTrip = false; expandedId = null; bookingsOpen = false; peopleOpen = false; savedCopy = null; savedTrips = []; void load(); });

  const wanted = $derived(new URLSearchParams(route.query).get("segment"));
  let openedWanted = "";
  $effect(() => {
    if (!trip || !wanted) return;
    void cards;
    const found = cards.find((c) => c.segments.some((s) => String(s.id) === wanted));
    if (!found) return;
    const key = `${id}:${wanted}`;
    if (openedWanted === key) return;
    openedWanted = key;
    tick().then(() => document.getElementById(`segment-${found.lead.id}`)?.scrollIntoView?.({ block: "start" }));
    expandedId = found.lead.id;
    if (completedPage && viewport.phone) bookingsOpen = true;
  });

  const done = $derived(trip?.done_at != null);
  const costsShown = $derived(app.state?.show_costs !== false);
  const over = $derived(trip ? isPast(trip, dayIn(now, viewerZone())) : false);
  const completedPage = $derived(over && !staticDemo);
  $effect(() => {
    if (!(trip && tripId === null)) return;
    layout.wide = true;
    return () => { layout.wide = false; };
  });
  const cards = $derived(trip ? bookingCards(trip.segments) : []);
  const toggleCard = (s: Segment) => { expandedId = expandedId === s.id ? null : s.id; };
  const editFromDetail = (s: Segment, field = "") => { bookingsOpen = false; edit(s, field); };
  const moveFromDetail = (s: Segment) => { moving = s; moveTo = ""; moveOpen = true; void loadOthers(); };
  const removeFromDetail = (s: Segment) => { removing = s; asking = true; };
  const liveOn = $derived(flightStatus.list?.enabled === true);
  const upNext = $derived(trip && !completedPage ? nextUp([trip], now) : null);
  const heroSegment = $derived(upNext?.segment ?? null);
  const heroCard = $derived(heroSegment ? (cards.find((c) => c.segments.some((b) => b.id === heroSegment.id)) ?? null) : null);
  const thenCards = $derived(cards.filter((c) => c !== heroCard));
  const counts = $derived(trip ? bookingCounts(trip) : { total: 0, kinds: [], words: "" });
  const everyone = $derived(trip ? tripTravellers(trip.segments) : []);
  const eyebrowOf = (s: Segment) => `${kindName(s)} · ${dayLabel(s.start_local)}`;
  const kindName = (s: Segment) => KINDS.find(([k]) => k === s.kind)?.[1] ?? s.kind;
  const tripOptions = $derived(!trip || form ? [] : [
    { label: "People on this trip", icon: Users, onselect: () => { peopleOpen = true; } },
    { label: "Add a booking", icon: Plus, onselect: () => { focus = ""; form = blankFor(people, app.state?.person_id, trip!.id, trip!.costs.totals[0]?.currency); } },
    { label: "Merge another trip", icon: GitMerge, onselect: () => { mergeWith = ""; merging = true; void loadOthers(); } },
    { label: "Delete trip", icon: Trash2, destructive: true, divided: true, onselect: () => { deleting = true; } },
  ]);
  const dates = (t: Trip) => t.start_date && t.end_date ? (t.start_date === t.end_date ? dateLabel(t.start_date) : `${dateLabel(t.start_date)} – ${dateLabel(t.end_date)}`) : "No dates yet";

  function reveal(node: HTMLElement) {
    const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    node.scrollIntoView?.({ block: "nearest", behavior: calm ? "auto" : "smooth" });
  }

  function revealForm(node: HTMLElement) {
    reveal(node);
    node.querySelector<HTMLElement>("select, input, textarea")?.focus({ preventScroll: true });
  }

  function edit(s: Segment, field = "") {
    leave(() => {
      focus = field;
      form = draftOf(s, trip?.costs.totals[0]?.currency);
    });
  }

  async function saved(s: Segment) {
    form = null;
    toast.success("Saved");
    if (trip && s.trip_id !== trip.id) { dropDrafts(); if (onchanged) onchanged(s.trip_id); else location.hash = `#trip/${s.trip_id}`; return; }
    onchanged?.();
    await load();
  }

  const deleteTrip = () => act(async () => {
    if (!trip) return;
    await apiCall<"DELETE /api/trips/{id}">(`/api/trips/${trip.id}`, { method: "DELETE" });
    toast.success("Trip deleted");
    dropDrafts();
    if (onchanged) onchanged(); else location.hash = "#trips";
  });

  const loadOthers = () => act(async () => {
    others = (await apiCall<"GET /api/trips">("/api/trips")).trips.filter((o) => o.id !== (trip?.id ?? -1))
      .sort((a, b) => (b.start_date ?? "").localeCompare(a.start_date ?? ""));
  });

  const merge = (confirm = false) => act(async () => {
    if (!trip || !mergeWith) return;
    const body = { merge: Number(mergeWith), ...(confirm ? { confirm: true } : {}) };
    try {
      replace(await apiCall<"POST /api/trips/{id}/merge">(`/api/trips/${trip.id}/merge`, { method: "POST", body }));
    } catch (e) {
      const said = e as { status?: number; data?: { see_booking?: unknown; see_trip?: unknown } };
      if (said.status === 409 && Array.isArray(said.data?.see_booking)) {
        newlySeeThisTrip = namesOf(said.data.see_booking);
        newlySeeOtherTrip = namesOf(said.data.see_trip);
        confirmMergeOpen = true;
        return;
      }
      throw e;
    }
    toast.success("Merged");
    onchanged?.();
  });

  const move = (confirm = false) => act(async () => {
    const s = moving;
    if (!s || !moveTo) return;
    const body = { trip_id: moveTo === "new" ? null : Number(moveTo), ...(confirm ? { confirm: true } : {}) };
    let into: Trip;
    try {
      into = await apiCall<"POST /api/segments/{id}/move">(`/api/segments/${s.id}/move`, { method: "POST", body });
    } catch (e) {
      const said = e as { status?: number; data?: { see_booking?: unknown; see_trip?: unknown } };
      if (said.status === 409 && Array.isArray(said.data?.see_booking)) {
        newlySeeBooking = namesOf(said.data.see_booking);
        newlySeeTrip = namesOf(said.data.see_trip);
        confirmMoveOpen = true;
        return;
      }
      throw e;
    }
    toast.success("Moved");
    dropDrafts();
    if (onchanged) onchanged(into.id); else location.hash = `#trip/${into.id}`;
  });

  const remove = (s: Segment) => act(async () => {
    await apiCall<"DELETE /api/segments/{id}">(`/api/segments/${s.id}`, { method: "DELETE" });
    toast.success("Removed");
    onchanged?.();
    if (trip && trip.segments.length === 1 && trip.auto) { dropDrafts(); if (!onchanged) location.hash = "#trips"; return; }
    await load();
  });
</script>

<div>
{#if tripId === null && !trip}
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
          {#if s.price && costsShown}<p class="mt-1 text-sm" class:line-through={s.status === "cancelled"}>{formatMoney(s.price.amount_minor, s.price.currency)}</p>{/if}
        </li>
      {/each}
    </ul>
    {#if costsShown && copy.costs?.totals.length}<p class="mt-3 text-sm" data-trip-total><span class="eyebrow">Total</span> <span class="font-medium">{formatTotals(copy.costs.totals)}</span>{#if countNote(copy.costs)}<span class="text-muted-foreground"> · {countNote(copy.costs)}</span>{/if}</p>{/if}
  {:else if savedTrips.length}
    <div class="mb-6 space-y-2" data-testid="trip-not-saved">
      <h1 class="text-display">This trip isn’t saved on this device</h1>
      <p class="text-muted-foreground">Only trips under way or starting within a week, and your next upcoming trip, are saved. Saved:</p>
      <ul class="flex flex-col gap-1">
        {#each savedTrips as t (t.id)}<li><a class="underline underline-offset-2" href={`#trip/${t.id}`}>{t.name}</a></li>{/each}
      </ul>
    </div>
  {:else}
    <SavedTripLock onunlocked={openSaved} onremoved={() => (lockedCopy = false)} />
  {/if}
{:else if shellCopy}
  <OfflineTrip copy={shellCopy} />
{:else if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if trip === null}
  <div class="h-40 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" role="progressbar" aria-busy="true" aria-label="Loading"></div>
{:else}
  {@const t = trip}
  <ArrivalOpen tripId={t.id} segments={t.segments} {now} />
  {#if completedPage}
    <PastTrip trip={t} {people} {now} dates={dates(t)} {costsShown} {loads} back={tripId === null} options={tripOptions} onpeople={() => (peopleOpen = true)} bind:editing={editingTrip} onsaved={(next) => { replace(next); onchanged?.(); }}
      onbookings={() => (bookingsOpen = true)} bookings={pastBookings} />
    {#if form && form.id === null}
      <div class="mt-6 mb-6" use:reveal><SegmentForm initial={form} {people} {focus} oncancel={() => (form = null)} onsaved={saved} /></div>
    {/if}
  {:else}
  <div class="@container">
  <div class="flex items-center justify-between gap-3">
    {#if tripId === null}
      <a class="-ml-1 inline-flex min-h-11 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground" href="#trips"><ArrowLeft class="size-4" aria-hidden="true" /> Trips</a>
    {:else}
      <span></span>
    {/if}
    <div class="flex items-center">
      {#if !editingTrip}<Button bind:ref={editButton} variant="ghost" size="icon" aria-label="Edit trip details" onclick={() => void details?.open()}><Pencil /></Button>{/if}
      {#if tripOptions.length}<OptionsMenu popup iconOnly variant="ghost" label="Trip options" text="Trip options" icon={Ellipsis} items={tripOptions} />{/if}
    </div>
  </div>

  <TripDetails bind:this={details} bind:editing={editingTrip} trip={t} dates={dates(t)} onsaved={(next) => { replace(next); onchanged?.(); }} bare returnFocus={() => editButton} />
  {#if editingTrip}
    <h1 class="sr-only">{t.name}</h1>
  {:else}
    <div class="mt-1 flex items-start justify-between gap-4">
      <div class="min-w-0">
        <h1 class="break-words text-display @[52rem]:text-display-lg">{t.name}</h1>
        <p class="mt-1 min-w-0 break-words text-muted-foreground">{dates(t)}{t.destination ? ` · ${t.destination}` : ""}</p>
        <TripSummary tripId={t.id} revision={`${loads}.${photoChanges}`} />
      </div>
      {#if showTripTravellers(everyone, app.state?.person_id ?? null)}
        <button type="button" class="mt-0.5 inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-full outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" data-trip-travellers
          aria-label={`People on this trip: ${tripPeople(t).map((p) => p.name).join(", ")}`} onclick={() => (peopleOpen = true)}><AvatarStack people={tripPeople(t)} neutral /></button>
      {/if}
    </div>
  {/if}
  {#if costsShown && t.costs.totals.length}
    <p class="mt-2 text-sm" data-trip-total><span class="eyebrow">Total</span> <span class="break-words font-medium">{formatTotals(t.costs.totals)}</span>
      {#if countNote(t.costs)}<span class="text-muted-foreground"> · {countNote(t.costs)}</span>{/if}</p>
  {/if}
  {#if t.notes && !editingTrip}<p class="mt-2 whitespace-pre-line break-words text-sm">{t.notes}</p>{/if}

  {#if form && form.id === null}
    <div class="mt-6" use:revealForm><SegmentForm initial={form} {people} {focus} oncancel={() => (form = null)} onsaved={saved} /></div>
  {/if}

  {#if t.segments.length === 0}
    <p class="mt-6 text-muted-foreground">Nothing booked on this trip yet.</p>
  {/if}
  <div data-testid="trip-bookings" class={`mt-6 grid gap-8 ${heroCard ? "@[52rem]:grid-cols-2 @[52rem]:items-start" : ""}`}>
    {#if heroCard}
      {@const s = heroSegment ?? heroCard.lead}
      <section class="min-w-0" aria-labelledby="next-up-title">
        <h2 id="next-up-title" class="eyebrow sr-only mb-3 @[52rem]:not-sr-only">Next up</h2>
        <ul class="flex flex-col gap-3" aria-label="Next up">
          {#if s.kind === "flight"}
            <li id={`segment-${heroCard.lead.id}`} class="scroll-mt-20" data-flight-card>
              <FlightCard segment={s} status={liveOn ? statusFor(s.id) : undefined} {liveOn} {now} online={typeof navigator === "undefined" || navigator.onLine !== false} highlight={wanted === String(s.id)} paused={liveOn ? flightStatus.list?.paused : null} href={`#trip/${t.id}/flight/${s.id}`} travellers={showBookingTravellers(s, everyone)} tripSegments={t.segments} statusOf={statusFor} ondetail={() => toggleCard(heroCard.lead)} detailOpen={expandedId === heroCard.lead.id} detailId={`booking-detail-${heroCard.lead.id}`}>
                {#snippet detail()}{@render cardDetail(heroCard)}{/snippet}
              </FlightCard>
            </li>
          {:else}
            <BookingCard card={heroCard} {now} id={`segment-${heroCard.lead.id}`} highlight={wanted === String(heroCard.lead.id)} expanded={expandedId === heroCard.lead.id} ontoggle={toggleCard}>
              {#snippet detail()}{@render cardDetail(heroCard)}{/snippet}
            </BookingCard>
          {/if}
        </ul>
      </section>
    {/if}
    <section class="min-w-0" aria-label="Then">
      {#if heroCard && thenCards.length}<h2 class="eyebrow mb-3">Then</h2>{/if}
      {#if thenCards.length}
        <ul class="flex flex-col gap-3" aria-label="Bookings">
          {#each thenCards as card (card.id)}
            <BookingCard {card} {now} id={`segment-${card.lead.id}`} highlight={wanted === String(card.lead.id)} expanded={expandedId === card.lead.id} ontoggle={toggleCard}>
              {#snippet detail()}{@render cardDetail(card)}{/snippet}
            </BookingCard>
          {/each}
        </ul>
      {/if}
      {#if !form}
        <p class="mt-4 flex flex-wrap items-center justify-between gap-x-3 text-sm text-muted-foreground" data-trip-footer>
          <span>{counts.total === 0 ? "No bookings" : `${counts.total} ${counts.total === 1 ? "booking" : "bookings"}`}</span>
          <Button variant="link" class="min-h-11 px-0 text-muted-foreground" onclick={() => { focus = ""; form = blankFor(people, app.state?.person_id, t.id, t.costs.totals[0]?.currency); }}>Add booking</Button>
        </p>
      {/if}
    </section>
  </div>

  <div class="mt-8 flex flex-col gap-6">
    <RouteReplay trip={t} {now} />
    <TripPhotos onchanged={() => photoChanges++} trip={t} {people} {now} />
  </div>
  </div>
  {/if}

  <TripDone trip={t} ondone={() => { onchanged?.(); void load(); }} />
{/if}
</div>

{#if trip}
  <TripPeopleSheet bind:open={peopleOpen} {trip} {people} me={app.state?.person_id ?? null} onsaved={(next) => { replace(next); onchanged?.(); }} onguest={(guest) => (people = [...people, guest])} />
{/if}

<PastBookingsSheet bind:open={bookingsOpen} segments={trip?.segments ?? []} expanded={expandedId} ontoggle={toggleCard}>
  {#snippet detail(card)}{@render cardDetail(card)}{/snippet}
</PastBookingsSheet>

{#snippet cardDetail(card: Card)}
  <BookingDetailBody {card} {everyone} canChange={!done} inline withTimes={!completedPage} onedit={editFromDetail} onmove={moveFromDetail} onremove={removeFromDetail}>
    {#snippet above()}{@render detailActions(card)}{/snippet}
    {#snippet below()}{@render detailMore(card)}{/snippet}
  </BookingDetailBody>
{/snippet}

{#snippet pastBookings()}
  {#if trip}
    {@const counts = bookingCounts(trip)}
    {#if counts.total > 0}
      <section class="flex flex-col gap-2.5" aria-labelledby="past-bookings-title">
        <div class="flex items-baseline justify-between gap-3">
          <h2 id="past-bookings-title" class="text-[17px] leading-snug font-semibold tracking-tight">Bookings · {counts.total}</h2>
          <span class="text-caption text-muted-foreground">{counts.words}</span>
        </div>
        <PastBookings segments={trip.segments} grouped={false} expanded={expandedId} ontoggle={toggleCard}>
          {#snippet detail(card)}{@render cardDetail(card)}{/snippet}
        </PastBookings>
      </section>
    {/if}
  {/if}
{/snippet}

<OfflineSetup bind:open={askOffline} onenabled={() => trip && void saveTripCopy(trip)} />

<Sheet bind:open={() => form !== null && form.id !== null, (v) => { if (!v) form = null; }} title="Edit this booking">
  {#if form && form.id !== null}
    <SegmentForm initial={form} {people} {focus} titled={false} oncancel={() => (form = null)} onsaved={saved} />
  {/if}
</Sheet>

{#snippet actionRow(s: Segment, tone: "action" | "outline" = "action", name = headline(s))}
  {@const vendor = vendorLink(s, isMobile())}
  {@const live = s.kind === "flight" && s.status !== "cancelled" && !untimed(s) && !over}
  {#if (!over || staticDemo) && (live || s.links.app || vendor || (s.status !== "cancelled" && (s.links.directions || s.links.call)) || s.has_email || s.gate_code)}
    <div class="mt-2 flex flex-wrap gap-2" role="group" aria-label={`Actions for ${name}`}>
      {#if live}<Button variant="outline" size="sm" href={`#trip/${s.trip_id}/flight/${s.id}`}>Live status</Button>{/if}
      {#if s.links.app}<Button variant={tone} size="sm" href={s.links.app} target="_blank" rel="noopener noreferrer">{appWord(s, now, isMobile())}</Button>
      {:else if vendor}<Button variant={tone} size="sm" href={vendor.href}>{vendor.label}</Button>{/if}
      {#if s.status !== "cancelled" && s.links.directions}<Button variant="outline" size="sm" href={s.links.directions} target="_blank" rel="noopener noreferrer">Directions</Button>{/if}
      {#if s.status !== "cancelled" && s.links.call}<Button variant="outline" size="sm" href={s.links.call}>Call</Button>{/if}
      <GateCode segment={s} {now} onchanged={() => void load()} />
      {#if s.has_email}
        {@const mail = mails[s.id]}
        <Button variant="outline" size="sm" aria-expanded={!!mail} aria-label={`${mail ? "Hide" : "View"} email for ${name}`} onclick={() => toggleMail(s)}>{mail ? "Hide email" : "View email"}</Button>
      {/if}
    </div>
  {/if}
  {#if (!over || staticDemo) && s.has_email}
    {@const mail = mails[s.id]}
    {#if mail}
      <div class="mt-2 space-y-4" role="region" aria-label={`The email for ${name}`}>
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

{#snippet detailActions(card: Card)}
  {#if card && !completedPage}
    {#if card.timesDiffer}<p class="text-sm font-medium" data-times-differ><Badge variant="secondary">Times differ between bookings</Badge> <span class="text-muted-foreground">Each booking’s times are listed here.</span></p>{/if}
    {#each card.segments as s (s.id)}
      {#if (s.kind === "hotel" || s.kind === "cruise" || s.kind === "parking") && !s.details.address && s.status !== "cancelled" && !over}
        <p class="text-sm"><button type="button" class="underline underline-offset-2 phone:min-h-11" onclick={() => editFromDetail(s, "segment-address")} aria-label={`Add address to ${headline(s)}`}>Add address</button></p>
      {/if}
      {@const several = card.segments.length > 1}
      {@const label = several && s.confirmation ? `${headline(s)} booking ${s.confirmation}` : headline(s)}
      {#if several}<p class="eyebrow" data-booking-actions>Booking {s.confirmation ?? "without a code"}</p>{/if}
      {@render actionRow(s, "outline", label)}
    {/each}
  {/if}
{/snippet}

{#snippet detailMore(card: Card)}
  {#if card}
    {#each card.segments as s (s.id)}
      {@render ports(s)}
      {#if !over}{@render membershipList(s)}{/if}
    {/each}
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
                  {#if p.arrive_local}arrives <PlaceTime local={p.arrive_local} />{#if p.depart_local}, leaves <PlaceTime local={p.depart_local} />{/if}
                  {:else if p.depart_local}leaves <PlaceTime local={p.depart_local} />
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

{#snippet membershipList(s: Segment)}
  {@const numbers = loyaltyNumbers(s, loyalty)}
  {#if numbers.length}
    <h3 class="eyebrow">Loyalty</h3>
    <ul class="flex flex-col gap-1" data-membership>
      {#each numbers as entry (entry.id)}
        <li class="text-sm text-muted-foreground">{entry.program} <LoyaltyNumber {entry} /></li>
      {/each}
    </ul>
  {/if}
{/snippet}

<ConfirmDialog bind:open={deleting} title={`Delete ${trip?.name ?? "this trip"}?`} confirmLabel="Delete trip" busyLabel="Deleting…" destructive
  description={trip ? `${trip.segments.length === 0 ? "It has no bookings." : trip.segments.length === 1 ? "Its 1 booking is removed too." : `Its ${trip.segments.length} bookings are removed too.`} This can’t be undone.` : ""}
  onconfirm={async () => await deleteTrip()} />

<ConfirmDialog bind:open={merging} title="Merge another trip into this one" confirmLabel="Merge" busyLabel="Merging…" disabled={!mergeWith}
  onconfirm={async () => await merge()}>
  {#snippet description()}
    <p>Its bookings move here and that trip goes away.</p>
    <label class="flex flex-col gap-1.5 text-foreground"><span class="font-medium">Trip to merge in</span>
      <select bind:value={mergeWith} class={pick}>
        <option value="">Choose a trip</option>
        {#each others as o (o.id)}<option value={String(o.id)}>{o.name} · {dates(o)}</option>{/each}
      </select></label>
  {/snippet}
</ConfirmDialog>

<ConfirmDialog bind:open={confirmMergeOpen} title="Merge them anyway?" confirmLabel="Merge anyway" busyLabel="Merging…"
  onconfirm={async () => await merge(true)}>
  {#snippet description()}
    <p>These trips involve different people, so merging them changes who sees what.</p>
    {#if newlySeeThisTrip.length}<p><strong class="text-foreground">Will newly see this trip’s bookings:</strong> {newlySeeThisTrip.join(", ")}</p>{/if}
    {#if newlySeeOtherTrip.length}<p><strong class="text-foreground">Will newly see the other trip’s bookings:</strong> {newlySeeOtherTrip.join(", ")}</p>{/if}
  {/snippet}
</ConfirmDialog>

<ConfirmDialog bind:open={moveOpen} title={`Move ${moving ? headline(moving) : "this booking"}`} confirmLabel="Move" busyLabel="Moving…" disabled={!moveTo}
  onconfirm={async () => await move()}>
  {#snippet description()}
    <label class="flex flex-col gap-1.5 text-foreground"><span class="font-medium">Move it to</span>
      <select bind:value={moveTo} class={pick}>
        <option value="">Choose a trip</option>
        {#if (trip?.segments.length ?? 0) > 1}<option value="new">A new trip of its own</option>{/if}
        {#each moveChoices as o (o.id)}<option value={String(o.id)}>{o.name} · {dates(o)}</option>{/each}
      </select></label>
  {/snippet}
</ConfirmDialog>

<ConfirmDialog bind:open={confirmMoveOpen} title="Move it anyway?" confirmLabel="Move anyway" busyLabel="Moving…"
  onconfirm={async () => await move(true)}>
  {#snippet description()}
    <p>That trip involves different people, so this changes who sees what.</p>
    {#if newlySeeBooking.length}<p><strong class="text-foreground">Will newly see this booking:</strong> {newlySeeBooking.join(", ")}</p>{/if}
    {#if newlySeeTrip.length}<p><strong class="text-foreground">Will newly see that trip:</strong> {newlySeeTrip.join(", ")}</p>{/if}
  {/snippet}
</ConfirmDialog>

<ConfirmDialog bind:open={asking} title={`Remove ${removing ? headline(removing) : "this booking"}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="It’s deleted from the trip. This can’t be undone."
  onconfirm={async () => { const s = removing; return s ? await remove(s) : true; }} />
