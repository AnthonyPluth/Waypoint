// Doing something on the server and saying so when it fails.

import { toast } from "svelte-sonner";

/** What went wrong, in words for the person: the message of whatever was thrown. */
export function errMsg(e: unknown): string {
  const m = (e as { message?: unknown } | null)?.message;
  return typeof m === "string" ? m : String(e);
}

type Options = {
  /** Told `true` as the action starts and `false` when it ends, however it ends. */
  busy?: (on: boolean) => void;
  /** What to do with a failure, instead of a toast: set an error line, put a control back. */
  onError?: (message: string, err: unknown) => void;
};

const FAILED = Symbol("failed");

async function run<T>(fn: () => T | Promise<T>, o: Options): Promise<Awaited<T> | typeof FAILED> {
  o.busy?.(true);
  try { return await fn(); }
  catch (err) { if (o.onError) o.onError(errMsg(err), err); else toast.error(errMsg(err)); return FAILED; }
  finally { o.busy?.(false); }
}

/** Runs `fn`, and on failure shows its message in a toast (or hands it to `onError`). Resolves to whether it worked,
 * so a caller can carry on only after a success; it never rejects. */
export async function act(fn: () => unknown, o: Options = {}): Promise<boolean> {
  return (await run(fn, o)) !== FAILED;
}

/** Like `act`, but resolves to what `fn` returned, or `null` after a failure. */
export async function actGet<T>(fn: () => T | Promise<T>, o: Options = {}): Promise<Awaited<T> | null> {
  const r = await run(fn, o);
  return r === FAILED ? null : r;
}
