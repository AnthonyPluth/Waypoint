<script lang="ts">
  import { avatarTone, type AvatarPerson } from "$lib/avatar";
  import { initials } from "$lib/nav";

  let { people }: { people: AvatarPerson[] } = $props();

  const MAX = 4;
  const shown = $derived(people.slice(0, MAX));
  const hidden = $derived(people.length - shown.length);
  const label = $derived(people.map((p) => p.name).join(", "));
</script>

{#if people.length}
  <span class="flex shrink-0 items-center" role="img" aria-label={label} data-testid="avatar-stack">
    {#each shown as person, i (i)}
      <span
        class={`inline-flex size-7 items-center justify-center rounded-full text-[11px] font-semibold ring-2 ring-card ${i ? "-ml-2" : ""} ${avatarTone(person)}`}
        aria-hidden="true"
      >{initials(person.name)}</span>
    {/each}
    {#if hidden > 0}
      <span class="-ml-2 inline-flex size-7 items-center justify-center rounded-full bg-surface-3 text-[11px] font-semibold text-muted-foreground ring-2 ring-card" aria-hidden="true">+{hidden}</span>
    {/if}
  </span>
{/if}
