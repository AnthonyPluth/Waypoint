<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Segment } from "$lib/api-types";
  import { app } from "$lib/app.svelte";
  import AddressLink from "$lib/components/AddressLink.svelte";
  import AvatarStack from "$lib/components/AvatarStack.svelte";
  import CopyButton from "$lib/components/CopyButton.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Button } from "$lib/components/ui/button";
  import { OptionsMenu } from "$lib/components/ui/options-menu";
  import { legName, moreItems } from "$lib/booking-menu";
  import { emailNews } from "$lib/email-news";
  import { formatMoney } from "$lib/money";
  import { bookingChip } from "$lib/status";
  import { bookingSpan, bookingTravellers, clock, dayLabel, dayOf, dayShift, extraAddress, headline, seatsInOrder, showBookingTravellers, START_WORD, END_WORD, untimed, type Card, type TripTraveller } from "$lib/trips";

  type Props = {
    card: Card; everyone: TripTraveller[]; canChange: boolean; onedit: (segment: Segment) => void;
    onmove: (segment: Segment) => void; onremove: (segment: Segment) => void;
    above?: Snippet; below?: Snippet; withTimes?: boolean; inline?: boolean;
  };
  let { card, everyone, canChange, onedit, onmove, onremove, above, below, withTimes = false, inline = false }: Props = $props();

  type Row = { label: string; value?: string; lines?: boolean; strike?: boolean; address?: string; link?: boolean; code?: string; codes?: string[]; people?: { id: number | null; name: string; notes: string[] }[] };

  const first = $derived(card.lead);
  const showCosts = $derived(app.state?.show_costs !== false);
  const cancelled = $derived(card.cancelled);

  const at = (s: Segment, local: string, place: string | null | undefined, dated: boolean): string => {
    const time = untimed(s) ? "time not recorded" : clock(local);
    const shift = local === s.end_local && (s.kind === "flight" || s.kind === "train") ? dayShift(s.start_local, s.end_local) : "";
    return [dated ? dayLabel(local) : "", time, shift, place].filter(Boolean).join(" · ");
  };

  function rowsOf(s: Segment): Row[] {
    const struck = s.status === "cancelled";
    const seat = seatsInOrder(s.details.seat || s.travelers.map((t) => t.seat).filter(Boolean).join(", "));
    const when = (label: string, value: string): Row => ({ label, value, lines: true, strike: struck });
    const dates = (): Row => ({ label: "Dates", value: bookingSpan(s), strike: struck });
    const rows: Row[] = [];
    if (s.kind === "flight" || s.kind === "train") {
      const unnamed = seat.split(", ").filter((x) => x && !(shownTravellers && seatsNamed.has(x))).join(", ");
      rows.push(when(START_WORD[s.kind], at(s, s.start_local, s.origin, false)), when(END_WORD[s.kind], at(s, s.end_local, s.destination, false)));
      if (s.kind === "flight") rows.push({ label: "Terminal", value: s.details.terminal });
      rows.push({ label: "Seat", value: unnamed }, { label: "Cabin", value: s.details.cabin });
    } else if (s.kind === "hotel") {
      rows.push(dates(), ...(withTimes ? [when(START_WORD.hotel, at(s, s.start_local, null, true)), when(END_WORD.hotel, at(s, s.end_local, null, true))] : []), { label: "Address", value: s.details.address?.trim(), address: s.details.address?.trim(), link: !struck }, { label: "Room", value: s.details.room });
    } else if (s.kind === "car") {
      const pickup = extraAddress(s)?.trim();
      rows.push(when(START_WORD.car, at(s, s.start_local, s.origin, true)), when(END_WORD.car, at(s, s.end_local, s.destination, true)),
        { label: "Car", value: s.details.car_class }, { label: "Pick-up address", value: pickup, address: pickup, link: !struck });
    } else if (s.kind === "cruise") {
      const ports = [...new Set(s.days.flatMap((d) => (d.sea ? [] : d.stops.map((p) => p.name))))].join(", ");
      rows.push(when(START_WORD.cruise, at(s, s.start_local, s.origin, true)), when(END_WORD.cruise, at(s, s.end_local, s.destination || s.origin, true)),
        { label: "Ports", value: ports, lines: true }, { label: "Terminal address", value: s.details.address?.trim(), address: s.details.address?.trim(), link: !struck }, { label: "Ship", value: s.details.ship }, { label: "Cabin", value: s.details.room }, { label: "Deck", value: s.details.deck });
    } else if (s.kind === "parking") {
      rows.push(dates(), ...(withTimes ? [when(START_WORD.parking, at(s, s.start_local, null, true)), when(END_WORD.parking, at(s, s.end_local, null, true))] : []), { label: "Address", value: s.details.address?.trim(), address: s.details.address?.trim(), link: !struck }, { label: "Space", value: s.details.space_type },
        { label: "Vehicle", value: s.details.vehicle }, { label: "Notes", value: s.details.notes, lines: true });
    } else {
      const from = dayOf(s, s.start_local), to = dayOf(s, s.end_local);
      rows.push({ label: "Dates", value: from === to ? from : `${from} – ${to}`, strike: struck }, { label: "Place", value: headline(s) }, { label: "Notes", value: s.details.notes, lines: true });
    }
    if (struck && !card.cancelled) rows.push({ label: "Status", value: "Cancelled, so not in the trip’s total", code: s.confirmation ?? undefined });
    return rows.filter((r) => r.value);
  }

  const codes = $derived([...new Set(card.segments.map((s) => s.confirmation).filter((c): c is string => !!c))]);
  const isPerson = (p: { id: number | null; name: string }) => (t: { person_id: number | null; name: string }): boolean =>
    p.id != null ? t.person_id === p.id : t.person_id == null && t.name.trim().toLowerCase() === p.name.trim().toLowerCase();
  const split = $derived(!card.cancelled && card.segments.some((s) => s.status === "cancelled"));
  const combined = $derived(card.segments.length > 1);
  const travellers = $derived(bookingTravellers(card.segments));
  const shownTravellers = $derived(travellers.people.length > 0 && showBookingTravellers(first, everyone));
  const people = $derived(travellers.people.map((p) => {
    const legs = card.segments.flatMap((s) => { const t = s.travelers.find(isPerson(p)); return t ? [{ s, seat: t.seat }] : []; });
    const live = legs.filter((l) => l.s.status !== "cancelled");
    const seated = (live.length ? live : legs).filter((l) => l.seat);
    const tag = (c: string | null) => (combined && c ? ` (${c})` : "");
    const differ = new Set(seated.map((l) => l.seat)).size > 1;
    const dead = split ? legs.find((l) => l.s.status === "cancelled") : undefined;
    return {
      ...p,
      seats: seated.map((l) => l.seat as string),
      notes: [...(differ ? seated.map((l) => `Seat ${l.seat}${tag(l.s.confirmation)}`) : seated.length ? [`Seat ${seated[0].seat}`] : []), ...(dead ? [`On cancelled booking${dead.s.confirmation ? ` ${dead.s.confirmation}` : ""}`] : [])],
    };
  }));
  const seatsNamed = $derived(new Set(people.flatMap((p) => p.seats)));
  const rows = $derived<Row[]>([
    ...card.segments.flatMap((s): Row[] => [...(combined && card.timesDiffer && s.status !== "cancelled" ? [{ label: "Booking", value: s.confirmation ?? "No confirmation code" }] : []), ...rowsOf(s)]),
    ...(codes.length ? [{ label: codes.length > 1 ? "Confirmations" : "Confirmation", codes }] : []),
    ...(shownTravellers ? [{ label: "Travellers", people }] : []),
    ...(showCosts ? card.segments.filter((s) => s.price).map((s): Row => ({ label: "Price", value: formatMoney(s.price!.amount_minor, s.price!.currency), strike: s.status === "cancelled" })) : []),
  ]);

  const items = $derived(moreItems(card, { onedit, onmove, onremove }));
  const notes = $derived(card.segments.flatMap((s) => [
    ...(s.email_update ? [emailNews(s.email_update).updated && `Updated from a newer email: ${emailNews(s.email_update).updated} changed.`, emailNews(s.email_update).disagreed && `A newer email disagreed with what you set for ${emailNews(s.email_update).disagreed}. It was left as you set it; edit the booking if it should change.`] : []),
    ...(s.check_times ? ["Check the times: the email gave them in UTC and Waypoint couldn’t tell which clock they mean. Edit the booking to correct or confirm them."] : []),
  ]).filter(Boolean));
