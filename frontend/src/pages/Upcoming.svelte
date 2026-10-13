<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { app, refreshState } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { MailboxList, Person, Segment, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import DayTime from "$lib/components/DayTime.svelte";
  import GateCode from "$lib/components/GateCode.svelte";
  import { takeEarlyTrips } from "$lib/early";
  import { flightStatus, loadFlightStatus, statusFor } from "$lib/flightstatus.svelte";
  import PassCard from "$lib/components/PassCard.svelte";
  import { dateLabel, dayIn, dayLabel, END_WORD, featuredTrip, flightEvidence, headline, nextUp, subline, timesDiffer, tripDays, untimed, upcomingTitle, viewerZone } from "$lib/trips";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Sheet } from "$lib/components/ui/sheet";
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
    catch { mail = null; }
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

<h1 class="mb-6 text-display">Upcoming</h1>

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
          <li><a class="underline underline-offset-2" href="#settings">Save your current trip for offline use</a></li>
        </ul>
      </details>
    </div>
  </section>
{:else}
  {#if next}
    {@const s = next.segment}
    {@const proof = s.kind === "flight" && flightStatus.list?.enabled ? flightEvidence(statusFor(s.id), now, typeof navigator === "undefined" || navigator.onLine !== false) : "scheduled"}
    {@const grounded = proof === "landed" || proof === "cancelled" || proof === "diverted"}
    {@const eyebrow = next.state !== "now" ? "Next up" : s.kind !== "flight" ? "Under way" : grounded ? "Latest flight" : proof === "departed" ? "In the air" : proof === "delayed" ? "Delayed" : "In the air, by schedule"}
    <PassCard segment={s} bookings={next.bookings} {now} level={2} class="mb-8" condensed {eyebrow} pulse={next.state === "now" && !grounded}>
      {#snippet live()}{#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}{/snippet}
      {#snippet footer()}<span class="flex flex-wrap gap-2"><GateCode segment={s} {now} onchanged={load} /><Button href={`#trip/${s.trip_id}?segment=${s.id}`} variant="outline" size="sm">Open {next.trip.name}</Button></span>{/snippet}
    </PassCard>
    {#if next.alongside.length}
      <section class="-mt-4 mb-8" aria-label="Also under way">
        <p class="eyebrow mb-2">Also under way</p>
        <ul class="rows">
          {#each next.alongside as item (item.segment.id)}
            {@const seg = item.segment}
            <li class="row row-tap items-start">
              <BrandLogo src={seg.logo} label={seg.logo_label} size={32} class="mt-0.5" />
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
    <h2 class="mb-1 text-title"><a class="inline-flex items-center phone:min-h-11 underline-offset-2 hover:underline" href={`#trip/${featured.id}`}>{featured.name}</a></h2>
    {#if featured.start_date && featured.end_date}<p class="mb-4 text-caption text-muted-foreground">{dateLabel(featured.start_date)} – {dateLabel(featured.end_date)}</p>{/if}
    <ol class="flex flex-col gap-6" aria-label={`${featured.name}, day by day`}>
      {#each days as day (day.date)}
        <li>
          <h3 class="eyebrow mb-2">{dayLabel(`${day.date}T00:00`)}{day.date === today ? " · Today" : ""}</h3>
          <ul class="rows">
            {#each day.items as item (`${item.segment.id}-${item.role}`)}
              {@const seg = item.segment}
              <li class="row row-tap items-start" class:opacity-60={seg.status === "cancelled"}>
                <BrandLogo src={seg.logo} label={seg.logo_label} size={32} class="mt-0.5" />
                <div class="min-w-0 flex-1">
                  <p class="break-words text-body font-medium" class:line-through={seg.status === "cancelled"}>
                    <a class="row-tap-link underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${seg.trip_id}?segment=${seg.id}`}
                    title={upcomingTitle(seg) === headline(seg) ? undefined : headline(seg)} onclick={(e) => openDetail(e, seg, item.bookings)}>{item.role === "end" ? `${END_WORD[seg.kind]}: ${upcomingTitle(seg)}` : upcomingTitle(seg)}</a></p>
                  {#if item.role === "start" && subline(seg, true)}<p class="break-words text-caption text-muted-foreground">{subline(seg, true)}</p>{/if}
                  {#if item.role === "start" && item.bookings.length > 1}<p class="text-caption text-muted-foreground">{item.bookings.length} bookings{timesDiffer(item.bookings) ? " · times differ between bookings" : ""}</p>{/if}
                </div>
                <p class="text-body font-medium">
                  <DayTime segment={seg} end={item.role === "end"} />
                </p>
              </li>
            {/each}
          </ul>
        </li>
      {/each}
    </ol>
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
