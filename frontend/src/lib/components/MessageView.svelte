<script lang="ts">
  import { apiImage } from "$lib/api";
  import EmailFrame from "$lib/components/EmailFrame.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Dialog } from "bits-ui";
  import Maximize2 from "@lucide/svelte/icons/maximize-2";
  import X from "@lucide/svelte/icons/x";

  type Props = { subject?: string | null; text: string; html?: string | null; truncated?: boolean; original?: boolean; images?: number; imagesAt?: string | null; width?: number | null };
  let { subject = null, text, html = null, truncated = false, original = true, images = 0, imagesAt = null, width = null }: Props = $props();
  let plain = $state(false);
  let pictures = $state<Record<number, string>>({});
  let fetching = $state(false);
  let larger = $state(false);
  const title = $derived(subject ? `The email: ${subject}` : "The email");

  const POLICY = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'";
  const SHEET = "html{color-scheme:light}body{margin:0;padding:12px;background:#ffffff;color:#1f2937;font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;overflow-wrap:anywhere}img{max-width:100%;height:auto;border:0}a{color:#1d4ed8}";
  const PLAIN_SHEET = "body{margin:0;padding:12px;background:#1a1e29;color:#f3f5f9;font:14px/1.6 system-ui,-apple-system,'Segoe UI',sans-serif;overflow-wrap:anywhere}a{color:#4f9dff}blockquote{border-left:2px solid #9aa4b8;margin:8px 0;padding-left:12px}td,th{padding:4px;vertical-align:top}p{margin:8px 0}";

  function pageOf(markup: string, found: Record<number, string>, designed: boolean): string {
    const body = markup.replace(/ data-i="(\d+)"/g, (_all, n: string) => (found[Number(n)] ? ` src="${found[Number(n)]}"` : ""));
    return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${POLICY}"><style>${designed ? SHEET : PLAIN_SHEET}</style></head><body>${body}</body></html>`;
  }

  const page = $derived(html ? pageOf(html, pictures, original) : "");

  $effect(() => {
    const base = imagesAt;
    const count = images;
    if (!base || !count) return;
    let current = true;
    fetching = true;
    void (async () => {
      const found: Record<number, string> = {};
      for (let i = 0; i < count && current; i++) {
        try { found[i] = await apiImage(`${base}${i}`); }
        catch (err) { if (err && typeof err === "object" && "status" in err && (err.status === 401 || err.status === 403)) break; }
      }
      if (!current) return;
      pictures = found;
      fetching = false;
    })();
    return () => { current = false; };
  });
</script>

<div class="space-y-2">
  {#if subject}<p class="break-words font-medium" data-testid="message-subject">{subject}</p>{/if}
  {#snippet toggle()}
    <Button variant="outline" size="sm" onclick={() => (plain = !plain)}>{plain ? "Show as formatted" : "Show as plain text"}</Button>
  {/snippet}
  {#snippet enlarge()}
    {@render toggle()}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="outline" size="sm"><Maximize2 />Larger view</Button>
      {/snippet}
    </Dialog.Trigger>
  {/snippet}
  {#if html && !plain && original}
    <Dialog.Root bind:open={larger}>
      <EmailFrame {title} {page} {width} busy={fetching} leading={enlarge} />
      <Dialog.Portal>
        <Dialog.Overlay class="sheet-overlay" />
        <Dialog.Content class="email-dialog">
          <div class="flex items-center justify-between gap-3">
            <Dialog.Title class="min-w-0 truncate font-medium">{title}</Dialog.Title>
            <Dialog.Close>
              {#snippet child({ props })}
                <Button {...props} variant="ghost" size="icon" aria-label="Close"><X /></Button>
              {/snippet}
            </Dialog.Close>
          </div>
          <Dialog.Description class="sr-only">The whole email, with controls to zoom it.</Dialog.Description>
          <EmailFrame {title} {page} {width} busy={fetching} fill />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  {:else if html && !plain}
    <iframe {title} sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" srcdoc={page} aria-busy={fetching}
      class="h-[30rem] w-full rounded-lg border-0 bg-muted" data-testid="preview-html"></iframe>
    {@render toggle()}
  {:else}
    <pre class="max-h-96 overflow-auto rounded-lg bg-muted p-3 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap">{text || "(This message has no text.)"}</pre>
    {#if html}{@render toggle()}{/if}
  {/if}
  {#if !original}<p class="text-sm text-muted-foreground" data-testid="message-old">This email was kept before Waypoint could show the original, so its layout and pictures can’t be shown.</p>{/if}
  {#if truncated}<p class="text-sm text-muted-foreground">This email was cut short.</p>{/if}
</div>
