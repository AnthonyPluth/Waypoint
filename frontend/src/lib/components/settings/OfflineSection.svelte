<script lang="ts">
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import OfflineSetup from "$lib/components/OfflineSetup.svelte";
  import { offline, refreshOffline, removeOffline } from "$lib/offline.svelte";
  import { deviceCheckName } from "$lib/platform";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  const check = deviceCheckName();
  let setting = $state(false);
  let asking = $state(false);
  onMount(refreshOffline);

  async function removeIt() {
    await removeOffline();
    toast.success("The saved trip is removed");
    return true;
  }
</script>

<section aria-labelledby="offline-title" class="space-y-2">
  <h2 id="offline-title" class="eyebrow px-1">Offline access</h2>
  <div class="rows">
    {#if !offline.checked}
      <div class="row"><p class="text-sm text-muted-foreground">Checking this device…</p></div>
    {:else if offline.setUp}
      <div class="row">
        <div class="min-w-0">
          <p class="font-medium">On for this device</p>
          <p class="text-sm text-muted-foreground">The saved trip is encrypted and opens offline only with {check}.{offline.hasCopy ? "" : " Nothing is saved yet: open a trip while online."}</p>
        </div>
        <Badge variant="outline">On</Badge>
      </div>
      <div class="row">
        <p class="min-w-0 text-sm text-muted-foreground">Removing it deletes the saved trip and the key from this device.</p>
        <Button variant="outline" onclick={() => (asking = true)}>Remove saved trip</Button>
      </div>
    {:else if offline.damaged}
      <div class="row">
        <div class="min-w-0">
          <p class="font-medium">The saved trip can’t be read</p>
          <p class="text-sm text-muted-foreground">Remove it, then set up offline access again.</p>
        </div>
        <Button variant="outline" onclick={() => (asking = true)}>Remove saved trip</Button>
      </div>
    {:else if !offline.supported}
      <div class="row" data-testid="offline-unavailable">
        <div class="min-w-0">
          <p class="font-medium">Offline access isn’t available on this device</p>
          <p class="text-sm text-muted-foreground" role="status">{offline.reason}</p>
          <p class="text-sm text-muted-foreground">Waypoint works online as always.</p>
        </div>
        <Badge variant="outline">Unavailable</Badge>
      </div>
    {:else}
      <div class="row">
        <div class="min-w-0">
          <p class="font-medium">Off on this device</p>
          <p class="text-sm text-muted-foreground">Keep an encrypted copy of your trip to open without a connection, unlocked with {check}.</p>
        </div>
        <Button onclick={() => (setting = true)}>Set up offline access</Button>
      </div>
    {/if}
  </div>
</section>

<OfflineSetup bind:open={setting} title="Set up offline access" />

<ConfirmDialog bind:open={asking} title="Remove the saved trip?" confirmLabel="Remove" busyLabel="Removing…" destructive
  description="It’s deleted from this device only. You can set up offline access again later." onconfirm={removeIt} />
