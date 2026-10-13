<script lang="ts" module>
  export const clampProgress = (progress: number | null | undefined): number =>
    progress == null || Number.isNaN(progress) ? 0 : Math.min(1, Math.max(0, progress));
</script>

<script lang="ts">
  import Plane from "@lucide/svelte/icons/plane";

  let { progress = 0, label = "", class: cls = "" }: { progress?: number | null; label?: string; class?: string } = $props();

  const along = $derived(clampProgress(progress));
  const percent = $derived(`${Math.round(along * 1000) / 10}%`);
  const height = $derived(`${Math.round((1 - 2 * along * (1 - along)) * 1000) / 10}%`);
  const tilt = $derived(Math.round((2 * along - 1) * 30));
</script>

<span class={`flex h-12 min-w-0 items-center px-2.5 ${cls}`} data-progress={along} role={label ? "img" : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : "true"}>
  <span class="relative my-2.5 h-7 w-full" style={`--along: ${percent}`}>
    <svg class="absolute inset-0 size-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" fill="none" aria-hidden="true">
      <path d="M0 100 Q50 0 100 100" class="stroke-border" stroke-width="2" stroke-dasharray="4 4" vector-effect="non-scaling-stroke" />
    </svg>
    <svg class="absolute inset-0 size-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" fill="none" aria-hidden="true" style="clip-path: inset(-4px calc(100% - var(--along)) -4px -4px)">
      <path d="M0 100 Q50 0 100 100" class="stroke-primary" stroke-width="2" vector-effect="non-scaling-stroke" />
    </svg>
    <Plane class="absolute size-5 -translate-x-1/2 -translate-y-1/2 text-primary" style={`left: var(--along); top: ${height}; transform: translate(-50%, -50%) rotate(${45 + tilt}deg)`} />
  </span>
</span>
