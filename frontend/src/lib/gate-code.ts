export const MARGIN = 0.2;
export const SHARE = 1 / (1 + 2 * MARGIN);
export const WHOLE_ENOUGH = 0.8;

export function squareSide(room: number, natural: number): number {
  const share = room * SHARE;
  if (!natural || share < natural) return room;
  const whole = Math.floor(share / natural) * natural;
  return whole >= share * WHOLE_ENOUGH ? whole / SHARE : room;
}

export const showsCode = (s: { kind: string; status: string; gate_code: { state: string } | null }, endMs: number, now: number): boolean =>
  s.kind === "parking" && s.status !== "cancelled" && s.gate_code?.state === "ready" && endMs > now;
