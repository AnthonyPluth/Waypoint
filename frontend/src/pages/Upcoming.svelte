<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { app, refreshState } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { MailboxList, Person, Segment, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { Badge } from "$lib/components/ui/badge";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import FlightBooking from "$lib/components/FlightBooking.svelte";
  import FlightHome from "$lib/components/FlightHome.svelte";
  import FlightRow from "$lib/components/FlightRow.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import DayTime from "$lib/components/DayTime.svelte";
  import ArrivalCard from "$lib/components/ArrivalCard.svelte";
  import GateCode from "$lib/components/GateCode.svelte";
  import { takeEarlyTrips } from "$lib/early";
  import AvatarStack from "$lib/components/AvatarStack.svelte";
  import { flightCardView, flightsToday, nextFlightShown } from "$lib/flightcard";
  import { formatMoney } from "$lib/money";
  import { isMobile } from "$lib/platform";
  import { flightStatus, loadFlightStatus, statusFor, followFlightStatus } from "$lib/flightstatus.svelte";
  import OfflineStatus from "$lib/components/OfflineStatus.svelte";
  import PassCard from "$lib/components/PassCard.svelte";
  import { dateTile, laterLine, laterTrips, startsIn } from "$lib/side-column";
  import { showsCode } from "$lib/gate-code";
  import RowShowCode from "$lib/components/RowShowCode.svelte";
  import { type Day, type DayItem, appWord, bookingTravellers, vendorLink, dayIn, dayLabel, END_WORD, START_WORD, endAt, featuredTrip, flightEvidence, headline, nextUp, nightsLabel, rangeLabel, startAt, subline, timesDiffer, todayLabel, tripDays, untimed, upcomingTitle, viewerZone } from "$lib/trips";
  import KindTile from "$lib/components/KindTile.svelte";
  import { offlineWorking } from "$lib/offline.svelte";
  import { viewport } from "$lib/phone.svelte";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Sheet } from "$lib/components/ui/sheet";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Plus from "@lucide/svelte/icons/plus";
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
  followFlightStatus(() => (trips ?? []).flatMap((t) => t.segments), () => app.sessionExpired);
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
  const later = $derived(trips && featured ? laterTrips(trips, featured, today) : []);
  const liveOn = $derived(flightStatus.list?.enabled === true);
  const online = $derived(typeof navigator === "undefined" || navigator.onLine !== false);
  const compactFlight = (s: Segment) => s.kind === "flight" && s.status !== "cancelled" && !untimed(s);
  const homeFlight = $derived(next !== null && compactFlight(next.segment)
    && nextFlightShown(flightCardView({ segment: next.segment, status: liveOn ? statusFor(next.segment.id) : undefined, liveOn, now, online, city: (code) => code }), startAt(next.segment), now));
  const todays = $derived(trips ? flightsToday(trips, now, viewerZone()) : []);
  const happened = (i: DayItem) => dayIn(i.role === "end" ? endAt(i.segment) : startAt(i.segment), viewerZone()) < today;
  const firstAhead = $derived(days.findIndex((d) => !d.items.every(happened)));
  const earlier = $derived(firstAhead < 0 ? days : days.slice(0, firstAhead));
  const ahead = $derived(firstAhead < 0 ? [] : days.slice(firstAhead));
  const toCome = (i: DayItem) => i.segment.status !== "cancelled" && (i.role === "end" ? endAt(i.segment) : startAt(i.segment)) > now;
  const markedDay = $derived(ahead.find((d) => d.items.some(toCome))?.date ?? null);
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

