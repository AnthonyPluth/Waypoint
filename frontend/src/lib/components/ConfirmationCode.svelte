<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import CopyButton from "$lib/components/CopyButton.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import { Button } from "$lib/components/ui/button";
  import { dayOf, headline, untimed } from "$lib/trips";
  import { Dialog } from "bits-ui";
  import X from "@lucide/svelte/icons/x";

  type Props = { segment: Segment; open?: boolean };
  let { segment, open = $bindable(false) }: Props = $props();

  const stay = $derived(segment.kind === "hotel");
  const title = $derived(stay ? "Check-in" : "Pickup");
  const hint = $derived(stay ? "Show this at the front desk." : "Show this at the counter.");
  const code = $derived(segment.confirmation?.trim() ?? "");
  const name = $derived(headline(segment));
  const address = $derived(segment.details.address?.trim() || (stay ? "" : segment.origin?.trim() ?? ""));
  const people = $derived(segment.travelers.map((t) => t.name.trim()).filter(Boolean).join(", "));
  const room = $derived(segment.details.room?.trim() ?? "");
  const carClass = $derived(segment.details.car_class?.trim() ?? "");
</script>

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Overlay class="sheet-overlay" />
    <Dialog.Content class="code-dialog" data-testid="confirmation-dialog">
      <div class="flex items-center justify-between gap-3">
        <Dialog.Title class="min-w-0 truncate font-medium">{title}</Dialog.Title>
        <Dialog.Close>
          {#snippet child({ props })}
            <Button {...props} variant="ghost" size="icon" aria-label="Close"><X /></Button>
          {/snippet}
        </Dialog.Close>
      </div>
      <Dialog.Description class="sr-only">The confirmation number for {name}. {hint}</Dialog.Description>
      <div class="flex min-h-0 flex-1 items-center justify-center overflow-y-auto">
        <div class="flex w-full max-w-md flex-col items-center gap-2.5 rounded-[22px] border border-border bg-surface-1 px-4 py-5">
          <p class="eyebrow">Confirmation</p>
          <p class="mono break-all text-center text-[2.5rem] font-semibold leading-tight tracking-[0.08em]" data-testid="confirmation-number">{code}</p>
          <CopyButton text={code} name={`Copy confirmation ${code}`} />
          <dl class="mt-2 grid w-full grid-cols-[auto_1fr] gap-x-3.5 gap-y-1.5 text-left text-sm" data-testid="confirmation-rows">
            {#if stay}
              <dt class="text-muted-foreground">Hotel</dt><dd class="break-words">{name}</dd>
              <dt class="text-muted-foreground">Check-in</dt>
              <dd>
                {#if untimed(segment)}{dayOf(segment, segment.start_local)}, <span class="text-muted-foreground">time not recorded</span>
                {:else}{dayOf(segment, segment.start_local)} from <PlaceTime local={segment.start_local} />{/if}
              </dd>
              <dt class="text-muted-foreground">Room</dt><dd>{room || "Not known yet"}</dd>
              {#if people}<dt class="text-muted-foreground">Guests</dt><dd class="break-words">{people}</dd>{/if}
            {:else}
              {#if segment.provider}<dt class="text-muted-foreground">Company</dt><dd class="break-words">{segment.provider}</dd>{/if}
              <dt class="text-muted-foreground">Pickup</dt>
              <dd>
                {#if untimed(segment)}{dayOf(segment, segment.start_local)}, <span class="text-muted-foreground">time not recorded</span>
                {:else}{dayOf(segment, segment.start_local)}, <PlaceTime local={segment.start_local} />{/if}
              </dd>
              {#if address}<dt class="text-muted-foreground">Where</dt><dd class="break-words">{address}</dd>{/if}
              {#if carClass}<dt class="text-muted-foreground">Car</dt><dd class="break-words">{carClass}</dd>{/if}
              {#if people}<dt class="text-muted-foreground">Driver</dt><dd class="break-words">{people}</dd>{/if}
            {/if}
          </dl>
        </div>
      </div>
      <p class="text-center text-sm text-muted-foreground">{hint}</p>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
