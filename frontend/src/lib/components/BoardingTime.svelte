<script lang="ts">
  import { airportInfo } from "$lib/airport-zones";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import { dayLabel } from "$lib/trips";

  type Props = { local: string; zone: string; code?: string | null; unknown?: boolean; shift?: number; shiftWords?: string; align?: "start" | "end"; label?: string };
  let { local, zone, code = null, unknown = false, shift = 0, shiftWords = "", align = "start", label = "" }: Props = $props();

  let found = $state<{ code: string; city: string } | null>(null);

  $effect(() => {
    const wanted = code;
    if (!wanted) return;
    let current = true;
    void airportInfo(wanted).then((airport) => { if (current) found = { code: wanted, city: airport?.city ?? "" }; });
    return () => { current = false; };
  });

  const zoneCity = $derived((zone.split("/").pop() ?? zone).replaceAll("_", " "));
  const city = $derived((code && found && found.code === code ? found.city : "") || zoneCity);
  const shiftText = $derived(`${shift > 0 ? "+" : "−"}${Math.abs(shift)}`);
</script>

<div class={`min-w-0 ${align === "end" ? "text-right" : ""}`}>
  {#if label}<p class="eyebrow mb-1">{label}</p>{/if}
  <p class={`flex items-baseline gap-2 ${align === "end" ? "justify-end" : ""}`}>
    {#if unknown}
      <span class="text-sm text-muted-foreground">Time not recorded</span>
    {:else}
      <span class="mono text-title font-medium"><PlaceTime {local} /></span>
      {#if shift}<span class="rounded-full bg-signal-soft px-2 py-0.5 text-xs font-semibold text-signal-ink" data-day-shift><span aria-hidden="true">{shiftText}</span><span class="sr-only">, {shiftWords}</span></span>{/if}
    {/if}
  </p>
  <p class="mt-1 text-sm text-muted-foreground">{dayLabel(local)}</p>
  {#if !unknown}<p class="text-sm text-muted-foreground">{city} time</p>{/if}
</div>
