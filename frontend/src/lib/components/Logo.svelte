<script lang="ts">
  // The mark (waypoint/static/logo.svg): an amber W on a split-flap tile, like a letter on a departure board.
  let { size = 28, class: cls = "" }: { size?: number; class?: string } = $props();
</script>

<img class={`shrink-0 rounded-lg ${cls}`} src="/logo.svg" alt="" width={size} height={size} />
