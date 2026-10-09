<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Segment } from "$lib/api-types";
  import AirportCode from "$lib/components/AirportCode.svelte";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import RouteLine from "$lib/components/RouteLine.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { flightStatus, statusFor } from "$lib/flightstatus.svelte";
  import { isMobile } from "$lib/platform";
  import { segmentChips } from "$lib/status";
  import { appWord, dayLabel, seatsInOrder, END_WORD, headline, passHeadline, routeProgress, START_WORD, timesDiffer, untimed } from "$lib/trips";

  type Props = {
    segment: Segment; bookings?: Segment[]; now?: number; eyebrow?: string; pulse?: boolean; level?: 2 | 3; class?: string;
    as?: "section" | "li"; id?: string; highlight?: boolean; label?: string; showCode?: boolean; showApp?: boolean; omit?: string[];
    live?: Snippet; footer?: Snippet; times?: Snippet; details?: Snippet;
  };
  let { segment: s, bookings = [s], now = Date.now(), eyebrow = "", pulse = false, level = 3, class: cls = "", as: tag = "section", id, highlight = false, label, showCode = true, showApp = true, omit = [],
    live: liveArea, footer, times: timesArea, details }: Props = $props();

  const flight = $derived(s.kind === "flight");
  const cancelled = $derived(s.status === "cancelled");
  const unknown = $derived(untimed(s));
  const status = $derived(flight && !cancelled && flightStatus.list?.enabled ? statusFor(s.id) : undefined);
  const chips = $derived(segmentChips(s.status, status, !!flightStatus.list?.enabled));
  const codes = $derived(bookings.filter((b) => b.confirmation));
  const differ = $derived(bookings.length > 1 && timesDiffer(bookings));
  const progress = $derived(routeProgress(s, now));
  const seat = $derived(seatsInOrder(s.details.seat || s.travelers.map((t) => t.seat).filter(Boolean).join(", ")));
  const number = $derived(s.details.flight_number ?? "");
  const app = $derived(s.links.app ?? s.manage_url);
  const appLabel = $derived(appWord(s, now, isMobile()));
  const asOf = (t: string) => new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(t));
  const where = $derived([status?.dep_gate && `Gate ${status.dep_gate}`].filter(Boolean).join(" · "));
  const quiet = $derived(status ? [status.delay_minutes ? `${status.delay_minutes} min late` : "", where, `as of ${asOf(status.fetched_at)}`].filter(Boolean).join(" · ") : "");
  const rows = $derived<[string, string | null | undefined][]>(
    flight ? [["Terminal", s.details.terminal], ["Gate", status?.dep_gate], ["Seat", seat], ["Cabin", s.details.cabin]]
      : s.kind === "hotel" ? [["Address", s.details.address], ["Room", s.details.room]]
        : s.kind === "car" ? [["Car", s.details.car_class], ["Address", s.details.address]]
          : s.kind === "cruise" ? [["Ship", s.details.ship], ["Cabin", s.details.room], ["Deck", s.details.deck]]
            : [["Seat", seat], ["Cabin", s.details.cabin]],
  );
  const facts = $derived(rows.filter((f): f is [string, string] => !!f[1] && !omit.includes(f[0])));
</script>

