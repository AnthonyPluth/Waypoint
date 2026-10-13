<script lang="ts">
  import { buttonVariants } from "$lib/components/ui/button";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import type { Snippet } from "svelte";

  let { label, button = $bindable(), children }: { label: string; button?: HTMLElement | null | undefined; children: Snippet<[() => void]> } = $props();

  let menu = $state<HTMLDetailsElement | null>(null);
  const close = () => { if (menu) menu.open = false; };
</script>

<svelte:window
  onclick={(e) => { if (menu?.open && !menu.contains(e.target as Node)) close(); }}
  onkeydown={(e) => { if (e.key === "Escape" && menu?.open) { e.stopPropagation(); close(); button?.focus(); } }} />

<details bind:this={menu} class="relative" data-testid="action-menu">
  <summary bind:this={button} class={`${buttonVariants({ variant: "outline", size: "sm" })} list-none [&::-webkit-details-marker]:hidden`} aria-label={label}>More <ChevronDown aria-hidden="true" /></summary>
  <div class="absolute right-0 z-20 mt-1 flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-3 rounded-xl border border-border bg-card p-3 shadow-lg">{@render children(close)}</div>
</details>
