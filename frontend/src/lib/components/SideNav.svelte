<script lang="ts">
  import { route } from "$lib/app.svelte";
  import NavLink from "$lib/components/NavLink.svelte";
  import { NAV, pageFor } from "$lib/nav";

  // From 1024px up: a slim sidebar under the top bar; TabBar takes over below.
  const current = $derived(pageFor(route.page));
</script>

<aside class="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-56 shrink-0 border-r border-sidebar-border bg-sidebar p-3 lg:block">
  <nav aria-label="Main" class="flex flex-col gap-1">
    {#each NAV as item (item.page)}<NavLink {item} current={current === item.page} />{/each}
  </nav>
</aside>
