<script lang="ts">
  import { app, route } from "$lib/app.svelte";
  import NavLink from "$lib/components/NavLink.svelte";
  import { inMore, MORE, MORE_TAB, navFor, TABS } from "$lib/nav";
  import { cn } from "$lib/utils";

  let open = $state(false);
  let button = $state<HTMLButtonElement>();
  let menu = $state<HTMLElement>();

  const current = $derived(navFor(route.page));
  const moreCurrent = $derived(inMore(current));
  const currentLabel = $derived(MORE.find((m) => m.page === current)?.label);
  const waitingInMore = $derived(MORE.reduce((n, m) => n + (m.badge && app.state ? m.badge(app.state) : 0), 0));

  $effect(() => {
    void route.page;
    open = false;
  });

  function onKeydown(e: KeyboardEvent) {
    if (!open || e.key !== "Escape") return;
    open = false;
    button?.focus();
  }

  function onPointerDown(e: PointerEvent) {
    if (!open) return;
    const target = e.target as Node;
    if (!menu?.contains(target) && !button?.contains(target)) open = false;
  }

  function onFocusOut(e: FocusEvent) {
    const next = e.relatedTarget as Node | null;
    if (open && next && !menu?.contains(next) && !button?.contains(next)) open = false;
  }
</script>

<svelte:window onkeydown={onKeydown} onpointerdown={onPointerDown} />

<nav aria-label="Main" class="fixed inset-x-3 bottom-[calc(env(safe-area-inset-bottom)+0.75rem)] z-30 flex gap-1 rounded-[22px] border border-transparent bg-surface-2 p-1 shadow-[inset_0_1px_0_rgb(255_255_255/0.2),0_18px_40px_-16px_rgb(0_0_0/0.8)] supports-[backdrop-filter]:bg-white/[0.04] supports-[backdrop-filter]:backdrop-blur-[28px] supports-[backdrop-filter]:backdrop-saturate-200 supports-[backdrop-filter]:backdrop-brightness-110 lg:hidden">
  {#each TABS as item (item.page)}<NavLink {item} current={current === item.page} tab />{/each}
  <div class="relative flex flex-1" onfocusout={onFocusOut}>
    <button bind:this={button} type="button" aria-expanded={open} aria-controls="more-menu" aria-haspopup="true" aria-current={moreCurrent ? "true" : undefined} onclick={() => (open = !open)}
      class={cn("relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl text-xs font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
        moreCurrent ? "bg-surface-3 text-foreground" : open ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
      <MORE_TAB.icon class={cn("size-6", (moreCurrent || open) && "text-primary")} />
      <span>{MORE_TAB.label}</span>
      {#if moreCurrent}<span class="sr-only">(current page: {currentLabel})</span>{/if}
      {#if waitingInMore}<span class="sr-only">({waitingInMore} waiting)</span>{/if}
    </button>
    {#if open}
      <div bind:this={menu} id="more-menu" role="group" aria-label="More pages" class="absolute right-0 bottom-full mb-3 w-48 rounded-2xl border border-border bg-surface-2 p-1.5 shadow-elevation-3">
        {#each MORE as item (item.page)}<NavLink {item} current={current === item.page} menu />{/each}
      </div>
    {/if}
  </div>
</nav>
