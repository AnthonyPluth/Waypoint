<script lang="ts">
  import type { Trip } from "$lib/api-types";
  import { thumbnailUrl } from "$lib/photos";
  import { worthMapping } from "$lib/route-replay";
  import { cardLabel, cardRange, nightsWords, tripPeople } from "$lib/trips";
  import AvatarStack from "./AvatarStack.svelte";
  import RouteTile from "./RouteTile.svelte";
  import Camera from "@lucide/svelte/icons/camera";

  type Props = { trip: Trip; today: string; photos?: number; covers?: number[]; distance?: string; roomy?: boolean; coversKnown?: boolean };
  let { trip, today, photos = 0, covers = [], distance = "", roomy = false, coversKnown = true }: Props = $props();

  let broken = $state<number[]>([]);
  const shown = $derived(covers.filter((id) => !broken.includes(id)).slice(0, 3));
  const counted = $derived(covers.length > 0 ? photos : 0);
  const label = $derived(cardLabel(trip, counted, distance));
  const nights = $derived(nightsWords(trip));
  const people = $derived(tripPeople(trip));
  const whole = $derived(shown.length < 2);
  const layout = $derived(shown.length === 3 ? "grid-cols-[2fr_1fr] grid-rows-2" : shown.length === 2 ? "grid-cols-[2fr_1fr]" : "grid-cols-1");
</script>

<a class="block overflow-hidden rounded-2xl border border-border bg-card shadow-card transition-colors hover:bg-surface-3 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none" href={`#trip/${trip.id}`} aria-label={label}>
  <span class={`relative block overflow-hidden ${roomy ? "h-[220px]" : "h-[168px]"}`} aria-hidden="true" data-testid="past-mosaic">
    {#if shown.length}
      <span class={`grid size-full gap-0.5 bg-surface-3 ${layout}`}>
        {#each shown as id, i (id)}
          <img class={`size-full min-h-0 min-w-0 object-cover ${i === 0 && shown.length === 3 ? "row-span-2" : ""}`} src={thumbnailUrl(id)} alt="" loading="lazy" decoding="async" draggable="false" onerror={() => (broken = [...broken, id])} />
        {/each}
      </span>
    {:else}
      <RouteTile {trip} locate={coversKnown && covers.length === 0 && worthMapping(trip, today)} />
    {/if}
    <span class={`pointer-events-none absolute inset-y-0 left-0 bg-linear-to-b from-transparent from-[38%] to-background/84 ${whole ? "right-0" : "w-2/3"}`}></span>
    <span class={`absolute bottom-3 left-3.5 flex flex-col gap-0.5 text-white ${whole ? "right-3.5" : "right-[36%]"}`}>
      <span class={`font-bold leading-[1.15] tracking-tight [overflow-wrap:anywhere] ${roomy ? "text-[21px]" : "text-[19px]"}`}>{trip.name}</span>
      {#if roomy && trip.destination}<span class="truncate text-sm text-[#e1e6f0]">{trip.destination}</span>{/if}
    </span>
    {#if counted > 0}
      <span class={`absolute inline-flex items-center gap-[5px] rounded-full bg-[rgb(7_9_14/72%)] px-[9px] py-[3px] text-xs font-semibold text-white ${roomy ? "top-3 left-3" : "top-2.5 left-2.5"}`} data-testid="photo-pill"><Camera class="size-[13px]" aria-hidden="true" />{counted.toLocaleString()}</span>
    {/if}
  </span>
  <span class="flex items-center justify-between gap-3 px-3.5 py-2.5" aria-hidden="true" data-testid="past-footer">
    <span class="flex min-w-0 flex-wrap gap-x-2.5 gap-y-0.5 text-sm text-muted-foreground">
      <span class="font-semibold text-foreground">{cardRange(trip)}</span>
      {#if nights}<span>{nights}</span>{/if}
      {#if distance}<span>{distance}</span>{/if}
    </span>
    <span><AvatarStack {people} /></span>
  </span>
</a>
