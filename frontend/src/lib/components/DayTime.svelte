<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import { dayOf, sameDay, untimed } from "$lib/trips";

  type Props = { segment: Segment; end?: boolean; dated?: boolean };
  let { segment: s, end = false, dated = false }: Props = $props();

  const local = $derived(end ? s.end_local : s.start_local);
  const collapsed = $derived(end && sameDay(s));
</script>

{#if s.kind === "visit"}
  {#if collapsed}Same day{:else}{dayOf(s, local)}{/if}
{:else if untimed(s)}
  {#if collapsed}<span>same day</span>{:else}{dayOf(s, local)}{/if}, <span class="text-muted-foreground">time not recorded</span>
{:else if dated}
  {dayOf(s, local)}, <PlaceTime {local} />
{:else}
  <PlaceTime {local} />
{/if}
