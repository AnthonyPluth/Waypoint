<script lang="ts" module>
  import type { Restored } from "$lib/api-types";
  // What the last restore said that's worth keeping (where the copy of what it replaced went, secrets it couldn't read):
  // it stays under Restore until dismissed, through Settings being left and opened again.
  let lastRestore: Restored | null = null;
</script>

<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { api } from "$lib/api";
  import type { BackupContents } from "$lib/api-types";
  import { app, refreshState } from "$lib/app.svelte";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import X from "@lucide/svelte/icons/x";
  import { toast } from "svelte-sonner";

  // Settings → Data: download everything, or replace everything with a backup file. A chosen file is read first
  // (POST /api/backup/inspect) so you see what it holds before typing RESTORE; the server keeps a copy of what was here.
  let file = $state<File | null>(null);
  let inspected = $state<BackupContents | null>(null);
  let problem = $state("");
  let asking = $state(false);
  let restored = $state<Restored | null>(lastRestore);
  $effect(() => { lastRestore = restored; });

  async function choose(f: File | null) {
    file = f; inspected = null; problem = "";
    if (!f) return;
    try {
      const r = await api<BackupContents>("/api/backup/inspect", { method: "POST", body: f, failed: "Couldn’t read that backup" });
      if (file === f) inspected = r;   // not a file chosen before this one
    } catch (err) { if (file === f) problem = errMsg(err); }
  }

  const n = (k: number, word: string) => `${k.toLocaleString("en-US")} ${word}${k === 1 ? "" : "s"}`;
  const total = (c: Record<string, number>) => Object.values(c).reduce((a, b) => a + b, 0);
  const when = (t: string | null | undefined) => {
    const d = t ? new Date(t) : null;
    return d && !isNaN(d.getTime()) ? d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "an unknown date";
  };
  const dbName = (s: string | null | undefined) => (s === "postgres" ? "Postgres" : s === "sqlite" ? "SQLite" : s || "an unknown database");
  const summary = $derived(inspected ? `Backup from ${when(inspected.created)} (${dbName(inspected.source)}): ${n(total(inspected.counts), "row")}` : "");
  /** The tables the backup or this Waypoint has anything in, each with both counts. */
  const tables = $derived(inspected
    ? [...new Set([...Object.keys(inspected.counts), ...Object.keys(inspected.current)])].sort()
      .map((t) => ({ name: t.replace(/_/g, " "), backup: inspected!.counts[t] ?? 0, here: inspected!.current[t] ?? 0 }))
      .filter((t) => t.backup || t.here)
    : []);
  const hasData = $derived(!!inspected && total(inspected.current) > 0);

  // "Last backup: Sep 28": when one was last downloaded from here (the year too when it isn't this one).
  const lastBackup = $derived.by(() => {
    const d = app.state?.last_backup ? new Date(app.state.last_backup) : null;
    if (!d || isNaN(d.getTime())) return null;
    const year = d.getFullYear() !== new Date().getFullYear();
    return { day: d.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}) }), full: when(app.state!.last_backup) };
  });
  // The browser saves the file itself, so there's no telling when it's done: look again once it likely is.
  // (Only the "last backup" line depends on it, and the next state check corrects it, so a failed look says nothing.)
  function downloaded() { setTimeout(() => { refreshState().catch(() => { /* stays quiet: see above */ }); }, 3000); }

  async function restore() {
    const f = file;
    if (!f) return false;
    return act(async () => {
      restored = await api<Restored>("/api/restore", { method: "POST", body: f, failed: "Restore failed" });
      toast.success("Restored");
      await refreshState();
    });
  }
</script>

