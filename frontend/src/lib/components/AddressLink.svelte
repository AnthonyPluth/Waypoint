<script lang="ts">
  import { toast } from "svelte-sonner";
  import { Sheet } from "$lib/components/ui/sheet";
  import { directionsFor } from "$lib/directions";

  let { address, text = address, class: klass = "" }: { address: string; text?: string; class?: string } = $props();
  let open = $state(false);

  async function tap() {
    try { await navigator.clipboard.writeText(address); toast.success("Address copied"); }
    catch { toast("Couldn’t copy it: select the address instead."); }
    open = true;
  }
</script>

<button type="button" class={`rounded-md text-left underline-offset-2 hover:underline phone:min-h-11 focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none ${klass}`}
  aria-label={`Copy address ${address} and get directions`} onclick={tap}>{text}</button>

<Sheet bind:open title="Get directions" description={address}>
  <ul class="flex flex-col gap-2">
    {#each directionsFor(address) as r (r.id)}
      <li><a class="flex min-h-11 items-center rounded-md border border-border px-4 font-medium hover:bg-accent focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none" href={r.url} target="_blank" rel="noopener noreferrer" onclick={() => (open = false)}>{r.label}</a></li>
    {/each}
  </ul>
</Sheet>
