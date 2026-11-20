<script lang="ts">
  import type { Snippet } from "svelte";
  import type { FlightStatus, FlightStatusPause, Segment } from "$lib/api-types";
  import { cityNames } from "$lib/cities.svelte";
  import FlightHero from "$lib/components/FlightHero.svelte";
  import { flightCardView } from "$lib/flightcard";

  type Props = { segment: Segment; status?: FlightStatus; liveOn?: boolean; now?: number; online?: boolean; highlight?: boolean; level?: 2 | 3; paused?: FlightStatusPause | null; href?: string; travellers?: boolean; ondetail?: (from: HTMLElement) => void; footer?: Snippet };
  let { segment, status, liveOn = false, now = Date.now(), online = true, highlight = false, level = 2, paused = null, href, travellers = false, ondetail, footer }: Props = $props();

  const cities = cityNames(() => [segment.origin, segment.destination, status?.destination]);
  const view = $derived(flightCardView({ segment, status, liveOn, now, online, city: (code) => cities[code] || code }));
</script>

<FlightHero {segment} {view} {cities} {now} {paused} {href} linkLabel={`${view.name}, open live status`} {highlight} {level} {travellers} {ondetail} {footer} />
