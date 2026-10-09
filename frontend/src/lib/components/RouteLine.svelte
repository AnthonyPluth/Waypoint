<script lang="ts" module>
  export const clampProgress = (progress: number | null | undefined): number =>
    progress == null || Number.isNaN(progress) ? 0 : Math.min(1, Math.max(0, progress));
</script>

<script lang="ts">
  import Plane from "@lucide/svelte/icons/plane";

  let { progress = 0, label = "", class: cls = "" }: { progress?: number | null; label?: string; class?: string } = $props();

  const along = $derived(clampProgress(progress));
  const percent = $derived(`${Math.round(along * 1000) / 10}%`);
</script>

<span class={`flex h-6 min-w-0 items-center px-2.5 ${cls}`} data-progress={along} role={label ? "img" : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : "true"}>
  <span class="relative h-full w-full" style={`--along: ${percent}`}>
    <span class="absolute inset-x-0 top-1/2 border-t-2 border-dashed border-border"></span>
    <span class="absolute left-0 top-1/2 border-t-2 border-primary" style="width: var(--along)"></span>
    <Plane class="absolute top-1/2 size-5 -translate-x-1/2 -translate-y-1/2 rotate-45 text-primary" style="left: var(--along)" />
  </span>
</span>
