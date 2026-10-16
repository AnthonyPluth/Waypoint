<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { app, refreshState } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { MailboxList, Person, Segment, Trip, TripPlaces } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import DayTime from "$lib/components/DayTime.svelte";
  import GateCode from "$lib/components/GateCode.svelte";
  import { takeEarlyTrips } from "$lib/early";
  import { flightStatus, loadFlightStatus, statusFor } from "$lib/flightstatus.svelte";
  import OfflineStatus from "$lib/components/OfflineStatus.svelte";
  import PassCard from "$lib/components/PassCard.svelte";
  import RouteMapCard from "$lib/components/RouteMapCard.svelte";
  import { NO_ROADS, stopsOf } from "$lib/route-replay";
  import { dateTile, usablePlaces, laterLine, laterTrips, startsIn, tripTotals } from "$lib/side-column";
  import { type Day, type DayItem, dayIn, dayLabel, dayParts, END_WORD, endAt, featuredTrip, flightEvidence, headline, nextUp, nightsLabel, rangeLabel, startAt, subline, timesDiffer, todayLabel, tripDays, untimed, upcomingTitle, viewerZone } from "$lib/trips";
  import KindTile from "$lib/components/KindTile.svelte";
  import { offlineWorking } from "$lib/offline.svelte";
  import { viewport } from "$lib/phone.svelte";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Sheet } from "$lib/components/ui/sheet";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Inbox from "@lucide/svelte/icons/inbox";
  import Plus from "@lucide/svelte/icons/plus";
  import PlaneTakeoff from "@lucide/svelte/icons/plane-takeoff";
  import { toast } from "svelte-sonner";

  let trips = $state<Trip[] | null>(null);
  let loadError = $state("");
  let now = $state(Date.now());
  let guests = $state<Person[]>([]);
  let claiming = $state<Person | null>(null);
  let asking = $state(false);
  let mail = $state<MailboxList | null>(null);
  let connecting = $state(false);
  let offlineOpen = $state(false);
  let detail = $state<{ segment: Segment; bookings: Segment[] } | null>(null);

  function openDetail(e: MouseEvent, segment: Segment, bookings: Segment[]) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    detail = { segment, bookings };
  }

  async function load() {
    loadError = "";
    try {
      const early = takeEarlyTrips("upcoming");
      const loaded = (await (early ?? apiCall<"GET /api/trips">("/api/trips"))).trips;
      if (!early) void loadFlightStatus();
      guests = loaded.length ? [] : (await apiCall<"GET /api/people/claim-suggestions">("/api/people/claim-suggestions")).guests;
      if (!loaded.length) await loadMail();
      trips = loaded;
    } catch (err) { trips = null; guests = []; loadError = errMsg(err); }
  }
  async function loadMail() {
    try {
      const found = await apiCall<"GET /api/mailboxes">("/api/mailboxes");
      mail = Array.isArray(found?.mailboxes) ? found : null;
    }
    catch { return; }
  }
  $effect(() => {
    void load();
    const tick = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(tick);
  });
  $effect(() => {
    if (!mail?.mailboxes.some((m) => m.scanning)) return;
    const poll = setInterval(() => { void loadMail(); void refreshState(true); }, 5_000);
    return () => clearInterval(poll);
  });

  let wasScanning = false;
  $effect(() => {
    const isScanning = scanning;
    if (wasScanning && !isScanning) void load();
    wasScanning = isScanning;
  });

  const connect = () => act(async () => {
    const r = await apiCall<"POST /api/mailboxes/connect">("/api/mailboxes/connect", { method: "POST" });
    location.href = r.url;
  }, { busy: (on) => (connecting = on) });

  const claim = (g: Person) => act(async () => {
    await apiCall<"POST /api/people/{id}/claim">(`/api/people/${g.id}/claim`, { method: "POST" });
    toast.success(`Linked ${g.display_name} to you`);
    await load();
  });
  const noneOfThese = () => act(async () => {
    await apiCall<"POST /api/people/claim-suggestions/dismiss">("/api/people/claim-suggestions/dismiss", { method: "POST" });
    guests = [];
  });

  const today = $derived(dayIn(now, viewerZone()));
  const next = $derived(trips ? nextUp(trips, now) : null);
  const featured = $derived(trips ? featuredTrip(trips, next, today) : null);
  const days = $derived(featured ? tripDays(featured) : []);
  const featuredId = $derived(featured?.id ?? null);
  const later = $derived(trips && featured ? laterTrips(trips, featured, today) : []);
  let places = $state<TripPlaces | null>(null);
  const stops = $derived(featured && places ? stopsOf(featured, places) : []);
  const totals = $derived(featured ? tripTotals(featured, places) : null);
  let placesRequest = 0;
  $effect(() => {
    const mine = ++placesRequest;
    const id = featuredId;
    places = null;
    if (id === null || viewport.phone) return;
    apiCall<"GET /api/trips/{id}/places">(`/api/trips/${id}/places`).then(
      (found) => { if (mine === placesRequest && usablePlaces(found)) places = found; },
      () => { if (mine === placesRequest) places = null; },
    );
  });
  const happened = (i: DayItem) => dayIn(i.role === "end" ? endAt(i.segment) : startAt(i.segment), viewerZone()) < today;
  const firstAhead = $derived(days.findIndex((d) => !d.items.every(happened)));
  const earlier = $derived(firstAhead < 0 ? days : days.slice(0, firstAhead));
  const earlierDates = $derived(new Set(earlier.map((d) => d.date)));
  const ahead = $derived(firstAhead < 0 ? [] : days.slice(firstAhead));
  const nextId = $derived(next?.segment.id ?? null);
  const waiting = $derived(app.state?.review_count ?? 0);
  const boxes = $derived(mail?.mailboxes ?? []);
  const scanning = $derived(boxes.some((m) => m.scanning));
  const broken = $derived(boxes.find((m) => m.status !== "connected"));
  const canConnect = $derived(!!mail?.configured && (boxes.length === 0 || !!broken));
  const setup = $derived(
    waiting > 0 ? { id: "review", title: `${waiting} ${waiting === 1 ? "email is" : "emails are"} waiting for your review`, text: "Waypoint found what look like bookings but needs you to check them before adding them to a trip." }
    : scanning ? { id: "scanning", title: "Scanning your mailbox", text: "Waypoint is reading your confirmation emails now. Trips appear here as soon as it finds them." }
    : broken ? { id: "reconnect", title: "Reconnect Gmail", text: "Waypoint can’t read your mailbox right now, so no trips can be found in it." }
    : canConnect ? { id: "connect", title: "Connect Gmail", text: "Waypoint reads your confirmation emails privately, on this server, and adds the trips it finds." }
    : { id: "manual", title: "No trips yet", text: "Add your first booking by hand: a flight, a stay, a rental car." });
