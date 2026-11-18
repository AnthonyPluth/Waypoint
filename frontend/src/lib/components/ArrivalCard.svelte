<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import { arrival, checkArrivalHere, dismissArrival, openable } from "$lib/arrival.svelte";
  import ArrivalCode from "$lib/components/ArrivalCode.svelte";
  import KindTile from "$lib/components/KindTile.svelte";
  import { Button } from "$lib/components/ui/button";
  import { headline } from "$lib/trips";
  import X from "@lucide/svelte/icons/x";

  type Props = { segments: Segment[]; now: number };
  let { segments, now }: Props = $props();

  let open = $state(false);

  const here = $derived(arrival.here);
  const segment = $derived(here ? segments.find((s) => s.id === here.segmentId && s.trip_id === here.tripId) : undefined);
  const shown = $derived(segment !== undefined && openable(segment, now) && arrival.dismissed !== segment.id ? segment : null);
  const place = $derived(shown ? headline(shown) : "");
  const label = $derived(shown?.kind === "parking" ? "Show QR code" : shown?.kind === "hotel" ? "Show check-in" : "Show pickup");
  const tone = $derived(shown?.kind === "car" ? "var(--kind-car)" : shown?.kind === "hotel" ? "var(--kind-stay)" : "var(--kind-parking)");

  $effect(() => {
    void checkArrivalHere();
    const back = () => { if (document.visibilityState === "visible") void checkArrivalHere(); };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  });
</script>

{#if shown}
  <section class="mb-4 flex items-start gap-3 rounded-[18px] border border-border p-3 pl-3.5 shadow-sm" role="status" aria-label={`You’re at ${place}`} data-testid="arrival-card"
    style={`background: linear-gradient(165deg, color-mix(in oklab, ${tone} 16%, var(--card)) 0%, var(--card) 70%)`}>
    <KindTile kind={shown.kind} decorative />
    <div class="min-w-0 flex-1">
      <p class="break-words text-[15px] font-semibold">You’re at {place}</p>
      <p class="text-caption text-muted-foreground">Your code is one tap away.</p>
      <div class="mt-2"><Button size="sm" onclick={() => (open = true)}>{label}</Button></div>
    </div>
    <Button variant="ghost" size="icon" class="-mr-1.5 -mt-1.5" aria-label="Dismiss" onclick={() => dismissArrival(shown.id)}><X /></Button>
  </section>
  <ArrivalCode segment={shown} {now} bind:open />
{/if}
