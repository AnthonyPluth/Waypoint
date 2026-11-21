<script lang="ts" module>
  import type { Component } from "svelte";
  export type OptionsMenuItem = { label: string; name?: string; onselect: () => void; destructive?: boolean; icon?: Component; divided?: boolean };
</script>

<script lang="ts">
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import { Button } from "$lib/components/ui/button";
  import { cn } from "$lib/utils";

  let { label, text, items, size = "default", align = "right", up = false, icon: Icon = Ellipsis, iconOnly = false, variant = "outline", popup = false, button = $bindable(null) }: {
    label: string; text: string; items: OptionsMenuItem[]; size?: "default" | "sm"; align?: "left" | "right"; up?: boolean;
    icon?: Component; iconOnly?: boolean; variant?: "outline" | "default" | "ghost"; popup?: boolean; button?: HTMLButtonElement | null;
  } = $props();

  const id = $props.id();
  let open = $state(false);
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

  const entries = () => [...(menu?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];

  $effect(() => {
    if (open && popup && menu) entries()[0]?.focus();
  });

  function onMenuKeydown(e: KeyboardEvent) {
    if (!popup) return;
    const list = entries();
    const at = list.indexOf(document.activeElement as HTMLElement);
    const to = e.key === "ArrowDown" ? (at + 1) % list.length : e.key === "ArrowUp" ? (at <= 0 ? list.length - 1 : at - 1) : e.key === "Home" ? 0 : e.key === "End" ? list.length - 1 : -1;
    if (to < 0) {
      if (e.key === "Tab") open = false;
      return;
    }
    e.preventDefault();
    list[to]?.focus();
  }

  function choose(item: OptionsMenuItem) {
    open = false;
    button?.focus();
    item.onselect();
  }
</script>

<svelte:window onkeydown={onKeydown} onpointerdown={onPointerDown} />

<div class="relative" onfocusout={onFocusOut}>
  <Button bind:ref={button} {variant} size={iconOnly ? "icon" : size} aria-label={label} aria-haspopup={popup ? "menu" : undefined} aria-expanded={open} aria-controls={id} onclick={() => (open = !open)}><Icon />{#if !iconOnly} {text}{/if}</Button>
  {#if open}
    <div bind:this={menu} {id} role={popup ? "menu" : "group"} onkeydown={onMenuKeydown} aria-label={label} class={cn("absolute z-20 flex min-w-48 max-w-[calc(100vw-2rem)] flex-col rounded-2xl border border-border bg-surface-2 p-1.5 shadow-elevation-3", up ? "bottom-full mb-2" : "top-full mt-2", align === "right" ? "right-0" : "left-0")}>
      {#each items as item (item.label)}
        {#if item.divided}<hr class="my-1 border-border" />{/if}
        <button type="button" role={popup ? "menuitem" : undefined} tabindex={popup ? -1 : undefined} aria-label={item.name} class={cn("flex min-h-10 phone:min-h-11 w-full items-center gap-2.5 break-words rounded-xl px-3 py-2 text-left text-sm font-medium outline-none hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50", item.destructive && "text-destructive")} onclick={() => choose(item)}>{#if item.icon}{@const ItemIcon = item.icon}<ItemIcon class="size-4 shrink-0" aria-hidden="true" />{/if}{item.label}</button>
      {/each}
    </div>
  {/if}
</div>
