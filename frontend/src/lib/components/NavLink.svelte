<script lang="ts">
  import { app } from "$lib/app.svelte";
  import type { NavItem } from "$lib/nav";
  import { cn } from "$lib/utils";

  let { item, current, tab = false, menu = false }: { item: NavItem; current: boolean; tab?: boolean; menu?: boolean } = $props();
  const waiting = $derived(item.badge && app.state ? item.badge(app.state) : 0);
</script>

<a href={`#${item.page}`} aria-current={current ? "page" : undefined}
  class={cn("relative flex items-center transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
    tab ? "min-h-14 flex-1 flex-col justify-center gap-0.5 rounded-2xl text-xs font-medium" : "h-11 gap-3 rounded-xl px-3 text-sm font-medium",
    current
      ? tab ? "bg-surface-3 text-foreground" : menu ? "bg-surface-3 font-semibold text-foreground" : "bg-sidebar-accent font-semibold text-sidebar-accent-foreground"
      : "text-muted-foreground hover:text-foreground " + (tab ? "" : "hover:bg-sidebar-accent/60"))}>
  <span class="relative flex">
    <item.icon class={tab ? cn("size-6", current && "text-primary") : cn("size-5", current && "text-primary")} />
    {#if waiting && tab}<span class="absolute -top-1 -right-2 min-w-4 rounded-full bg-signal px-1 text-center text-[10px] leading-4 font-semibold text-signal-foreground" aria-hidden="true" data-testid="nav-badge">{waiting > 99 ? "99+" : waiting}</span>{/if}
  </span>
  <span>{item.label}</span>
  {#if waiting}<span class={cn("rounded-full bg-signal px-1.5 text-center text-xs leading-5 font-semibold text-signal-foreground", tab ? "sr-only" : "ml-auto min-w-5")} data-testid={tab ? undefined : "nav-badge"}>{waiting > 99 ? "99+" : waiting}<span class="sr-only"> waiting</span></span>{/if}
</a>
