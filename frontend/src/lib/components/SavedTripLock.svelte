<script lang="ts">
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import Lock from "@lucide/svelte/icons/lock";
  import { removeOffline } from "$lib/offline.svelte";
  import { deviceCheckName } from "$lib/platform";
  import { unlock, VaultError } from "$lib/offline-vault";
  import { toast } from "svelte-sonner";

  let { onunlocked, onremoved }: { onunlocked: (value: unknown) => void; onremoved?: () => void } = $props();

  const check = deviceCheckName();
  type Phase = "locked" | "working" | "cancelled" | "failed" | "gone";
  let phase = $state<Phase>("locked");
  let asking = $state(false);

  async function open() {
    phase = "working";
    try {
      onunlocked(await unlock());
    } catch (err) {
      const code = err instanceof VaultError ? err.code : "failed";
      phase = code === "cancelled" ? "cancelled" : code === "passkey-missing" || code === "damaged" || code === "not-set-up" ? "gone" : "failed";
    }
  }

  async function removeIt() {
    await removeOffline();
    toast.success("The saved trip is removed");
    onremoved?.();
    return true;
  }
</script>

<section class="mx-auto flex max-w-md flex-col items-center gap-4 rounded-2xl border border-border bg-card p-6 text-center shadow-card" aria-labelledby="locked-title">
  <span class="grid size-12 place-items-center rounded-full bg-muted text-muted-foreground" aria-hidden="true"><Lock class="size-6" /></span>
  <div class="space-y-1">
    <h1 id="locked-title" class="text-heading font-semibold">Saved trip is locked</h1>
    {#if phase === "gone"}
      <p class="text-sm text-muted-foreground">This device can’t unlock it: the passkey it needs is gone, which happens on a new device or when the passkey is deleted. Remove the saved trip, then reconnect and set up offline access again to save a fresh copy.</p>
    {:else}
      <p class="text-sm text-muted-foreground">Unlock it with {check} to see the trip saved on this device.</p>
    {/if}
  </div>
  {#if phase === "cancelled"}
    <Alert class="text-left"><AlertDescription>Unlocking was cancelled, so the trip stays locked.</AlertDescription></Alert>
  {:else if phase === "failed"}
    <Alert class="text-left"><AlertDescription>That didn’t work, so the trip stays locked.</AlertDescription></Alert>
  {/if}
  {#if phase === "gone"}
    <Button variant="destructive" class="w-full" onclick={() => (asking = true)}>Remove saved trip</Button>
  {:else}
    <Button class="w-full" disabled={phase === "working"} onclick={open}>
      {phase === "working" ? "Waiting for your device…" : phase === "cancelled" || phase === "failed" ? "Try again" : "Unlock"}
    </Button>
  {/if}
</section>

<ConfirmDialog bind:open={asking} title="Remove the saved trip?" confirmLabel="Remove" busyLabel="Removing…" destructive
  description="It’s deleted from this device only. When you’re back online and set up offline access again, a fresh copy is saved." onconfirm={removeIt} />
