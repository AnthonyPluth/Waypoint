<script lang="ts">
  let { kind }: { kind: "live" | "booking" } = $props();
</script>

{#if kind === "live"}<span role="img" aria-label="From live status" class="mr-px size-[7px] flex-none rounded-full bg-primary"></span>
{:else}<span role="img" aria-label="From the booking" class="mr-px size-[7px] flex-none rounded-full border-[1.5px] border-muted-foreground"></span>{/if}
