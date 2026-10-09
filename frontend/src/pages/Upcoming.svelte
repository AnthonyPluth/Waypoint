<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Person, Segment, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import { takeEarlyTrips } from "$lib/early";
  import { loadFlightStatus } from "$lib/flightstatus.svelte";
  import PassCard from "$lib/components/PassCard.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import { dateLabel, dayIn, dayLabel, END_WORD, featuredTrip, headline, nextUp, subline, timesDiffer, tripDays, untimed, upcomingTitle, viewerZone } from "$lib/trips";
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
      trips = (await (early ?? apiCall<"GET /api/trips">("/api/trips"))).trips;
      if (!early) void loadFlightStatus();
      guests = trips.length ? [] : (await apiCall<"GET /api/people/claim-suggestions">("/api/people/claim-suggestions")).guests;
    } catch (err) { trips = null; guests = []; loadError = errMsg(err); }
  }
  $effect(() => {
    void load();
    const tick = setInterval(() => (now = Date.now()), 30_000);
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
        <p class="eyebrow">Next trip</p>
        <h2 id="empty-title" class="text-title">No trips yet</h2>
        <p class="max-w-prose text-body text-muted-foreground">No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add one.</p>
      </div>
      <Button href="#trips" variant="outline">Add a booking</Button>
    </div>
  </section>
{:else}
  {#if next}
    {@const s = next.segment}
    <PassCard segment={s} bookings={next.bookings} {now} level={2} class="mb-8" eyebrow={next.state === "now" ? "Under way" : "Next up"} pulse={next.state === "now"}>
      {#snippet live()}{#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}{/snippet}
      {#snippet footer()}<Button href={`#trip/${s.trip_id}?segment=${s.id}`} variant="outline" size="sm">Open {next.trip.name}</Button>{/snippet}
    </PassCard>
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
              <li class="row items-start" class:opacity-60={seg.status === "cancelled"}>
                <BrandLogo src={seg.logo} label={seg.logo_label} size={32} class="mt-0.5" />
                <div class="min-w-0 flex-1">
                  <p class="break-words text-body font-medium" class:line-through={seg.status === "cancelled"}>
                    <a class="underline-offset-2 hover:underline focus-visible:underline" href={`#trip/${seg.trip_id}?segment=${seg.id}`}
                    title={upcomingTitle(seg) === headline(seg) ? undefined : headline(seg)} onclick={(e) => openDetail(e, seg, item.bookings)}>{item.role === "end" ? `${END_WORD[seg.kind]}: ${upcomingTitle(seg)}` : upcomingTitle(seg)}</a></p>
                  {#if item.role === "start" && subline(seg, true)}<p class="break-words text-caption text-muted-foreground">{subline(seg, true)}</p>{/if}
                  {#if item.role === "start" && item.bookings.length > 1}<p class="text-caption text-muted-foreground">{item.bookings.length} bookings{timesDiffer(item.bookings) ? " · times differ between bookings" : ""}</p>{/if}
                </div>
                <p class="text-body font-medium">
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

<Sheet bind:open={() => detail !== null, (v) => { if (!v) detail = null; }} title={detail ? headline(detail.segment) : "Booking"}>
  {#if detail}
    {@const d = detail}
    <PassCard segment={d.segment} bookings={d.bookings} {now} level={3} class="mb-4">
      {#snippet live()}{#if d.segment.kind === "flight" && d.segment.status !== "cancelled" && !untimed(d.segment)}<FlightStatus segment={d.segment} />{/if}{/snippet}
      {#snippet footer()}<Button href={`#trip/${d.segment.trip_id}?segment=${d.segment.id}`} variant="outline" size="sm" onclick={() => (detail = null)}>Open trip</Button>{/snippet}
    </PassCard>
  {/if}
</Sheet>

<ConfirmDialog bind:open={asking} title={`Link ${claiming?.display_name ?? "this guest"} to you?`} confirmLabel="This is me" busyLabel="Linking…"
  description="Their trips, loyalty and Known Traveler numbers and names become yours, and the guest is removed. This can’t be undone in Waypoint: restoring a backup is the way back."
  onconfirm={async () => { const g = claiming; return g ? await claim(g) : true; }} />
