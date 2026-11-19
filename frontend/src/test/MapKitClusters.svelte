<script lang="ts">
  import RouteReplayMapKit from "$lib/components/RouteReplayMapKit.svelte";
  import type { Maps } from "$lib/mapkit";
  import type { Boundaries, Roads, Stop } from "$lib/route-replay";

  let { maps, stops: first, roads: firstRoads, boundaries: firstBoundaries }: { maps: Maps; stops: Stop[]; roads: Roads; boundaries: Boundaries } = $props();
  let stops = $state.raw(first);
  let roads = $state.raw(firstRoads);
  let boundaries = $state.raw(firstBoundaries);
  let more = $state.raw([{ latitude: 37.8, longitude: -122.4 }]);
</script>

<button type="button" onclick={() => { more = [{ latitude: 37.8, longitude: -122.4 }]; }}>same</button>
<button type="button" onclick={() => { more = [{ latitude: 40.1, longitude: -105.2 }]; }}>moved</button>
<button type="button" onclick={() => { stops = stops.map((s) => ({ ...s })); roads = { ...roads, interstates: [...roads.interstates] }; boundaries = [...boundaries]; }}>again</button>
<RouteReplayMapKit {maps} {stops} {roads} {boundaries} width={960} height={520} progress={0} playing={false} calm={false} onfailure={() => {}} {more} />
