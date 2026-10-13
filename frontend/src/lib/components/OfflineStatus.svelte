<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import OfflineSetup from "$lib/components/OfflineSetup.svelte";
  import { ago } from "$lib/offline";
  import { offline, refreshOffline, syncSavedTrip } from "$lib/offline.svelte";
  import HardDriveDownload from "@lucide/svelte/icons/hard-drive-download";
  import { onMount } from "svelte";

  let { tripId = null }: { tripId?: number | null } = $props();

  let setting = $state(false);
  let retrying = $state(false);
  let now = $state(Date.now());
  onMount(() => {
    if (!offline.checked) void refreshOffline();
    const tick = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(tick);
  });

  const savedElsewhere = $derived(tripId !== null && offline.tripId !== null && offline.tripId !== tripId);
  const unidentified = $derived(tripId !== null && offline.tripId === null);
  const savedHere = $derived(offline.hasCopy && !savedElsewhere && !unidentified);
  const which = $derived(offline.tripName ? `“${offline.tripName}”` : "your current trip");

  async function retry() {
    retrying = true;
    try { await syncSavedTrip(); } finally { retrying = false; now = Date.now(); }
  }
</script>

{#if offline.checked}
  <section class="mt-3 max-w-prose rounded-xl border border-border bg-card p-3 text-sm" aria-label="Offline access" data-testid="offline-status">
    <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <p class="flex min-w-0 items-start gap-2">
        <HardDriveDownload class="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span class="min-w-0 break-words" data-testid="offline-status-line">
          {#if offline.damaged}
            <span class="font-medium">The saved trip can’t be read.</span> <a class="underline underline-offset-2" href="#settings/offline">Remove it in Settings</a>, then set up offline access again.
          {:else if !offline.supported}
            <span class="font-medium">Offline access isn’t available on this device.</span> <span class="text-muted-foreground">{offline.reason}</span>
          {:else if !offline.setUp}
            <span class="font-medium">Not saved for offline use.</span> <span class="text-muted-foreground">Set up offline access to open your current trip with no connection.</span>
          {:else if offline.off}
            <span class="font-medium">Offline saving is off on this device.</span> <a class="underline underline-offset-2" href="#settings/offline">Turn it on in Settings</a>.
          {:else if offline.failed}
            <span class="font-medium">Couldn’t save the trip on this device.</span> <span class="text-muted-foreground">{savedHere && offline.savedAt ? `The copy from ${ago(offline.savedAt, now)} is still there.` : "Nothing is saved yet."}</span>
          {:else if savedElsewhere}
            <span class="font-medium">Saved on this device: {which}.</span> <span class="text-muted-foreground">This trip isn’t the one saved: only your current trip is.</span>
          {:else if offline.hasCopy && unidentified}
            <span class="font-medium">A trip is saved on this device</span>
            {#if offline.savedAt}<span class="text-muted-foreground">· updated {ago(offline.savedAt, now)}</span>{/if}
          {:else if savedHere && offline.savedAt}
            <span class="font-medium">Saved on this device</span> <span class="text-muted-foreground">· updated {ago(offline.savedAt, now)}{tripId === null && offline.tripName ? ` · ${which}` : ""}</span>
          {:else if savedHere}
            <span class="font-medium">A trip is saved on this device.</span>
          {:else}
            <span class="font-medium">Nothing is saved yet.</span> <span class="text-muted-foreground">Your current trip is saved when you open Waypoint online.</span>
          {/if}
        </span>
      </p>
      {#if offline.supported && !offline.damaged}
        {#if !offline.setUp}
          <Button size="sm" onclick={() => (setting = true)}>Set up offline access</Button>
        {:else if offline.failed}
          <Button size="sm" variant="outline" disabled={retrying} onclick={retry}>{retrying ? "Saving…" : "Try again"}</Button>
        {/if}
      {/if}
    </div>
  </section>
  <OfflineSetup bind:open={setting} title="Set up offline access" />
{/if}
