<script lang="ts">
  import { Button } from "$lib/components/ui/button";

  export type Row = { key: string; name: string; sub?: string | null; value: string };
  let { title, rows, limit = 5 }: { title: string; rows: Row[]; limit?: number } = $props();
  let all = $state(false);
  const shown = $derived(all ? rows : rows.slice(0, limit));
  const id = $derived(`top-${title.toLowerCase().replace(/\W+/g, "-")}`);
</script>

{#if rows.length}
  <section aria-labelledby={id} class="space-y-2">
    <h3 {id} class="eyebrow px-1">{title}</h3>
    <ol class="rows">
      {#each shown as r, i (r.key)}
        <li class="row flex-nowrap">
          <div class="flex min-w-0 flex-1 items-baseline gap-3">
            <span class="w-5 shrink-0 text-sm tabular-nums text-muted-foreground">{i + 1}</span>
            <div class="min-w-0"><p class="truncate font-medium" title={r.name}>{r.name}</p>{#if r.sub}<p class="truncate text-sm text-muted-foreground" title={r.sub}>{r.sub}</p>{/if}</div>
          </div>
          <span class="shrink-0 whitespace-nowrap text-sm tabular-nums text-muted-foreground">{r.value}</span>
        </li>
      {/each}
    </ol>
    {#if rows.length > limit}
      <Button variant="ghost" size="sm" aria-expanded={all} onclick={() => (all = !all)}>{all ? "Show fewer" : `Show all ${rows.length}`}</Button>
    {/if}
  </section>
{/if}
