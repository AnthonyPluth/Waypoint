<script lang="ts">
  import { viewport } from "$lib/phone.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Dialog } from "bits-ui";
  import X from "@lucide/svelte/icons/x";
  import type { Snippet } from "svelte";

  let { open = $bindable(false), title, description, children }: {
    open?: boolean; title: string; description?: string; children: Snippet;
  } = $props();

  const CLOSE_DISTANCE = 96;
  const side = $derived(viewport.phone ? "bottom" : "right");
  let drag = $state(0);
  let startY: number | null = null;

  function grab(e: PointerEvent) {
    startY = e.clientY;
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  }
  function pull(e: PointerEvent) {
    if (startY !== null) drag = Math.max(0, e.clientY - startY);
  }
  function release() {
    if (startY === null) return;
    const far = drag >= CLOSE_DISTANCE;
    startY = null;
    drag = 0;
    if (far) open = false;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Overlay data-slot="sheet-overlay" class="sheet-overlay" />
    <Dialog.Content data-slot="sheet" data-side={side} class="sheet" style={drag ? `--sheet-drag: ${drag}px` : undefined} data-dragging={drag ? "" : undefined}>
      {#if side === "bottom"}
        <div class="sheet-handle" data-sheet-handle onpointerdown={grab} onpointermove={pull} onpointerup={release} onpointercancel={release} role="presentation">
          <span class="sheet-grip" aria-hidden="true"></span>
        </div>
      {/if}
      <div class="flex items-start justify-between gap-3 px-5 pb-2 pt-3 md:px-6 md:pt-5">
        <div class="min-w-0">
          <Dialog.Title class="text-heading font-semibold break-words">{title}</Dialog.Title>
          {#if description}<Dialog.Description class="text-caption text-muted-foreground">{description}</Dialog.Description>{/if}
        </div>
        <Dialog.Close>
          {#snippet child({ props })}
            <Button {...props} variant="ghost" size="icon" class="-mr-2 shrink-0" aria-label="Close"><X /></Button>
          {/snippet}
        </Dialog.Close>
      </div>
      <div class="px-5 pb-6 md:px-6">{@render children()}</div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
