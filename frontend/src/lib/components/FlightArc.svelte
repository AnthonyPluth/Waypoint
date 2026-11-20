<script lang="ts">
  import type { Snippet } from "svelte";
  import { arcHeading, arcPoint, arcTravelled } from "$lib/flightcard";

  type Props = { progress: number | null; box?: number; pixels?: number; plane?: number; class?: string; hero?: boolean; landed?: boolean; children?: Snippet };
  let { progress, box = 60, pixels = 46, plane = 20, class: cls = "", hero = false, landed = false, children }: Props = $props();

  const PLANE = "M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z";
  let width = $state(0);
  const point = $derived(progress === null ? null : arcPoint(progress, pixels));
  const heading = $derived(progress === null ? 0 : arcHeading(progress, width || 160, pixels));
</script>

<div class={`relative ${cls}`} style={`height: ${box}px`} bind:clientWidth={width} aria-hidden="true" data-arc>
  <svg class="absolute inset-x-0 top-0 w-full" style={`height: ${pixels}px`} viewBox="0 0 100 40" preserveAspectRatio="none">
    <path d="M2 38 Q50 -16 98 38" fill="none" class={hero ? "stroke-label/60" : "stroke-map-border"} stroke-width="2" stroke-linecap="round" stroke-dasharray="1 5" vector-effect="non-scaling-stroke" />
    {#if progress !== null || !hero}
      <path d={arcTravelled(progress ?? 0)} fill="none" class={hero ? "stroke-primary" : "stroke-map-route"} stroke-width="2.5" stroke-linecap="round" vector-effect="non-scaling-stroke" data-travelled />
    {/if}
  </svg>
  {#if point}
    <span class={`absolute grid place-items-center ${hero ? (landed ? "text-foreground" : "text-primary") : "text-map-route"}`} style={`width: ${plane + 2}px; height: ${plane + 2}px; left: ${point.left}%; top: ${point.top}px; transform: translate(-50%, -50%) rotate(${90 + heading}deg)`} data-plane><svg style={`width: ${plane}px; height: ${plane}px`} aria-hidden="true" viewBox="0 0 24 24" fill="currentColor"><path d={PLANE} /></svg></span>
  {/if}
  {@render children?.()}
</div>
