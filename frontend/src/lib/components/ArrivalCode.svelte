<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import ConfirmationCode from "$lib/components/ConfirmationCode.svelte";
  import GateCode from "$lib/components/GateCode.svelte";

  type Props = { segment: Segment; now: number; open?: boolean };
  let { segment, now, open = $bindable(false) }: Props = $props();
</script>

{#if segment.kind === "parking"}
  <GateCode {segment} {now} buttons={false} bind:showing={open} />
{:else}
  <ConfirmationCode {segment} bind:open />
{/if}
