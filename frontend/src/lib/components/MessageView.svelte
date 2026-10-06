<script lang="ts">
  import { Button } from "$lib/components/ui/button";

  let { subject = null, text, html = null, truncated = false }: { subject?: string | null; text: string; html?: string | null; truncated?: boolean } = $props();
  let plain = $state(false);
</script>

<div class="space-y-2">
  {#if subject}<p class="break-words font-medium" data-testid="message-subject">{subject}</p>{/if}
  {#if html && !plain}
    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
    <div class="max-h-96 overflow-auto rounded-lg bg-muted p-3 text-sm leading-relaxed break-words [&_a]:text-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:ml-5 [&_ol]:list-decimal [&_p]:my-2 [&_table]:max-w-full [&_td]:p-1 [&_td]:align-top [&_th]:p-1 [&_th]:text-left [&_ul]:list-disc" data-testid="preview-html">{@html html}</div>
  {:else}
    <pre class="max-h-96 overflow-auto rounded-lg bg-muted p-3 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap">{text || "(This message has no text.)"}</pre>
  {/if}
  {#if html}<Button variant="outline" size="sm" onclick={() => (plain = !plain)}>{plain ? "Show as formatted" : "Show as plain text"}</Button>{/if}
  {#if truncated}<p class="text-sm text-muted-foreground">Cut short here.</p>{/if}
</div>
