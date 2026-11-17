<script lang="ts">
  import RouteReplayMapKit from "$lib/components/RouteReplayMapKit.svelte";
  import type { Maps } from "$lib/mapkit";
  import type { Roads, Stop } from "$lib/route-replay";

  let { maps, stops, roads }: { maps: Maps; stops: Stop[]; roads: Roads } = $props();
  let more = $state.raw([{ latitude: 37.8, longitude: -122.4 }]);
</script>

<button type="button" onclick={() => { more = [{ latitude: 37.8, longitude: -122.4 }]; }}>same</button>
<button type="button" onclick={() => { more = [{ latitude: 40.1, longitude: -105.2 }]; }}>moved</button>
<RouteReplayMapKit {maps} {stops} {roads} width={960} height={520} progress={0} playing={false} calm={false} onfailure={() => {}} {more} />
