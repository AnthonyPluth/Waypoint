<script lang="ts">
  let { size = 28, class: cls = "" }: { size?: number; class?: string } = $props();
</script>

<img class={`shrink-0 rounded-lg ${cls}`} src="/logo.svg" alt="" width={size} height={size} />
