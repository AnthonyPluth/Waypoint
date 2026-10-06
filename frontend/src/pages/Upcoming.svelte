<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Person, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import { loadFlightStatus } from "$lib/flightstatus.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import { dateLabel, dayIn, dayLabel, END_WORD, endAt, featuredTrip, headline, nextUp, startAt, START_WORD, subline, timesDiffer, tripDays, untimed, viewerZone, when } from "$lib/trips";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import PlaneTakeoff from "@lucide/svelte/icons/plane-takeoff";
  import { toast } from "svelte-sonner";

  // The next thing on your trips (a card), then the trip it belongs to, day by day. A failed load leaves nothing drawn that
  // could pass for current, with a Try again.
  let trips = $state<Trip[] | null>(null);
  let loadError = $state("");
  let now = $state(Date.now());
  // A member who was already a guest sees no trips until they say so: the guests their name matches, to claim ("This is me").
  let guests = $state<Person[]>([]);
  let claiming = $state<Person | null>(null);
  let asking = $state(false);

  async function load() {
    loadError = "";
    try {
      trips = (await apiCall<"GET /api/trips">("/api/trips")).trips; void loadFlightStatus();
      guests = trips.length ? [] : (await apiCall<"GET /api/people/claim-suggestions">("/api/people/claim-suggestions")).guests;
    } catch (err) { trips = null; guests = []; loadError = errMsg(err); }
  }
  $effect(() => {
    void load();
    const tick = setInterval(() => (now = Date.now()), 30_000);   // the countdown
    return () => clearInterval(tick);
  });

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
</script>

