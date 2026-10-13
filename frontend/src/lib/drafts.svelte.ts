import { getContext, setContext } from "svelte";
import { SvelteSet } from "svelte/reactivity";

export type DraftGuard = { dirty: () => boolean; saving: () => boolean; discard: () => void; asking: boolean };

const guards = new SvelteSet<DraftGuard>();
const SCOPE = Symbol("draft-scope");
let pending: { proceed: () => void; among: DraftGuard[] } | null = null;

export function sheetScope(): DraftGuard[] {
  const scope: DraftGuard[] = [];
  setContext(SCOPE, scope);
  return scope;
}

export function draftGuard(opts: { dirty: () => boolean; saving?: () => boolean; discard: () => void }): DraftGuard {
  const guard = $state<DraftGuard>({ dirty: opts.dirty, saving: opts.saving ?? (() => false), discard: opts.discard, asking: false });
  const scope = getContext<DraftGuard[] | undefined>(SCOPE);
  guards.add(guard);
  scope?.push(guard);
  $effect(() => () => {
    guards.delete(guard);
    if (scope) scope.splice(scope.indexOf(guard), 1);
  });
  return guard;
}

export function baseline(get: () => unknown): { reset: () => void; changed: () => boolean } {
  let base = JSON.stringify(get());
  return { reset: () => { base = JSON.stringify(get()); }, changed: () => JSON.stringify(get()) !== base };
}

export const anyDirty = (): boolean => [...guards].some((g) => g.dirty());
export const anySaving = (): boolean => [...guards].some((g) => g.saving());

export function leave(proceed: () => void, among: DraftGuard[] = [...guards]): boolean {
  if (among.some((g) => g.saving())) return false;
  const changed = among.filter((g) => g.dirty());
  if (!changed.length) { proceed(); return true; }
  pending = { proceed, among: changed };
  changed[0].asking = true;
  return false;
}

export function dropDrafts(): void {
  [...guards].filter((g) => g.dirty()).forEach((g) => g.discard());
}

export function keepEditing(): void {
  pending = null;
}

export function discardChanges(): void {
  const go = pending;
  pending = null;
  if (!go) return;
  go.among.forEach((g) => g.discard());
  go.proceed();
}

window.addEventListener("beforeunload", (e) => {
  if (!anyDirty()) return;
  e.preventDefault();
  e.returnValue = "";
});