</script>

{#snippet dayBlock(day: Day)}
  {@const parts = dayParts(day.date)}
  {@const isToday = day.date === today}
  <li class="grid grid-cols-[64px_minmax(0,1fr)] items-start gap-4 phone:block">
    <h3 class="eyebrow mb-2 sr-only phone:not-sr-only">{dayLabel(`${day.date}T00:00`)}{isToday ? " · Today" : ""}</h3>
    <div class="flex flex-col items-center pt-3 text-center phone:hidden" aria-hidden="true">
      <span class="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{parts.weekday}</span>
      <span class="text-3xl font-bold leading-none" class:text-primary={isToday}>{parts.day}</span>
      <span class="text-xs text-muted-foreground">{parts.month}</span>
      {#if isToday}<span class="mt-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-primary">Today</span>{/if}
    </div>
    <ul class="divide-y divide-border overflow-hidden rounded-[18px] border border-border bg-surface-1">
      {#each day.items as item (`${item.segment.id}-${item.role}`)}
        {@const seg = item.segment}
        {@const startCollapsed = earlierDates.has(seg.start_local.slice(0, 10))}
        {@const isNext = seg.id === nextId && (item.role === "start" ? !startCollapsed : startCollapsed)}
        <li class={`row-tap flex items-center gap-3 px-4 py-3 phone:items-start ${isNext ? "bg-primary/10" : ""}`} class:opacity-60={seg.status === "cancelled"} data-next={isNext ? "true" : undefined}>
          <p class="mono w-[72px] shrink-0 text-sm font-medium order-first phone:order-last phone:w-auto phone:pt-0.5 phone:text-right">
            <DayTime segment={seg} end={item.role === "end"} />
          </p>
          {#if seg.logo}
            <BrandLogo src={seg.logo} label={seg.logo_label} size={viewport.phone ? 34 : 36} class="mt-0.5" />
          {:else}
            <KindTile kind={seg.kind} size={viewport.phone ? 34 : 36} decorative />
          {/if}
          <div class="min-w-0 flex-1">
            <p class="break-words text-body font-medium" class:line-through={seg.status === "cancelled"}>
              <a class="row-tap-link underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${seg.trip_id}?segment=${seg.id}`}
              title={upcomingTitle(seg) === headline(seg) ? undefined : headline(seg)} onclick={(e) => openDetail(e, seg, item.bookings)}>{item.role === "end" ? `${END_WORD[seg.kind]}: ${upcomingTitle(seg)}` : upcomingTitle(seg)}</a></p>
            {#if item.role === "start" && subline(seg, true)}<p class="break-words text-caption text-muted-foreground">{subline(seg, true)}</p>{/if}
            {#if item.role === "start" && item.bookings.length > 1}<p class="text-caption text-muted-foreground">{item.bookings.length} bookings{timesDiffer(item.bookings) ? " · times differ between bookings" : ""}</p>{/if}
            {#if isNext && viewport.phone}<span class="mt-1 inline-block rounded-full bg-primary px-2.5 py-0.5 text-xs font-semibold text-primary-foreground" data-testid="next-up-pill">Next up</span>{/if}
          </div>
          {#if isNext && !viewport.phone}
            <span class="shrink-0 self-center rounded-full bg-primary px-2.5 py-0.5 text-xs font-semibold text-primary-foreground" data-testid="next-up-pill">Next up</span>
          {:else if !isNext}
            <ChevronRight class="size-4 shrink-0 self-center text-muted-foreground phone:hidden" aria-hidden="true" />
          {/if}
        </li>
      {/each}
    </ul>
  </li>
{/snippet}

<div class="mb-4 flex items-end justify-between gap-3 md:mb-6">
  <div class="min-w-0">
    <p class="eyebrow mb-1" data-testid="today-eyebrow">{todayLabel(now, viewerZone(), viewport.phone)}</p>
    <h1 class="text-title md:text-display">Upcoming</h1>
  </div>
  {#if trips && trips.length > 0}
    <div class="flex shrink-0 items-center gap-2">
      <OfflineStatus pill open={offlineOpen} ontoggle={() => (offlineOpen = !offlineOpen)} />
      <Button href="#trips?add=booking" class="phone:size-11 phone:p-0"><Plus aria-hidden="true" /><span class="phone:sr-only">Add a booking</span></Button>
    </div>
  {/if}
</div>

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if trips === null}
  <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading"></div>
{:else if trips.length === 0}
  {#if guests.length}
    <section class="rows mb-6" aria-labelledby="claim-title">
      <div class="row items-stretch">
        <div class="flex w-full flex-col gap-3">
          <h2 id="claim-title" class="text-heading">Are you one of these?</h2>
          <p class="text-body text-muted-foreground">Bookings were already made for someone with your name. If it’s you, their trips become yours.</p>
          <ul class="flex flex-col gap-2" aria-label="Guests that match your name">
            {#each guests as g (g.id)}
              <li class="flex flex-wrap items-center justify-between gap-2">
                <span class="min-w-0 break-words font-medium">{g.display_name}</span>
                <Button size="sm" aria-label={`This is me: ${g.display_name}`} onclick={() => { claiming = g; asking = true; }}>This is me</Button>
              </li>
            {/each}
          </ul>
          <div><Button variant="outline" size="sm" onclick={noneOfThese}>None of these</Button></div>
        </div>
      </div>
    </section>
  {/if}
  <section class="pass" aria-labelledby="empty-title">
    <div class="flex flex-col items-start gap-4 p-6 md:p-8">
      <span class="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary"><PlaneTakeoff class="size-6" aria-hidden="true" /></span>
      <div class="space-y-1.5">
        <p class="eyebrow">Get started</p>
        <h2 id="empty-title" class="text-title" data-state={setup.id}>{setup.title}</h2>
        <p class="max-w-prose text-body text-muted-foreground">{setup.text}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        {#if setup.id === "review"}<Button href="#review">Review {waiting === 1 ? "the email" : `${waiting} emails`}</Button>{/if}
        {#if setup.id === "connect" || setup.id === "reconnect"}<Button disabled={connecting} onclick={connect}>{connecting ? "Opening Google…" : setup.id === "reconnect" ? "Reconnect Gmail" : "Connect Gmail"}</Button>{/if}
        <Button href="#trips?add=booking" variant={setup.id === "manual" ? "default" : "outline"}>Add a booking</Button>
      </div>
      <details class="w-full text-body">
        <summary class="inline-flex min-h-11 cursor-pointer items-center font-medium underline-offset-2 hover:underline">Setup checklist (optional)</summary>
        <ul class="mt-2 flex list-disc flex-col gap-1 pl-5 text-muted-foreground" aria-label="Setup checklist">
          <li><a class="underline underline-offset-2" href="#people">Add the people who travel with you</a></li>
          <li><a class="underline underline-offset-2" href="#trips?add=booking">Add your first booking</a></li>
          <li><a class="underline underline-offset-2" href="#settings/offline">Save your upcoming trips for offline use</a></li>
        </ul>
      </details>
    </div>
  </section>
{:else}
  {#if waiting > 0}
    {#if viewport.phone}
      <a href="#review" class="mb-4 flex min-h-[52px] items-center gap-3 rounded-2xl border border-signal/22 bg-signal-soft px-4 text-sm" data-testid="review-banner">
        <Inbox class="size-5 shrink-0 text-signal" aria-hidden="true" />
        <span class="min-w-0 flex-1 font-semibold">{waiting} {waiting === 1 ? "email" : "emails"} to review</span>
        <span class="flex items-center gap-1 font-semibold text-signal-ink">Review<ChevronRight class="size-4" aria-hidden="true" /></span>
      </a>
    {:else}
      <section class="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-signal/22 bg-signal-soft px-4 py-3 text-sm" aria-label="Emails to review" data-testid="review-banner">
        <Inbox class="size-5 shrink-0 text-signal" aria-hidden="true" />
        <p class="min-w-0 flex-1"><strong class="font-semibold">{waiting} {waiting === 1 ? "email" : "emails"} to review.</strong> Waypoint found what look like bookings and needs you to check them.</p>
        <Button href="#review" class="bg-signal text-signal-foreground hover:bg-signal/90">Review emails</Button>
      </section>
    {/if}
  {/if}
  {#if !offlineWorking() || offlineOpen}<div class="-mt-1 mb-6"><OfflineStatus /></div>{/if}
  {#if next}
    {@const s = next.segment}
    {@const proof = s.kind === "flight" && flightStatus.list?.enabled ? flightEvidence(statusFor(s.id), now, typeof navigator === "undefined" || navigator.onLine !== false) : "scheduled"}
    {@const grounded = proof === "landed" || proof === "cancelled" || proof === "diverted"}
    {@const eyebrow = next.state !== "now" ? "Next up" : s.kind !== "flight" ? "Under way" : grounded ? "Latest flight" : proof === "departed" ? "In the air" : proof === "delayed" ? "Delayed" : "Under way"}
    <PassCard segment={s} bookings={next.bookings} {now} level={2} class="mb-6" condensed boarding tripName={next.trip.name} showApp={!(s.links.directions || s.links.call)} {eyebrow} pulse={next.state === "now" && !grounded}>
      {#snippet live()}{#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}{/snippet}
      {#snippet footer()}<span class="contents">
        {#if s.status !== "cancelled" && s.links.directions}<Button href={s.links.directions} target="_blank" rel="noopener noreferrer" variant="outline" size="sm" class="phone:hidden">Directions</Button>{/if}
        {#if s.status !== "cancelled" && s.links.call}<Button href={s.links.call} variant="outline" size="sm" class="phone:hidden">Call</Button>{/if}
        <GateCode segment={s} {now} onchanged={load} /><Button href={`#trip/${s.trip_id}?segment=${s.id}`} variant="outline" size="sm" class="phone:flex-1">Open trip<span class="sr-only">: {next.trip.name}</span></Button></span>{/snippet}
    </PassCard>
    {#if next.alongside.length}
      <section class="-mt-2 mb-6" aria-label="Also under way">
        <p class="eyebrow mb-2">Also under way</p>
        <ul class="divide-y divide-border overflow-hidden rounded-[18px] border border-border bg-surface-1">
          {#each next.alongside as item (item.segment.id)}
            {@const seg = item.segment}
            <li class="row-tap flex items-center gap-3 px-4 py-3 phone:items-start">
              {#if seg.logo}<BrandLogo src={seg.logo} label={seg.logo_label} size={viewport.phone ? 34 : 36} class="mt-0.5" />{:else}<KindTile kind={seg.kind} size={viewport.phone ? 34 : 36} decorative />{/if}
              <div class="min-w-0 flex-1">
                <p class="break-words text-body font-medium"><a class="row-tap-link underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${seg.trip_id}?segment=${seg.id}`} onclick={(e) => openDetail(e, seg, item.bookings)}>{upcomingTitle(seg)}</a></p>
                <p class="text-caption text-muted-foreground">{END_WORD[seg.kind]} <DayTime segment={seg} end dated /></p>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {:else}
    <p class="mb-8 text-muted-foreground">Nothing coming up: every trip you can see is over. <a class="underline" href="#trips">See your trips</a>.</p>
  {/if}

  {#if featured}
    <div class="@container">
      <div class="grid gap-6 @[900px]:grid-cols-[minmax(0,1fr)_340px] @[900px]:items-start">
        <div class="min-w-0">
        <div class="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 class="text-title"><a class="inline-flex items-center phone:min-h-11 underline-offset-2 hover:underline" href={`#trip/${featured.id}`}>{featured.name}</a></h2>
          {#if featured.start_date && featured.end_date}<p class="text-caption text-muted-foreground">{rangeLabel(featured.start_date, featured.end_date)}{nightsLabel(featured.start_date, featured.end_date) ? ` · ${nightsLabel(featured.start_date, featured.end_date)}` : ""}</p>{/if}
        </div>
        <ol class="flex flex-col gap-6" aria-label={`${featured.name}, day by day`}>
          {#if earlier.length}
            <li>
              <details class="group">
                <summary class="inline-flex min-h-11 cursor-pointer items-center rounded-md font-medium text-muted-foreground underline-offset-2 hover:underline focus-visible:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">Earlier in this trip · {earlier.length} {earlier.length === 1 ? "day" : "days"}</summary>
                <ol class="mt-3 flex flex-col gap-6" aria-label={`${featured.name}, earlier days`}>
                  {#each earlier as day (day.date)}
                    {@render dayBlock(day)}
                  {/each}
                </ol>
              </details>
            </li>
          {/if}
          {#each ahead as day (day.date)}
            {@render dayBlock(day)}
          {/each}
        </ol>
        </div>
        <aside class="flex min-w-0 flex-col gap-4" aria-label="Trip summary" data-testid="side-column">
          {#if !viewport.phone}
            {#if stops.length >= 2}<RouteMapCard tripId={featured.id} {stops} roads={places?.roads ?? NO_ROADS} />{/if}
            {#if totals}
              <dl class="grid grid-cols-3 divide-x divide-border overflow-hidden rounded-[18px] border border-border bg-surface-1 text-center" data-testid="trip-totals">
                <div class="flex flex-col-reverse px-2 py-3"><dt class="eyebrow">{totals.nights === 1 ? "Night" : "Nights"}</dt><dd class="text-title">{totals.nights}</dd></div>
                <div class="flex flex-col-reverse px-2 py-3"><dt class="eyebrow">{totals.bookings === 1 ? "Booking" : "Bookings"}</dt><dd class="text-title">{totals.bookings}</dd></div>
                <div class="flex flex-col-reverse px-2 py-3"><dt class="eyebrow">{totals.cities === 1 ? "City" : "Cities"}</dt><dd class="text-title">{totals.cities}</dd></div>
              </dl>
            {/if}
          {/if}
          {#if later.length}
            {#if viewport.phone}
              <section aria-label="Later">
                <h2 class="eyebrow mb-2">Later</h2>
                <ul class="grid grid-cols-2 gap-3">
                  {#each later as t (t.id)}
                    {@const tile = dateTile(t)}
                    <li class="row-tap rounded-[18px] border border-border bg-surface-1 p-3">
                      <p class="text-[11px] font-semibold uppercase tracking-[0.12em] text-signal">{tile.month} {tile.day}</p>
                      <p class="break-words text-body font-medium"><a class="row-tap-link underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${t.id}`}>{t.name}</a></p>
                      <p class="text-caption text-muted-foreground">{startsIn(t, today)}</p>
                    </li>
                  {/each}
                </ul>
              </section>
            {:else}
              <section class="overflow-hidden rounded-[18px] border border-border bg-surface-1" aria-label="Later">
                <h2 class="eyebrow px-4 pt-3">Later</h2>
                <ul class="divide-y divide-border">
                  {#each later as t (t.id)}
                    {@const tile = dateTile(t)}
                    <li class="row-tap flex items-center gap-3 px-4 py-3">
                      <span class="flex size-12 shrink-0 flex-col items-center justify-center rounded-xl bg-muted" aria-hidden="true">
                        <span class="text-[10px] font-semibold uppercase leading-none tracking-[0.12em] text-signal">{tile.month}</span>
                        <span class="text-xl font-bold leading-tight">{tile.day}</span>
                      </span>
                      <div class="min-w-0 flex-1">
                        <p class="break-words text-body font-medium"><a class="row-tap-link underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${t.id}`}>{t.name}</a></p>
                        <p class="text-caption text-muted-foreground">{laterLine(t, today)}</p>
                      </div>
                    </li>
                  {/each}
                </ul>
                <a class="flex min-h-11 items-center justify-between border-t border-border px-4 text-sm font-medium underline-offset-2 hover:underline" href="#trips?when=upcoming">All trips<ChevronRight class="size-4 text-muted-foreground" aria-hidden="true" /></a>
              </section>
            {/if}
          {/if}
        </aside>
      </div>
    </div>
  {/if}
{/if}

<Sheet bind:open={() => detail !== null, (v) => { if (!v) detail = null; }} title={detail ? headline(detail.segment) : "Booking"}>
  {#if detail}
    {@const d = detail}
    <PassCard segment={d.segment} bookings={d.bookings} {now} level={3} class="mb-4">
      {#snippet live()}{#if d.segment.kind === "flight" && d.segment.status !== "cancelled" && !untimed(d.segment)}<FlightStatus segment={d.segment} />{/if}{/snippet}
      {#snippet footer()}<span class="flex flex-wrap gap-2"><GateCode segment={d.segment} {now} onchanged={load} /><Button href={`#trip/${d.segment.trip_id}?segment=${d.segment.id}`} variant="outline" size="sm" onclick={() => (detail = null)}>Open trip</Button></span>{/snippet}
    </PassCard>
  {/if}
</Sheet>

<ConfirmDialog bind:open={asking} title={`Link ${claiming?.display_name ?? "this guest"} to you?`} confirmLabel="This is me" busyLabel="Linking…"
  description="Their trips, loyalty and Known Traveler numbers and names become yours, and the guest is removed. This can’t be undone in Waypoint: restoring a backup is the way back."
  onconfirm={async () => { const g = claiming; return g ? await claim(g) : true; }} />
