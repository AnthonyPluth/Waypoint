<script lang="ts">
  import { boot, route } from "$lib/app.svelte";
  import * as Card from "$lib/components/ui/card";
  import { Button } from "$lib/components/ui/button";
  import OfflineTrip from "$lib/components/OfflineTrip.svelte";
  import SavedTripLock from "$lib/components/SavedTripLock.svelte";
  import { clearSaved, expiryOf, isSavedCopy, type SavedCopy } from "$lib/offline";
  import { offline, refreshOffline } from "$lib/offline.svelte";
  import { onLock } from "$lib/offline-vault";
  import { onMount } from "svelte";

  let copy = $state<SavedCopy | null>(null);
  onMount(refreshOffline);
  $effect(() => onLock(() => { copy = null; }));

  const savedTripPage = $derived(route.page === "upcoming" || route.page === "trip");

  async function opened(value: unknown) {
    if (!isSavedCopy(value)) throw new Error("unreadable");
    const expires = expiryOf(value);
    if (expires !== null && Date.now() >= expires) {
      await clearSaved();
      await refreshOffline();
      return;
    }
    copy = value;
  }
</script>

{#if !offline.checked}
  <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading"></div>
{:else if !savedTripPage}
  <Card.Root class="mx-auto mt-10 max-w-md" data-testid="needs-connection">
    <Card.Header>
      <Card.Title>This page needs a connection</Card.Title>
      <Card.Description>You’re offline. Only the trip saved on this device is available now.</Card.Description>
    </Card.Header>
    <Card.Content class="flex gap-2">
      <Button href="#upcoming">Saved trip</Button>
      <Button variant="outline" onclick={boot}>Try again</Button>
    </Card.Content>
  </Card.Root>
{:else if copy}
  <OfflineTrip {copy} />
{:else if offline.hasCopy}
  <SavedTripLock onunlocked={opened} onremoved={() => refreshOffline()} />
{:else}
  <Card.Root class="mx-auto mt-10 max-w-md" data-testid="nothing-saved">
    <Card.Header>
      <Card.Title>You’re offline, and no trip is saved on this device</Card.Title>
      <Card.Description>{offline.setUp ? offline.off ? "Saving a trip for offline use is switched off on this device." : "A trip is saved here when you open Waypoint online and one is under way or starting within a week." : "Set up offline access in Settings while you’re online, and your current trip is saved here."}</Card.Description>
    </Card.Header>
    <Card.Content><Button variant="outline" onclick={boot}>Try again</Button></Card.Content>
  </Card.Root>
{/if}