<h1 class="mb-6 text-3xl font-semibold tracking-tight">Upcoming</h1>

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
          <h2 id="claim-title" class="font-medium">Are you one of these?</h2>
          <p class="text-sm text-muted-foreground">Bookings were already made for someone with your name. If it’s you, their trips become yours.</p>
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
        <p class="eyebrow">Next trip</p>
        <h2 id="empty-title" class="text-xl font-semibold tracking-tight">No trips yet</h2>
        <p class="max-w-prose leading-relaxed text-muted-foreground">No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add one.</p>
      </div>
      <Button href="#trips" variant="outline">Add a booking</Button>
    </div>
  </section>
{:else}
  {#if next}
    {@const s = next.segment}
    {@const differ = timesDiffer(next.bookings)}
    <section class="pass mb-8" aria-labelledby="next-title">
      <div class="flex flex-col gap-3 p-6 md:p-8">
        <p class="eyebrow">{next.state === "now" ? "Under way" : "Next up"}</p>
        <div class="flex items-center gap-3">
          <BrandLogo src={s.logo} size={48} />
          <h2 id="next-title" class="min-w-0 break-words text-2xl font-semibold tracking-tight">{headline(s)}</h2>
        </div>
        <p class="text-lg font-medium" data-countdown>
          {next.state === "now" ? when(END_WORD[s.kind], endAt(s) - now) : when(START_WORD[s.kind], startAt(s) - now)}
        </p>
        {#if subline(s)}<p class="break-words text-muted-foreground">{subline(s)}</p>{/if}
        {#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}
      </div>
      <div class="pass-tear" aria-hidden="true"></div>
      <dl class="grid grid-cols-2 gap-x-4 gap-y-3 p-6 text-sm md:p-8">
        {#if differ}
          <div class="col-span-2"><dt class="eyebrow">Times</dt>
            <dd class="mt-1 flex flex-col gap-1 text-base font-medium">
              <span><Badge variant="secondary">Times differ between bookings</Badge></span>
              {#each next.bookings as b (b.id)}
                <span>{b.confirmation ? `${b.confirmation}: ` : ""}{START_WORD[b.kind].toLowerCase()} {dayLabel(b.start_local)}, <PlaceTime local={b.start_local} zone={b.start_zone} />, {END_WORD[b.kind].toLowerCase()} {dayLabel(b.end_local)}, <PlaceTime local={b.end_local} zone={b.end_zone} /></span>
              {/each}
            </dd></div>
        {:else}
          <div><dt class="eyebrow">{START_WORD[s.kind]}</dt>
            <dd class="mt-1 text-base font-medium">{dayLabel(s.start_local)}, {#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.start_local} zone={s.start_zone} />{/if}</dd></div>
          <div><dt class="eyebrow">{END_WORD[s.kind]}</dt>
            <dd class="mt-1 text-base font-medium">{#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}{dayLabel(s.end_local)}, <PlaceTime local={s.end_local} zone={s.end_zone} />{/if}</dd></div>
        {/if}
        {#if s.details.terminal}<div><dt class="eyebrow">Terminal</dt><dd class="mt-1 text-base font-medium">{s.details.terminal}</dd></div>{/if}
        {#if (s.kind === "hotel" || s.kind === "cruise") && s.details.address}<div class="col-span-2"><dt class="eyebrow">Address</dt><dd class="mt-1 break-words text-base font-medium">{s.details.address}</dd></div>{/if}
        {#if next.bookings.some((b) => b.confirmation)}
          <div><dt class="eyebrow">{next.bookings.length > 1 ? "Confirmations" : "Confirmation"}</dt>
            <dd class="mt-1 flex flex-wrap gap-x-3 text-lg">{#each next.bookings as b (b.id)}{#if b.confirmation}<CopyCode code={b.confirmation} />{/if}{/each}</dd></div>
        {/if}
      </dl>
      <div class="px-6 pb-6 md:px-8 md:pb-8"><Button href={`#trip/${s.trip_id}?segment=${s.id}`} variant="outline" size="sm">Open {next.trip.name}</Button></div>
    </section>
  {:else}
    <p class="mb-8 text-muted-foreground">Nothing coming up: every trip you can see is over. <a class="underline" href="#trips">See your trips</a>.</p>
  {/if}

  {#if featured}
    <h2 class="mb-1 text-xl font-semibold tracking-tight"><a class="underline-offset-2 hover:underline" href={`#trip/${featured.id}`}>{featured.name}</a></h2>
    {#if featured.start_date && featured.end_date}<p class="mb-4 text-sm text-muted-foreground">{dateLabel(featured.start_date)} – {dateLabel(featured.end_date)}</p>{/if}
    <ol class="flex flex-col gap-6" aria-label={`${featured.name}, day by day`}>
      {#each days as day (day.date)}
        <li>
          <h3 class="eyebrow mb-2">{dayLabel(`${day.date}T00:00`)}{day.date === today ? " · Today" : ""}</h3>
          <ul class="rows">
            {#each day.items as item (`${item.segment.id}-${item.role}`)}
              {@const seg = item.segment}
              <li class="row items-start" class:opacity-60={seg.status === "cancelled"}>
                <BrandLogo src={seg.logo} size={32} class="mt-0.5" />
                <div class="min-w-0 flex-1">
                  <p class="break-words font-medium" class:line-through={seg.status === "cancelled"}>
                    <a class="underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${seg.trip_id}?segment=${seg.id}`}>{item.role === "end" ? `${END_WORD[seg.kind]}: ${headline(seg)}` : headline(seg)}</a></p>
                  {#if item.role === "start" && subline(seg)}<p class="break-words text-sm text-muted-foreground">{subline(seg)}</p>{/if}
                  {#if item.role === "start" && item.bookings.length > 1}<p class="text-sm text-muted-foreground">{item.bookings.length} bookings{timesDiffer(item.bookings) ? " · times differ between bookings" : ""}</p>{/if}
                </div>
                <p class="text-sm font-medium">
                  {#if untimed(seg)}<span class="text-muted-foreground">time not recorded</span>
                  {:else if item.role === "end"}<PlaceTime local={seg.end_local} zone={seg.end_zone} />
                  {:else}<PlaceTime local={seg.start_local} zone={seg.start_zone} />{/if}
                </p>
              </li>
            {/each}
          </ul>
        </li>
      {/each}
    </ol>
  {/if}
{/if}

<ConfirmDialog bind:open={asking} title={`Link ${claiming?.display_name ?? "this guest"} to you?`} confirmLabel="This is me" busyLabel="Linking…"
  description="Their trips, loyalty and Known Traveler numbers and names become yours, and the guest is removed. This can’t be undone in Waypoint: restoring a backup is the way back."
  onconfirm={async () => { const g = claiming; return g ? await claim(g) : true; }} />
