import { vi } from "vitest";
import type { ShellRequest } from "../lib/offline-shell";

export type FakeShell = { posts: ShellRequest[]; saving: boolean; trips: unknown[]; savedAt: number | null; replies: Map<string, unknown>; uninstall: () => void };

const names = (trips: unknown[]) => trips.map((c) => { const t = (c as { trip: { id: number; name: string } }).trip; return { id: t.id, name: t.name }; });

export function installShell(initial: { saving?: boolean; trips?: unknown[]; savedAt?: number | null } = {}): FakeShell {
  const shell: FakeShell = { posts: [], saving: initial.saving ?? true, trips: initial.trips ?? [], savedAt: initial.savedAt ?? null, replies: new Map(), uninstall: () => {} };
  const status = () => ({ version: 1, saving: shell.saving, savedAt: shell.trips.length ? shell.savedAt : null, trips: names(shell.trips) });
  const postMessage = vi.fn(async (message: ShellRequest) => {
    shell.posts.push(message);
    if (shell.replies.has(message.type)) return shell.replies.get(message.type);
    if (message.type === "load") return { version: 1, trips: shell.trips };
    if (message.type === "setSaving") { shell.saving = message.on; if (!message.on) shell.trips = []; }
    if (message.type === "remove") shell.trips = [];
    return status();
  });
  vi.stubGlobal("webkit", { messageHandlers: { waypointOffline: { postMessage } } });
  shell.uninstall = () => vi.unstubAllGlobals();
  return shell;
}
