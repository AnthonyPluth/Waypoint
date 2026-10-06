<script lang="ts">
  import { route } from "$lib/app.svelte";
  import NavLink from "$lib/components/NavLink.svelte";
  import { NAV, navFor } from "$lib/nav";

  const current = $derived(navFor(route.page));
</script>

<nav aria-label="Main" class="fixed inset-x-0 bottom-0 z-30 flex border-t border-border/60 bg-background/80 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden">
  {#each NAV as item (item.page)}<NavLink {item} current={current === item.page} tab />{/each}
</nav>
