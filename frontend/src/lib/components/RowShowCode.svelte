<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import GateCode from "$lib/components/GateCode.svelte";
  import { headline } from "$lib/trips";

  type Props = { segment: Segment; now: number };
  let { segment, now }: Props = $props();

  let showing = $state(false);
  let button = $state<HTMLElement | null>(null);
</script>

<button bind:this={button} type="button" class="relative z-10 inline-flex min-h-11 shrink-0 cursor-pointer items-center rounded-md px-1 text-sm font-bold text-primary outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
  aria-label={`Show code for ${headline(segment)}`} onclick={() => (showing = true)}>Show code</button>
<GateCode {segment} {now} buttons={false} readOnly bind:showing={() => showing, (v) => { showing = v; if (!v) button?.focus(); }} />
