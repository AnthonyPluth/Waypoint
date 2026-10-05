<script lang="ts">
  import { app } from "$lib/app.svelte";
  import type { NavItem } from "$lib/nav";
  import { cn } from "$lib/utils";

  // One page's link, in the tab bar (`tab`: icon over label) or the sidebar (icon beside it). A page with something waiting
  // shows how much, as a number on the link (and in its name, for a screen reader).
  let { item, current, tab = false }: { item: NavItem; current: boolean; tab?: boolean } = $props();
  const waiting = $derived(item.badge && app.state ? item.badge(app.state) : 0);
</script>

<a href={`#${item.page}`} aria-current={current ? "page" : undefined}
  class={cn("relative flex items-center transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
    tab ? "min-h-14 flex-1 flex-col justify-center gap-0.5 text-xs font-medium" : "h-10 gap-3 rounded-lg px-3 text-sm font-medium",
    current
      ? tab ? "text-primary" : "bg-sidebar-accent text-sidebar-accent-foreground"
      : "text-muted-foreground hover:text-foreground " + (tab ? "" : "hover:bg-sidebar-accent/60"))}>
  {#if tab && current}<span class="absolute top-0 h-0.5 w-10 rounded-full bg-primary" aria-hidden="true"></span>{/if}
  <span class="relative flex">
    <item.icon class={tab ? "size-6" : cn("size-5", current && "text-primary")} />
    {#if waiting && tab}<span class="absolute -top-1 -right-2 min-w-4 rounded-full bg-signal px-1 text-center text-[10px] leading-4 font-semibold text-signal-foreground" aria-hidden="true" data-testid="nav-badge">{waiting > 99 ? "99+" : waiting}</span>{/if}
  </span>
  <span>{item.label}</span>
  {#if waiting}<span class={cn("rounded-full bg-signal px-1.5 text-center text-xs leading-5 font-semibold text-signal-foreground", tab ? "sr-only" : "ml-auto min-w-5")} data-testid={tab ? undefined : "nav-badge"}>{waiting > 99 ? "99+" : waiting}<span class="sr-only"> waiting</span></span>{/if}
</a>
