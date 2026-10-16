<script lang="ts">
  import { chipClass } from "$lib/chip";

  let { years, selected, onpick }: { years: number[]; selected: number | null; onpick: (year: number | null) => void } = $props();
</script>

<div class="flex flex-col gap-2 md:flex-row md:items-center md:gap-3">
  <span class="eyebrow" aria-hidden="true">Year</span>
  <div class="flex flex-wrap gap-2" role="group" aria-label="Year">
    {#each years as y (y)}
      <button type="button" class={chipClass(selected === y)} aria-pressed={selected === y} onclick={() => onpick(selected === y ? null : y)}>{y}</button>
    {/each}
  </div>
</div>
