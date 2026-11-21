<script lang="ts">
  import AvatarStack from "$lib/components/AvatarStack.svelte";
  import AirportCode from "$lib/components/AirportCode.svelte";
  import FlightCard from "$lib/components/FlightCard.svelte";
  import FlightHome from "$lib/components/FlightHome.svelte";
  import KindTile from "$lib/components/KindTile.svelte";
  import PassCard from "$lib/components/PassCard.svelte";
  import RouteLine from "$lib/components/RouteLine.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { bookingChip, liveChip } from "$lib/status";
  import { instant } from "$lib/trips";
  import type { FlightStatus, Segment } from "$lib/api-types";

  const flight: Segment = {
    id: 1, trip_id: 1, kind: "flight", status: "confirmed", confirmation: "K7Q2ZM", provider: "Example Air",
    start_local: "2026-11-20T07:05", start_zone: "America/Chicago", end_local: "2026-11-20T09:20", end_zone: "America/Los_Angeles",
    origin: "MSP", destination: "LAX", details: { flight_number: "EA 214", terminal: "1", cabin: "Economy" }, manage_url: "https://example.com/manage",
    source: "manual", booked_by: null, locked_fields: [], check_times: false, travelers: [{ id: 1, person_id: null, name: "Jane Doe", seat: "14C" }],
    itinerary: [], days: [], logo: null, logo_label: null, hotel_brand: null, has_email: false, email_update: null, gate_code: null, price: null, links: { app: "https://example.com/manage", open: null, open_kind: null, directions: null, call: null },
  };
  const stay: Segment = {
    ...flight, id: 2, kind: "hotel", confirmation: "HT5521", provider: "Example Hotels", origin: "Harbour Hotel", destination: null,
    start_local: "2026-11-20T15:00", start_zone: "America/Los_Angeles", end_local: "2026-11-24T11:00", end_zone: "America/Los_Angeles",
    details: { address: "1 Quay Street, Los Angeles", room: "412" }, manage_url: null, links: { app: null, open: null, open_kind: null, directions: null, call: null }, travelers: [],
  };
  const flightNow = instant("2026-11-20T07:05", "America/Chicago") - 3 * 3_600_000;
  const underWayNow = instant("2026-11-20T07:05", "America/Chicago") + 90 * 60_000;
  const stayNow = instant("2026-11-20T08:00", "America/Los_Angeles");

  const flightEA: Segment = {
    ...flight, id: 3, confirmation: "EA2140", provider: "Example Air", origin: "DEN", destination: "GJT",
    start_local: "2025-06-12T09:40", start_zone: "America/Denver", end_local: "2025-06-12T10:52", end_zone: "America/Denver",
    details: { flight_number: "EA 214", cabin: "Economy" }, travelers: [{ id: 1, person_id: null, name: "Jane Doe", seat: "12A" }],
  };
  const at = (local: string) => instant(local, "America/Denver");
  const minutesBefore = (now: number, minutes: number) => new Date(now - minutes * 60_000).toISOString();
  const status = (now: number, minutes: number, extra: Partial<FlightStatus>): FlightStatus => ({
    segment_id: 3, state: "scheduled", origin: "DEN", destination: "GJT", dep_scheduled: "2025-06-12T09:40", dep_estimated: null, dep_actual: null, dep_zone: "America/Denver",
    dep_terminal: null, dep_gate: null, arr_scheduled: "2025-06-12T10:52", arr_estimated: null, arr_actual: null, arr_zone: "America/Denver", arr_terminal: null, arr_gate: null,
    delay_minutes: null, fetched_at: minutesBefore(now, minutes), ...extra,
  });
  const cardNow = {
    scheduled: at("2025-06-09T08:00"), boarding: at("2025-06-12T09:15"), delayed: at("2025-06-12T08:50"), air: at("2025-06-12T10:14"),
    landed: at("2025-06-12T10:55"), cancelled: at("2025-06-12T08:30"), diverted: at("2025-06-12T10:20"), none: at("2025-06-02T08:00"),
  };
  const flightCards: { name: string; now: number; status?: FlightStatus; segment: Segment }[] = [
    { name: "Scheduled", now: cardNow.scheduled, status: status(cardNow.scheduled, 4, { dep_terminal: "B" }), segment: flightEA },
    { name: "Boarding", now: cardNow.boarding, status: status(cardNow.boarding, 2, { dep_terminal: "B", dep_gate: "B14" }), segment: flightEA },
    { name: "Delayed", now: cardNow.delayed, status: status(cardNow.delayed, 4, { state: "delayed", dep_estimated: "2025-06-12T10:15", arr_estimated: "2025-06-12T11:27", dep_terminal: "B", dep_gate: "B14", delay_minutes: 35 }), segment: flightEA },
    { name: "In the air", now: cardNow.air, status: status(cardNow.air, 1, { state: "departed", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:52", arr_terminal: "1", arr_gate: "A3" }), segment: flightEA },
    { name: "Landed", now: cardNow.landed, status: status(cardNow.landed, 1, { state: "landed", dep_actual: "2025-06-12T09:46", arr_actual: "2025-06-12T10:49", arr_terminal: "1", arr_gate: "A3" }), segment: flightEA },
    { name: "Cancelled", now: cardNow.cancelled, status: status(cardNow.cancelled, 12, { state: "cancelled" }), segment: flightEA },
    { name: "Diverted", now: cardNow.diverted, status: status(cardNow.diverted, 3, { state: "diverted", destination: "MTJ", dep_actual: "2025-06-12T09:46", arr_estimated: "2025-06-12T10:41" }), segment: flightEA },
    { name: "Scheduled, no live status", now: cardNow.none, segment: flightEA },
    { name: "Scheduled, Premium Economy", now: cardNow.scheduled, status: status(cardNow.scheduled, 4, { dep_terminal: "B" }), segment: { ...flightEA, details: { ...flightEA.details, cabin: "Premium Economy" } } },
  ];

  const NEW_YORK = "America/New_York";
  const LISBON = "Europe/Lisbon";
  const crewSeats = (a: string, b: string, c: string) => [
    { id: 1, person_id: null, name: "Mara Quist", seat: a }, { id: 2, person_id: null, name: "Tomas Reyes", seat: b }, { id: 3, person_id: null, name: "Ines Vale", seat: c },
  ];
  const connectionLegs: Segment[] = [
    {
      ...flight, id: 11, confirmation: "QZXW74", provider: "Aurora Air", origin: "BOS", destination: "JFK", start_local: "2026-03-09T06:10", start_zone: NEW_YORK,
      end_local: "2026-03-09T07:28", end_zone: NEW_YORK, details: { flight_number: "AU1402", terminal: "B" }, travelers: crewSeats("14A", "14B", "22C"),
      journey: { lead: 11, leg: 1, legs: 2, previous: null, next: 12 },
    },
    {
      ...flight, id: 12, confirmation: "QZXW74", provider: "Aurora Air", origin: "JFK", destination: "LIS", start_local: "2026-03-09T09:40", start_zone: NEW_YORK,
      end_local: "2026-03-09T21:15", end_zone: LISBON, details: { flight_number: "AU212", terminal: "4" }, travelers: crewSeats("31A", "31B", "31C"),
      journey: { lead: 11, leg: 2, legs: 2, previous: 11, next: null },
    },
  ];
  const connectionNow = { before: instant("2026-03-07T05:00", NEW_YORK), at: instant("2026-03-09T07:50", NEW_YORK) };
  const connectionStatus = (leg: Segment, now: number, extra: Partial<FlightStatus>): FlightStatus => ({
    segment_id: leg.id, state: "scheduled", origin: leg.origin ?? "", destination: leg.destination ?? "", dep_scheduled: leg.start_local, dep_estimated: null, dep_actual: null, dep_zone: leg.start_zone,
    dep_terminal: null, dep_gate: null, arr_scheduled: leg.end_local, arr_estimated: null, arr_actual: null, arr_zone: leg.end_zone, arr_terminal: null, arr_gate: null,
    delay_minutes: null, fetched_at: minutesBefore(now, 3), ...extra,
  });
  const beforeFirst = connectionStatus(connectionLegs[0], connectionNow.before, { dep_terminal: "B", dep_gate: "B9" });
  const earlierLeg = connectionStatus(connectionLegs[0], connectionNow.at, { state: "landed", dep_actual: "2026-03-09T06:14", arr_actual: "2026-03-09T07:28" });
  const atStop = connectionStatus(connectionLegs[1], connectionNow.at, { dep_terminal: "4", dep_gate: "B22" });

  const tileKinds = ["flight", "hotel", "train", "car", "cruise", "parking", "visit"] as const;
  const crew = ["Jane Doe", "Mia Doe", "Sam Roe", "Lee Poe", "Ann Coe", "Bob Foe"].map((name, i) => ({ id: i + 1, name }));
  const stacks = [1, 3, 6].map((n) => ({ n, people: crew.slice(0, n) }));
  const booking = (["confirmed", "changed", "cancelled"] as const).map(bookingChip);
  const live = [
    liveChip({ state: "scheduled", delay_minutes: null }),
    liveChip({ state: "delayed", delay_minutes: 25 }),
    liveChip({ state: "departed", delay_minutes: null }),
    liveChip({ state: "landed", delay_minutes: null }),
    liveChip({ state: "diverted", delay_minutes: null }),
  ];
  const routes = [
    { when: "Before departure", progress: 0 },
    { when: "Under way", progress: 0.55 },
    { when: "After arrival", progress: 1 },
  ];
  const type = [
    { name: "Display", cls: "text-display desktop:text-display-lg", sample: "Upcoming" },
    { name: "Hero fact", cls: "text-hero-fact desktop:text-hero-fact-lg", sample: "in 3 h 20 m" },
    { name: "Airport", cls: "font-mono text-airport desktop:text-airport-lg", sample: "MSP" },
    { name: "Fact", cls: "font-mono text-fact desktop:text-fact-lg", sample: "7:05 AM" },
    { name: "Card fact", cls: "text-fact-card", sample: "Gate B12" },
    { name: "Code", cls: "text-display", sample: "K7Q2ZM" },
    { name: "Title", cls: "text-title", sample: "Upcoming" },
    { name: "Heading", cls: "text-heading", sample: "Check-in is open" },
    { name: "Body", cls: "text-body", sample: "Departs at 7:05 AM from Terminal 1." },
    { name: "Caption", cls: "text-caption text-muted-foreground", sample: "As of 6:42 AM" },
    { name: "Mono", cls: "mono text-heading", sample: "07:05 MSP K7Q2ZM 14C 0123" },
    { name: "Eyebrow", cls: "text-eyebrow uppercase text-label", sample: "Next up" },
  ];
  const surfaces = [
    { name: "Surface 1", cls: "bg-surface-1 shadow-elevation-1" },
    { name: "Surface 2", cls: "bg-surface-2 shadow-elevation-2" },
    { name: "Surface 3", cls: "bg-surface-3 shadow-elevation-3" },
  ];
</script>

<h1 class="mb-6 text-4xl font-bold tracking-tight">Design</h1>

<div class="flex flex-col gap-8">
  <section class="flex flex-col gap-3" aria-labelledby="design-status">
    <h2 id="design-status" class="text-heading">Status</h2>
    <p class="text-caption text-muted-foreground">The booking chip leads. The live chip is smaller and appears only when live flight status is on.</p>
    <div class="rows"><div class="row"><span class="text-caption text-muted-foreground">Booking</span><span class="flex flex-wrap gap-2">{#each booking as chip (chip.label)}<StatusChip {chip} />{/each}</span></div>
      <div class="row"><span class="text-caption text-muted-foreground">Live</span><span class="flex flex-wrap gap-2">{#each live as chip (chip.label)}<StatusChip {chip} small />{/each}</span></div></div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-codes">
    <h2 id="design-codes" class="text-heading">Airport codes</h2>
    <div class="rows"><div class="row"><AirportCode code="MSP" name="Minneapolis–Saint Paul" /><AirportCode code="LAX" name="Los Angeles" size="medium" /><AirportCode code="JFK" name="New York Kennedy" size="small" /></div></div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-route">
    <h2 id="design-route" class="text-heading">Route line</h2>
    <p class="text-caption text-muted-foreground">The plane is placed from the booked times, from 0 at departure to 1 at arrival.</p>
    <div class="rows">
      {#each routes as r (r.when)}
        <div class="row">
          <span class="w-36 text-caption text-muted-foreground">{r.when}</span>
          <span class="flex min-w-0 flex-1 items-center gap-3"><AirportCode code="MSP" size="small" /><RouteLine class="flex-1" progress={r.progress} label={`${r.when}, based on the booked times`} /><AirportCode code="LAX" size="small" /></span>
        </div>
      {/each}
    </div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-pass">
    <h2 id="design-pass" class="text-heading">Pass card</h2>
    <p class="text-caption text-muted-foreground">One card for a booking you are planning or checking in for. The headline and the plane come from the booked times unless live flight status says otherwise.</p>
    <div class="grid gap-4 lg:grid-cols-2">
      <PassCard segment={flight} now={flightNow} />
      <PassCard segment={flight} now={underWayNow} />
      <PassCard segment={stay} now={stayNow} />
    </div>
    <h3 class="text-caption text-muted-foreground">Next up (boarding) variant: the plane starts at the left of the arc before departure and rides it in the air.</h3>
    <div class="grid gap-4">
      <PassCard segment={flight} now={flightNow} boarding eyebrow="Next up" tripName="Trip to Minneapolis" />
      <PassCard segment={flight} now={underWayNow} boarding eyebrow="Under way" tripName="Trip to Minneapolis" pulse />
    </div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-flight-card">
    <h2 id="design-flight-card" class="text-heading">Flight card</h2>
    <p class="text-caption text-muted-foreground">The flight on the trip page, in its eight states: a raised slate card with no edge or shadow, its airport codes, times and seats in Geist Mono. A fact is marked as from live status (a filled dot) or from the booking (a ring), and a dash is a fact not known yet.</p>
    <div class="grid gap-4 lg:grid-cols-2">
      {#each flightCards as c (c.name)}
        <FlightCard segment={c.segment} status={c.status} liveOn now={c.now} />
      {/each}
    </div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-connection">
    <h2 id="design-connection" class="text-heading">Flight card: a connection</h2>
    <p class="text-caption text-muted-foreground">Two flights on one booking that follow each other: the whole journey on the arc with the stop, the leg you are on, a Then line before the first leg and an Earlier line during the connection.</p>
    <div class="grid gap-4 lg:grid-cols-2">
      <FlightHome segment={connectionLegs[0]} status={beforeFirst} liveOn now={connectionNow.before} eyebrow="Next up" tripName="Trip to Lisbon" tripSegments={connectionLegs} />
      <FlightHome segment={connectionLegs[1]} status={atStop} liveOn now={connectionNow.at} eyebrow="Next up" tripName="Trip to Lisbon" tripSegments={connectionLegs} statusOf={(id) => (id === 11 ? earlierLeg : undefined)} />
    </div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-kinds">
    <h2 id="design-kinds" class="text-heading">Kind tiles</h2>
    <p class="text-caption text-muted-foreground">One tile per kind of booking, at 28 and 36 px.</p>
    <div class="rows">{#each [28, 36] as const as size (size)}<div class="row"><span class="w-20 text-caption text-muted-foreground">{size} px</span><span class="flex flex-wrap gap-2">{#each tileKinds as kind (kind)}<KindTile {kind} {size} />{/each}</span></div>{/each}</div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-people">
    <h2 id="design-people" class="text-heading">Avatar stack</h2>
    <p class="text-caption text-muted-foreground">Up to four people, then a count.</p>
    <div class="rows">{#each stacks as s (s.n)}<div class="row"><span class="w-20 text-caption text-muted-foreground">{s.n} {s.n === 1 ? "person" : "people"}</span><AvatarStack people={s.people} /></div>{/each}</div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-type">
    <h2 id="design-type" class="text-heading">Type</h2>
    <div class="rows">{#each type as t (t.name)}<div class="row"><span class="w-20 text-caption text-muted-foreground">{t.name}</span><span class={`min-w-0 flex-1 break-words ${t.cls}`}>{t.sample}</span></div>{/each}</div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-colour">
    <h2 id="design-colour" class="text-heading">Colour rules</h2>
    <div class="rows">
      <div class="row"><span class="w-28 text-caption text-muted-foreground">Blue</span><span class="flex min-w-0 flex-1 items-center gap-2 text-primary"><span class="size-2.5 rounded-full bg-primary"></span>Live, now, the one primary action</span></div>
      <div class="row"><span class="w-28 text-caption text-muted-foreground">Green</span><span class="flex min-w-0 flex-1 items-center gap-2 text-success"><span class="size-2.5 rounded-full bg-success"></span>Confirmed, on time, good news</span></div>
      <div class="row"><span class="w-28 text-caption text-muted-foreground">Amber</span><span class="flex min-w-0 flex-1 items-center gap-2 text-signal"><span class="size-2.5 rounded-full bg-signal"></span>Changed, needs attention</span></div>
    </div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-surfaces">
    <h2 id="design-surfaces" class="text-heading">Surfaces</h2>
    <div class="grid gap-3 sm:grid-cols-3">{#each surfaces as s (s.name)}<div class={`rounded-2xl border p-4 text-caption ${s.cls}`}>{s.name}</div>{/each}</div>
  </section>
</div>
