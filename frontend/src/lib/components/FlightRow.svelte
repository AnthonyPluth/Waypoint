<script lang="ts">
  import type { FlightStatus, Segment } from "$lib/api-types";
  import { cityNames } from "$lib/cities.svelte";
  import KindTile from "$lib/components/KindTile.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { flightCardView, rowMeta, routeTitle } from "$lib/flightcard";
  import { dayIn, viewerZone } from "$lib/trips";

  type Props = { segment: Segment; status?: FlightStatus; liveOn?: boolean; now?: number; online?: boolean };
  let { segment, status, liveOn = false, now = Date.now(), online = true }: Props = $props();

  const cities = cityNames(() => [segment.origin, segment.destination, status?.destination]);
  const view = $derived(flightCardView({ segment, status, liveOn, now, online, city: (code) => cities[code] || code }));
  const meta = $derived(rowMeta(view, dayIn(now, viewerZone()), viewerZone()));
</script>

<li class="relative flex min-h-14 items-center gap-3 px-4 py-3 hover:bg-muted/40" data-flight-row data-state={view.state}>
  <a class="absolute inset-0 z-[1] outline-none focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/60" href={`#trip/${segment.trip_id}/flight/${segment.id}`} aria-label={view.name}></a>
  <span class="flex min-w-0 flex-1 items-center gap-3" aria-hidden="true">
    <KindTile kind="flight" size={34} decorative />
    <span class="min-w-0 flex-1">
      <b class="block truncate text-body font-semibold">{routeTitle(view)}</b>
      <span class="block text-caption text-muted-foreground">{meta}</span>
    </span>
    {#if view.pill}<StatusChip chip={view.pill} class="py-[3px]! font-bold! uppercase tracking-[0.04em]" />{/if}
  </span>
</li>
