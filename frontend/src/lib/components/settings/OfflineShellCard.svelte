<script lang="ts">
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { ago, WHEN_SAVED } from "$lib/offline";
  import { offline, refreshOffline, switchSaving } from "$lib/offline.svelte";
  import type { Chip } from "$lib/status";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  const PREVIEW = 3;
  let changing = $state(false);
  let showAll = $state(false);
  let waiting = $state(0);
  let now = $state(Date.now());
  onMount(() => { void refreshOffline(); now = Date.now(); });

  const polling = $derived(offline.syncing || waiting > 0);
  $effect(() => {
    if (!polling) return;
    const timer = setInterval(() => {
      if (waiting > 0) waiting -= 1;
      void refreshOffline().then(() => { now = Date.now(); });
    }, 1000);
    return () => clearInterval(timer);
  });

  const saved = $derived(offline.hasCopy && offline.savedAt !== null);
  const names = $derived(offline.trips.map((t) => `“${t.name}”`));
  const extra = $derived(names.length - PREVIEW);
  const chip = $derived<Chip | null>(
    offline.damaged ? { label: "Damaged", tone: "bad" }
      : offline.off || offline.syncing ? null
      : offline.failed ? { label: saved ? "Not updated" : "Not saved", tone: "bad" }
      : saved ? { label: "Saved", tone: "ok" }
      : null,
  );
  const title = $derived(
    offline.damaged ? "The saved trips can’t be read"
      : offline.off ? "Off on this device"
      : !offline.syncing && offline.failed ? "Couldn’t save the trips"
      : "On for this device",
  );
  const showBackups = $derived(!offline.damaged && !offline.syncing && !offline.failed);

  async function toggle(input: HTMLInputElement) {
    const on = input.checked;
    changing = true;
    try {
      await switchSaving(on);
      if (on) waiting = 3;
    } catch {
      toast.error("Couldn’t change saving on this device");
      input.checked = !on;
      await refreshOffline();
    } finally {
      changing = false;
      now = Date.now();
    }
  }
</script>

<section aria-labelledby="offline-title" class="space-y-2" data-testid="offline-shell-card">
  <h2 id="offline-title" class="eyebrow px-1">Offline access</h2>
  <div class="rows">
    {#if !offline.checked}
      <div class="row"><p class="text-sm text-muted-foreground">Checking this device…</p></div>
    {:else}
      <div class="row">
        <div class="min-w-0 flex-[1_1_220px] space-y-1">
          <p class="flex flex-wrap items-center gap-x-2 gap-y-1 font-medium">{title}{#if chip}<StatusChip {chip} small />{/if}</p>
          {#if offline.damaged}
            <p class="text-sm text-muted-foreground">Switch saving off to delete them, then switch it on again to save your trips afresh.</p>
          {:else if offline.off}
            <p class="text-sm text-muted-foreground">Your upcoming trips aren’t kept on this device. Turn saving on to open them with no connection, even in airplane mode. Anything saved before was deleted when you switched it off.</p>
          {:else if offline.syncing}
            <p class="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite"><LoaderCircle class="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />Saving your trips…</p>
          {:else if offline.failed}
            <p class="text-sm text-muted-foreground" data-testid="offline-saved">{#if saved && offline.savedAt}The copy from {ago(offline.savedAt, now)} is still there: {names.join(", ")}.{:else}Nothing is saved on this device yet.{/if}</p>
            <p class="text-sm text-muted-foreground">Saving is tried again each time you open Waypoint online.</p>
          {:else if saved && offline.savedAt}
            {#if extra > 0 && !showAll}
              <p class="text-sm text-muted-foreground" data-testid="offline-saved">Saved {ago(offline.savedAt, now)}: {names.slice(0, PREVIEW).join(", ")} and {extra} more.</p>
              <button type="button" class="min-h-11 cursor-pointer text-sm underline underline-offset-2" onclick={() => (showAll = true)}>Show all {names.length}</button>
            {:else if extra > 0}
              <p class="text-sm text-muted-foreground" data-testid="offline-saved">Saved {ago(offline.savedAt, now)}.</p>
              <ul class="list-disc pl-5 text-sm text-muted-foreground">{#each names as name, i (i)}<li>{name}</li>{/each}</ul>
              <button type="button" class="min-h-11 cursor-pointer text-sm underline underline-offset-2" onclick={() => (showAll = false)}>Show fewer</button>
            {:else}
              <p class="text-sm text-muted-foreground" data-testid="offline-saved">Saved {ago(offline.savedAt, now)}: {names.join(", ")}.</p>
            {/if}
            <p class="text-sm text-muted-foreground">Each trip is removed 3 days after it ends.</p>
          {:else}
            <p class="text-sm text-muted-foreground" data-testid="offline-saved">Nothing is saved yet. {WHEN_SAVED}</p>
            <p class="text-sm text-muted-foreground">The first save happens when you open Waypoint online after signing in.</p>
          {/if}
        </div>
        <label class="flex min-h-11 shrink-0 cursor-pointer items-center gap-2.5 text-sm has-[:disabled]:cursor-default has-[:disabled]:opacity-60">
          <input type="checkbox" role="switch" class="peer sr-only" checked={!offline.off} disabled={changing || offline.syncing} onchange={(e) => toggle(e.currentTarget)} />
          <span class="relative h-7 w-[46px] flex-none rounded-full bg-input after:absolute after:left-[3px] after:top-[3px] after:size-[22px] after:rounded-full after:bg-foreground peer-checked:bg-primary peer-checked:after:left-[21px] peer-checked:after:bg-primary-foreground peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring/50" aria-hidden="true"></span>
          Save my upcoming trips
        </label>
      </div>
      {#if showBackups}
        <div class="row"><p class="min-w-0 text-sm text-muted-foreground">The saved copy can be part of your iCloud and computer backups.</p></div>
      {/if}
    {/if}
  </div>
</section>
