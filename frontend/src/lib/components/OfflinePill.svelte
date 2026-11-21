<script lang="ts">
  import { offline, offlineWorking, refreshOffline } from "$lib/offline.svelte";
  import CloudCheck from "@lucide/svelte/icons/cloud-check";
  import { onMount } from "svelte";

  onMount(() => {
    if (!offline.checked) void refreshOffline();
  });
</script>

{#if offlineWorking()}
  <a href="#settings/offline" class="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border border-status-ok-ink/30 bg-status-ok-soft px-3.5 text-sm font-medium text-status-ok-ink outline-none transition-colors hover:bg-status-ok-soft/70 focus-visible:ring-[3px] focus-visible:ring-ring/50 phone:size-11 phone:justify-center phone:px-0"
    data-testid="offline-pill">
    <CloudCheck class="size-4 shrink-0" aria-hidden="true" /><span class="phone:sr-only">Saved for offline</span>
  </a>
{/if}
