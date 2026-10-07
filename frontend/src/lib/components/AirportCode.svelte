<script lang="ts">
  import { cn } from "$lib/utils";

  let { code, class: klass = "" }: { code: string; class?: string } = $props();
</script>

<span class={cn("font-mono font-semibold tracking-tight", klass)} data-testid="airport-code">{code}</span>
