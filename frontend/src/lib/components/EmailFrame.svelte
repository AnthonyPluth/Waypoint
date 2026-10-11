<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import ZoomIn from "@lucide/svelte/icons/zoom-in";
  import ZoomOut from "@lucide/svelte/icons/zoom-out";
  import type { Snippet } from "svelte";

  type Props = { title: string; page: string; width?: number | null; busy?: boolean; fill?: boolean; leading?: Snippet };
  let { title, page, width = null, busy = false, fill = false, leading }: Props = $props();

  const STEP = 25;
  const MAX = 300;
  let box = $state({ width: 0, height: 0 });
  let zoomed = $state<number | null>(null);
  let viewport = $state<HTMLElement | null>(null);

  const fit = $derived(width && box.width && width > box.width ? box.width / width : 1);
  const scale = $derived(zoomed === null ? fit : Math.max(zoomed, fit));
  const percent = $derived(Math.round(scale * 100));
  const fitPercent = $derived(Math.round(fit * 100));
  const layoutWidth = $derived(width && width > box.width ? width : box.width);
  const sized = $derived(box.width > 0 && box.height > 0);

  function zoomIn() {
    zoomed = Math.min(MAX, (Math.floor(percent / STEP) + 1) * STEP) / 100;
  }
  function zoomOut() {
    const next = (Math.ceil(percent / STEP) - 1) * STEP;
    zoomed = next <= fitPercent ? null : next / 100;
  }

  $effect(() => {
    if (!viewport) return;
    const watcher = new ResizeObserver((entries) => {
      const found = entries[0]?.contentRect;
      if (found) box = { width: found.width, height: found.height };
    });
    watcher.observe(viewport);
    return () => watcher.disconnect();
  });
</script>

<div class={fill ? "flex min-h-0 flex-1 flex-col gap-2" : "space-y-2"}>
  <div bind:this={viewport} class={`${fill ? "min-h-0 flex-1" : "h-[30rem]"} overflow-auto rounded-lg bg-muted`} data-testid="preview-viewport">
    <div class="overflow-hidden" style={sized ? `width:${layoutWidth * scale}px;height:${box.height}px` : "width:100%;height:100%"} data-testid="preview-sizer">
      <iframe {title} sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" srcdoc={page} aria-busy={busy}
        class="block border-0 bg-muted"
        style={sized ? `width:${layoutWidth}px;height:${box.height / scale}px;transform:scale(${scale});transform-origin:0 0` : "width:100%;height:100%"}
        data-testid="preview-html"></iframe>
    </div>
  </div>
  <div class="flex flex-wrap items-center gap-2" role="group" aria-label="Email view">
    {@render leading?.()}
    <Button variant="outline" size="icon" aria-label="Zoom out" disabled={percent <= fitPercent} onclick={zoomOut}><ZoomOut /></Button>
    <Button variant="outline" size="icon" aria-label="Zoom in" disabled={percent >= MAX} onclick={zoomIn}><ZoomIn /></Button>
    <Button variant="outline" size="sm" disabled={zoomed === null} onclick={() => (zoomed = null)}>Fit</Button>
    <span class="min-w-12 text-sm tabular-nums text-muted-foreground" aria-live="polite" aria-atomic="true" data-testid="zoom-level">{percent}%</span>
  </div>
</div>
