<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { McpConnection, McpSettings } from "$lib/api-types";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Input } from "$lib/components/ui/input";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  // Settings → AI assistants (MCP): the address an assistant is given, the household switch that decides whether an
  // assistant may be allowed to change trips (each assistant is approved on Waypoint’s own page, where the person ticks what it gets),
  // and the assistants connected, each with Disconnect.
  let list = $state<McpSettings | null>(null);
  let problem = $state("");
  let leaving = $state<McpConnection | null>(null);
  let asking = $state(false);
  let address = $state<HTMLInputElement | null>(null);
  let saving = $state(false);

  async function load() {
    try { list = await apiCall<"GET /api/mcp-settings">("/api/mcp-settings"); problem = ""; }
    catch (err) { problem = errMsg(err); }
  }
  onMount(load);

  // The switch shows what the server kept. If the server refuses, the box goes back to where it was and the toast says why.
  async function choose(e: Event) {
    const box = e.currentTarget as HTMLInputElement, allow = box.checked;
    await act(async () => {
      const r = await apiCall<"POST /api/mcp-settings/writes">("/api/mcp-settings/writes", { method: "POST", body: { allow }, failed: "Couldn’t save that" });
      if (list) list = { ...list, allow_writes: r.allow };
    }, { busy: (on) => (saving = on) });
    if (list) box.checked = list.allow_writes;   // as the server has it (after a refusal, as it was)
  }

  async function copy() {
    if (!list?.url) return;
    try { await navigator.clipboard.writeText(list.url); toast.success("Copied"); }
    catch { address?.select(); toast("Couldn’t copy it: it’s selected, so copy it yourself."); }   // no clipboard (a plain http page, a refused permission)
  }

  async function disconnect() {
    const c = leaving;
    if (!c) return false;
    return act(async () => {
      await apiCall<"DELETE /api/mcp-settings/connections/{id}">(`/api/mcp-settings/connections/${c.id}`, { method: "DELETE", failed: "Couldn’t disconnect" });
      toast.success(`${c.client || "The assistant"} is disconnected`);
      await load();
    });
  }

  const SCOPES: Record<string, string> = { read: "Read", write: "Change trips" };
  /** What an approval allows, as words: read always, then whatever else it was given. */
  const access = (scope: string[]) => Object.keys(SCOPES).filter((s) => s === "read" || scope.includes(s)).map((s) => SCOPES[s]);

  /** A moment in time, in the viewer's own time zone. */
  const at = (t: string) => new Date(t).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
</script>

<section aria-labelledby="mcp-title" class="space-y-2">
  <h2 id="mcp-title" class="eyebrow scroll-mt-20 px-1">AI assistants (MCP)</h2>
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={load}>Try again</Button></div>
    {:else if !list}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      <div class="row">
        <div class="min-w-0 grow space-y-2">
          {#if list.oauth && list.url}
            <p class="text-sm text-muted-foreground">
              Add this address to Claude or another assistant, then approve it here when it asks.
              <a class="underline underline-offset-2" href="https://anthonypluth.github.io/waypoint/start/mcp/" target="_blank" rel="noopener noreferrer">Learn more</a>
            </p>
            <div class="flex gap-2">
              <Input readonly value={list.url} aria-label="MCP address" class="font-mono" bind:ref={address} onfocus={(e) => e.currentTarget.select()} />
              <Button variant="outline" onclick={copy}>Copy</Button>
            </div>
          {:else}
            <p class="font-medium">Assistants can’t connect yet</p>
            <p class="text-sm text-muted-foreground">
              {list.reason}
              <a class="underline underline-offset-2" href="https://anthonypluth.github.io/waypoint/start/mcp/" target="_blank" rel="noopener noreferrer">Learn more</a>
            </p>
          {/if}
        </div>
      </div>
      <label class="row cursor-pointer flex-nowrap">
        <span class="min-w-0">
          <span class="block font-medium">Let assistants change trips</span>
          <span id="mcp-writes-help" class="block text-sm text-muted-foreground">Add, change and remove trips, bookings, people and loyalty entries. The assistant is told to ask before each change. Never mailboxes, email, AI settings, backups or sign-in.</span>
        </span>
        <input type="checkbox" class="size-5 shrink-0" aria-describedby="mcp-writes-help" checked={list.allow_writes} disabled={saving} onchange={choose} />
      </label>
      {#each list.connections as c (c.id)}
        <div class="row" data-testid="assistant">
          <div class="min-w-0">
            <p class="truncate font-medium">{c.client || "Unnamed app"}</p>
            <p class="text-sm text-muted-foreground">
              Approved{c.who ? ` by ${c.who}` : ""}{c.created ? ` ${at(c.created)}` : ""}. {c.last_used ? `Last used ${at(c.last_used)}.` : "Not used yet."}
            </p>
            <p class="mt-1 flex flex-wrap gap-1">{#each access(c.scope) as a (a)}<Badge variant="secondary">{a}</Badge>{/each}</p>
          </div>
          <Button variant="outline" onclick={() => { leaving = c; asking = true; }}>Disconnect</Button>
        </div>
      {/each}
    {/if}
  </div>
</section>

<ConfirmDialog bind:open={asking} title={`Disconnect ${leaving?.client || "this assistant"}?`} confirmLabel="Disconnect" busyLabel="Disconnecting…" destructive
  onconfirm={disconnect}>
  {#snippet description()}
    <p>It stops working at once and can’t see or change anything. You can approve it again later.</p>
  {/snippet}
</ConfirmDialog>
