<script lang="ts">
  // The mark (waypoint/static/logo.svg): a dotted route with a stop along the way and an amber end point.
  let { size = 28, class: cls = "" }: { size?: number; class?: string } = $props();
</script>

<img class={`shrink-0 rounded-lg ${cls}`} src="/logo.svg" alt="" width={size} height={size} />
