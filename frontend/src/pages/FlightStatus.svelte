<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { Segment, Trip } from "$lib/api-types";
  import { app, route } from "$lib/app.svelte";
  import { cityNames } from "$lib/cities.svelte";
  import { apiCall } from "$lib/contract";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import FlightArc from "$lib/components/FlightArc.svelte";
  import SourceDot from "$lib/components/SourceDot.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { pausedWords, type Stamp } from "$lib/flightcard";
  import { flightLiveView } from "$lib/flightlive";
  import { flightStatus, followFlightStatus, loadFlightStatus, refreshFlightStatus, statusFor } from "$lib/flightstatus.svelte";
  import { flightRoute } from "$lib/nav";
  import { viewport } from "$lib/phone.svelte";
  import { endAt, untimed } from "$lib/trips";
  import ChevronLeft from "@lucide/svelte/icons/chevron-left";
  import Plane from "@lucide/svelte/icons/plane";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { toast } from "svelte-sonner";

  const AFTER_LANDING = 6 * 3_600_000;

  let trip = $state<Trip | null>(null);
  let loadError = $state("");
  let busy = $state(false);
  let refreshFailed = $state(false);
  let now = $state(Date.now());
  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(tick);
  });

  const tripId = $derived(route.sub);
  const segmentId = $derived(flightRoute(route.rest));
  const segment = $derived<Segment | null>(trip?.segments.find((s) => s.id === segmentId && s.kind === "flight") ?? null);
  const list = $derived(flightStatus.list);
  const liveOn = $derived(list?.enabled === true);
  const status = $derived(segment ? statusFor(segment.id) : undefined);
  const paused = $derived(liveOn ? list?.paused ?? null : null);
  let online = $state(typeof navigator === "undefined" || navigator.onLine !== false);
  $effect(() => {
    const set = () => (online = navigator.onLine !== false);
    window.addEventListener("online", set);
    window.addEventListener("offline", set);
    return () => { window.removeEventListener("online", set); window.removeEventListener("offline", set); };
  });
  const cities = cityNames(() => [segment?.origin, segment?.destination, liveOn ? status?.destination : null]);
  const view = $derived(segment ? flightLiveView({ segment, status: liveOn ? status : undefined, liveOn, now, online, city: (code) => cities[code] || code }) : null);
  const canRefresh = $derived(liveOn && !paused && !!segment && (!!status || now <= endAt(segment) + AFTER_LANDING));
  const phone = $derived(viewport.phone);

  followFlightStatus(() => (segment ? [segment] : []), () => app.sessionExpired);

  let latest = 0;
  async function load() {
    const mine = ++latest;
    loadError = "";
    refreshFailed = false;
    if (!/^\d+$/.test(tripId)) { trip = null; loadError = "No such trip"; return; }
    try {
      const found = await apiCall<"GET /api/trips/{id}">(`/api/trips/${tripId}`);
      if (mine !== latest) return;
      trip = found;
      void loadFlightStatus();
    } catch (err) {
      if (mine !== latest) return;
      trip = null;
      loadError = errMsg(err);
    }
  }
  $effect(() => { void tripId; trip = null; void load(); });

  async function refresh() {
    if (!segment) return;
    const id = segment.id;
    const ok = await act(() => refreshFlightStatus(id), { busy: (on) => (busy = on) });
    refreshFailed = !ok;
    if (ok && !statusFor(id) && !flightStatus.list?.paused) toast("No live status found for this flight yet.");
  }

  const clockOf = (iso: string) => new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(iso));
  const updatedLine = $derived.by(() => {
    if (refreshFailed) return status ? `Couldn’t refresh. Last updated ${clockOf(status.fetched_at)}.` : "Couldn’t refresh.";
    return view?.updated ? `${view.updated} · live status` : "";
  });

  const grid = (n: number) => `grid-template-columns: repeat(${Math.max(1, n)}, minmax(0, 1fr))`;
  const cityOf = (code: string) => cities[code] ?? "";
</script>

