<script lang="ts">
  let { years, selected, onpick }: { years: number[]; selected: number | null; onpick: (year: number | null) => void } = $props();

  const chipClass = (on: boolean) => `inline-flex min-h-10 phone:min-h-11 items-center rounded-full border px-4 text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 ${on ? "border-primary bg-primary/15 text-primary" : "border-input bg-secondary hover:bg-input/60"}`;
</script>

<div class="flex flex-col gap-2 md:flex-row md:items-center md:gap-3">
  <span class="eyebrow" aria-hidden="true">Year</span>
  <div class="flex flex-wrap gap-2" role="group" aria-label="Year">
    {#each years as y (y)}
      <button type="button" class={chipClass(selected === y)} aria-pressed={selected === y} onclick={() => onpick(selected === y ? null : y)}>{y}</button>
    {/each}
  </div>
</div>
