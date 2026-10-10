<script lang="ts">
  import { clock } from "$lib/trips";

  let { local }: { local: string } = $props();
</script>

<time datetime={local}>{clock(local)}</time>
