<script lang="ts" module>
  import type { FlightStatus, Segment } from "$lib/api-types";

  export type ChipKind = "booking" | "live";
  export type ChipStatus = Segment["status"] | FlightStatus["state"];
  type Tone = "confirmed" | "changed" | "cancelled" | "ontime" | "delayed" | "airborne" | "diverted";

  const TONE: Record<ChipStatus, Tone> = {
    confirmed: "confirmed", changed: "changed", cancelled: "cancelled",
    scheduled: "ontime", delayed: "delayed", departed: "airborne", landed: "airborne", diverted: "diverted",
  };

  const WORD: Record<ChipStatus, string> = {
    confirmed: "Confirmed", changed: "Changed", cancelled: "Cancelled",
    scheduled: "On time", delayed: "Delayed", departed: "Departed", landed: "Landed", diverted: "Diverted",
  };

  const SURFACE: Record<Tone, string> = {
    confirmed: "bg-confirmed-soft text-confirmed-ink",
    changed: "bg-changed-soft text-changed-ink",
    cancelled: "bg-cancelled-soft text-cancelled-ink",
    ontime: "bg-ontime-soft text-ontime-ink",
    delayed: "bg-delayed-soft text-delayed-ink",
    airborne: "bg-airborne-soft text-airborne-ink",
    diverted: "bg-diverted-soft text-diverted-ink",
  };

  const SIZE: Record<ChipKind, string> = {
    booking: "px-2.5 py-0.5 text-sm font-semibold",
    live: "px-2 py-px text-xs font-medium",
  };

  export const chipLabel = (status: ChipStatus, delay?: number | null): string =>
    status === "delayed" && delay ? `${WORD[status]} ${delay} min` : WORD[status];

  export const chipSurface = (status: ChipStatus): string => SURFACE[TONE[status]];
</script>

<script lang="ts">
  import { cn } from "$lib/utils";

  let { status, kind = "booking", delay = null, class: klass = "" }:
    { status: ChipStatus; kind?: ChipKind; delay?: number | null; class?: string } = $props();
</script>

<span class={cn("inline-flex w-fit shrink-0 items-center justify-center whitespace-nowrap rounded-full border border-transparent", SIZE[kind], chipSurface(status), klass)}
  data-testid="status-chip" data-status={status} data-kind={kind}>{chipLabel(status, delay)}</span>
