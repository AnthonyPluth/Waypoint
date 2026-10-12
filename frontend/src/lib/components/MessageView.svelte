<script lang="ts">
  import { apiImage } from "$lib/api";
  import EmailView from "$lib/components/EmailView.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Dialog } from "bits-ui";
  import Maximize2 from "@lucide/svelte/icons/maximize-2";
  import X from "@lucide/svelte/icons/x";

  type Props = { subject?: string | null; text: string; html?: string | null; truncated?: boolean; original?: boolean; images?: number; imagesAt?: string | null };
  let { subject = null, text, html = null, truncated = false, original = true, images = 0, imagesAt = null }: Props = $props();
  let pictures = $state<Record<number, string>>({});
  let fetching = $state(false);
  let larger = $state(false);
  const title = $derived(subject ? `The email: ${subject}` : "The email");

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
  {#snippet enlarge()}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="outline" size="sm"><Maximize2 />Larger view</Button>
      {/snippet}
    </Dialog.Trigger>
  {/snippet}
  {#if html && original}
    <Dialog.Root bind:open={larger}>
      <EmailView {title} {html} {pictures} busy={fetching} leading={enlarge} />
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
          <EmailView {title} {html} {pictures} busy={fetching} fill />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  {:else if html}
    <EmailView {title} {html} {pictures} legacy controls={false} busy={fetching} />
  {:else}
    <pre class="max-h-96 overflow-auto rounded-lg bg-muted p-3 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap">{text || "(This message has no text.)"}</pre>
  {/if}
  {#if !original}<p class="text-sm text-muted-foreground" data-testid="message-old">This email was kept before Waypoint could show the original, so its layout and pictures can’t be shown.</p>{/if}
  {#if truncated}<p class="text-sm text-muted-foreground">This email was cut short.</p>{/if}
</div>
