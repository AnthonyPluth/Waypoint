<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Segment } from "$lib/api-types";
  import AirportCode from "$lib/components/AirportCode.svelte";
  import BrandLogo from "$lib/components/BrandLogo.svelte";
  import CopyCode from "$lib/components/CopyCode.svelte";
  import DayTime from "$lib/components/DayTime.svelte";
  import PlaceTime from "$lib/components/PlaceTime.svelte";
  import RouteLine from "$lib/components/RouteLine.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { flightStatus, statusFor } from "$lib/flightstatus.svelte";
  import { isMobile } from "$lib/platform";
  import { formatMoney } from "$lib/money";
  import { segmentChips } from "$lib/status";
  import { appWord, dayLabel, extraAddress, flightEvidence, placeOf, seatsInOrder, END_WORD, headline, passHeadline, routeProgress, START_WORD, timesDiffer, untimed, vendorLink } from "$lib/trips";

  type Props = {
    segment: Segment; bookings?: Segment[]; now?: number; eyebrow?: string; pulse?: boolean; level?: 2 | 3; class?: string;
    as?: "section" | "li"; id?: string; highlight?: boolean; label?: string; showCode?: boolean; showApp?: boolean; omit?: string[]; condensed?: boolean; compact?: boolean; showCost?: boolean;
    live?: Snippet; footer?: Snippet; times?: Snippet; details?: Snippet;
  };
  let { segment: s, bookings = [s], now = Date.now(), eyebrow = "", pulse = false, level = 3, class: cls = "", as: tag = "section", id, highlight = false, label, showCode = true, showApp = true, omit = [], condensed = false, compact = false, showCost = true,
    live: liveArea, footer, times: timesArea, details }: Props = $props();

  const flight = $derived(s.kind === "flight");
  const cancelled = $derived(s.status === "cancelled");
  const unknown = $derived(untimed(s));
  const noHeadline = $derived(s.kind === "visit" && unknown && !cancelled);
  const status = $derived(flight && !cancelled && flightStatus.list?.enabled ? statusFor(s.id) : undefined);
  const chips = $derived(segmentChips(s.status, status, !!flightStatus.list?.enabled));
  const codes = $derived(bookings.filter((b) => b.confirmation));
  const differ = $derived(bookings.length > 1 && timesDiffer(bookings));
  const online = $derived(typeof navigator === "undefined" || navigator.onLine !== false);
  const evidence = $derived(flight ? flightEvidence(status, now, online) : "scheduled");
  const grounded = $derived(cancelled || evidence === "cancelled");
  const progress = $derived(evidence === "landed" ? 1 : routeProgress(s, now));
  const headlineText = $derived(passHeadline(s, now, status, online));
  const bad = $derived(grounded || evidence === "diverted");
  const seat = $derived(seatsInOrder(s.details.seat || s.travelers.map((t) => t.seat).filter(Boolean).join(", ")));
  const number = $derived(s.details.flight_number ?? "");
  const app = $derived(s.links.app ?? s.manage_url);
  const appLabel = $derived(appWord(s, now, isMobile()));
  const vendor = $derived(vendorLink(s, isMobile()));
  const asOf = (t: string) => new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(t));
  const where = $derived([status?.dep_gate && `Gate ${status.dep_gate}`].filter(Boolean).join(" · "));
  const quiet = $derived(status ? [status.delay_minutes ? `${status.delay_minutes} min late` : "", where, `as of ${asOf(status.fetched_at)}`].filter(Boolean).join(" · ") : "");
  const rows = $derived<[string, string | null | undefined][]>(
    flight ? [["Terminal", s.details.terminal], ["Gate", status?.dep_gate], ["Seat", seat], ["Cabin", s.details.cabin]]
      : s.kind === "hotel" ? [["Address", condensed ? placeOf(s.details.address) : s.details.address], ["Room", s.details.room]]
        : s.kind === "car" ? [["Car", s.details.car_class], ["Pick-up address", condensed ? placeOf(extraAddress(s)) : extraAddress(s)]]
          : s.kind === "parking" ? [["Address", condensed ? placeOf(s.details.address) : s.details.address], ["Space", s.details.space_type], ["Vehicle", s.details.vehicle], ["Notes", s.details.notes]]
          : s.kind === "cruise" ? [["Ship", s.details.ship], ["Cabin", s.details.room], ["Deck", s.details.deck]]
            : [["Seat", seat], ["Cabin", s.details.cabin]],
  );
  const cost = $derived(showCost && bookings.length === 1 && s.price ? formatMoney(s.price.amount_minor, s.price.currency) : "");
  const COMPACT_OMIT = ["Cost", "Room", "Cabin", "Notes", "Vehicle", "Space", "Car", "Deck", "Ship"];
  const facts = $derived([...rows, ["Cost", cost] as [string, string]].filter((f): f is [string, string] => !!f[1] && !omit.includes(f[0]) && !(compact && COMPACT_OMIT.includes(f[0]))));
  const pad = $derived(compact ? "p-4 md:p-6" : "p-6 md:p-8");
</script>

