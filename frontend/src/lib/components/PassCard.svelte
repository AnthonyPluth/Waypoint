<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Segment } from "$lib/api-types";
  import { app as appState } from "$lib/app.svelte";
  import AirportCode from "$lib/components/AirportCode.svelte";
  import AirportName from "$lib/components/AirportName.svelte";
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
  import AvatarStack from "$lib/components/AvatarStack.svelte";
  import BoardingTime from "$lib/components/BoardingTime.svelte";
  import KindTile from "$lib/components/KindTile.svelte";
  import Plane from "@lucide/svelte/icons/plane";
  import TrainFront from "@lucide/svelte/icons/train-front";
  import { duration } from "$lib/stats";
  import { appWord, daysBetween, dayLabel, dayShift, dayShiftWords, endAt, extraAddress, startAt, flightEvidence, placeOf, seatsInOrder, END_WORD, headline, passHeadline, routeProgress, START_WORD, timesDiffer, untimed, vendorLink } from "$lib/trips";

  type Props = {
    segment: Segment; bookings?: Segment[]; now?: number; eyebrow?: string; pulse?: boolean; level?: 2 | 3; class?: string;
    as?: "section" | "li"; id?: string; highlight?: boolean; label?: string; showCode?: boolean; showApp?: boolean; omit?: string[]; condensed?: boolean; compact?: boolean; showCost?: boolean; boarding?: boolean; tripName?: string;
    live?: Snippet; footer?: Snippet; times?: Snippet; details?: Snippet;
  };
  let { segment: s, bookings = [s], now = Date.now(), eyebrow = "", pulse = false, level = 3, class: cls = "", as: tag = "section", id, highlight = false, label, showCode = true, showApp = true, omit = [], condensed = false, compact = false, showCost = true, boarding = false, tripName = "",
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
  const asOf = (t: string) => new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(t));
  const shift = $derived(flight ? dayShift(s.start_local, s.end_local) : "");
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
  const cost = $derived(showCost && appState.state?.show_costs !== false && bookings.length === 1 && s.price ? formatMoney(s.price.amount_minor, s.price.currency) : "");
  const COMPACT_OMIT = ["Cost", "Room", "Cabin", "Notes", "Vehicle", "Space", "Car", "Deck", "Ship"];
  const facts = $derived([...rows, ["Cost", cost] as [string, string]].filter((f): f is [string, string] => !!f[1] && !omit.includes(f[0]) && !(compact && COMPACT_OMIT.includes(f[0]))));
  const pad = $derived(compact ? "p-4 md:p-5" : "p-5 md:p-6");

  const routed = $derived(flight || s.kind === "train");
  const showCountdown = $derived(!cancelled && !unknown);
  const countdown = $derived(/^(.*\sin\s)(.+)$/.exec(headlineText));
  const airborne = $derived(flight && !grounded && evidence !== "landed" && progress > 0 && progress < 1);
  const planeAt = $derived(airborne ? progress : 0.5);
  const flightSeconds = $derived((endAt(s) - startAt(s)) / 1000);
  const length = $derived(flight && !unknown && flightSeconds > 0 ? duration(flightSeconds) : "");
  const daysLater = $derived(flight ? daysBetween(s.start_local, s.end_local) : 0);
  const boardFacts = $derived<[string, string][]>([
    ...rows.map(([name, value]): [string, string | null | undefined] => [name === "Seat" && seat.includes(",") ? "Seats" : name, value]),
    ["Cost", cost] as [string, string],
  ].filter(([name, value]) => (flight && name === "Gate") || (!!value && !omit.includes(name))).map(([name, value]): [string, string] => [name, value ?? ""]));
  const hasCode = $derived(showCode && codes.length > 0);
  const people = $derived(s.travelers.map((t) => ({ id: t.person_id, name: t.name })));
  const firstNames = $derived(((names) => (names.length > 1 ? `${names.slice(0, -1).join(", ")} & ${names[names.length - 1]}` : (names[0] ?? "")))(people.map((p) => p.name.trim().split(/\s+/)[0]).filter(Boolean)));
</script>

