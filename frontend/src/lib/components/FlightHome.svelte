<script lang="ts">
  import type { Snippet } from "svelte";
  import type { FlightStatus, FlightStatusPause, Segment } from "$lib/api-types";
  import { cityNames } from "$lib/cities.svelte";
  import FlightHero from "$lib/components/FlightHero.svelte";
  import { flightCardView } from "$lib/flightcard";

  type Props = { segment: Segment; status?: FlightStatus; liveOn?: boolean; now?: number; online?: boolean; eyebrow: string; tripName: string; paused?: FlightStatusPause | null; ondetail?: (from: HTMLElement) => void; footer?: Snippet; class?: string };
  let { segment, status, liveOn = false, now = Date.now(), online = true, eyebrow, tripName, paused = null, ondetail, footer, class: cls = "" }: Props = $props();

  const cities = cityNames(() => [segment.origin, segment.destination, status?.destination]);
  const view = $derived(flightCardView({ segment, status, liveOn, now, online, city: (code) => cities[code] || code }));
</script>

<section class={cls} data-flight-home>
  <p class="eyebrow mb-2">{eyebrow}{#if tripName}<span>{" · "}{tripName}</span>{/if}</p>
  <FlightHero {segment} {view} {cities} {now} {paused} href={`#trip/${segment.trip_id}/flight/${segment.id}`} linkLabel={view.name} level={2} {ondetail} {footer} />
</section>
