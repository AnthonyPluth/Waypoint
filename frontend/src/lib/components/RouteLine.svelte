<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import AirportCode from "$lib/components/AirportCode.svelte";
  import { headline, route } from "$lib/trips";
  import { cn } from "$lib/utils";
  import Plane from "@lucide/svelte/icons/plane";

  let { segment, progress = null, class: klass = "" }:
    { segment: Segment; progress?: number | null; class?: string } = $props();

  const ends = $derived(route(segment));
  const at = $derived(Math.min(1, Math.max(0, progress ?? 0)));
  const place = $derived(`${Math.round(at * 1000) / 10}%`);
</script>

{#if ends}
  <span class={cn("inline-flex items-center gap-2", klass)} data-testid="route-line" data-progress={at}>
    <AirportCode code={ends[0]} />
    <span class="relative mx-1 flex h-5 min-w-20 flex-1 items-center">
      <span class="absolute inset-x-0 top-1/2 -translate-y-1/2 border-t border-dashed border-foreground/40" aria-hidden="true"></span>
      <span class="absolute left-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-signal" aria-hidden="true" data-testid="route-fill" style={`width:${place}`}></span>
      <span class="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-signal" aria-hidden="true" data-testid="route-plane" style={`left:${place}`}>
        <Plane class="size-4 rotate-45" />
      </span>
      <span class="sr-only">{" → "}</span>
    </span>
    <AirportCode code={ends[1]} />
  </span>
{:else}{headline(segment)}{/if}
