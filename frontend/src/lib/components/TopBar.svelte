<script lang="ts">
  import { app } from "$lib/app.svelte";
  import Logo from "$lib/components/Logo.svelte";
  import { initials } from "$lib/nav";

  const user = $derived(app.state?.user);
  const who = $derived(user && !user.local ? user.name || user.email || "" : "");
</script>

<header class="sticky top-0 z-30 border-b border-border bg-surface-1/80 pt-[env(safe-area-inset-top)] backdrop-blur-xl">
  <div class="flex h-14 items-center justify-between gap-3 px-4 md:px-6">
    <a href="#upcoming" class="flex items-center gap-2.5 rounded-lg text-lg font-bold tracking-tight outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
      <Logo />Waypoint
    </a>
    {#if who}
      <a href="#settings" title={who} aria-label={`Signed in as ${who}`}
        class="flex size-9 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground shadow-elevation-1 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">{initials(who)}</a>
    {/if}
  </div>
</header>
