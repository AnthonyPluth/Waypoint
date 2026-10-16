<script lang="ts">
  import { app, route } from "$lib/app.svelte";
  import Logo from "$lib/components/Logo.svelte";
  import NavLink from "$lib/components/NavLink.svelte";
  import { initials, NAV, navFor } from "$lib/nav";

  const current = $derived(navFor(route.page));
  const user = $derived(app.state?.user);
  const who = $derived(user && !user.local ? user.name || user.email || "" : "");
</script>

<aside class="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-5 border-r border-sidebar-border bg-sidebar px-3 py-5 lg:flex">
  <a href="#upcoming" class="flex h-11 items-center gap-2.5 rounded-xl px-3 text-lg font-bold tracking-tight outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
    <Logo />Waypoint
  </a>
  <nav aria-label="Main" class="flex flex-col gap-1.5">
    {#each NAV as item (item.page)}<NavLink {item} current={current === item.page} />{/each}
  </nav>
  {#if who}
    <a href="#settings" title={who} aria-label={`Signed in as ${who}`} data-testid="side-user"
      class="mt-auto flex min-h-11 items-center gap-3 rounded-xl px-3 py-2 transition-colors outline-none hover:bg-sidebar-accent/60 focus-visible:ring-[3px] focus-visible:ring-ring/50">
      <span class="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground" aria-hidden="true">{initials(who)}</span>
      <span class="flex min-w-0 flex-col" aria-hidden="true">
        <span class="truncate text-sm font-medium text-sidebar-foreground">{who}</span>
        <span class="text-xs text-muted-foreground">Signed in</span>
      </span>
    </a>
  {/if}
</aside>
