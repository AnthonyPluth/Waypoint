<script lang="ts">
  import { tick, untrack } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Sheet } from "$lib/components/ui/sheet";
  import TripPhotoSharing from "$lib/components/TripPhotoSharing.svelte";
  import { viewport } from "$lib/phone.svelte";
  import type { PersonSharing } from "$lib/trip-sharing.svelte";
  import X from "@lucide/svelte/icons/x";

  let { acting, tripName, fallback, button = $bindable(null), open = $bindable(false), align = "end", trigger = true }: {
    acting: PersonSharing[]; tripName: string; fallback: () => HTMLElement | null | undefined; button?: HTMLElement | null; open?: boolean; align?: "start" | "end"; trigger?: boolean;
  } = $props();

  const TITLE = "Photo sharing for this trip";
  const id = $props.id();
  const panelId = `photo-sharing-${id}`;
  const cards = $derived(acting.filter((a) => a.mode === "card"));
  const asking = $derived(acting.some((a) => a.dialog));
  let opened = $state<Set<number>>(new Set());
  let panel = $state<HTMLElement | null>(null);
  let title = $state<HTMLElement | null>(null);

  const expandedFor = (a: PersonSharing, at: number) => at === 0 || opened.has(a.personId);
  const toggle = (a: PersonSharing) => {
    const next = new Set(opened);
    if (!next.delete(a.personId)) next.add(a.personId);
    opened = next;
  };

  export async function show() {
    opened = new Set();
    open = true;
    await tick();
    title?.focus();
  }

  function hide(returnFocus: boolean) {
    open = false;
    if (returnFocus) button?.focus();
  }

  $effect(() => {
    if (cards.length > 0 || !open) return;
    const active = document.activeElement;
    const inside = !active || active === document.body || !!panel?.contains(active) || active === button;
    untrack(() => {
      open = false;
      if (inside) void tick().then(() => fallback()?.focus());
    });
  });

  const outside = (target: EventTarget | null) => !panel?.contains(target as Node) && !(trigger && button?.contains(target as Node));

  function keydown(e: KeyboardEvent) {
    if (!open || viewport.phone || asking || e.key !== "Escape" || e.defaultPrevented) return;
    e.preventDefault();
    hide(true);
  }

  function pointerdown(e: PointerEvent) {
    if (open && !viewport.phone && !asking && outside(e.target)) hide(false);
  }

  function focusout(e: FocusEvent) {
    const next = e.relatedTarget as Node | null;
    if (open && !viewport.phone && !asking && next && outside(next)) hide(false);
  }
</script>

<svelte:window onkeydowncapture={keydown} onpointerdowncapture={pointerdown} />

{#if cards.length > 0}
  {#if trigger}
    <span class="relative inline-flex" onfocusout={focusout}>
      <Button variant="outline" size="sm" bind:ref={button} aria-haspopup="dialog" aria-expanded={open} aria-controls={viewport.phone ? undefined : panelId} onclick={() => (open ? hide(false) : void show())}>Sharing</Button>
      {#if open && !viewport.phone}{@render popover()}{/if}
    </span>
  {:else if open && !viewport.phone}
    {@render popover()}
  {/if}
  {#if viewport.phone}
    <Sheet bind:open title={TITLE}>
      {@render sections()}
    </Sheet>
  {/if}
{/if}

{#snippet popover()}
  <div bind:this={panel} id={panelId} role="dialog" aria-modal="false" aria-labelledby={`${panelId}-title`} onfocusout={trigger ? undefined : focusout}
    class={`absolute top-[calc(100%+10px)] ${align === "start" ? "left-[-6px]" : "right-[-6px]"} z-20 flex w-[392px] max-w-[calc(100vw-2rem)] flex-col gap-3.5 rounded-[18px] border border-border bg-popover p-4 shadow-elevation-3`}>
    <span class={`absolute top-[-6px] ${align === "start" ? "left-[22px]" : "right-7"} size-[11px] rotate-45 border-t border-l border-border bg-popover`} aria-hidden="true"></span>
    <div class="flex items-start justify-between gap-3">
      <h2 id={`${panelId}-title`} class="text-heading outline-none" tabindex="-1" bind:this={title}>{TITLE}</h2>
      <Button variant="ghost" size="icon" class="-mt-1.5 -mr-1.5 size-8" aria-label="Close" onclick={() => hide(true)}><X /></Button>
    </div>
    {@render sections()}
  </div>
{/snippet}

{#snippet sections()}
  {#each cards as a, at (a.personId)}
    <TripPhotoSharing sharing={a} {tripName} part="problem" />
    <TripPhotoSharing sharing={a} {tripName} part="card" panel expanded={expandedFor(a, at)} ontoggle={at === 0 ? undefined : () => toggle(a)} />
  {/each}
{/snippet}
