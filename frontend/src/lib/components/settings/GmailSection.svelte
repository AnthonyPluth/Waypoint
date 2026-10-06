<script lang="ts" module>
  // What Google's return says (?gmail=<code>, set by the server's callback), as words. Only these fixed codes come back,
  // never anything Google said.
  const OUTCOMES: Record<string, { ok: boolean; text: string }> = {
    connected: { ok: true, text: "Gmail connected." },
    denied: { ok: false, text: "Google didn’t connect it: access wasn’t allowed." },
    scope: { ok: false, text: "Waypoint needs permission to read your email, and Google didn’t give it. Connect again and leave the box ticked." },
    refused: { ok: false, text: "That connection didn’t start here, or took too long. Choose Connect again." },
    failed: { ok: false, text: "Google couldn’t connect it. Try again in a moment." },
  };
</script>

<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { Mailbox, MailboxList } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  // Settings → Gmail: this member's own connected Gmail accounts (each member sees only theirs). Connecting sends the
  // browser to Google for read-only access and comes back here; Disconnect revokes the access at Google first.
  let list = $state<MailboxList | null>(null);
  let problem = $state("");
  let notice = $state<{ ok: boolean; text: string } | null>(null);
  let connecting = $state(false);
  let leaving = $state<Mailbox | null>(null);
  let asking = $state(false);
  let starting = $state<number | null>(null);

  async function load() {
    try { list = await apiCall<"GET /api/mailboxes">("/api/mailboxes"); problem = ""; }
    catch (err) { problem = errMsg(err); }
  }

  // A scan runs on the server for a while: check on it until it's done.
  const POLL_MS = 3000;
  let watching = $state(false);
  let watchUntil = 0;
  $effect(() => {
    const busy = !!list?.mailboxes?.some((m) => m.scanning);
    if (!busy && !watching) return;
    const timer = setInterval(() => {
      if (watching && Date.now() > watchUntil) watching = false;   // (just a few looks after a click)
      void load();
    }, POLL_MS);
    return () => clearInterval(timer);
  });

  onMount(() => {
    const code = new URLSearchParams(location.search).get("gmail");
    if (code && OUTCOMES[code]) {
      notice = OUTCOMES[code];
      history.replaceState(null, "", location.pathname + location.hash);   // so reloading doesn't say it again
    }
    load();
  });

  // Google's consent screen is another site: the server makes the address (with this connection's state), the browser goes.
  const connect = () => act(async () => {
    const r = await apiCall<"POST /api/mailboxes/connect">("/api/mailboxes/connect", { method: "POST" });
    location.href = r.url;
  }, { busy: (on) => (connecting = on) });

  const scan = (m: Mailbox) => act(async () => {
    const r = await apiCall<"POST /api/mailboxes/{id}/scan">(`/api/mailboxes/${m.id}/scan`, { method: "POST", failed: "Couldn’t start the scan" });
    if (!r.started) toast("A scan of this mailbox is already running.");
    await load();
    watchUntil = Date.now() + 2 * POLL_MS + 500;
    watching = true;   // a scan that can't start ends at once: look again for a moment to say why
  }, { busy: (on) => (starting = on ? m.id : null) });

  // Showing a mailbox's unread mail to the household: the box shows what the server kept, and goes back if it refuses.
  const share = (m: Mailbox, box: HTMLInputElement) => act(async () => {
    try {
      await apiCall<"POST /api/mailboxes/{id}/share">(`/api/mailboxes/${m.id}/share`, { method: "POST", body: { share: box.checked }, failed: "Couldn’t change it" });
      toast.success(box.checked ? "Shared with the household" : "No longer shared");
    } finally { await load(); box.checked = list?.mailboxes.find((x) => x.id === m.id)?.share_review ?? m.share_review; }
  });

  async function disconnect() {
    const m = leaving;
    if (!m) return false;
    return act(async () => {
      const r = await apiCall<"DELETE /api/mailboxes/{id}">(`/api/mailboxes/${m.id}`, { method: "DELETE", failed: "Couldn’t disconnect" });
      if (r.revoked) toast.success("Disconnected");
      else toast.warning("Disconnected, but Waypoint couldn’t unlock its saved access to tell Google. Remove Waypoint at myaccount.google.com/permissions.");
      await load();
    });
  }

  /** When a scan finished, in the viewer's own time zone (it's a moment in time, unlike a booking's times). */
  const scanned = (m: Mailbox) => (m.last_scan ? new Date(m.last_scan).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : null);

  const label = (m: Mailbox) => (m.status === "connected" ? "Connected" : m.status === "reconnect" ? "Reconnect" : "Couldn’t reach Google");