<svelte:element this={tag} {id} class={`pass scroll-mt-20 ${cls}`} class:ring-2={highlight} class:ring-ring={highlight} class:opacity-80={cancelled} aria-label={label ?? (tag === "section" ? headline(s) : undefined)} data-kind={s.kind} data-progress={flight ? progress : undefined}>
{#if boarding}
  <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-5 py-3 md:px-6">
    <p class="flex min-w-0 items-center gap-2 text-sm">
      {#if eyebrow}
        <span class={`size-2 shrink-0 rounded-full bg-primary ${pulse ? "animate-pulse motion-reduce:animate-none" : ""}`} aria-hidden="true" data-dot></span>
        <span class="eyebrow shrink-0 text-foreground">{eyebrow}</span>
      {/if}
      {#if tripName}<span class="min-w-0 truncate text-muted-foreground">{eyebrow ? "· " : ""}{tripName}</span>{/if}
    </p>
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <StatusChip chip={chips.booking} small />
      {#if !liveArea && chips.live}<StatusChip chip={chips.live} small />{/if}
      {#if showCountdown}
        {#key headlineText}<p class="text-sm" class:text-destructive={bad} data-countdown>
          {#if countdown}
            <span class="sr-only" data-headline>{headlineText}</span>
            <span aria-hidden="true"><span class="text-muted-foreground">{countdown[1]}</span><strong class="font-semibold" class:text-primary={!bad}>{countdown[2]}</strong></span>
          {:else}
            <strong class="font-semibold" class:text-primary={!bad} data-headline>{headlineText}</strong>
          {/if}
        </p>{/key}
      {/if}
    </div>
  </div>

  <div class="desktop:grid desktop:grid-cols-[minmax(0,1fr)_300px]">
    <div class="flex min-w-0 flex-col gap-5 p-5 md:p-6">
      <div class="flex items-center gap-3">
        <BrandLogo src={s.logo} label={s.logo_label} size={40} />
        <div class="min-w-0">
          {#if flight}
            <svelte:element this={`h${level}`} class="sr-only">{headline(s)}</svelte:element>
            <p class="break-words font-medium" class:line-through={cancelled}>{[s.provider, number].filter(Boolean).join(" ")}</p>
            {#if length}<p class="text-sm text-muted-foreground">{length} · nonstop</p>{/if}
          {:else if s.kind === "train"}
            <svelte:element this={`h${level}`} class="sr-only">{headline(s)}</svelte:element>
            <p class="break-words font-medium" class:line-through={cancelled}>{s.provider ?? "Train"}</p>
          {:else}
            <svelte:element this={`h${level}`} class="break-words text-title font-semibold" class:line-through={cancelled}>{headline(s)}</svelte:element>
          {/if}
        </div>
      </div>

      {#if routed}
        <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] gap-x-3 desktop:gap-x-5" class:line-through={cancelled}>
          <p class="break-words text-[44px] font-semibold leading-none tracking-tight desktop:text-[64px]" data-code="origin">{s.origin ?? "—"}</p>
          <span class="relative flex h-11 min-w-0 items-center desktop:h-16" role="img" aria-label={evidence === "landed" ? "Route, with the plane at the destination" : "Route"} data-progress={planeAt}>
            <span class="absolute inset-x-0 top-1/2 border-t-2 border-dashed border-border"></span>
            {#if airborne}<span class="absolute left-0 top-1/2 border-t-2 border-primary" style={`width: ${planeAt * 100}%`}></span>{/if}
            <span class="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 bg-card px-1 text-primary" style={`left: ${planeAt * 100}%`} data-plane>
              {#if flight}<Plane class="size-5 rotate-45" aria-hidden="true" />{:else}<TrainFront class="size-5" aria-hidden="true" />{/if}
            </span>
          </span>
          <p class="break-words text-right text-[44px] font-semibold leading-none tracking-tight desktop:text-[64px]" data-code="destination">{s.destination ?? "—"}</p>
          {#if flight}
            <div class="min-w-0"><AirportName code={s.origin ?? ""} /></div>
            <span></span>
            <div class="min-w-0 text-right"><AirportName code={s.destination ?? ""} /></div>
          {/if}
        </div>
        {#if differ}
          <div class="flex flex-col gap-1 text-sm">
            <span><Badge variant="secondary">Times differ between bookings</Badge></span>
            {#each bookings as b (b.id)}
              <span>{b.confirmation ? `${b.confirmation}: ` : ""}{START_WORD[b.kind].toLowerCase()} {dayLabel(b.start_local)}, <PlaceTime local={b.start_local} />, {END_WORD[b.kind].toLowerCase()} {dayLabel(b.end_local)}, <PlaceTime local={b.end_local} /></span>
            {/each}
          </div>
        {:else}
          <div class="flex flex-wrap justify-between gap-x-4 gap-y-3" class:line-through={cancelled}>
            <BoardingTime local={s.start_local} zone={s.start_zone} code={flight ? s.origin : null} {unknown} />
            <BoardingTime local={s.end_local} zone={s.end_zone} code={flight ? s.destination : null} {unknown} align="end" shift={daysLater} shiftWords={dayShiftWords(s.start_local, s.end_local)} />
          </div>
        {/if}
      {:else}
        <div class="flex items-end gap-4" class:line-through={cancelled}>
          <BoardingTime local={s.start_local} zone={s.start_zone} {unknown} label={START_WORD[s.kind]} />
          <span class="relative mb-5 flex h-7 min-w-8 flex-1 items-center justify-center" aria-hidden="true">
            <span class="absolute inset-x-0 top-1/2 border-t-2 border-dashed border-border"></span>
            <span class="relative bg-card px-1"><KindTile kind={s.kind} decorative /></span>
          </span>
          <BoardingTime local={s.end_local} zone={s.end_zone} {unknown} align="end" label={END_WORD[s.kind]} />
        </div>
      {/if}

      {#if liveArea}{@render liveArea()}{:else if status && chips.live}<p class="text-sm text-muted-foreground" data-live-line>{quiet}</p>{/if}

      {#if (showApp && (app || vendor)) || footer}
        <div class="flex flex-wrap items-center gap-2">
          {#if app && showApp}
            <Button href={app} target="_blank" rel="noopener noreferrer" size="sm" class="phone:flex-1">{appLabel}</Button>
          {:else if vendor && showApp}
            <Button href={vendor.href} size="sm" class="phone:flex-1">{vendor.label}</Button>
          {/if}
          {#if footer}{@render footer()}{/if}
        </div>
      {/if}
    </div>

    <div class="flex min-w-0 flex-col gap-5 border-t-2 border-dashed border-border p-5 desktop:border-l-2 desktop:border-t-0 md:p-6" data-stub>
      <dl class="grid grid-cols-2 gap-x-4 gap-y-4 phone:grid-cols-4">
        {#if hasCode}
          <div class="col-span-2 min-w-0 phone:col-span-1">
            <dt class="eyebrow"><span class="phone:hidden">{codes.length > 1 ? "Confirmations" : "Confirmation"}</span><span class="desktop:hidden">Code</span></dt>
            <dd class="mt-1 flex flex-wrap gap-x-4">{#each codes as b (b.id)}<CopyCode code={b.confirmation ?? ""} class="mono w-fit min-h-11 text-title font-semibold phone:text-heading" />{/each}</dd>
          </div>
        {/if}
        {#each boardFacts as [name, value], i (name)}
          <div class={`min-w-0 ${i >= (hasCode ? 3 : 4) ? "phone:hidden" : ""}`}>
            <dt class="eyebrow">{name}</dt>
            {#if value}<dd class="mt-1 break-words text-base font-medium" class:line-through={name === "Cost" && cancelled}>{value}</dd>{:else}<dd class="mt-1 text-base text-muted-foreground">Not yet</dd>{/if}
            {#if name === "Cost" && cancelled}<dd class="text-sm text-muted-foreground">Cancelled, so not in the trip’s total</dd>{/if}
          </div>
        {/each}
      </dl>
      {#if people.length}
        <div class="mt-auto flex items-center gap-2.5">
          <AvatarStack {people} />
          <span class="min-w-0 truncate text-sm font-medium">{firstNames}</span>
        </div>
      {/if}
    </div>
  </div>
{:else}
  <div class={`flex flex-col gap-3 ${pad}`}>
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
        <RouteLine progress={grounded ? 0 : progress} label={evidence === "landed" ? "Route, with the plane at the destination" : "Route"} />
        <AirportCode code={s.destination ?? "—"} size="medium" class="text-right" />
        <div class="col-span-3 grid grid-cols-2 gap-x-3">
          <div class="min-w-0"><AirportName code={s.origin ?? ""} /></div>
          <div class="min-w-0 text-right"><AirportName code={s.destination ?? ""} /></div>
        </div>
        {#if timesArea}{:else if differ}
          <div class="col-span-3 mt-2 flex flex-col gap-1 text-sm">
            <span><Badge variant="secondary">Times differ between bookings</Badge></span>
            {#each bookings as b (b.id)}
              <span>{b.confirmation ? `${b.confirmation}: ` : ""}{START_WORD[b.kind].toLowerCase()} {dayLabel(b.start_local)}, <PlaceTime local={b.start_local} />, {END_WORD[b.kind].toLowerCase()} {dayLabel(b.end_local)}, <PlaceTime local={b.end_local} /></span>
            {/each}
          </div>
        {:else}
        <div class="col-span-3 flex flex-wrap justify-between gap-x-4 text-sm">
          <p><DayTime segment={s} /><span class="sr-only"> ({s.start_zone})</span></p>
          <p class="text-right"><DayTime segment={s} end />{#if shift}<span class="ml-1.5 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground" data-day-shift><span aria-hidden="true">{shift}</span><span class="sr-only">, {dayShiftWords(s.start_local, s.end_local)}</span></span>{/if}<span class="sr-only"> ({s.end_zone})</span></p>
        </div>
        {/if}
      </div>
      {#if timesArea}
        {@render timesArea()}
        {#if !unknown}
          <p class="text-xs text-muted-foreground">{#if shift}Arrives <span class="rounded-full bg-secondary px-2 py-0.5 font-medium text-secondary-foreground" data-day-shift><span aria-hidden="true">{shift}</span><span class="sr-only">{dayShiftWords(s.start_local, s.end_local)}</span></span>{/if}<span class="sr-only"> (departs {s.start_zone}, arrives {s.end_zone})</span></p>
        {/if}
      {/if}
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

  <div class={`flex flex-col gap-3 ${compact ? "px-4 pb-4 md:px-5 md:pb-5" : pad}`}>
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
{/if}
</svelte:element>
