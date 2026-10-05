<script lang="ts">
  import { Button } from "$lib/components/ui/button";

  // A top-five list (the first `limit` rows), with Show all to see the rest. Each row has a name, a line under it if there's
  // something to say, and a count.
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
        <li class="row">
          <div class="flex min-w-0 items-baseline gap-3">
            <span class="w-5 shrink-0 text-sm tabular-nums text-muted-foreground">{i + 1}</span>
            <div class="min-w-0"><p class="truncate font-medium">{r.name}</p>{#if r.sub}<p class="truncate text-sm text-muted-foreground">{r.sub}</p>{/if}</div>
          </div>
          <span class="text-sm tabular-nums text-muted-foreground">{r.value}</span>
        </li>
      {/each}
    </ol>
    {#if rows.length > limit}
      <Button variant="ghost" size="sm" aria-expanded={all} onclick={() => (all = !all)}>{all ? "Show fewer" : `Show all ${rows.length}`}</Button>
    {/if}
  </section>
{/if}