</script>

<section aria-labelledby="gmail-title" class="space-y-2">
  <h2 id="gmail-title" class="eyebrow px-1">Gmail</h2>
  {#if notice}
    <Alert variant={notice.ok ? "default" : "destructive"} class="pr-11">
      <AlertDescription>{notice.text}</AlertDescription>
    </Alert>
  {/if}
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={load}>Try again</Button></div>
    {:else if !list}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      {#each list.mailboxes as m (m.id)}
        <div class="row" data-testid="mailbox">
          <div class="min-w-0">
            <p class="truncate font-medium">{m.address}</p>
            <p class="text-sm text-muted-foreground">
              {#if m.status === "connected"}Waypoint can read this mailbox, read-only.{:else}{m.last_error ?? "Waypoint can’t read this mailbox right now."}{/if}
            </p>
            {#if m.scanning}
              <p class="text-sm text-muted-foreground" role="status">Scanning for bookings…</p>
            {:else if m.status !== "reconnect"}
              <p class="text-sm text-muted-foreground">{scanned(m) ? `Last scanned ${scanned(m)}.` : "Not scanned yet."}</p>
            {/if}
            <label class="mt-2 flex items-start gap-2 text-sm">
              <input type="checkbox" class="mt-0.5 size-4 shrink-0" checked={m.share_review} onchange={(e) => share(m, e.currentTarget)} />
              <span>Show this mailbox’s unread mail to the household<span class="block text-muted-foreground">Anyone in the household sees who each one is from and its day in Review, and can add it by hand or dismiss it. Never its subject or text, and only you can open it in Gmail. Off until you turn it on.</span></span>
            </label>
            {#if m.scan_notice && !m.scanning && m.status !== "reconnect"}<p class="text-sm text-muted-foreground" role="status">The scan couldn’t start: {m.scan_notice}</p>{/if}
            {#if m.scan_error}<p class="text-sm text-signal-ink" role="status">The last scan stopped: {m.scan_error} What it had read is kept, and the next scan carries on.</p>{/if}
          </div>
          <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
            <Badge variant={m.status === "connected" ? "outline" : "secondary"}>{label(m)}</Badge>
            {#if m.status === "reconnect"}<Button disabled={connecting} onclick={connect}>Reconnect</Button>
            {:else}<Button variant="outline" disabled={m.scanning || starting === m.id} onclick={() => scan(m)}>{m.scanning ? "Scanning…" : "Scan now"}</Button>{/if}
            <Button variant="outline" onclick={() => { leaving = m; asking = true; }}>Disconnect</Button>
          </div>
        </div>
      {/each}
      {#if !list.configured}
        <div class="row">
          <div>
            <p class="font-medium">Gmail isn’t set up</p>
            <p class="text-sm text-muted-foreground">
              Whoever runs Waypoint creates a Google client and sets <code class="code rounded bg-muted px-1 normal-case tracking-normal">GOOGLE_CLIENT_ID</code>
              and <code class="code rounded bg-muted px-1 normal-case tracking-normal">GOOGLE_CLIENT_SECRET</code>.
              <a class="underline underline-offset-2" href="https://anthonypluth.github.io/Waypoint/start/gmail/" target="_blank" rel="noopener noreferrer">How</a>
            </p>
          </div>
        </div>
      {:else}
        <div class="row">
          <div>
            <p class="font-medium">{list.mailboxes.length ? "Add another Gmail" : "Connect your Gmail"}</p>
            <p class="text-sm text-muted-foreground">Read-only: Waypoint can’t send, delete or change anything. Only you see what you connect.</p>
          </div>
          <Button disabled={connecting} onclick={connect}>{connecting ? "Opening Google…" : list.mailboxes.length ? "Connect another" : "Connect Gmail"}</Button>
        </div>
      {/if}
    {/if}
  </div>
</section>

<ConfirmDialog bind:open={asking} title={`Disconnect ${leaving?.address ?? "this Gmail"}?`} confirmLabel="Disconnect" busyLabel="Disconnecting…" destructive
  onconfirm={disconnect}>
  {#snippet description()}
    <p>Waypoint tells Google to end its access, then forgets the connection. You can connect it again later.</p>
  {/snippet}
</ConfirmDialog>
