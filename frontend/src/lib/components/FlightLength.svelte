<script lang="ts">
  import { airportZone } from "$lib/airport-zones";
  import { longFlightWarning } from "$lib/segment-form";

  let { origin, destination, start, end }: { origin: string; destination: string; start: string; end: string } = $props();
  let zones = $state<{ origin: string; destination: string; startZone: string | null; endZone: string | null } | null>(null);

  $effect(() => {
    const from = origin, to = destination;
    let current = true;
    void Promise.all([airportZone(from), airportZone(to)]).then(([startZone, endZone]) => {
      if (current) zones = { origin: from, destination: to, startZone, endZone };
    });
    return () => { current = false; };
  });

  const warning = $derived(zones && zones.origin === origin && zones.destination === destination ? longFlightWarning(start, end, zones.startZone, zones.endZone) : null);
</script>

{#if warning}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="status">{warning}</p>{/if}
