<script lang="ts">
  import { app } from "$lib/app.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import ExternalLink from "@lucide/svelte/icons/external-link";

  const DOCS = "https://anthonypluth.github.io/Waypoint";
  const on = $derived(app.state?.mapkit === true);
</script>

<section aria-labelledby="maps-title" class="space-y-2">
  <h2 id="maps-title" class="eyebrow px-1">Maps</h2>
  <div class="rows">
    <div class="row" data-testid="maps-row">
      <div class="min-w-0 flex-1">
        <p class="font-medium">Maps</p>
        {#if on}
          <p class="text-sm text-muted-foreground">Apple Maps. The route replay, Past trips cards and Stats are drawn by Apple; Apple learns the areas shown.</p>
          <a class="inline-flex min-h-11 items-center gap-1 text-sm underline underline-offset-2" href={`${DOCS}/start/trips/#apples-map-for-the-route-replay`} target="_blank" rel="noopener noreferrer">What Apple learns <ExternalLink class="size-3.5" aria-hidden="true" /></a>
        {:else}
          <p class="text-sm text-muted-foreground">Off: this server has no MapKit key, so Waypoint shows no maps or route replays.</p>
          <a class="inline-flex min-h-11 items-center gap-1 text-sm underline underline-offset-2" href={`${DOCS}/reference/configuration/`} target="_blank" rel="noopener noreferrer">How to turn on maps <ExternalLink class="size-3.5" aria-hidden="true" /></a>
        {/if}
      </div>
      <StatusChip chip={on ? { label: "On", tone: "info" } : { label: "Off", tone: "quiet" }} />
    </div>
  </div>
</section>
