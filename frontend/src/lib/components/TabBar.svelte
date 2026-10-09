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

<nav aria-label="Main" class="fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-surface-1/90 pb-[env(safe-area-inset-bottom)] shadow-elevation-3 backdrop-blur-xl lg:hidden">
  {#each TABS as item (item.page)}<NavLink {item} current={current === item.page} tab />{/each}
  <div class="relative flex flex-1" onfocusout={onFocusOut}>
    <button bind:this={button} type="button" aria-expanded={open} aria-controls="more-menu" aria-haspopup="true" aria-current={moreCurrent ? "true" : undefined} onclick={() => (open = !open)}
      class={cn("relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
        moreCurrent || open ? "text-primary" : "text-muted-foreground hover:text-foreground")}>
      {#if moreCurrent}<span class="absolute top-0 h-0.5 w-10 rounded-full bg-primary" aria-hidden="true"></span>{/if}
      <MORE_TAB.icon class="size-6" />
      <span>{MORE_TAB.label}</span>
      {#if moreCurrent}<span class="sr-only">(current page: {currentLabel})</span>{/if}
      {#if waitingInMore}<span class="sr-only">({waitingInMore} waiting)</span>{/if}
    </button>
    {#if open}
      <div bind:this={menu} id="more-menu" role="group" aria-label="More pages" class="absolute right-2 bottom-full mb-2 w-48 rounded-2xl border border-border bg-surface-2 p-1.5 shadow-elevation-3">
        {#each MORE as item (item.page)}<NavLink {item} current={current === item.page} menu />{/each}
      </div>
    {/if}
  </div>
</nav>
