
import { toast } from "svelte-sonner";

export function errMsg(e: unknown): string {
  const m = (e as { message?: unknown } | null)?.message;
  return typeof m === "string" ? m : String(e);
}

export function ignoreFailure(): void {}

type Options = {
  busy?: (on: boolean) => void;
  onError?: (message: string, err: unknown) => void;
};

const FAILED = Symbol("failed");

async function run<T>(fn: () => T | Promise<T>, o: Options): Promise<Awaited<T> | typeof FAILED> {
  o.busy?.(true);
  try { return await fn(); }
  catch (err) { if (o.onError) o.onError(errMsg(err), err); else toast.error(errMsg(err)); return FAILED; }
  finally { o.busy?.(false); }
}

export async function act(fn: () => unknown, o: Options = {}): Promise<boolean> {
  return (await run(fn, o)) !== FAILED;
}

export async function actGet<T>(fn: () => T | Promise<T>, o: Options = {}): Promise<Awaited<T> | null> {
  const r = await run(fn, o);
  return r === FAILED ? null : r;
}
