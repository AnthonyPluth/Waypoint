export type Position = { scroll: number; inner: number; revealed: number };

let live: Position | null = null;
const kept = new Map<number, Position>();

export const track = (position: Position | null): void => { live = position; };
export const park = (entry: number): void => { if (live) kept.set(entry, { ...live }); };
export const forgetFrom = (entry: number): void => {
  for (const key of [...kept.keys()]) if (key >= entry) kept.delete(key);
};
export const parkedAt = (entry: number): boolean => kept.has(entry);
export function take(entry: number): Position | null {
  const position = kept.get(entry) ?? null;
  kept.delete(entry);
  return position;
}
