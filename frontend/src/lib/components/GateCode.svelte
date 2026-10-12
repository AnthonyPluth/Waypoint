<script lang="ts">
  import { act, ignoreFailure } from "$lib/act";
  import { apiImage } from "$lib/api";
  import { apiCall } from "$lib/contract";
  import type { Segment } from "$lib/api-types";
  import DayTime from "$lib/components/DayTime.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Sheet } from "$lib/components/ui/sheet";
  import { SHARE, squareSide } from "$lib/gate-code";
  import { endAt, headline } from "$lib/trips";
  import { Dialog } from "bits-ui";
  import X from "@lucide/svelte/icons/x";
  import { toast } from "svelte-sonner";

  type Props = { segment: Segment; now: number; onchanged?: () => void };
  let { segment, now, onchanged }: Props = $props();

  type Picture = { email: number; image: number; src: string };

  let showing = $state(false);
  let choosing = $state(false);
  let src = $state<string | null>(null);
  let failed = $state(false);
  let natural = $state(0);
  let stage = $state({ width: 0, height: 0 });
  let pictures = $state<Picture[] | null>(null);
  let pictureError = $state("");
  let showButton = $state<HTMLElement | null>(null);
  let chooseButton = $state<HTMLElement | null>(null);
  let returnTo: HTMLElement | null = null;

  const code = $derived(segment.gate_code);
  const live = $derived(segment.kind === "parking" && segment.status !== "cancelled" && code !== null && endAt(segment) > now);
  const lot = $derived(headline(segment));
  const side = $derived(squareSide(Math.min(stage.width, stage.height), natural));

  async function look() {
    src = null;
    failed = false;
    natural = 0;
    try { src = await apiImage(`/api/segments/${segment.id}/code`); }
    catch { failed = true; }
  }

  $effect(() => {
    if (showing) void look();
    else { src = null; failed = false; natural = 0; }
  });

  $effect(() => {
    if (!showing || !("wakeLock" in navigator)) return;
    let closed = false;
    let held: WakeLockSentinel | null = null;
    const hold = () => {
      if (closed || document.visibilityState !== "visible") return;
      navigator.wakeLock.request("screen").then((s) => { if (closed) void s.release().catch(ignoreFailure); else held = s; }, ignoreFailure);
    };
    hold();
    document.addEventListener("visibilitychange", hold);
    return () => {
      closed = true;
      document.removeEventListener("visibilitychange", hold);
      void held?.release().catch(ignoreFailure);
    };
  });

  function open(button: HTMLElement | null) {
    returnTo = button;
    showing = true;
  }

  function giveFocusBack(e: Event) {
    e.preventDefault();
    returnTo?.focus();
  }

  async function loadPictures() {
    pictures = null;
    pictureError = "";
    const found: Picture[] = [];
    try {
      const { emails } = await apiCall<"GET /api/segments/{id}/emails">(`/api/segments/${segment.id}/emails`);
      for (const [email, kept] of emails.entries()) {
        for (let image = 0; image < kept.images; image++) {
          try { found.push({ email, image, src: await apiImage(`/api/segments/${segment.id}/emails/${email}/images/${image}`) }); }
          catch (err) { if (err && typeof err === "object" && "status" in err && (err.status === 401 || err.status === 403)) throw err; }
        }
      }
      pictures = found;
    } catch { pictureError = "The pictures can’t be shown right now."; }
  }

  $effect(() => {
    if (choosing) void loadPictures();
    else pictures = null;
  });

  const pick = (p: Picture) => act(async () => {
    await apiCall<"POST /api/segments/{id}/code">(`/api/segments/${segment.id}/code`, { method: "POST", body: { email: p.email, image: p.image } });
    choosing = false;
    toast.success("Saved");
    onchanged?.();
  });
</script>

{#if live && code}
  {#if code.state === "ready"}
    <Button bind:ref={showButton} variant="outline" size="sm" aria-label={`Show the QR code for ${lot}`} onclick={() => open(showButton)}>Show QR code</Button>
    {#if segment.has_email}
      <Button bind:ref={chooseButton} variant="ghost" size="sm" aria-label={`Choose a different picture for the code of ${lot}`} onclick={() => { returnTo = chooseButton; choosing = true; }}>Choose another picture</Button>
    {/if}
  {:else}
    <Button bind:ref={chooseButton} variant="outline" size="sm" aria-label={`Choose the code for ${lot}`} onclick={() => { returnTo = chooseButton; choosing = true; }}>Choose the code</Button>
  {/if}
{/if}

<Dialog.Root bind:open={showing}>
  <Dialog.Portal>
    <Dialog.Overlay class="sheet-overlay" />
    <Dialog.Content class="code-dialog" onCloseAutoFocus={giveFocusBack}>
      <div class="flex items-center justify-between gap-3">
        <Dialog.Title class="min-w-0 truncate font-medium">QR code</Dialog.Title>
        <Dialog.Close>
          {#snippet child({ props })}
            <Button {...props} variant="ghost" size="icon" aria-label="Close"><X /></Button>
          {/snippet}
        </Dialog.Close>
      </div>
      <Dialog.Description class="sr-only">The code that opens the gate, shown as it was received. Turn your screen brightness up.</Dialog.Description>
      <div class="flex min-h-0 flex-1 items-center justify-center" style="container-type: size" bind:clientWidth={stage.width} bind:clientHeight={stage.height} data-testid="code-stage">
        <div class="flex aspect-square items-center justify-center bg-white" data-testid="code-square"
          style={`width:${side ? `${side}px` : "min(100cqw, 100cqh)"}`}>
          {#if src}
            <img {src} alt={`QR code for ${lot}`} class="block aspect-square object-contain" style={`image-rendering: pixelated;width:${SHARE * 100}%`}
              onload={(e) => (natural = (e.currentTarget as HTMLImageElement).naturalWidth)} />
          {:else if failed}
            <p class="text-center text-sm text-black" role="alert">The code can’t be shown right now. Check your connection and try again.</p>
          {:else}
            <p class="text-sm text-black" role="status">Opening the code…</p>
          {/if}
        </div>
      </div>
      <div class="space-y-1 text-center">
        <p class="break-words text-lg font-semibold" data-testid="code-lot">{lot}</p>
        <p class="text-sm text-muted-foreground" data-testid="code-times">
          Entry <DayTime segment={segment} dated /> · Exit <DayTime segment={segment} end dated />
        </p>
        <p class="text-sm font-medium">Turn your screen brightness up</p>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<Sheet bind:open={choosing} title="Choose the code" description="Pick the picture in this booking’s emails that is the QR code for the gate.">
  {#if pictureError}
    <p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{pictureError}</p>
  {:else if pictures === null}
    <p class="text-sm text-muted-foreground" role="status">Opening the pictures…</p>
  {:else if !pictures.length}
    <p class="text-sm text-muted-foreground">These emails have no pictures to choose from.</p>
  {:else}
    <ul class="grid grid-cols-2 gap-3 sm:grid-cols-3" aria-label="Pictures in the emails">
      {#each pictures as p, n (`${p.email}-${p.image}`)}
        <li>
          <button type="button" class="flex w-full items-center justify-center rounded-xl border border-border bg-white p-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 phone:min-h-11"
            aria-label={`Use picture ${n + 1} as the code`} onclick={() => pick(p)}>
            <img src={p.src} alt="" class="max-h-40 w-auto object-contain" style="image-rendering: pixelated" />
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</Sheet>