</script>

<div class="flex flex-col gap-3" data-testid="booking-detail">
  {#if cancelled}
    <div class="flex flex-col gap-1.5">
      <StatusChip chip={bookingChip("cancelled")} />
      <p class="text-caption text-muted-foreground">Cancelled, so not in the trip’s total</p>
    </div>
  {:else if card.changed}
    <StatusChip chip={bookingChip("changed")} />
  {/if}
  {#each notes as note (note)}<p class="text-sm text-signal-ink" role="note">{note}</p>{/each}
  {@render above?.()}
  <dl class="border-t border-border">
    {#each rows as row, i (i)}
      <div class="flex items-start justify-between gap-4 border-b border-border py-[11px] last:border-b-0 md:py-[13px]">
        <dt class="eyebrow shrink-0 pt-0.5 text-muted-foreground">{row.label}</dt>
        <dd class={`flex min-w-0 gap-2 text-right text-base font-medium ${row.lines ? "flex-col items-end" : "items-center"}`}>
          {#if row.codes}
            {#each row.codes as code (code)}<span class="flex items-center gap-2"><span class="mono text-[17px] tracking-[0.04em]">{code}</span><CopyButton text={code} name={`Copy confirmation code ${code}`} /></span>{/each}
          {:else if row.people}
            <span class="flex items-center gap-2"><span aria-hidden="true"><AvatarStack people={row.people} /></span>
              {#if row.people.some((p) => p.notes.length)}
                <span class="flex min-w-0 flex-col items-end">{#each row.people as p, j (j)}<span class="break-words">{p.name}{#each p.notes as note (note)}{" "}<span class="font-normal text-muted-foreground">· {note}</span>{/each}</span>{/each}</span>
              {:else}
                <span class="min-w-0 break-words">{row.people.map((p) => p.name).join(", ")}</span>
              {/if}
            </span>
          {:else}
            {#if row.address && row.link}<AddressLink address={row.address} text={row.value} class="min-w-0 break-words" />{:else}<span class={`min-w-0 break-words ${row.strike ? "text-muted-foreground line-through" : ""}`}>{row.value}</span>{/if}
            {#if row.code}<span class="mono text-muted-foreground">{row.code}</span>{/if}
            {#if row.address}<CopyButton text={row.address} name="Copy address" />{/if}
          {/if}
        </dd>
      </div>
    {/each}
  </dl>
  {@render below?.()}
  {#if inline && canChange}
    <div class="flex flex-wrap gap-2">
      <Button variant="outline" size="sm" onclick={() => onedit(first)}>Edit</Button>
      <OptionsMenu size="sm" align="right" up label={`More options for ${legName(card, first)}`} text="More" {items} />
    </div>
  {/if}
</div>