<svelte:element this={tag} {id} class={`pass scroll-mt-20 ${cls}`} class:ring-2={highlight} class:ring-ring={highlight} class:opacity-80={cancelled} aria-label={label ?? (tag === "section" ? headline(s) : undefined)} data-kind={s.kind} data-progress={flight ? progress : undefined}>
  <div class="flex flex-col gap-4 p-6 md:p-8">
    {#if eyebrow}<p class="eyebrow flex items-center gap-2">{#if pulse}<span class="size-2 animate-pulse rounded-full bg-primary motion-reduce:animate-none" aria-hidden="true"></span>{/if}{eyebrow}</p>{/if}
    {#key passHeadline(s, now)}<p class="countdown text-heading font-semibold" class:text-primary={!cancelled} class:text-destructive={cancelled} data-headline data-countdown>{passHeadline(s, now)}</p>{/key}
    {#if flight}<svelte:element this={`h${level}`} class="sr-only">{headline(s)}</svelte:element>{/if}

    {#if showCode && codes.length}
      <div class="flex flex-col gap-1">
        <p class="eyebrow">{codes.length > 1 ? "Confirmations" : "Confirmation"}</p>
        <p class="flex flex-wrap gap-x-4">{#each codes as b (b.id)}<CopyCode code={b.confirmation ?? ""} class="w-fit text-display" />{/each}</p>
      </div>
    {/if}

    <div class="flex items-center gap-3">
      <BrandLogo src={s.logo} label={s.logo_label} size={40} />
      <div class="min-w-0">
        {#if flight}
          <p class="break-words font-medium" class:line-through={cancelled}>{[s.provider, number].filter(Boolean).join(" ")}</p>
          <p class="text-sm text-muted-foreground">
            {#if !timesArea}{dayLabel(s.start_local)}{#if unknown}, time not recorded{:else if !differ}, <PlaceTime local={s.start_local} zone={s.start_zone} />{/if}{/if}
          </p>
        {:else}
          <svelte:element this={`h${level}`} class="break-words text-title font-semibold" class:line-through={cancelled}>{headline(s)}</svelte:element>
        {/if}
      </div>
    </div>

    {#if app && showApp}
      <div><Button variant="outline" href={app} target="_blank" rel="noopener noreferrer">{appLabel}</Button></div>
    {/if}

    {#if flight}
      <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
        <AirportCode code={s.origin ?? "—"} size="medium" />
        <span title="The plane’s place is worked out from the booked times, not live data" class="min-w-0">
          <RouteLine progress={cancelled ? 0 : progress} label="Route, with the plane placed from the booked times" />
        </span>
        <AirportCode code={s.destination ?? "—"} size="medium" class="text-right" />
        {#if timesArea}{:else if differ}
          <div class="col-span-3 mt-2 flex flex-col gap-1 text-sm">
            <span><Badge variant="secondary">Times differ between bookings</Badge></span>
            {#each bookings as b (b.id)}
              <span>{b.confirmation ? `${b.confirmation}: ` : ""}{START_WORD[b.kind].toLowerCase()} {dayLabel(b.start_local)}, <PlaceTime local={b.start_local} zone={b.start_zone} />, {END_WORD[b.kind].toLowerCase()} {dayLabel(b.end_local)}, <PlaceTime local={b.end_local} zone={b.end_zone} /></span>
            {/each}
          </div>
        {:else}
        <div class="col-span-3 flex flex-wrap justify-between gap-x-4 text-sm">
          <p>{#if unknown}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.start_local} zone={s.start_zone} />{/if}</p>
          <p class="text-right">{#if unknown}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.end_local} zone={s.end_zone} />{/if}</p>
        </div>
        {/if}
      </div>
      {#if timesArea}{@render timesArea()}{/if}
    {:else if timesArea}
      {@render timesArea()}
    {:else}
      <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
        <div><dt class="eyebrow">{START_WORD[s.kind]}</dt>
          <dd class="mt-1 font-medium">{dayLabel(s.start_local)}, {#if unknown}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.start_local} zone={s.start_zone} />{/if}</dd></div>
        <div><dt class="eyebrow">{END_WORD[s.kind]}</dt>
          <dd class="mt-1 font-medium">{dayLabel(s.end_local)}, {#if unknown}<span class="text-muted-foreground">time not recorded</span>{:else}<PlaceTime local={s.end_local} zone={s.end_zone} />{/if}</dd></div>
      </dl>
    {/if}
    {#if details}{@render details()}{/if}
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
      {#if !liveArea && chips.live}<StatusChip chip={chips.live} small />{/if}
    </div>
    {#if liveArea}{@render liveArea()}{:else if status && chips.live}<p class="text-sm text-muted-foreground" data-live-line>{quiet}</p>{/if}
    {#if footer}<div>{@render footer()}</div>{/if}
  </div>
</svelte:element>
