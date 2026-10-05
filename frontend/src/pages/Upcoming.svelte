<script lang="ts">
  import { errMsg } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import FlightStatus from "$lib/components/FlightStatus.svelte";
  import { loadFlightStatus } from "$lib/flightstatus.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import { dateLabel, dayIn, dayLabel, END_WORD, endAt, featuredTrip, headline, nextUp, startAt, START_WORD, subline, tripDays, untimed, viewerZone, when } from "$lib/trips";
  import PlaneTakeoff from "@lucide/svelte/icons/plane-takeoff";

  // The next thing on your trips (a card), then the trip it belongs to, day by day. A failed load leaves nothing drawn that
  // could pass for current, with a Try again.
  let trips = $state<Trip[] | null>(null);
  let loadError = $state("");
  let now = $state(Date.now());

  async function load() {
    loadError = "";
    try { trips = (await apiCall<"GET /api/trips">("/api/trips")).trips; void loadFlightStatus(); }
    catch (err) { trips = null; loadError = errMsg(err); }
  }
  $effect(() => {
    void load();
    const tick = setInterval(() => (now = Date.now()), 30_000);   // the countdown
    return () => clearInterval(tick);
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
    <section class="pass mb-8" aria-labelledby="next-title">
      <div class="flex flex-col gap-3 p-6 md:p-8">
        <p class="eyebrow">{next.state === "now" ? "Under way" : "Next up"}</p>
        <h2 id="next-title" class="break-words text-2xl font-semibold tracking-tight">{headline(s)}</h2>
        <p class="text-lg font-medium" data-countdown>
          {next.state === "now" ? when(END_WORD[s.kind], endAt(s) - now) : when(START_WORD[s.kind], startAt(s) - now)}
        </p>
        {#if subline(s)}<p class="break-words text-muted-foreground">{subline(s)}</p>{/if}
        {#if s.kind === "flight" && s.status !== "cancelled" && !untimed(s)}<FlightStatus segment={s} />{/if}
      </div>
      <div class="pass-tear" aria-hidden="true"></div>
      <dl class="grid grid-cols-2 gap-x-4 gap-y-3 p-6 text-sm md:p-8">
        <div><dt class="eyebrow">{START_WORD[s.kind]}</dt>
          <dd class="mt-1 text-base font-medium">{dayLabel(s.start_local)}, {#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.start_local} zone={s.start_zone} />{/if}</dd></div>
        <div><dt class="eyebrow">{END_WORD[s.kind]}</dt>
          <dd class="mt-1 text-base font-medium">{#if untimed(s)}<span class="text-muted-foreground">time not recorded</span>{:else}{dayLabel(s.end_local)}, <PlaceTime local={s.end_local} zone={s.end_zone} />{/if}</dd></div>
        {#if s.details.terminal}<div><dt class="eyebrow">Terminal</dt><dd class="mt-1 text-base font-medium">{s.details.terminal}</dd></div>{/if}
        {#if s.kind === "hotel" && s.details.address}<div class="col-span-2"><dt class="eyebrow">Address</dt><dd class="mt-1 break-words text-base font-medium">{s.details.address}</dd></div>{/if}
        {#if s.confirmation}<div><dt class="eyebrow">Confirmation</dt><dd class="mt-1 text-lg"><CopyCode code={s.confirmation} /></dd></div>{/if}
      </dl>
      <div class="px-6 pb-6 md:px-8 md:pb-8"><Button href={`#trip/${s.trip_id}`} variant="outline" size="sm">Open {next.trip.name}</Button></div>
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
                <div class="min-w-0 flex-1">
                  <p class="break-words font-medium" class:line-through={seg.status === "cancelled"}>{item.role === "end" ? `${END_WORD[seg.kind]}: ${headline(seg)}` : headline(seg)}</p>
                  {#if item.role === "start" && subline(seg)}<p class="break-words text-sm text-muted-foreground">{subline(seg)}</p>{/if}
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
