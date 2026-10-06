<script lang="ts">
  let { src, label = null, size = 40, class: cls = "" }: { src: string | null; label?: string | null; size?: number; class?: string } = $props();
  let failed = $state<string | null>(null);
</script>

{#if src && failed !== src}
  <span class={`inline-flex shrink-0 flex-col items-center gap-1 ${cls}`}>
    <img class="rounded-lg object-contain" {src} alt="" width={size} height={size} loading="lazy" onerror={() => (failed = src)} />
    {#if label}<span class="max-w-20 truncate rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium leading-none text-muted-foreground" title={label}>{label}</span>{/if}
  </span>
{/if}
