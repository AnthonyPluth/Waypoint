<script lang="ts">
  import { cn, type WithElementRef } from "$lib/utils";
  import type { HTMLAttributes } from "svelte/elements";

  let { ref = $bindable(null), class: className, children, ...restProps }: WithElementRef<HTMLAttributes<HTMLElement>> = $props();
</script>

<p bind:this={ref} data-slot="card-description" class={cn("text-muted-foreground text-sm", className)} {...restProps}>
  {@render children?.()}
</p>
