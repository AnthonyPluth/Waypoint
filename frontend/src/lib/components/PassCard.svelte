<script lang="ts">
  import type { Segment } from "$lib/api-types";
  import AirportCode from "$lib/components/AirportCode.svelte";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import RouteLine from "$lib/components/RouteLine.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Button } from "$lib/components/ui/button";
  import { flightStatus, statusFor } from "$lib/flightstatus.svelte";
  import { isMobile } from "$lib/platform";
  import { segmentChips } from "$lib/status";
  import { dayLabel, END_WORD, headline, passHeadline, routeProgress, START_WORD, untimed } from "$lib/trips";

  let { segment: s, now = Date.now() }: { segment: Segment; now?: number } = $props();

  const flight = $derived(s.kind === "flight");
  const cancelled = $derived(s.status === "cancelled");
  const unknown = $derived(untimed(s));
  const live = $derived(flight && !cancelled ? statusFor(s.id) : undefined);
  const chips = $derived(segmentChips(s.status, live, !!flightStatus.list?.enabled));
  const progress = $derived(routeProgress(s, now));
  const seat = $derived(s.details.seat || [...new Set(s.travelers.map((t) => t.seat).filter(Boolean))].join(", "));
  const number = $derived(s.details.flight_number ?? "");
  const app = $derived(s.links.app ?? s.manage_url);
  const appWord = $derived(isMobile() ? "Open in app" : "Manage booking");
  const asOf = (t: string) => new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(t));
  const where = $derived([live?.dep_gate && `Gate ${live.dep_gate}`].filter(Boolean).join(" · "));
  const quiet = $derived(live ? [live.delay_minutes ? `${live.delay_minutes} min late` : "", where, `as of ${asOf(live.fetched_at)}`].filter(Boolean).join(" · ") : "");
  const rows = $derived<[string, string | null | undefined][]>(
    flight ? [["Terminal", s.details.terminal], ["Gate", live?.dep_gate], ["Seat", seat], ["Cabin", s.details.cabin]]
      : s.kind === "hotel" ? [["Address", s.details.address], ["Room", s.details.room]]
        : s.kind === "car" ? [["Car", s.details.car_class], ["Address", s.details.address]]
          : s.kind === "cruise" ? [["Ship", s.details.ship], ["Cabin", s.details.room], ["Deck", s.details.deck]]
            : [["Seat", seat], ["Cabin", s.details.cabin]],
  );
  const facts = $derived(rows.filter((f): f is [string, string] => !!f[1]));
</script>

<section class="pass" class:opacity-70={cancelled} aria-label={headline(s)} data-kind={s.kind} data-progress={flight ? progress : undefined}>
  <div class="flex flex-col gap-4 p-6 md:p-8">
    <p class="text-heading font-semibold" class:text-primary={!cancelled} class:text-destructive={cancelled} data-headline>{passHeadline(s, now)}</p>

    {#if s.confirmation}
      <div class="flex flex-col gap-1">
        <p class="eyebrow">Confirmation</p>
        <CopyCode code={s.confirmation} class="w-fit text-display" />
      </div>
    {/if}

    <div class="flex items-center gap-3">
      <BrandLogo src={s.logo} label={s.logo_label} size={40} />
      <div class="min-w-0">
        {#if flight}
          <p class="break-words font-medium" class:line-through={cancelled}>{[s.provider, number].filter(Boolean).join(" ")}</p>
          <p class="text-sm text-muted-foreground">
            {dayLabel(s.start_local)}{#if !unknown}, <PlaceTime local={s.start_local} zone={s.start_zone} />{:else}, time not recorded{/if}
          </p>
        {:else}
          <p class="break-words text-title font-semibold" class:line-through={cancelled}>{headline(s)}</p>
        {/if}
      </div>
    </div>

    {#if app}
      <div><Button variant="outline" href={app} target="_blank" rel="noopener noreferrer">{appWord}</Button></div>
    {/if}

    {#if flight}
      <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
        <AirportCode code={s.origin ?? "—"} size="medium" />
        <span title="The plane’s place is worked out from the booked times, not live data" class="min-w-0">
          <RouteLine progress={cancelled ? 0 : progress} label="Route, with the plane placed from the booked times" />
        </span>
        <AirportCode code={s.destination ?? "—"} size="medium" class="text-right" />
        <div class="col-span-3 flex flex-wrap justify-between gap-x-4 text-sm">
          <p>{#if unknown}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.start_local} zone={s.start_zone} />{/if}</p>
          <p class="text-right">{#if unknown}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.end_local} zone={s.end_zone} />{/if}</p>
        </div>
      </div>
    {:else}
      <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
        <div><dt class="eyebrow">{START_WORD[s.kind]}</dt>
          <dd class="mt-1 font-medium">{dayLabel(s.start_local)}, {#if unknown}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.start_local} zone={s.start_zone} />{/if}</dd></div>
        <div><dt class="eyebrow">{END_WORD[s.kind]}</dt>
          <dd class="mt-1 font-medium">{dayLabel(s.end_local)}, {#if unknown}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.end_local} zone={s.end_zone} />{/if}</dd></div>
      </dl>
    {/if}
  </div>

  <div class="pass-tear" aria-hidden="true"></div>

  <div class="flex flex-col gap-3 p-6 md:p-8">
    {#if facts.length}
      <dl class="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        {#each facts as [label, value] (label)}
          <div class="min-w-0"><dt class="eyebrow">{label}</dt><dd class="mt-1 break-words text-base font-medium">{value}</dd></div>
        {/each}
      </dl>
    {/if}
    <div class="flex flex-wrap items-center gap-2">
      <StatusChip chip={chips.booking} />
      {#if chips.live}<StatusChip chip={chips.live} small />{/if}
    </div>
    {#if live && chips.live}<p class="text-sm text-muted-foreground" data-live-line>{quiet}</p>{/if}
  </div>
</section>
