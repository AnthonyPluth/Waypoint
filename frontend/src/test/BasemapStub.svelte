<script lang="ts">
  let { center, zoom, onfail }: { center: [number, number]; zoom: number; onfail: () => void } = $props();
</script>

<div data-testid="basemap-stub" data-center={center.join(",")} data-zoom={zoom}><button type="button" onclick={onfail}>fail the basemap</button></div>
