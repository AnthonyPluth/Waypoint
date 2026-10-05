<script lang="ts">
  import type { NavItem } from "$lib/nav";
  import { cn } from "$lib/utils";

  // One page's link, in the tab bar (`tab`: icon over label) or the sidebar (icon beside it).
  let { item, current, tab = false }: { item: NavItem; current: boolean; tab?: boolean } = $props();
</script>

<a href={`#${item.page}`} aria-current={current ? "page" : undefined}
  class={cn("relative flex items-center transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
    tab ? "min-h-14 flex-1 flex-col justify-center gap-0.5 text-xs font-medium" : "h-10 gap-3 rounded-lg px-3 text-sm font-medium",
    current
      ? tab ? "text-primary" : "bg-sidebar-accent text-sidebar-accent-foreground"
      : "text-muted-foreground hover:text-foreground " + (tab ? "" : "hover:bg-sidebar-accent/60"))}>
  {#if tab && current}<span class="absolute top-0 h-0.5 w-10 rounded-full bg-primary" aria-hidden="true"></span>{/if}
  <item.icon class={tab ? "size-6" : cn("size-5", current && "text-primary")} />
  <span>{item.label}</span>
</a>
