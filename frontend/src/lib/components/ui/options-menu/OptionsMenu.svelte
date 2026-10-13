<script lang="ts" module>
  export type OptionsMenuItem = { label: string; name?: string; onselect: () => void; destructive?: boolean };
</script>

<script lang="ts">
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import { Button } from "$lib/components/ui/button";
  import { cn } from "$lib/utils";

  let { label, text, items, size = "default", align = "right" }: { label: string; text: string; items: OptionsMenuItem[]; size?: "default" | "sm"; align?: "left" | "right" } = $props();

  const id = $props.id();
  let open = $state(false);
  let button = $state<HTMLButtonElement | null>(null);
  let menu = $state<HTMLElement>();

  function onKeydown(e: KeyboardEvent) {
    if (!open || e.key !== "Escape") return;
    e.stopPropagation();
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

  function choose(item: OptionsMenuItem) {
    open = false;
    button?.focus();
    item.onselect();
  }
</script>

<svelte:window onkeydown={onKeydown} onpointerdown={onPointerDown} />

<div class="relative" onfocusout={onFocusOut}>
  <Button bind:ref={button} variant="outline" {size} aria-label={label} aria-expanded={open} aria-controls={id} onclick={() => (open = !open)}><Ellipsis /> {text}</Button>
  {#if open}
    <div bind:this={menu} {id} role="group" aria-label={label} class={cn("absolute top-full z-20 mt-2 flex min-w-48 max-w-[calc(100vw-2rem)] flex-col rounded-2xl border border-border bg-surface-2 p-1.5 shadow-elevation-3", align === "right" ? "right-0" : "left-0")}>
      {#each items as item (item.label)}
        <button type="button" aria-label={item.name} class={cn("flex min-h-10 phone:min-h-11 w-full items-center break-words rounded-xl px-3 py-2 text-left text-sm font-medium outline-none hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50", item.destructive && "text-destructive")} onclick={() => choose(item)}>{item.label}</button>
      {/each}
    </div>
  {/if}
</div>