<svelte:element this={tag} {id} class={`pass scroll-mt-20 ${cls}`} class:ring-2={highlight} class:ring-ring={highlight} class:opacity-80={cancelled} aria-label={label ?? (tag === "section" ? headline(s) : undefined)} data-kind={s.kind} data-progress={flight ? progress : undefined}>
  <div class={`flex flex-col ${compact ? "gap-3" : "gap-4"} ${pad}`}>
    {#if eyebrow}<p class="eyebrow flex items-center gap-2">{#if pulse}<span class="size-2 animate-pulse rounded-full bg-primary motion-reduce:animate-none" aria-hidden="true"></span>{/if}{eyebrow}</p>{/if}
    {#if !noHeadline}{#key headlineText}<p class="countdown text-heading font-semibold" class:text-primary={!bad} class:text-destructive={bad} data-headline data-countdown>{headlineText}</p>{/key}{/if}
    {#if flight}<svelte:element this={`h${level}`} class="sr-only">{headline(s)}</svelte:element>{/if}

    {#if showCode && codes.length}
      <div class={compact ? "flex flex-wrap items-baseline gap-x-3 gap-y-1" : "flex flex-col gap-1"}>
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
            {#if !timesArea}{dayLabel(s.start_local)}{#if unknown}, time not recorded{:else if !differ}, <PlaceTime local={s.start_local} />{/if}{/if}
          </p>
        {:else}
          <svelte:element this={`h${level}`} class="break-words text-title font-semibold" class:line-through={cancelled}>{headline(s)}</svelte:element>
        {/if}
      </div>
    </div>

    {#if app && showApp}
      <div><Button variant="outline" href={app} target="_blank" rel="noopener noreferrer">{appLabel}</Button></div>
    {:else if vendor && showApp}
      <div><Button variant="outline" href={vendor.href}>{vendor.label}</Button></div>
    {/if}

    {#if flight}
      <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
        <AirportCode code={s.origin ?? "—"} size="medium" />
        <span title="The plane’s place is worked out from the booked times, not live data" class="min-w-0">
          <RouteLine progress={grounded ? 0 : progress} label={evidence === "landed" ? "Route, with the plane at the destination" : "Route, with the plane placed from the booked times"} />
          {#if evidence !== "landed" && !grounded}<span class="block text-center text-xs text-muted-foreground" data-schedule-label>Based on schedule</span>{/if}
        </span>
        <AirportCode code={s.destination ?? "—"} size="medium" class="text-right" />
        {#if timesArea}{:else if differ}
          <div class="col-span-3 mt-2 flex flex-col gap-1 text-sm">
            <span><Badge variant="secondary">Times differ between bookings</Badge></span>
            {#each bookings as b (b.id)}
              <span>{b.confirmation ? `${b.confirmation}: ` : ""}{START_WORD[b.kind].toLowerCase()} {dayLabel(b.start_local)}, <PlaceTime local={b.start_local} />, {END_WORD[b.kind].toLowerCase()} {dayLabel(b.end_local)}, <PlaceTime local={b.end_local} /></span>
            {/each}
          </div>
        {:else}
        <div class="col-span-3 flex flex-wrap justify-between gap-x-4 text-sm">
          <p><DayTime segment={s} /></p>
          <p class="text-right"><DayTime segment={s} end /></p>
        </div>
        {/if}
      </div>
      {#if timesArea}{@render timesArea()}{/if}
    {:else if timesArea}
      {@render timesArea()}
    {:else}
      <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
        <div><dt class="eyebrow">{START_WORD[s.kind]}</dt>
          <dd class="mt-1 font-medium"><DayTime segment={s} dated /></dd></div>
        <div><dt class="eyebrow">{END_WORD[s.kind]}</dt>
          <dd class="mt-1 font-medium"><DayTime segment={s} end dated /></dd></div>
      </dl>
    {/if}
    {#if details}{@render details()}{/if}
  </div>

  {#if !compact}<div class="pass-tear" aria-hidden="true"></div>{/if}

  <div class={`flex flex-col gap-3 ${compact ? "px-4 pb-4 md:px-6 md:pb-6" : pad}`}>
    {#if facts.length}
      <dl class="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        {#each facts as [label, value] (label)}
          <div class="min-w-0"><dt class="eyebrow">{label}</dt><dd class="mt-1 break-words text-base font-medium" class:line-through={label === "Cost" && cancelled}>{value}</dd>
            {#if label === "Cost" && cancelled}<dd class="text-sm text-muted-foreground">Cancelled, so not in the trip’s total</dd>{/if}</div>
        {/each}
      </dl>
    {/if}
    <div class="flex flex-wrap items-center gap-2">
      <StatusChip chip={chips.booking} />
      {#if !liveArea && chips.live}<StatusChip chip={chips.live} small />{/if}
      {#if compact && footer}<div class="contents">{@render footer()}</div>{/if}
    </div>
    {#if liveArea}{@render liveArea()}{:else if status && chips.live}<p class="text-sm text-muted-foreground" data-live-line>{quiet}</p>{/if}
    {#if footer && !compact}<div>{@render footer()}</div>{/if}
  </div>
</svelte:element>
