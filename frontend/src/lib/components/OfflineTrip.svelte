<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import MessageView from "$lib/components/MessageView.svelte";
  import PassCard from "$lib/components/PassCard.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import { Button } from "$lib/components/ui/button";
  import { ago, type SavedCopy } from "$lib/offline";
  import { bookingCards, dateLabel, dayLabel, headline } from "$lib/trips";
  import WifiOff from "@lucide/svelte/icons/wifi-off";

  let { copy }: { copy: SavedCopy } = $props();

  let now = $state(Date.now());
  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(tick);
  });

  const trip = $derived(copy.trip!);
  const cards = $derived(bookingCards(trip.segments));
  const dates = $derived(trip.start_date && trip.end_date
    ? (trip.start_date === trip.end_date ? dateLabel(trip.start_date) : `${dateLabel(trip.start_date)} – ${dateLabel(trip.end_date)}`) : "No dates yet");
  const emailsOf = (s: Segment) => copy.messages.find((m) => m.segment_id === s.id)?.emails ?? [];
  const kindName = (s: Segment) => ({ flight: "Flight", hotel: "Hotel", car: "Car", train: "Train", cruise: "Cruise" })[s.kind];
</script>

<div class="mb-4 flex items-start gap-3 rounded-2xl border border-border bg-card p-4 text-sm" role="status" data-testid="offline-banner">
  <WifiOff class="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
  <div class="min-w-0">
    <p class="font-medium">Offline. Saved {ago(copy.savedAt, now)}.</p>
    <p class="text-muted-foreground">This is the copy saved on this device. Editing and adding need a connection.</p>
  </div>
</div>

<div class="mb-6 space-y-1">
  <h1 class="break-words text-display">{trip.name}</h1>
  <p class="text-muted-foreground">{dates}{trip.destination ? ` · ${trip.destination}` : ""}</p>
  {#if trip.notes}<p class="mt-2 whitespace-pre-line break-words text-sm">{trip.notes}</p>{/if}
</div>

{#if trip.segments.length === 0}
  <p class="text-muted-foreground">Nothing booked on this trip yet.</p>
{/if}
<ul class="ml-2 flex flex-col gap-6 border-l-2 border-dashed border-border pl-4 sm:pl-6" aria-label="Bookings">
  {#each cards as card (card.id)}
    {@const s = card.lead}
    <PassCard as="li" id={`segment-${s.id}`} segment={s} bookings={card.segments} {now} level={2} eyebrow={`${kindName(s)} · ${dayLabel(s.start_local)}`}>
      {#snippet details()}
        {#if s.itinerary.length}
          <div class="mt-2 text-sm">
            <p class="eyebrow">Ports of call</p>
            <ol class="mt-1 flex flex-col gap-2">
              {#each s.itinerary as p, i (i)}
                <li class="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span class="break-words font-medium">{p.name}</span>
                  <span class="text-muted-foreground">
                    {#if p.arrive_local}{dayLabel(p.arrive_local)}, arrives <PlaceTime local={p.arrive_local} zone={p.zone} />{#if p.depart_local}, leaves <PlaceTime local={p.depart_local} zone={p.zone} />{/if}
                    {:else if p.depart_local}{dayLabel(p.depart_local)}, leaves <PlaceTime local={p.depart_local} zone={p.zone} />
                    {:else}Time not recorded{/if}
                  </span>
                </li>
              {/each}
            </ol>
          </div>
        {/if}
      {/snippet}
      {#snippet footer()}
        <div class="flex flex-col gap-4">
          {#each card.segments as b (b.id)}
            <div class="flex flex-col gap-2" data-booking>
              {#if card.segments.length > 1 && b.confirmation}<p class="text-lg"><CopyCode code={b.confirmation} /></p>{/if}
              {#if b.details.phone}<p class="text-sm"><span class="eyebrow">Phone</span> <a class="underline underline-offset-2" href={b.links.call ?? `tel:${b.details.phone}`}>{b.details.phone}</a></p>{/if}
              {#if b.travelers.length}
                <h3 class="eyebrow">Travellers</h3>
                <ul class="flex flex-col gap-1">
                  {#each b.travelers as who (who.id)}
                    <li class="text-sm"><span class="break-words font-medium">{who.name}</span>{#if who.seat}<span class="text-muted-foreground"> · Seat {who.seat}</span>{/if}</li>
                  {/each}
                </ul>
              {/if}
              {#if emailsOf(b).length}
                <details class="text-sm">
                  <summary class="cursor-pointer"><Button variant="outline" size="sm" class="pointer-events-none">View email for {headline(b)}</Button></summary>
                  <div class="mt-2 space-y-4" role="region" aria-label={`The email for ${headline(b)}`}>
                    {#each emailsOf(b) as e, i (i)}
                      <div>
                        {#if e.received || e.sender_domain}<p class="mb-1 text-sm text-muted-foreground">{[e.sender_domain, e.received && `sent ${e.received}`].filter(Boolean).join(" · ")}</p>{/if}
                        <MessageView subject={e.subject} text={e.text} html={e.html} truncated={e.truncated} offline />
                      </div>
                    {/each}
                  </div>
                </details>
              {/if}
            </div>
          {/each}
        </div>
      {/snippet}
    </PassCard>
  {/each}
</ul>
