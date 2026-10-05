<script lang="ts" module>
  /** "19:50" from a wall-clock time ("2026-11-20T19:50"): read off as it is, never turned into a Date (which would move it
   *  into the browser's zone). */
  export const clock = (local: string | null) => (local ? local.slice(11, 16) : "");

  /** " (+1 day)" when the time falls on another day than the booked one. */
  export function dayShift(local: string | null, booked: string | null): string {
    if (!local || !booked) return "";
    const days = Math.round((Date.UTC(+local.slice(0, 4), +local.slice(5, 7) - 1, +local.slice(8, 10)) -
      Date.UTC(+booked.slice(0, 4), +booked.slice(5, 7) - 1, +booked.slice(8, 10))) / 86_400_000);
    return days === 0 ? "" : ` (${days > 0 ? "+" : "−"}${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"})`;
  }
</script>

<script lang="ts">
  import { act } from "$lib/act";
  import type { FlightStatus } from "$lib/api-types";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { flightStatus, refreshFlightStatus, statusFor } from "$lib/flightstatus.svelte";

  // The live status of one flight segment, beside its booked times (which it never changes): the state, the time the flight
  // is now expected, the gate and terminal, when the answer came, and a Refresh. Nothing without RAPIDAPI_KEY. A parent
  // shows it on a flight's card: <FlightStatus segmentId={segment.id} />. The list is loaded by whoever shows it
  // (loadFlightStatus), once for all the cards on the page.
  let { segmentId }: { segmentId: number } = $props();
  let busy = $state(false);

  const list = $derived(flightStatus.list);
  const s = $derived(statusFor(segmentId));
  const asOf = (t: string) => new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(t));

  const WORDS: Record<FlightStatus["state"], string> = {
    scheduled: "On time", delayed: "Delayed", departed: "Departed", landed: "Landed", cancelled: "Cancelled", diverted: "Diverted",
  };
  const label = (x: FlightStatus) => (x.state === "delayed" && x.delay_minutes ? `Delayed ${x.delay_minutes} min` : WORDS[x.state]);
  const variant = (x: FlightStatus) => (x.state === "cancelled" || x.state === "diverted" ? "destructive" : x.state === "delayed" ? "secondary" : "outline");

  /** "Terminal 7 · Gate B24" */
  const where = (terminal: string | null, gate: string | null) =>
    [terminal && `Terminal ${terminal}`, gate && `Gate ${gate}`].filter(Boolean).join(" · ");

  // Why nothing is being fetched, as words: the monthly limit lasts to the 1st, the others an hour.
  function pausedText(p: NonNullable<typeof list>["paused"]): string {
    if (!p) return "";
    const until = new Date(p.until);
    if (p.reason === "limit") return `Live status paused until ${until.toLocaleDateString(undefined, { month: "short", day: "numeric" })} (monthly limit)`;
    const time = asOf(p.until);
    return `Live status paused until ${time} (${p.reason === "rate" ? "rate limit" : "RapidAPI didn’t accept the key"})`;
  }

  const refresh = () => act(() => refreshFlightStatus(segmentId), { busy: (on) => (busy = on) });
</script>

{#if list?.enabled}
  <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm" data-testid="flight-status">
    {#if s}
      <Badge variant={variant(s)} class={s.state === "delayed" ? "bg-signal-soft text-signal-ink border-transparent" : ""}>{label(s)}</Badge>
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
    {:else}
      <Button variant="ghost" size="sm" disabled={busy} onclick={refresh}>{busy ? "Refreshing…" : s ? "Refresh" : "Check live status"}</Button>
    {/if}
  </div>
{/if}
