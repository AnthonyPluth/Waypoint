<script lang="ts">
  type Size = "large" | "medium" | "small";

  let { code, name = null, size = "large", class: cls = "" }: { code: string; name?: string | null; size?: Size; class?: string } = $props();

  const SIZE: Record<Size, string> = { large: "text-display", medium: "text-title", small: "text-heading" };
  const classes = $derived(`font-mono uppercase leading-none tracking-wide no-underline ${SIZE[size]} ${cls}`);
</script>

{#if name}<abbr title={name} class={classes}>{code}</abbr>{:else}<span class={classes}>{code}</span>{/if}
