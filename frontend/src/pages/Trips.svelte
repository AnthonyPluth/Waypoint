<script lang="ts">
  import { errMsg } from "$lib/act";
  import { route, setQuery } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { Person, Trip } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import SegmentForm from "$lib/components/SegmentForm.svelte";
  import { blank } from "$lib/segment-form";
  import { dateLabel, dayIn, splitTrips, viewerZone } from "$lib/trips";
  import Plus from "@lucide/svelte/icons/plus";

  // The trips you can see, upcoming and past, filtered by who's travelling (kept in the address as ?who=<id>). A failed load
  // leaves nothing drawn that could pass for current, with a Try again.
  let trips = $state<Trip[] | null>(null);
  let people = $state<Person[]>([]);
  let loadError = $state("");
  let adding = $state(false);

  async function load() {
    loadError = "";
    try {
      const [t, p] = await Promise.all([apiCall<"GET /api/trips">("/api/trips"), apiCall<"GET /api/people">("/api/people")]);
      trips = t.trips; people = p.people;
    } catch (err) { trips = null; loadError = errMsg(err); }
  }
  $effect(() => { void load(); });

  const who = $derived(Number(new URLSearchParams(route.query).get("who")) || null);
  const pick = (e: Event) => { const v = (e.currentTarget as HTMLSelectElement).value; setQuery(v ? `who=${v}` : ""); };
  const shown = $derived(trips && splitTrips(trips.filter((t) => !who || t.segments.some((s) => s.travelers.some((x) => x.person_id === who))), dayIn(Date.now(), viewerZone())));
  const names = (t: Trip) => [...new Set(t.segments.flatMap((s) => s.travelers.map((x) => x.name)))].join(", ");
  const dates = (t: Trip) => t.start_date && t.end_date ? (t.start_date === t.end_date ? dateLabel(t.start_date) : `${dateLabel(t.start_date)} – ${dateLabel(t.end_date)}`) : "No dates yet";
  const selectClass = "border-input bg-card dark:bg-secondary rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";
</script>

<div class="mb-6 flex flex-wrap items-center justify-between gap-3">
  <h1 class="text-4xl font-bold tracking-tight">Trips</h1>
  {#if trips && !adding}<Button onclick={() => (adding = true)}><Plus /> Add a booking</Button>{/if}
</div>

{#if adding}
  <SegmentForm initial={blank()} {people} oncancel={() => (adding = false)} onsaved={(s) => { adding = false; location.hash = `#trip/${s.trip_id}`; }} />
{/if}

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if shown === null}
  <div class="h-40 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading"></div>
{:else}
  {#if people.length > 1}
    <label class="mb-6 flex flex-col gap-1.5 text-sm sm:max-w-xs"><span class="font-medium">Travelling</span>
      <select class={selectClass} value={who ?? ""} onchange={pick}>
        <option value="">Everyone</option>
        {#each people as p (p.id)}<option value={p.id}>{p.display_name}</option>{/each}
      </select></label>
  {/if}
  {#if shown.upcoming.length === 0 && shown.past.length === 0}
    <p class="text-muted-foreground">{who ? "No trips with them." : "No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add a booking."}</p>
  {/if}
  {#each [["Upcoming", shown.upcoming], ["Past", shown.past]] as const as [title, list] (title)}
    {#if list.length}
      <section class="mb-8" aria-labelledby={`trips-${title}`}>
        <h2 id={`trips-${title}`} class="eyebrow mb-2">{title}</h2>
        <ul class="flex flex-col gap-3" aria-label={`${title} trips`}>
          {#each list as t (t.id)}
            <li>
              <a class="row items-start rounded-2xl border bg-card shadow-card transition-colors hover:bg-accent/60 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none" href={`#trip/${t.id}`}>
                <span class="min-w-0 flex-1">
                  <span class="flex flex-wrap items-center gap-2 text-lg font-bold tracking-tight"><span class="break-words">{t.name}</span>{#if !t.auto}<Badge variant="outline">Edited</Badge>{/if}</span>
                  <span class="block text-sm text-muted-foreground">{dates(t)}{t.destination ? ` · ${t.destination}` : ""}</span>
                  {#if names(t)}<span class="block break-words text-sm text-muted-foreground">{names(t)}</span>{/if}
                </span>
              </a>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {/each}
{/if}
