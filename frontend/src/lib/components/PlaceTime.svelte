<script lang="ts">
  import { placeTime } from "$lib/trips";

  // A time where it happens ("7:00 PM"), with what it is for you in brackets when your zone's offset then differs.
  let { local, zone, mine }: { local: string; zone: string; mine?: string } = $props();
  const shown = $derived(placeTime(local, zone, mine));
</script>

<time datetime={local}>{shown.text}</time>{#if shown.yours}{" "}<span class="text-muted-foreground" title="The same moment in your time zone">[{shown.yours}]</span>{/if}
