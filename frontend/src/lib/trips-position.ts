export type Position = { scroll: number; inner: number; revealed: number };

let live: Position | null = null;
let kept: { entry: number; position: Position } | null = null;

export const track = (position: Position | null): void => { live = position; };
export const park = (entry: number): void => { if (live) kept = { entry, position: { ...live } }; };
export const forgetFrom = (entry: number): void => { if (kept && kept.entry >= entry) kept = null; };
export const parkedAt = (entry: number): boolean => kept?.entry === entry;
export function take(entry: number): Position | null {
  if (kept?.entry !== entry) return null;
  const { position } = kept;
  kept = null;
  return position;
}
