<script lang="ts">
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { Sheet } from "$lib/components/ui/sheet";
  import { offline, turnOnOffline } from "$lib/offline.svelte";
  import { deviceCheckName } from "$lib/platform";

  let { open = $bindable(false), title = "Keep this trip available offline", onenabled }: {
    open?: boolean; title?: string; onenabled?: () => void;
  } = $props();

  const check = deviceCheckName();
  let busy = $state(false);
  let problem = $state("");

  async function turnOn() {
    busy = true;
    problem = "";
    const failure = await turnOnOffline();
    busy = false;
    if (!failure) { open = false; onenabled?.(); return; }
    problem = failure.code === "cancelled" ? "Nothing was turned on. Try again, or choose Not now." : failure.message;
  }

  function notNow() {
    offline.declined = true;
    open = false;
  }
</script>

<Sheet bind:open={() => open, (v) => { if (busy) return; if (!v) offline.declined = true; open = v; }} {title}
  description={`Waypoint can keep an encrypted copy on this device and open it without a connection, with ${check}.`}>
  <div class="space-y-4">
    <ul class="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
      <li>The copy is locked on this device. Anyone who gets at a backup or a copy of the device’s stored data finds only scrambled text.</li>
      <li>Saving never asks for {check}. Only opening the saved trip offline does.</li>
      <li>Signing in to Waypoint works as before. The passkey this creates only unlocks the saved trip.</li>
    </ul>
    {#if !offline.supported}
      <Alert><AlertDescription>{offline.reason}</AlertDescription></Alert>
      <Button variant="outline" class="w-full" onclick={notNow}>Close</Button>
    {:else}
      {#if problem}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{problem}</p>{/if}
      <div class="flex flex-col gap-2 sm:flex-row-reverse">
        <Button class="sm:flex-1" disabled={busy} onclick={turnOn}>{busy ? "Waiting for your device…" : `Turn on with ${check}`}</Button>
        <Button variant="outline" class="sm:flex-1" disabled={busy} onclick={notNow}>Not now</Button>
      </div>
    {/if}
  </div>
</Sheet>
