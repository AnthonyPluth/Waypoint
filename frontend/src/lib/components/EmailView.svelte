<script lang="ts">
  import { attachEmail, renderEmail, showPictures } from "$lib/email-render";
  import { Button } from "$lib/components/ui/button";
  import ZoomIn from "@lucide/svelte/icons/zoom-in";
  import ZoomOut from "@lucide/svelte/icons/zoom-out";
  import { untrack, type Snippet } from "svelte";

  type Props = { title: string; html: string; pictures?: Record<number, string>; legacy?: boolean; controls?: boolean; busy?: boolean; fill?: boolean; leading?: Snippet };
  let { title, html, pictures = {}, legacy = false, controls = true, busy = false, fill = false, leading }: Props = $props();

  const STEP = 25;
  const MAX = 300;
  let box = $state({ width: 0, height: 0 });
  let layout = $state({ width: 0, height: 0 });
  let zoomed = $state<number | null>(null);
  let viewport = $state<HTMLElement | null>(null);
  let host = $state<HTMLElement | null>(null);
  let root: ShadowRoot | null = null;

  const fit = $derived(layout.width > box.width && box.width > 0 ? box.width / layout.width : 1);
  const scale = $derived(zoomed === null ? fit : Math.max(zoomed, fit));
  const percent = $derived(Math.round(scale * 100));
  const fitPercent = $derived(Math.round(fit * 100));
  const sized = $derived(box.width > 0 && layout.width > 0);

  function zoomIn() {
    zoomed = Math.min(MAX, (Math.floor(percent / STEP) + 1) * STEP) / 100;
  }
  function zoomOut() {
    const next = (Math.ceil(percent / STEP) - 1) * STEP;
    zoomed = next <= fitPercent ? null : next / 100;
  }

  function watch(target: HTMLElement | null, into: (size: { width: number; height: number }) => void) {
    if (!target) return;
    const watcher = new ResizeObserver((entries) => {
      const found = entries[0]?.contentRect;
      if (found) into({ width: found.width, height: found.height });
    });
    watcher.observe(target);
    return () => watcher.disconnect();
  }

  $effect(() => watch(viewport, (size) => (box = size)));
  $effect(() => watch(host, (size) => (layout = size)));

  $effect(() => {
    if (!host) return;
    root = attachEmail(host);
    renderEmail(root, html, untrack(() => pictures), legacy);
  });

  $effect(() => {
    const found = pictures;
    if (root) showPictures(root, found);
  });
</script>

<div class={fill ? "flex min-h-0 flex-1 flex-col gap-2" : "space-y-2"}>
  <div bind:this={viewport} class={`${fill ? "min-h-0 flex-1" : "max-h-[30rem]"} overflow-auto rounded-lg border border-border bg-white`} data-testid="preview-viewport">
    <div class="overflow-hidden" style={sized ? `width:${layout.width * scale}px;height:${layout.height * scale}px` : ""} data-testid="preview-sizer">
      <div style={box.width > 0 ? `width:${box.width}px` : "width:100%"}>
        <div bind:this={host} role="article" aria-label={title} aria-busy={busy} data-testid="preview-html"
          style={`all:initial;display:block;width:100%;min-width:min-content;contain:paint;transform:scale(${scale});transform-origin:0 0`}></div>
      </div>
    </div>
  </div>
  {#if controls}
    <div class="flex flex-wrap items-center gap-2" role="group" aria-label="Email view">
      {@render leading?.()}
      <Button variant="outline" size="icon" aria-label="Zoom out" disabled={percent <= fitPercent} onclick={zoomOut}><ZoomOut /></Button>
      <Button variant="outline" size="icon" aria-label="Zoom in" disabled={percent >= MAX} onclick={zoomIn}><ZoomIn /></Button>
      <Button variant="outline" size="sm" disabled={zoomed === null} onclick={() => (zoomed = null)}>Fit</Button>
      <span class="min-w-12 text-sm tabular-nums text-muted-foreground" aria-live="polite" aria-atomic="true" data-testid="zoom-level">{percent}%</span>
    </div>
  {/if}
</div>
