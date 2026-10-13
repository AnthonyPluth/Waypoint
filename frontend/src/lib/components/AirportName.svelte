<script lang="ts">
  import { airportInfo } from "$lib/airport-zones";
  import type { Airport } from "$lib/api-types";

  let { code, class: cls = "" }: { code: string; class?: string } = $props();
  let found = $state<{ code: string; airport: Airport | null } | null>(null);

  $effect(() => {
    const wanted = code;
    let current = true;
    void airportInfo(wanted).then((airport) => { if (current) found = { code: wanted, airport }; });
    return () => { current = false; };
  });

  const airport = $derived(found && found.code === code ? found.airport : null);
</script>

{#if airport}
  <span class={`mt-1 block min-w-0 break-words ${cls}`} data-airport-name>
    <span class="block text-sm font-medium">{airport.city || airport.name}</span>
    {#if airport.city && airport.name}<span class="block text-xs text-muted-foreground">{airport.name}</span>{/if}
  </span>
{/if}
