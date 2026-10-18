<script lang="ts">
  import { boot, route } from "$lib/app.svelte";
  import * as Card from "$lib/components/ui/card";
  import { Button } from "$lib/components/ui/button";
  import OfflineTrip from "$lib/components/OfflineTrip.svelte";
  import SavedTripLock from "$lib/components/SavedTripLock.svelte";
  import { clearSaved, expiryOf, isSavedCopy, WHEN_SAVED, type SavedCopy } from "$lib/offline";
  import { offline, refreshOffline } from "$lib/offline.svelte";
  import { onLock } from "$lib/offline-vault";
  import { onMount } from "svelte";

  let copies = $state<SavedCopy[]>([]);
  let chosen = $state<number | null>(null);
  onMount(refreshOffline);
  $effect(() => onLock(() => { copies = []; chosen = null; }));

  const savedTripPage = $derived(route.page === "upcoming" || route.page === "trip");
  const wanted = $derived(route.page === "trip" && /^\d+$/.test(route.sub) ? Number(route.sub) : null);
  const picked = $derived(wanted ?? chosen ?? (copies.length === 1 ? copies[0].trip.id : null));
  const shown = $derived(copies.find((c) => c.trip.id === picked) ?? null);

  async function opened(values: unknown) {
    if (!Array.isArray(values) || !values.every(isSavedCopy)) throw new Error("unreadable");
    const kept = values.filter((c) => { const expires = expiryOf(c); return expires === null || Date.now() < expires; });
    if (kept.length === 0) {
      await clearSaved();
      await refreshOffline();
      return;
    }
    copies = kept;
    chosen = null;
  }
</script>

{#if !offline.checked}
  <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" role="progressbar" aria-busy="true" aria-label="Loading"></div>
{:else if !savedTripPage}
  <Card.Root class="mx-auto mt-10 max-w-md" data-testid="needs-connection">
    <Card.Header>
      <Card.Title>This page needs a connection</Card.Title>
      <Card.Description>You’re offline. Only the trips saved on this device are available now.</Card.Description>
    </Card.Header>
    <Card.Content class="flex gap-2">
      <Button href="#upcoming">Saved trips</Button>
      <Button variant="outline" onclick={boot}>Try again</Button>
    </Card.Content>
  </Card.Root>
{:else if shown}
  {#if copies.length > 1 && wanted === null}
    <Button variant="ghost" class="mb-3" onclick={() => (chosen = null)}>All saved trips</Button>
  {/if}
  <OfflineTrip copy={shown} />
{:else if copies.length}
  <Card.Root class="mx-auto mt-10 max-w-md" data-testid="saved-trips">
    <Card.Header>
      <Card.Title>{wanted === null ? "Trips saved on this device" : "This trip isn’t saved on this device"}</Card.Title>
      <Card.Description>{wanted === null ? "Choose a trip to open." : "Only trips under way or starting within a week, and your next upcoming trip, are saved. These are:"}</Card.Description>
    </Card.Header>
    <Card.Content class="flex flex-col gap-2">
      {#each copies as c (c.trip.id)}
        <Button variant="outline" class="h-auto justify-start whitespace-normal text-left" href={wanted === null ? undefined : `#trip/${c.trip.id}`} onclick={() => (chosen = c.trip.id)}>{c.trip.name}</Button>
      {/each}
    </Card.Content>
  </Card.Root>
{:else if offline.hasCopy}
  <SavedTripLock onunlocked={opened} onremoved={() => refreshOffline()} />
{:else}
  <Card.Root class="mx-auto mt-10 max-w-md" data-testid="nothing-saved">
    <Card.Header>
      <Card.Title>You’re offline, and no trip is saved on this device</Card.Title>
      <Card.Description>{offline.setUp ? offline.off ? "Saving trips for offline use is switched off on this device." : WHEN_SAVED : "Set up offline access in Settings while you’re online, and your upcoming trips are saved here."}</Card.Description>
    </Card.Header>
    <Card.Content><Button variant="outline" onclick={boot}>Try again</Button></Card.Content>
  </Card.Root>
{/if}
