<script lang="ts">
  import type { Snippet } from "svelte";
  import type { FlightStatus, FlightStatusPause, Segment } from "$lib/api-types";
  import { cityNames } from "$lib/cities.svelte";
  import FlightHero from "$lib/components/FlightHero.svelte";
  import { flightCardView } from "$lib/flightcard";
  import type { HeroConnection } from "$lib/flighthero";
  import { journeyLegs } from "$lib/journey";

  type Props = { segment: Segment; status?: FlightStatus; liveOn?: boolean; now?: number; online?: boolean; highlight?: boolean; level?: 2 | 3; paused?: FlightStatusPause | null; href?: string; travellers?: boolean; tripSegments?: Segment[]; statusOf?: (id: number) => FlightStatus | undefined; ondetail?: (from: HTMLElement) => void; detailOpen?: boolean; detailId?: string; detail?: Snippet; footer?: Snippet };
  let { segment, status, liveOn = false, now = Date.now(), online = true, highlight = false, level = 2, paused = null, href, travellers = false, tripSegments = [], statusOf, ondetail, detailOpen, detailId, detail, footer }: Props = $props();

  const legs = $derived(journeyLegs(segment, tripSegments));
  const cities = cityNames(() => [segment.origin, segment.destination, status?.destination, ...(legs ?? []).flatMap((leg) => [leg.origin, leg.destination])]);
  const viewOf = (leg: Segment, live: FlightStatus | undefined) => flightCardView({ segment: leg, status: live, liveOn, now, online, city: (code) => cities[code] || code });
  const view = $derived(viewOf(segment, status));
  const index = $derived((segment.journey?.leg ?? 1) - 1);
  const connection: HeroConnection | null = $derived(legs ? { legs: legs.map((leg, i) => ({ segment: leg, view: i === index ? view : viewOf(leg, liveOn ? statusOf?.(leg.id) : undefined) })), index } : null);
</script>

<FlightHero {segment} {view} {cities} {now} {paused} {href} linkLabel={`${view.name}, open live status`} {highlight} {level} {travellers} {connection} {ondetail} {detailOpen} {detailId} {detail} {footer} />
