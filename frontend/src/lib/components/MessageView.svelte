<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import { errMsg } from "$lib/act";
  import { emailDocument, FRAME_SANDBOX, type Picture } from "$lib/email-frame";

  type Props = {
    subject?: string | null;
    text: string;
    html?: string | null;
    truncated?: boolean;
    full?: boolean;
    layout?: string | null;
    images?: number;
    loadImages?: () => Promise<Picture[]>;
    offline?: boolean;
  };
  let { subject = null, text, html = null, truncated = false, full = true, layout = null, images = 0, loadImages, offline = false }: Props = $props();
  let plain = $state(false);
  let pictures = $state<{ state: "loading" } | { state: "ready"; list: Picture[] } | { state: "failed"; message: string }>({ state: "loading" });

  $effect(() => {
    if (!layout || !images || !loadImages) { pictures = { state: "ready", list: [] }; return; }
    let current = true;
    pictures = { state: "loading" };
    loadImages().then(
      (list) => { if (current) pictures = { state: "ready", list }; },
      (err) => { if (current) pictures = { state: "failed", message: errMsg(err) }; },
    );
    return () => { current = false; };
  });

  const shown = $derived(layout && pictures.state !== "loading" ? emailDocument(layout, pictures.state === "ready" ? pictures.list : []) : null);
  const formatted = $derived(Boolean(layout || html));
</script>

<div class="space-y-2">
  {#if subject}<p class="break-words font-medium" data-testid="message-subject">{subject}</p>{/if}
  {#if layout && !plain}
    {#if shown}
      <iframe title={subject ? `The email: ${subject}` : "The email"} srcdoc={shown} sandbox={FRAME_SANDBOX} referrerpolicy="no-referrer" loading="lazy"
        class="block h-[32rem] max-h-[75vh] w-full rounded-lg border border-border bg-white" data-testid="email-frame"></iframe>
      {#if pictures.state === "failed"}<p class="text-sm text-muted-foreground" role="alert">The pictures couldn’t be loaded: {pictures.message}</p>{/if}
    {:else}<p class="text-sm text-muted-foreground" role="status">Opening the email…</p>{/if}
  {:else if html && !plain}
    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
    <div class="max-h-96 overflow-auto rounded-lg bg-muted p-3 text-sm leading-relaxed break-words [&_a]:text-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:ml-5 [&_ol]:list-decimal [&_p]:my-2 [&_table]:max-w-full [&_td]:p-1 [&_td]:align-top [&_th]:p-1 [&_th]:text-left [&_ul]:list-disc" data-testid="preview-html">{@html html}</div>
  {:else}
    <pre class="max-h-96 overflow-auto rounded-lg bg-muted p-3 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap">{text || "(This message has no text.)"}</pre>
  {/if}
  {#if formatted}<Button variant="outline" size="sm" onclick={() => (plain = !plain)}>{plain ? "Show as formatted" : "Show as plain text"}</Button>{/if}
  {#if truncated}<p class="text-sm text-muted-foreground" data-testid="cut-short">This email was cut short because it is very long.</p>{/if}
  {#if offline}<p class="text-sm text-muted-foreground" data-testid="not-saved-here">This device keeps the text of the email. Open Waypoint online to see it as it was sent, with its pictures.</p>
  {:else if !full}<p class="text-sm text-muted-foreground" data-testid="original-unavailable">The original can’t be shown for this email: it was saved before Waypoint kept the full message. This is the text and simple formatting that was kept.</p>{/if}
</div>
