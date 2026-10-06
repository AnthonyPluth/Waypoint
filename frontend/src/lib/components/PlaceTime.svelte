<script lang="ts">
  import { placeTime } from "$lib/trips";

  let { local, zone, mine }: { local: string; zone: string; mine?: string } = $props();
  const shown = $derived(placeTime(local, zone, mine));
</script>

<time datetime={local}>{shown.text}</time>{#if shown.yours}{" "}<span class="text-muted-foreground" title="The same moment in your time zone">[{shown.yours}]</span>{/if}
