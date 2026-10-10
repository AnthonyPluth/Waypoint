<script lang="ts">
  import { apiImage } from "$lib/api";
  import { Button } from "$lib/components/ui/button";

  type Props = { subject?: string | null; text: string; html?: string | null; truncated?: boolean; original?: boolean; images?: number; imagesAt?: string | null };
  let { subject = null, text, html = null, truncated = false, original = true, images = 0, imagesAt = null }: Props = $props();
  let plain = $state(false);
  let pictures = $state<Record<number, string>>({});

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
    void Promise.allSettled(Array.from({ length: count }, (_, i) => apiImage(`${base}${i}`))).then((done) => {
      if (!current) return;
      const found: Record<number, string> = {};
      done.forEach((r, i) => { if (r.status === "fulfilled") found[i] = r.value; });
      pictures = found;
    });
    return () => { current = false; };
  });
</script>

<div class="space-y-2">
  {#if subject}<p class="break-words font-medium" data-testid="message-subject">{subject}</p>{/if}
  {#if html && !plain}
    <iframe title={subject ? `The email: ${subject}` : "The email"} sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" srcdoc={page}
      class="h-[30rem] w-full rounded-lg border-0 bg-muted" data-testid="preview-html"></iframe>
  {:else}
    <pre class="max-h-96 overflow-auto rounded-lg bg-muted p-3 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap">{text || "(This message has no text.)"}</pre>
  {/if}
  {#if html}<Button variant="outline" size="sm" onclick={() => (plain = !plain)}>{plain ? "Show as formatted" : "Show as plain text"}</Button>{/if}
  {#if !original}<p class="text-sm text-muted-foreground" data-testid="message-old">This email was kept before Waypoint could show the original, so its layout and pictures can’t be shown.</p>{/if}
  {#if truncated}<p class="text-sm text-muted-foreground">This email was cut short.</p>{/if}
</div>
