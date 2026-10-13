<script lang="ts" module>
  export const clampProgress = (progress: number | null | undefined): number =>
    progress == null || Number.isNaN(progress) ? 0 : Math.min(1, Math.max(0, progress));

  export const headingDegrees = (progress: number, width: number, height: number): number =>
    width > 0 ? Math.round((Math.atan2(-2 * height * (1 - 2 * progress), width) * 180) / Math.PI) || 0 : 0;
</script>

<script lang="ts">
  import Plane from "@lucide/svelte/icons/plane";

  let { progress = 0, label = "", class: cls = "" }: { progress?: number | null; label?: string; class?: string } = $props();

  const along = $derived(clampProgress(progress));
  const percent = $derived(`${Math.round(along * 1000) / 10}%`);
  let width = $state(0);
  let height = $state(0);
  const lift = $derived(`${Math.round((1 - 2 * along * (1 - along)) * 1000) / 10}%`);
  const heading = $derived(headingDegrees(along, width, height));
</script>

<span class={`flex h-16 min-w-0 items-center px-2.5 ${cls}`} data-progress={along} role={label ? "img" : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : "true"}>
  <span class="relative my-3 h-10 w-full" style={`--along: ${percent}`} bind:clientWidth={width} bind:clientHeight={height}>
    <svg class="absolute inset-0 size-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" fill="none" aria-hidden="true">
      <path d="M0 100 Q50 0 100 100" class="stroke-border" stroke-width="2" stroke-dasharray="4 4" vector-effect="non-scaling-stroke" />
    </svg>
    <svg class="absolute inset-0 size-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" fill="none" aria-hidden="true" style="clip-path: inset(-4px calc(100% - var(--along)) -4px -4px)">
      <path d="M0 100 Q50 0 100 100" class="stroke-primary" stroke-width="2" vector-effect="non-scaling-stroke" />
    </svg>
    <Plane class="absolute size-5 text-primary" style={`left: var(--along); top: ${lift}; transform: translate(-50%, -50%) rotate(${45 + heading}deg)`} />
  </span>
</span>
