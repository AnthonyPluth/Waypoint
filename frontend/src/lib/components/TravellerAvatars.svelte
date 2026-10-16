<script lang="ts">
  import type { Person } from "$lib/api-types";
  import { avatarTone } from "$lib/avatar";
  import { initials } from "$lib/nav";

  let { people, selected, onpick }: { people: Person[]; selected: number | null; onpick: (id: number | null) => void } = $props();
</script>

<div class="flex flex-col gap-2 md:flex-row md:items-center md:gap-3">
  <span class="eyebrow" aria-hidden="true">Travelling</span>
  <div class="flex flex-wrap gap-2" role="group" aria-label="Travelling">
    {#each people as p (p.id)}
      {@const on = selected === p.id}
      <button type="button" class={`inline-flex size-10 phone:size-11 items-center justify-center rounded-full text-sm font-semibold outline-none before:content-[attr(data-initials)] transition-opacity focus-visible:ring-[3px] focus-visible:ring-ring/50 ${avatarTone({ id: p.id, name: p.display_name })} ${on ? "ring-2 ring-primary" : selected ? "opacity-60" : ""}`}
        aria-label={p.display_name} data-initials={initials(p.display_name)} aria-pressed={on} onclick={() => onpick(on ? null : p.id)}></button>
    {/each}
  </div>
</div>
