<script lang="ts">
  import { route } from "$lib/app.svelte";
  import NavLink from "$lib/components/NavLink.svelte";
  import { NAV, navFor } from "$lib/nav";

  // On a phone or tablet (below 1024px) the pages are tabs along the bottom, where a thumb reaches; the sidebar takes over above.
  const current = $derived(navFor(route.page));
</script>

<nav aria-label="Main" class="fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
  {#each NAV as item (item.page)}<NavLink {item} current={current === item.page} tab />{/each}
</nav>
