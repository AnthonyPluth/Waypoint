<script lang="ts" module>
  export const clock = (local: string | null) => (local ? local.slice(11, 16) : "");

  export function dayShift(local: string | null, booked: string | null): string {
    if (!local || !booked) return "";
    const days = Math.round((Date.UTC(+local.slice(0, 4), +local.slice(5, 7) - 1, +local.slice(8, 10)) -
      Date.UTC(+booked.slice(0, 4), +booked.slice(5, 7) - 1, +booked.slice(8, 10))) / 86_400_000);
    return days === 0 ? "" : ` (${days > 0 ? "+" : "−"}${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"})`;
  }
</script>

<script lang="ts">
  import { act } from "$lib/act";
  import type { Segment } from "$lib/api-types";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Button } from "$lib/components/ui/button";
  import { flightStatus, refreshFlightStatus, statusFor } from "$lib/flightstatus.svelte";
  import { liveChip } from "$lib/status";
  import { endAt } from "$lib/trips";
  import { toast } from "svelte-sonner";

  let { segment }: { segment: Segment } = $props();
  let busy = $state(false);

  const list = $derived(flightStatus.list);
  const s = $derived(statusFor(segment.id));
  const over = $derived(Date.now() > endAt(segment) + 6 * 3_600_000);
  const asOf = (t: string) => new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(t));

  const where = (terminal: string | null, gate: string | null) =>
    [terminal && `Terminal ${terminal}`, gate && `Gate ${gate}`].filter(Boolean).join(" · ");

  function pausedText(p: NonNullable<typeof list>["paused"]): string {
    if (!p) return "";
    const until = new Date(p.until);
    if (p.reason === "limit") return `Live status paused until ${until.toLocaleDateString(undefined, { month: "short", day: "numeric" })} (monthly limit)`;
    const time = asOf(p.until);
    return `Live status paused until ${time} (${p.reason === "rate" ? "rate limit" : "RapidAPI didn’t accept the key"})`;
  }

  async function refresh() {
    const ok = await act(() => refreshFlightStatus(segment.id), { busy: (on) => (busy = on) });
    if (ok && !statusFor(segment.id) && !flightStatus.list?.paused) toast("No live status found for this flight yet.");
  }
</script>

{#if list?.enabled && (s || !over)}
  <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm" data-testid="flight-status">
    {#if s}
      <StatusChip chip={liveChip(s)} small />
      <span class="min-w-0 text-muted-foreground">
        {#if s.state === "landed"}
          Landed {clock(s.arr_actual ?? s.arr_estimated)}{dayShift(s.arr_actual ?? s.arr_estimated, s.arr_scheduled)}
        {:else if s.state === "cancelled"}
          Booked {clock(s.dep_scheduled)}
        {:else if s.dep_actual ?? s.dep_estimated}
          {s.dep_actual ? "Left" : "Now"} {clock(s.dep_actual ?? s.dep_estimated)}{dayShift(s.dep_actual ?? s.dep_estimated, s.dep_scheduled)}
          <span class="whitespace-nowrap">(booked {clock(s.dep_scheduled)})</span>
        {:else}
          Booked {clock(s.dep_scheduled)}
        {/if}
      </span>
      {#if where(s.dep_terminal, s.dep_gate)}<span class="font-medium">{where(s.dep_terminal, s.dep_gate)}</span>{/if}
      {#if s.state !== "landed" && s.arr_estimated && s.arr_scheduled && s.arr_estimated !== s.arr_scheduled}
        <span class="text-muted-foreground">Arrives {clock(s.arr_estimated)}{dayShift(s.arr_estimated, s.arr_scheduled)}</span>
      {/if}
      {#if where(s.arr_terminal, s.arr_gate)}<span class="text-muted-foreground">Arrival {where(s.arr_terminal, s.arr_gate).toLowerCase()}</span>{/if}
      <span class="text-xs text-muted-foreground">as of {asOf(s.fetched_at)}</span>
    {/if}
    {#if list.paused}
      <span class="text-muted-foreground" role="status">{pausedText(list.paused)}</span>
    {:else if !over}
      <Button variant="ghost" size="sm" disabled={busy} onclick={refresh}>{busy ? "Refreshing…" : s ? "Refresh" : "Check live status"}</Button>
    {/if}
  </div>
{/if}
