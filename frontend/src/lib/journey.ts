import type { Segment } from "./api-types";

export function journeyLegs(segment: Segment, segments: Segment[]): Segment[] | null {
  const journey = segment.journey;
  if (!journey || journey.legs < 2) return null;
  const byId = new Map(segments.map((s) => [s.id, s]));
  const legs: Segment[] = [];
  let at = byId.get(journey.lead);
  while (at && legs.length < journey.legs) {
    legs.push(at);
    at = at.journey?.next == null ? undefined : byId.get(at.journey.next);
  }
  const whole = legs.length === journey.legs && legs.every((leg, i) => leg.journey?.leg === i + 1 && leg.journey.lead === journey.lead);
  return whole ? legs : null;
}
