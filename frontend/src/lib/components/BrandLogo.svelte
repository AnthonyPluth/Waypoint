<script lang="ts">
  // The logo of a booking's airline, hotel, rental company or cruise line, which the server gives only once Waypoint has fetched one
  // (waypoint/domain/logos.py). Nothing at all without one, or if the image fails to load. Drawn as it comes, with no tile behind it.
  // A hotel whose own brand has no logo shows its group's, with the brand's name under it as a small chip ("Hyatt Regency").
  let { src, label = null, size = 40, class: cls = "" }: { src: string | null; label?: string | null; size?: number; class?: string } = $props();
  let failed = $state<string | null>(null);   // the logo that failed to load
</script>

{#if src && failed !== src}
  <span class={`inline-flex shrink-0 flex-col items-center gap-1 ${cls}`}>
    <img class="rounded-lg object-contain" {src} alt="" width={size} height={size} loading="lazy" onerror={() => (failed = src)} />
    {#if label}<span class="max-w-20 truncate rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium leading-none text-muted-foreground" title={label}>{label}</span>{/if}
  </span>
{/if}
