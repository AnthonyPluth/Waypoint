<script lang="ts">
  // The logo of a booking's airline, hotel, rental company or cruise line, which the server gives only once Waypoint has fetched one
  // from Logo.dev (waypoint/domain/logos.py). Nothing at all without one, or if the image fails to load. Drawn as it comes, with no tile
  // behind it.
  let { src, size = 40, class: cls = "" }: { src: string | null; size?: number; class?: string } = $props();
  let failed = $state<string | null>(null);   // the logo that failed to load
</script>

{#if src && failed !== src}
  <img class={`shrink-0 rounded-lg object-contain ${cls}`} {src} alt="" width={size} height={size}
    loading="lazy" onerror={() => (failed = src)} />
{/if}
