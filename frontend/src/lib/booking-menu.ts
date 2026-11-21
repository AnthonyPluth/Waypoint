import type { Segment } from "$lib/api-types";
import type { OptionsMenuItem } from "$lib/components/ui/options-menu";
import { headline, type Card } from "$lib/trips";

export type BookingActions = { onedit: (segment: Segment) => void; onmove: (segment: Segment) => void; onremove: (segment: Segment) => void };

export const legName = (card: Card, s: Segment): string =>
  card.segments.length === 1 ? headline(s) : `${headline(s)} booking${s.confirmation ? ` ${s.confirmation}` : ""}`;

export function moreItems(card: Card, actions: BookingActions): OptionsMenuItem[] {
  return card.segments.flatMap((s) => {
    const who = legName(card, s);
    const tag = card.segments.length === 1 ? "" : s.confirmation ? ` ${s.confirmation}` : "";
    return [
      ...(s.id !== card.lead.id ? [{ label: `Edit${tag}`, name: `Edit ${who}`, onselect: () => actions.onedit(s) }] : []),
      { label: `Move${tag}`, name: `Move ${who}`, onselect: () => actions.onmove(s) },
      { label: `Remove${tag}`, name: `Remove ${who}`, destructive: true, onselect: () => actions.onremove(s) },
    ];
  });
}
