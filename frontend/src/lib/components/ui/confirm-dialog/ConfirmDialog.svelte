<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { cn } from "$lib/utils";
  import { Dialog } from "bits-ui";
  import type { Snippet } from "svelte";

  let { open = $bindable(false), title, description, confirmLabel = "Confirm", cancelLabel = "Cancel", busyLabel, destructive = false,
    typeToConfirm, disabled = false, onconfirm }: {
    open?: boolean; title: string; description?: string | Snippet; confirmLabel?: string; cancelLabel?: string; busyLabel?: string;
    destructive?: boolean; typeToConfirm?: string; disabled?: boolean; onconfirm: () => unknown;
  } = $props();

  let typed = $state("");
  let busy = $state(false);
  let box = $state<HTMLInputElement | null>(null);
  let cancel = $state<HTMLElement | null>(null);
  $effect(() => { if (open) typed = ""; });
  const ready = $derived(!busy && !disabled && (!typeToConfirm || typed.trim() === typeToConfirm.trim()));

  async function confirm(e: SubmitEvent) {
    e.preventDefault();
    if (!ready) return;
    busy = true;
    try { if ((await onconfirm()) !== false) open = false; }
    finally { busy = false; }
  }
</script>

<Dialog.Root bind:open={() => open, (v) => { if (!busy) open = v; }}>
  <Dialog.Portal>
    <Dialog.Overlay data-slot="confirm-overlay"
      class="fixed inset-0 z-[60] bg-black/60 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0" />
    <Dialog.Content data-slot="confirm-dialog" onOpenAutoFocus={(e) => { e.preventDefault(); (box ?? cancel)?.focus(); }}
      class="bg-card text-card-foreground fixed top-1/2 left-1/2 z-[60] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl border p-5 shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 duration-150">
      <form class="flex flex-col gap-4" onsubmit={confirm}>
        <Dialog.Title class="text-foreground text-base font-semibold">{title}</Dialog.Title>
        {#if description}
          <Dialog.Description class="text-muted-foreground flex flex-col gap-2 text-sm leading-relaxed">
            {#if typeof description === "string"}<p>{description}</p>{:else}{@render description()}{/if}
          </Dialog.Description>
        {/if}
        {#if typeToConfirm}
          <label class="flex flex-col gap-1.5 text-sm text-muted-foreground">
            <span>Type <strong class="text-foreground font-mono">{typeToConfirm}</strong> to confirm</span>
            <Input bind:ref={box} bind:value={typed} autocomplete="off"
              autocapitalize={typeToConfirm === typeToConfirm.toUpperCase() ? "characters" : "off"} spellcheck={false} disabled={busy} />
          </label>
        {/if}
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button bind:ref={cancel} variant="outline" disabled={busy} onclick={() => (open = false)}>{cancelLabel}</Button>
          <Button type="submit" variant={destructive ? "destructive" : "default"} disabled={!ready}
            class={cn(busy && "cursor-progress")}>{busy ? (busyLabel ?? confirmLabel) : confirmLabel}</Button>
        </div>
      </form>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
