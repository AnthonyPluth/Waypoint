<script lang="ts">
  import AirportCode from "$lib/components/AirportCode.svelte";
  import RouteLine from "$lib/components/RouteLine.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { bookingChip, liveChip } from "$lib/status";

  const booking = (["confirmed", "changed", "cancelled"] as const).map(bookingChip);
  const live = [
    liveChip({ state: "scheduled", delay_minutes: null }),
    liveChip({ state: "delayed", delay_minutes: 25 }),
    liveChip({ state: "departed", delay_minutes: null }),
    liveChip({ state: "landed", delay_minutes: null }),
    liveChip({ state: "diverted", delay_minutes: null }),
  ];
  const routes = [
    { when: "Before departure", progress: 0 },
    { when: "Under way", progress: 0.55 },
    { when: "After arrival", progress: 1 },
  ];
  const type = [
    { name: "Display", cls: "text-display", sample: "K7Q2ZM" },
    { name: "Title", cls: "text-title", sample: "Upcoming" },
    { name: "Heading", cls: "text-heading", sample: "Check-in is open" },
    { name: "Body", cls: "text-body", sample: "Departs at 7:05 AM from Terminal 1." },
    { name: "Caption", cls: "text-caption text-muted-foreground", sample: "As of 6:42 AM" },
    { name: "Eyebrow", cls: "text-eyebrow uppercase text-muted-foreground", sample: "Next up" },
  ];
  const surfaces = [
    { name: "Surface 1", cls: "bg-surface-1 shadow-elevation-1" },
    { name: "Surface 2", cls: "bg-surface-2 shadow-elevation-2" },
    { name: "Surface 3", cls: "bg-surface-3 shadow-elevation-3" },
  ];
</script>

<h1 class="mb-6 text-4xl font-bold tracking-tight">Design</h1>

<div class="flex flex-col gap-8">
  <section class="flex flex-col gap-3" aria-labelledby="design-status">
    <h2 id="design-status" class="text-heading">Status</h2>
    <p class="text-caption text-muted-foreground">The booking chip leads. The live chip is smaller and appears only when live flight status is on.</p>
    <div class="rows"><div class="row"><span class="text-caption text-muted-foreground">Booking</span><span class="flex flex-wrap gap-2">{#each booking as chip (chip.label)}<StatusChip {chip} />{/each}</span></div>
      <div class="row"><span class="text-caption text-muted-foreground">Live</span><span class="flex flex-wrap gap-2">{#each live as chip (chip.label)}<StatusChip {chip} small />{/each}</span></div></div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-codes">
    <h2 id="design-codes" class="text-heading">Airport codes</h2>
    <div class="rows"><div class="row"><AirportCode code="MSP" name="Minneapolis–Saint Paul" /><AirportCode code="LAX" name="Los Angeles" size="medium" /><AirportCode code="JFK" name="New York Kennedy" size="small" /></div></div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-route">
    <h2 id="design-route" class="text-heading">Route line</h2>
    <p class="text-caption text-muted-foreground">The plane is placed from the booked times, from 0 at departure to 1 at arrival.</p>
    <div class="rows">
      {#each routes as r (r.when)}
        <div class="row">
          <span class="w-36 text-caption text-muted-foreground">{r.when}</span>
          <span class="flex min-w-0 flex-1 items-center gap-3"><AirportCode code="MSP" size="small" /><RouteLine class="flex-1" progress={r.progress} label={`${r.when}, based on the booked times`} /><AirportCode code="LAX" size="small" /></span>
        </div>
      {/each}
    </div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-type">
    <h2 id="design-type" class="text-heading">Type</h2>
    <div class="rows">{#each type as t (t.name)}<div class="row"><span class="w-20 text-caption text-muted-foreground">{t.name}</span><span class={`min-w-0 flex-1 break-words ${t.cls}`}>{t.sample}</span></div>{/each}</div>
  </section>

  <section class="flex flex-col gap-3" aria-labelledby="design-surfaces">
    <h2 id="design-surfaces" class="text-heading">Surfaces</h2>
    <div class="grid gap-3 sm:grid-cols-3">{#each surfaces as s (s.name)}<div class={`rounded-2xl border p-4 text-caption ${s.cls}`}>{s.name}</div>{/each}</div>
  </section>
</div>
