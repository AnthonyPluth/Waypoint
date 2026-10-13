<script lang="ts">
  import "maplibre-gl/dist/maplibre-gl.css";
  import * as maplibregl from "maplibre-gl";
  import { Protocol } from "pmtiles";
  import { onDestroy, onMount } from "svelte";
  import { ATTRIBUTION_LINK, MAX_MAP_ZOOM } from "$lib/basemap";
  import { mapStyle } from "$lib/basemap-style";

  let { center, zoom, onfail }: { center: [number, number]; zoom: number; onfail: () => void } = $props();

  let host: HTMLDivElement;
  let map = $state.raw<maplibregl.Map | null>(null);
  let watcher: ResizeObserver | null = null;
  let protocol: Protocol | null = null;

  onMount(() => {
    let loaded = false;
    try {
      protocol = new Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      const made = new maplibregl.Map({
        container: host, style: mapStyle(location.origin), center, zoom, interactive: false, attributionControl: false,
        fadeDuration: 0, minZoom: -2, maxZoom: MAX_MAP_ZOOM, pitchWithRotate: false, dragRotate: false,
      });
      made.once("load", () => { loaded = true; });
      made.on("error", () => { if (!loaded) onfail(); });
      watcher = new ResizeObserver(() => made.resize());
      watcher.observe(host);
      map = made;
    } catch {
      onfail();
    }
  });

  onDestroy(() => {
    watcher?.disconnect();
    map?.remove();
    if (protocol) maplibregl.removeProtocol("pmtiles");
  });

  $effect(() => { map?.jumpTo({ center, zoom }); });
</script>

<div class="absolute inset-0" data-testid="basemap" aria-hidden="true"><div bind:this={host} class="h-full w-full"></div></div>
<p class="pointer-events-auto absolute bottom-1 right-1 z-10 rounded bg-card/80 px-1.5 py-0.5 text-[10px] leading-tight text-muted-foreground" data-testid="map-credit">
  <a href={ATTRIBUTION_LINK} target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">© OpenStreetMap contributors</a> · Protomaps
</p>