<section aria-labelledby="data-title" class="space-y-2">
  <h2 id="data-title" class="eyebrow px-1">Data</h2>
  <div class="rows">
    <div class="row">
      <div>
        <p class="font-medium">Back up everything</p>
        <p class="text-sm text-muted-foreground">
          {#if lastBackup}<span title={lastBackup.full}>Last backup {lastBackup.day}.</span>{:else}No backup downloaded yet.{/if}
          Your saved secrets are in it, encrypted. Keep the file private.
        </p>
      </div>
      <Button href="/api/backup" download onclick={downloaded}
        title={`Everything, from the ${app.state?.database === "postgres" ? "Postgres" : "SQLite"} database. Restoring it elsewhere needs this Waypoint’s secret key.`}>Download backup</Button>
    </div>
    <div class="row items-stretch">
      <div class="flex w-full flex-col gap-3">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <label class="flex min-w-0 flex-col gap-1.5 text-sm text-muted-foreground">
            <span class="font-medium text-foreground">Restore from a file</span>
            <input type="file" accept=".gz,.json,application/gzip,application/json" onchange={(e) => choose(e.currentTarget.files?.[0] ?? null)}
              class="w-full max-w-72 cursor-pointer text-sm file:mr-3 file:cursor-pointer file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium file:text-secondary-foreground" />
          </label>
          <Button variant="outline" disabled={!inspected} onclick={() => (asking = true)}>Restore…</Button>
        </div>
        {#if inspected}
          <div class="rounded-lg bg-muted p-3 text-sm" data-testid="backup-summary">
            <p class="mb-2">{summary}.</p>
            {#if tables.length}
              <table class="w-full text-left">
                <thead><tr class="text-xs text-muted-foreground"><th class="pb-1 font-medium">Table</th><th class="pb-1 text-right font-medium">In the backup</th><th class="pb-1 text-right font-medium">Here now</th></tr></thead>
                <tbody>{#each tables as t (t.name)}<tr><td class="py-0.5">{t.name}</td><td class="py-0.5 text-right">{t.backup.toLocaleString("en-US")}</td><td class="py-0.5 text-right">{t.here.toLocaleString("en-US")}</td></tr>{/each}</tbody>
              </table>
            {/if}
          </div>
        {:else if problem}<p class="text-sm text-signal-ink bg-signal-soft rounded-lg p-3" role="alert">{problem}</p>
        {:else if file}<p class="text-sm text-muted-foreground">Reading the backup…</p>{/if}
        {#if restored}
          <Alert class="pr-11">
            <AlertDescription class="flex flex-col gap-1.5 text-sm leading-relaxed">
              <p class="font-medium text-foreground">Restored the backup from {when(restored.created)}.</p>
              {#if restored.safety_copy}<p>A copy of what was here before is at <code class="code rounded bg-muted px-1 break-all normal-case tracking-normal">{restored.safety_copy}</code>.</p>{/if}
              {#if restored.unreadable_secrets.length}
                <p class="text-signal-ink">{n(restored.unreadable_secrets.length, "saved secret")} can’t be read with this Waypoint’s secret key
                  (<span class="code normal-case tracking-normal">{restored.unreadable_secrets.join(", ")}</span>). Set the key the backup was made with as
                  <code class="code rounded bg-muted px-1 normal-case tracking-normal">WAYPOINT_SECRET_KEY_OLD</code> and restart, or enter them again.</p>
              {/if}
            </AlertDescription>
            <Button variant="ghost" size="icon" class="absolute top-1.5 right-1.5" aria-label="Dismiss" onclick={() => (restored = null)}><X /></Button>
          </Alert>
        {/if}
      </div>
    </div>
  </div>
</section>

<ConfirmDialog bind:open={asking} title="Replace everything with this backup?" confirmLabel="Restore" busyLabel="Restoring…" destructive
  typeToConfirm="RESTORE" onconfirm={restore}>
  {#snippet description()}
    <p>{summary}.</p>
    <p>This replaces everything in this Waypoint (currently {n(total(inspected?.current ?? {}), "row")}) with the backup. It can’t be undone.</p>
    {#if hasData}<p>Waypoint first saves a copy of what’s here now in its data folder.</p>{/if}
  {/snippet}
</ConfirmDialog>
