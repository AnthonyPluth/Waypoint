<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import OfflineSetup from "$lib/components/OfflineSetup.svelte";
  import { ago, ONLY_THESE, savedList, WHEN_SAVED } from "$lib/offline";
  import { offline, offlineWorking, refreshOffline, syncSavedTrip } from "$lib/offline.svelte";
  import CloudCheck from "@lucide/svelte/icons/cloud-check";
  import HardDriveDownload from "@lucide/svelte/icons/hard-drive-download";
  import { onMount } from "svelte";

  let { tripId = null, pill = false, open = false, ontoggle }: { tripId?: number | null; pill?: boolean; open?: boolean; ontoggle?: () => void } = $props();

  let setting = $state(false);
  let retrying = $state(false);
  let now = $state(Date.now());
  onMount(() => {
    if (!pill && !offline.checked) void refreshOffline();
    const tick = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(tick);
  });

  const identified = $derived(offline.trips.every((t) => t.id !== null));
  const savedHere = $derived(tripId !== null && identified && offline.trips.some((t) => t.id === tripId));
  const notSaved = $derived(tripId !== null && offline.hasCopy && identified && !savedHere);
  const others = $derived(offline.trips.filter((t) => t.id !== tripId));

  async function retry() {
    retrying = true;
    try { await syncSavedTrip(); } finally { retrying = false; now = Date.now(); }
  }
</script>

{#if pill}
  {#if offlineWorking()}
    <button type="button" class="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border border-status-ok-ink/30 bg-status-ok-soft px-3.5 text-sm font-medium text-status-ok-ink outline-none transition-colors hover:bg-status-ok-soft/70 focus-visible:ring-[3px] focus-visible:ring-ring/50 phone:size-11 phone:justify-center phone:px-0"
      aria-expanded={open} onclick={ontoggle} data-testid="offline-pill">
      <CloudCheck class="size-4 shrink-0" aria-hidden="true" /><span class="phone:sr-only">Saved for offline</span>
    </button>
  {/if}
{:else if offline.checked}
  <section class="mt-3 max-w-prose rounded-xl border border-border bg-card p-3 text-sm" aria-label="Offline access" data-testid="offline-status">
    <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <p class="flex min-w-0 items-start gap-2">
        <HardDriveDownload class="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span class="min-w-0 break-words" data-testid="offline-status-line">
          {#if offline.damaged}
            <span class="font-medium">The saved trips can’t be read.</span> <a class="underline underline-offset-2" href="#settings/offline">Remove it in Settings</a>, then set up offline access again.
          {:else if !offline.supported}
            <span class="font-medium">Offline access isn’t available on this device.</span> <span class="text-muted-foreground">{offline.reason}</span>
          {:else if !offline.setUp}
            <span class="font-medium">Not saved for offline use.</span> <span class="text-muted-foreground">Set up offline access to open your upcoming trips with no connection.</span>
          {:else if offline.off}
            <span class="font-medium">Offline saving is off on this device.</span> <a class="underline underline-offset-2" href="#settings/offline">Turn it on in Settings</a>.
          {:else if offline.failed}
            <span class="font-medium">Couldn’t save the trips on this device.</span> <span class="text-muted-foreground">{offline.hasCopy && offline.savedAt ? `The copy from ${ago(offline.savedAt, now)} is still there.` : "Nothing is saved yet."}</span>
          {:else if notSaved}
            <span class="font-medium">This trip isn’t saved on this device.</span> <span class="text-muted-foreground">Saved: {savedList(offline.trips)}. {ONLY_THESE}</span>
          {:else if offline.hasCopy && !savedHere && tripId !== null}
            <span class="font-medium">Trips are saved on this device</span>
            {#if offline.savedAt}<span class="text-muted-foreground">· updated {ago(offline.savedAt, now)}</span>{/if}
          {:else if offline.hasCopy && offline.savedAt}
            <span class="font-medium">Saved on this device</span> <span class="text-muted-foreground">· updated {ago(offline.savedAt, now)}{tripId === null ? ` · ${savedList(offline.trips)}` : others.length ? ` · also saved: ${savedList(others)}` : ""}</span>
          {:else if offline.hasCopy}
            <span class="font-medium">{offline.trips.length === 1 ? "A trip is saved on this device." : "Trips are saved on this device."}</span>
          {:else}
            <span class="font-medium">Nothing is saved yet.</span> <span class="text-muted-foreground">{WHEN_SAVED}</span>
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