{#snippet differing(bookings: Segment[])}
  {#if bookings.length > 1 && timesDiffer(bookings)}
    <div class="flex w-full flex-col gap-1 text-sm">
      <span><Badge variant="secondary">Times differ between bookings</Badge></span>
      {#each bookings as b (b.id)}
        <span>{b.confirmation ? `${b.confirmation}: ` : ""}{START_WORD[b.kind].toLowerCase()} {dayLabel(b.start_local)}, <PlaceTime local={b.start_local} />, {END_WORD[b.kind].toLowerCase()} {dayLabel(b.end_local)}, <PlaceTime local={b.end_local} /></span>
      {/each}
    </div>
  {/if}
{/snippet}

{#snippet dayBlock(day: Day)}
  {@const isToday = day.date === today}
  <li>
    <div class="flex items-center gap-2 pb-1.5 pt-5">
      <h3 class="eyebrow">{dayLabel(`${day.date}T00:00`)}{isToday ? " · Today" : ""}</h3>
      {#if day.date === markedDay}<i class="size-2 rounded-full bg-primary shadow-[0_0_0_4px_color-mix(in_srgb,var(--primary)_25%,transparent)]" aria-hidden="true"></i><span class="eyebrow text-primary" data-testid="next-marker">Next</span>{/if}
    </div>
    <ul>
      {#each day.items as item (`${item.segment.id}-${item.role}`)}
        {@const seg = item.segment}
        <li class="row-tap flex min-h-14 items-center gap-3.5 border-b border-border py-2" class:opacity-60={seg.status === "cancelled"}>
          <p class="mono w-[76px] shrink-0 text-[15px] font-bold">
            <DayTime segment={seg} end={item.role === "end"} />
          </p>
          <span class="flex w-9 shrink-0 justify-center">
            {#if seg.logo}
              <BrandLogo src={seg.logo} label={seg.logo_label} size={viewport.phone ? 34 : 36} />
            {:else}
              <KindTile kind={seg.kind} size={viewport.phone ? 34 : 36} decorative outline />
            {/if}
          </span>
          <div class="min-w-0 flex-1">
            <p class="break-words text-body font-semibold" class:line-through={seg.status === "cancelled"}>
              <a class="row-tap-link underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${seg.trip_id}?segment=${seg.id}`}
              title={upcomingTitle(seg) === headline(seg) ? undefined : headline(seg)} onclick={(e) => openDetail(e, seg, item.bookings)}>{item.role === "end" ? `${END_WORD[seg.kind]}: ${upcomingTitle(seg)}` : upcomingTitle(seg)}</a></p>
            {#if item.role === "start" && subline(seg, true)}<p class="break-words text-caption text-muted-foreground">{subline(seg, true)}</p>{/if}
            {#if item.role === "start" && item.bookings.length > 1}<p class="text-caption text-muted-foreground">{item.bookings.length} bookings{timesDiffer(item.bookings) ? " · times differ between bookings" : ""}</p>{/if}
          </div>
          {#if item.role === "start" && showsCode(seg, endAt(seg), now)}
            <RowShowCode segment={seg} {now} />
          {:else}
            <ChevronRight class="size-4 shrink-0 text-label" aria-hidden="true" />
          {/if}
        </li>
      {/each}
    </ul>
  </li>
{/snippet}

<div class="mb-4 flex items-end justify-between gap-3 md:mb-6">
  <div class="min-w-0">
    <p class="eyebrow mb-1" data-testid="today-eyebrow">{todayLabel(now, viewerZone(), viewport.phone)}</p>
    <h1 class="text-display md:text-display-lg">Upcoming</h1>
  </div>
  {#if trips && trips.length > 0}
    <div class="flex shrink-0 items-center gap-2">
      <OfflineStatus pill open={offlineOpen} ontoggle={() => (offlineOpen = !offlineOpen)} />
      <Button href="#trips?add=booking" variant="secondary" class="phone:size-11 phone:p-0"><Plus aria-hidden="true" /><span class="phone:sr-only">Add a booking</span></Button>
    </div>
  {/if}
</div>

{#if trips}<ArrivalCard segments={trips.flatMap((t) => t.segments)} {now} />{/if}

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if trips === null}
  <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" role="progressbar" aria-busy="true" aria-label="Loading"></div>
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
  <section class="rounded-booking bg-card" aria-labelledby="empty-title">
    <div class="flex flex-col items-start gap-3.5 p-6">
      <div class="space-y-1.5">
        <p class="eyebrow">Get started</p>
        <h2 id="empty-title" class="text-title font-extrabold" data-state={setup.id}>{setup.title}</h2>
        <p class="max-w-prose text-body text-muted-foreground">{setup.text}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        {#if setup.id === "review"}<Button href="#review">Review {waiting === 1 ? "the email" : `${waiting} emails`}</Button>{/if}
        {#if setup.id === "connect" || setup.id === "reconnect"}<Button disabled={connecting} onclick={connect}>{connecting ? "Opening Google…" : setup.id === "reconnect" ? "Reconnect Gmail" : "Connect Gmail"}</Button>{/if}
        <Button href="#trips?add=booking" variant={setup.id === "manual" ? "default" : "secondary"}>Add a booking</Button>
      </div>
      <details class="w-full text-body">
        <summary class="inline-flex min-h-11 cursor-pointer items-center font-semibold text-muted-foreground underline-offset-2 hover:underline">Setup checklist (optional)</summary>
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
    <a href="#review" class="mb-4 flex min-h-11 items-center gap-2.5 text-[15px] text-muted-foreground" data-testid="review-line">
      <i class="size-2 shrink-0 rounded-full bg-signal" aria-hidden="true"></i>
      <span class="min-w-0 flex-1">{waiting} {waiting === 1 ? "email" : "emails"} to review</span>
      <ChevronRight class="size-4 shrink-0 text-label" aria-hidden="true" />
    </a>
  {/if}
  <div class="@container">
  <div class={`grid gap-x-8 gap-y-2 ${homeFlight ? "@[900px]:grid-cols-2 @[900px]:items-start" : ""}`} data-columns={homeFlight ? "two" : "one"}>
  <div class="min-w-0">
  {#if !offlineWorking() || offlineOpen}<div class="-mt-1 mb-6"><OfflineStatus /></div>{/if}
  {#if next}
    {@const s = next.segment}
    {@const proof = s.kind === "flight" && flightStatus.list?.enabled ? flightEvidence(statusFor(s.id), now, typeof navigator === "undefined" || navigator.onLine !== false) : "scheduled"}
    {@const grounded = proof === "landed" || proof === "cancelled" || proof === "diverted"}
    {@const eyebrow = next.state !== "now" ? "Next up" : s.kind !== "flight" ? "Under way" : grounded ? "Latest flight" : proof === "departed" ? "In the air" : proof === "delayed" ? "Delayed" : "Under way"}
    {#if homeFlight}
      <FlightHome segment={s} status={liveOn ? statusFor(s.id) : undefined} {liveOn} {now} {online} {eyebrow} tripName={next.trip.name} paused={liveOn ? flightStatus.list?.paused : null} tripSegments={next.trip.segments} statusOf={statusFor} class="mb-6">
        {#snippet footer()}
          {@render differing(next.bookings)}
          {@const manage = s.links.app ?? s.manage_url}
          {@const vendor = vendorLink(s, isMobile())}
          {#if !(s.links.directions || s.links.call) && manage}
            <Button variant="action" href={manage} target="_blank" rel="noopener noreferrer" size="sm" class="phone:flex-1">{appWord(s, now, isMobile())}</Button>
          {:else if !(s.links.directions || s.links.call) && vendor}
            <Button variant="action" href={vendor.href} size="sm" class="phone:flex-1">{vendor.label}</Button>
          {/if}
          {#each next.bookings.filter((b) => b.confirmation) as b (b.id)}<CopyCode code={b.confirmation ?? ""} class="mono min-h-11 max-w-full break-all text-left font-semibold" />{/each}
          {#if s.links.directions}<Button href={s.links.directions} target="_blank" rel="noopener noreferrer" variant="outline" size="sm" class="phone:hidden">Directions</Button>{/if}
          {#if s.links.call}<Button href={s.links.call} variant="outline" size="sm" class="phone:hidden">Call</Button>{/if}
          <GateCode segment={s} {now} onchanged={load} /><Button href={`#trip/${s.trip_id}?segment=${s.id}`} variant="outline" size="sm" class="phone:flex-1">Open trip<span class="sr-only">: {next.trip.name}</span></Button>
          {@const travellers = bookingTravellers(next.bookings)}
          {#if travellers.people.length}<div class="flex w-full items-center gap-2.5"><AvatarStack people={travellers.people} /><span class="min-w-0 truncate text-sm font-medium">{travellers.names}</span></div>{/if}
          {#if next.bookings.length === 1 && s.price && app.state?.show_costs !== false}<p class="w-full text-sm"><span class="eyebrow">Cost</span> <span class="font-medium" data-cost>{formatMoney(s.price.amount_minor, s.price.currency)}</span></p>{/if}
        {/snippet}
      </FlightHome>
    {:else}
      <PassCard segment={s} bookings={next.bookings} {now} level={2} class="mb-6" condensed boarding tripName={next.trip.name} showApp={!(s.links.directions || s.links.call)} {eyebrow} pulse={next.state === "now" && !grounded}>
        {#snippet live()}{#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}{/snippet}
        {#snippet footer()}<span class="contents">
          {#if s.status !== "cancelled" && s.links.directions}<Button href={s.links.directions} target="_blank" rel="noopener noreferrer" variant="outline" size="sm" class="phone:hidden">Directions</Button>{/if}
          {#if s.status !== "cancelled" && s.links.call}<Button href={s.links.call} variant="outline" size="sm" class="phone:hidden">Call</Button>{/if}
          <GateCode segment={s} {now} onchanged={load} /><Button href={`#trip/${s.trip_id}?segment=${s.id}`} variant="outline" size="sm" class="phone:flex-1">Open trip<span class="sr-only">: {next.trip.name}</span></Button></span>{/snippet}
      </PassCard>
    {/if}
    {#if next.alongside.length}
      <section class="-mt-2 mb-6" aria-label="Also under way">
        <p class="eyebrow mb-2">Also under way</p>
        <ul class="divide-y divide-border overflow-hidden rounded-booking bg-card">
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
    <div class="mb-6 flex flex-col items-start gap-3">
      <p class="text-[17px] text-muted-foreground">Nothing coming up: every trip you can see is over.</p>
      <Button href="#trips" variant="secondary">See your trips</Button>
    </div>
  {/if}

  {#if todays.length}
    <ul class="mb-6 divide-y divide-border overflow-hidden rounded-booking bg-card" aria-label="Flights today">
      {#each todays as f (f.id)}<FlightRow segment={f} status={liveOn ? statusFor(f.id) : undefined} {liveOn} {now} {online} />{/each}
    </ul>
  {/if}

  </div>

  {#if featured}
    <div class="min-w-0">
      {#if homeFlight}<p class="eyebrow mb-1 hidden @[900px]:block">Coming up</p>{/if}
      <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 class="text-title"><a class="inline-flex items-center phone:min-h-11 underline-offset-2 hover:underline" href={`#trip/${featured.id}`}>{featured.name}</a></h2>
        {#if featured.start_date && featured.end_date}<p class="text-caption text-muted-foreground">{rangeLabel(featured.start_date, featured.end_date)}{nightsLabel(featured.start_date, featured.end_date) ? ` · ${nightsLabel(featured.start_date, featured.end_date)}` : ""}</p>{/if}
      </div>
      <ol class="flex flex-col" aria-label={`${featured.name}, day by day`}>
        {#if earlier.length}
          <li class="pt-3">
            <details class="group">
              <summary class="inline-flex min-h-11 cursor-pointer items-center rounded-md font-semibold text-muted-foreground underline-offset-2 hover:underline focus-visible:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">Earlier in this trip · {earlier.length} {earlier.length === 1 ? "day" : "days"}</summary>
              <ol class="flex flex-col" aria-label={`${featured.name}, earlier days`}>
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
      {#if later.length}
        {#if viewport.phone}
          <section class="mt-8" aria-label="Later">
            <h2 class="eyebrow mb-2">Later</h2>
            <ul class="grid grid-cols-2 gap-3">
              {#each later as t (t.id)}
                {@const tile = dateTile(t)}
                <li class="row-tap rounded-booking bg-card p-4">
                  <p class="eyebrow">{tile.month} {tile.day}</p>
                  <p class="break-words text-body font-semibold"><a class="row-tap-link underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${t.id}`}>{t.name}</a></p>
                  <p class="text-caption text-muted-foreground">{startsIn(t, today)}</p>
                </li>
              {/each}
            </ul>
          </section>
        {:else}
          <section class="mt-8" aria-label="Later">
            <h2 class="eyebrow mb-1">Later</h2>
            <ul>
              {#each later as t (t.id)}
                {@const tile = dateTile(t)}
                <li class="row-tap flex min-h-14 items-center gap-3.5 border-b border-border py-2">
                  <p class="eyebrow w-[76px] shrink-0">{tile.month} {tile.day}</p>
                  <div class="min-w-0 flex-1">
                    <p class="break-words text-body font-semibold"><a class="row-tap-link underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${t.id}`}>{t.name}</a></p>
                    <p class="text-caption text-muted-foreground">{laterLine(t, today)}</p>
                  </div>
                  <ChevronRight class="size-4 shrink-0 text-label" aria-hidden="true" />
                </li>
              {/each}
            </ul>
            <a class="flex min-h-11 items-center justify-between text-sm font-semibold text-muted-foreground underline-offset-2 hover:underline" href="#trips">All trips<ChevronRight class="size-4 text-label" aria-hidden="true" /></a>
          </section>
        {/if}
      {/if}
    </div>
  {/if}
  </div>
  </div>
{/if}

<Sheet bind:open={() => detail !== null, (v) => { if (!v) detail = null; }} title={detail ? headline(detail.segment) : "Booking"}>
  {#if detail}
    {@const d = detail}
    {#if compactFlight(d.segment)}
      <div class="mb-4 flex flex-col gap-3">
        <FlightBooking segment={d.segment} status={liveOn ? statusFor(d.segment.id) : undefined} {liveOn} {now} {online} paused={liveOn ? flightStatus.list?.paused : null} showTimes={!(d.bookings.length > 1 && timesDiffer(d.bookings))} onopen={() => (detail = null)} />
        {@render differing(d.bookings)}
        {#if d.bookings.some((b) => b.confirmation)}<p class="flex flex-wrap gap-x-4">{#each d.bookings.filter((b) => b.confirmation) as b (b.id)}<CopyCode code={b.confirmation ?? ""} class="mono min-h-11 max-w-full break-all text-left text-heading font-semibold" />{/each}</p>{/if}
        <span class="flex flex-wrap gap-2"><GateCode segment={d.segment} {now} onchanged={load} /><Button href={`#trip/${d.segment.trip_id}?segment=${d.segment.id}`} variant="outline" size="sm" onclick={() => (detail = null)}>Open trip</Button></span>
      </div>
    {:else}
      <PassCard segment={d.segment} bookings={d.bookings} {now} level={3} class="mb-4">
        {#snippet live()}{#if d.segment.kind === "flight" && d.segment.status !== "cancelled" && !untimed(d.segment)}<FlightStatus segment={d.segment} />{/if}{/snippet}
        {#snippet footer()}<span class="flex flex-wrap gap-2"><GateCode segment={d.segment} {now} onchanged={load} /><Button href={`#trip/${d.segment.trip_id}?segment=${d.segment.id}`} variant="outline" size="sm" onclick={() => (detail = null)}>Open trip</Button></span>{/snippet}
      </PassCard>
    {/if}
  {/if}
</Sheet>

<ConfirmDialog bind:open={asking} title={`Link ${claiming?.display_name ?? "this guest"} to you?`} confirmLabel="This is me" busyLabel="Linking…"
  description="Their trips, loyalty and Known Traveler numbers and names become yours, and the guest is removed. This can’t be undone in Waypoint: restoring a backup is the way back."
  onconfirm={async () => { const g = claiming; return g ? await claim(g) : true; }} />
