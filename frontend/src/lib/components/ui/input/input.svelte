<script lang="ts">
  import { cn, type WithElementRef } from "$lib/utils";
  import type { HTMLInputAttributes } from "svelte/elements";

  let { ref = $bindable(null), value = $bindable(), class: className, ...restProps }: WithElementRef<HTMLInputAttributes> = $props();
</script>

<input bind:this={ref} bind:value data-slot="input"
  class={cn("border-input bg-secondary selection:bg-primary selection:text-primary-foreground ring-offset-background placeholder:text-muted-foreground flex h-10 w-full min-w-0 rounded-xl border px-3 py-1 text-base outline-none transition-[color,box-shadow] disabled:cursor-not-allowed disabled:opacity-50 md:text-sm focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/40 aria-invalid:border-destructive", className)}
  {...restProps} />
