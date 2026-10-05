<script lang="ts">
  import { act } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { LoyaltyEntry } from "$lib/api-types";
  import { toast } from "svelte-sonner";

  // A membership's number, masked: tapping it asks the server for that one number, shows it and copies it; tapping it again
  // hides it. It's kept only in this component (never in browser storage), and gone when you leave the page.
  let { entry }: { entry: LoyaltyEntry } = $props();
  let shown = $state<string | null>(null);

  async function toggle() {
    if (shown !== null) { shown = null; return; }
    await act(async () => {
      const { number } = await apiCall<"POST /api/loyalty/{id}/reveal">(`/api/loyalty/${entry.id}/reveal`, { method: "POST" });
      shown = number;
      try { await navigator.clipboard.writeText(number); toast.success("Copied"); }
      catch { toast("Couldn’t copy it: select the number instead."); }   // no clipboard (an insecure page, a refused permission)
    });
  }
</script>

{#if entry.readable}
  <button type="button" class="rounded-md px-1.5 py-0.5 font-mono underline-offset-2 hover:underline focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none"
    aria-label={shown !== null ? `Hide ${entry.program} number` : `Show and copy ${entry.program} number`} onclick={toggle}>{shown ?? entry.masked}</button>
{:else}
  <span class="text-muted-foreground">Can’t be read with this key: enter it again in <a class="underline" href="#people">People</a></span>
{/if}
