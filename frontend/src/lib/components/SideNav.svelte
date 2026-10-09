<script lang="ts">
  import { route } from "$lib/app.svelte";
  import NavLink from "$lib/components/NavLink.svelte";
  import { NAV, navFor } from "$lib/nav";

  const current = $derived(navFor(route.page));
</script>

<aside class="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-60 shrink-0 border-r border-sidebar-border bg-sidebar px-3 py-5 lg:block">
  <nav aria-label="Main" class="flex flex-col gap-1.5">
    {#each NAV as item (item.page)}<NavLink {item} current={current === item.page} />{/each}
  </nav>
</aside>