{#snippet when(t: Stamp, scheduled: string)}
  <span class="mt-1.5 whitespace-nowrap font-mono text-xl font-semibold" class:text-signal-ink={t.tone === "late"}><time datetime={t.local}>{t.time}</time></span>
  <span class="font-mono text-[11px] text-muted-foreground">{t.zoneName} · scheduled {scheduled}{#if t.later}<span>{" · "}{t.later}<span class="sr-only">, {t.laterWords}</span></span>{/if}</span>
{/snippet}

{#snippet refreshButton()}
  {#if phone}
    <Button variant="ghost" size="icon" class="size-11" aria-label="Refresh flight status" disabled={busy} onclick={refresh}><RefreshCw class={busy ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" /></Button>
  {:else}
    <Button variant="outline" size="sm" disabled={busy} onclick={refresh}><RefreshCw class={`size-3.5 ${busy ? "animate-spin motion-reduce:animate-none" : ""}`} aria-hidden="true" />Refresh</Button>
  {/if}
{/snippet}

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span>
    <span class="flex gap-2"><Button variant="outline" href="#trips">Back to trips</Button><Button variant="outline" onclick={load}>Try again</Button></span>
  </AlertDescription></Alert>
{:else if trip === null}
  <div class="h-40 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" role="progressbar" aria-busy="true" aria-label="Loading"></div>
{:else if !segment || !view}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>No such flight</span>
    <Button variant="outline" href={`#trip/${trip.id}`}>Back to {trip.name}</Button>
  </AlertDescription></Alert>
{:else if untimed(segment)}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>This flight has no time recorded yet, so there’s no live status to show.</span>
    <Button variant="outline" href={`#trip/${trip.id}`}>Back to {trip.name}</Button>
  </AlertDescription></Alert>
{:else}
  {@const card = view.card}
  <div class="flex flex-col gap-3.5 desktop:gap-[18px]" data-testid="flight-live" data-state={card.state}>
    <div class="flex items-center justify-between gap-3">
      <a href={`#trip/${trip.id}`} aria-label={`Back to ${trip.name}`} class="inline-flex min-h-11 min-w-0 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none rounded-lg"><ChevronLeft class="size-4 flex-none" aria-hidden="true" /><span class="truncate">{trip.name}</span></a>
      <span class="inline-flex items-center gap-3">
        {#if !phone && updatedLine}<span class="text-[13px] text-muted-foreground" data-updated>{updatedLine}</span>{/if}
        {#if canRefresh}{@render refreshButton()}{/if}
      </span>
    </div>

    <div class="grid gap-3.5 desktop:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] desktop:items-start desktop:gap-5">
      <div class="contents desktop:flex desktop:flex-col desktop:gap-[18px]">
        <div class="flex flex-col gap-3 rounded-[22px] border border-border bg-card p-4 shadow-card" data-kind="flight" data-state={card.state}>
          <div class="flex items-center gap-2.5">
            <span class="grid size-[30px] flex-none place-items-center rounded-[9px] bg-avatar-1 text-[11px] font-bold tracking-[0.02em] text-avatar-1-ink" aria-hidden="true">{#if card.carrier}{card.carrier}{:else}<Plane class="size-4" />{/if}</span>
            <span class="min-w-0">
              <b class="block font-mono text-sm font-semibold">{card.number || "Flight"}</b>
              {#if view.title}<span class="block truncate text-[13px] leading-[1.1] text-muted-foreground">{view.title}</span>{/if}
            </span>
            {#if card.pill}<StatusChip chip={card.pill} class="ml-auto py-[3px]! font-bold! uppercase tracking-[0.04em]" />{/if}
          </div>

          <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2.5">
            <div class="flex min-w-[78px] flex-col gap-0.5">
              <b class="text-[44px] font-[650] leading-none tracking-[-0.03em] desktop:text-[56px]" data-code="origin">{card.origin}</b>
              <span class="text-xs text-muted-foreground">{cityOf(card.origin)}</span>
              {#if !phone}{@render when(card.depart, view.scheduledDepart)}{/if}
            </div>
            <FlightArc progress={card.progress} class="mt-1.5" box={phone ? 56 : 70} pixels={phone ? 44 : 56} plane={phone ? 20 : 22} />
            <div class="flex min-w-[78px] flex-col items-end gap-0.5 text-right">
              <b class="text-[44px] font-[650] leading-none tracking-[-0.03em] desktop:text-[56px]" data-code="destination">{card.destination}</b>
              <span class="text-xs text-muted-foreground">{cityOf(card.destination)}</span>
              {#if !phone}{@render when(card.arrive, view.scheduledArrive)}{/if}
            </div>
          </div>

          <div class="flex flex-col gap-0.5">
            <h1 aria-live="polite" class="text-[26px] font-[650] tracking-[-0.025em] desktop:text-[28px]" data-headline>{view.headline}</h1>
            {#if phone ? view.detailPhone : view.detailDesktop}<span class="text-[13px] text-muted-foreground" data-detail>{phone ? view.detailPhone : view.detailDesktop}</span>{/if}
          </div>

          {#if view.percent !== null}
            <div role="progressbar" aria-label="Flight progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow={view.percent} class="h-1.5 overflow-hidden rounded-md bg-surface-3"><div class="h-full bg-status-info-ink" style={`width: ${view.percent}%`}></div></div>
          {/if}

          {#if paused}<p class="text-xs text-muted-foreground" role="status" data-paused>{pausedWords(paused)}</p>{/if}
        </div>

        <ul role="list" aria-label="Flight timeline" class="rounded-[18px] border border-border bg-card px-3.5 py-1 desktop:px-[18px]">
          {#each view.steps as step (step.title)}
            <li class="flex items-start gap-3 border-b border-border py-2.5 last:border-b-0" data-dot={step.dot}>
              <i aria-hidden="true" class={`mt-1.5 size-2.5 flex-none rounded-full ${step.dot === "done" ? "bg-status-ok-ink" : step.dot === "now" ? "bg-status-info-ink shadow-[0_0_0_4px_color-mix(in_srgb,var(--status-info-ink)_20%,transparent)]" : "border-2 border-muted-foreground"}`}></i>
              <span class="min-w-0"><b class="block text-sm font-semibold">{step.title}</b><span class="block text-[13px] text-muted-foreground">{step.note}</span></span>
              {#if step.when}<span class="ml-auto text-right font-mono text-[15px] font-semibold">{#if step.at}<time datetime={step.at}>{step.when}</time>{:else}{step.when}{/if}{#if step.later && phone}<span class="block text-[11px] font-normal text-muted-foreground">{step.later}<span class="sr-only">, {step.laterWords}</span></span>{/if}</span>{/if}
            </li>
          {/each}
        </ul>
      </div>

      <div class="contents desktop:flex desktop:flex-col desktop:gap-[18px]">
        <div class="flex flex-col gap-3 rounded-[22px] border border-border bg-card p-4 shadow-card phone:rounded-[18px] phone:p-3.5 phone:shadow-none">
          {#if !phone || card.side === "Departure"}<span class="eyebrow">{card.side}{cityOf(card.sideCode) ? ` · ${cityOf(card.sideCode)}` : ""}</span>{/if}
          <dl class="grid gap-2" style={grid(view.facts.length)} data-facts>
            {#each view.facts as fact (fact.label)}
              <div>
                <dt class="flex items-center gap-[5px] whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"><SourceDot kind={fact.source} />{fact.label}</dt>
                {#if fact.value}
                  <dd class="mt-0.5 break-words text-[22px] font-[650] tracking-[-0.02em] desktop:text-[30px]">{fact.value}</dd>
                {:else}
                  <dd class="mt-0.5 text-[22px] font-medium tracking-[-0.02em] text-muted-foreground desktop:text-[30px]"><span aria-hidden="true">—</span><span class="sr-only">Not known yet</span></dd>
                {/if}
              </div>
            {/each}
          </dl>
          {#if !phone && view.note}<p class="text-xs text-muted-foreground">{view.note}</p>{/if}
        </div>

        {#if phone}
          <div class="flex items-center justify-between gap-3">
            <span class="text-[13px] text-muted-foreground" data-updated>{updatedLine}</span>
            {#if view.seats.length}
              <div class="flex min-w-0 flex-wrap justify-end gap-x-1 text-[13px] text-muted-foreground">
                <span>Seats:</span>
                <ul aria-label="Seats by traveller" class="flex flex-wrap gap-x-1" role="list">
                  {#each view.seats as row (row.id)}
                    <li class="after:content-[','] last:after:content-none">{row.first}{" "}{#if row.seat}{row.seat}{:else}<span aria-hidden="true">—</span><span class="sr-only">Not known yet</span>{/if}</li>
                  {/each}
                </ul>
              </div>
            {/if}
          </div>
        {:else}
          {#if view.seats.length}
            <ul role="list" aria-label="Seats by traveller" class="overflow-hidden rounded-[18px] border border-border bg-card">
              {#each view.seats as row (row.id)}
                <li class="flex items-center gap-3 border-b border-border px-3.5 py-[11px] last:border-b-0">
                  <span class="min-w-0 flex-1"><b class="block truncate text-sm font-semibold">{row.name}</b><span class="text-[13px] text-muted-foreground">{row.seat ? `Seat ${row.seat}` : "Seat not known yet"}{row.cabin ? ` · ${row.cabin}` : ""}</span></span>
                  <SourceDot kind="booking" />
                </li>
              {/each}
            </ul>
          {/if}
          <p class="text-[13px] text-muted-foreground">Seats and cabin come from the booking. Gate, terminal and belt come from live status and can change.</p>
        {/if}
      </div>
    </div>
  </div>
{/if}
