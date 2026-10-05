<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { Reminders } from "$lib/api-types";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Input } from "$lib/components/ui/input";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  // Settings → Reminders: this member's own notifications ("Check-in opens", the day's summary) and private calendar feed.
  // The feed's address is shown once, when it's made: Waypoint keeps only a hash of its key, so it can't show it again.
  let list = $state<Reminders | null>(null);
  let problem = $state("");
  let address = $state("");
  let busy = $state(false);
  let replacing = $state(false);
  let turningOff = $state(false);

  const devices = $derived(list?.devices ?? []);
  const canPush = typeof navigator !== "undefined" && "serviceWorker" in navigator && typeof PushManager !== "undefined";

  async function load() {
    try { list = await apiCall<"GET /api/reminders">("/api/reminders"); problem = ""; }
    catch (err) { problem = errMsg(err); }
  }
  onMount(load);

  const choose = (change: { check_in?: boolean; day_of?: boolean }) => act(async () => {
    if (!list) return;
    list = await apiCall<"POST /api/reminders">("/api/reminders", { method: "POST", body: { check_in: list.check_in, day_of: list.day_of, ...change }, failed: "Couldn’t save that" });
  }, { busy: (on) => (busy = on) });

  /** The server's key as bytes, for the browser's push service. */
  const keyBytes = (b64u: string) => Uint8Array.from(atob(b64u.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

  const turnOn = () => act(async () => {
    if (!list) return;
    if ((await Notification.requestPermission()) !== "granted") {
      toast.error("Notifications are blocked for Waypoint in this browser. Allow them in its site settings, then try again.");
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(list.public_key) }));
    const json = sub.toJSON();
    await apiCall<"POST /api/reminders/devices">("/api/reminders/devices", { method: "POST", failed: "Couldn’t turn notifications on",
      body: { endpoint: json.endpoint ?? "", p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" } });
    toast.success("Notifications are on for this device");
    await load();
  }, { busy: (on) => (busy = on) });

  const removeDevice = (id: number) => act(async () => {
    await apiCall<"DELETE /api/reminders/devices/{id}">(`/api/reminders/devices/${id}`, { method: "DELETE", failed: "Couldn’t turn that off" });
    await load();
  }, { busy: (on) => (busy = on) });

  const makeFeed = () => act(async () => {
    const r = await apiCall<"POST /api/feed">("/api/feed", { method: "POST", failed: "Couldn’t make the calendar address" });
    address = r.url;
    await load();
  }, { busy: (on) => (busy = on) });

  async function replaceFeed() { await makeFeed(); return true; }

  async function turnOffFeed() {
    return act(async () => {
      await apiCall<"DELETE /api/feed">("/api/feed", { method: "DELETE", failed: "Couldn’t turn the calendar off" });
      address = "";
      await load();
    });
  }

  const copy = () => act(async () => {
    await navigator.clipboard.writeText(address);
    toast.success("Copied");
  });

  const when = (t: number) => new Date(t * 1000).toLocaleDateString(undefined, { dateStyle: "medium" });
</script>

<section aria-labelledby="reminders-title" class="space-y-2">
  <h2 id="reminders-title" class="eyebrow px-1">Reminders and calendar</h2>
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={load}>Try again</Button></div>
    {:else if !list}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      <label class="row cursor-pointer">
        <span class="min-w-0"><span class="block font-medium">Check-in opens</span><span class="block text-sm text-muted-foreground">24 hours before each flight.</span></span>
        <input type="checkbox" class="size-5 shrink-0" checked={list.check_in} disabled={busy} onchange={(e) => choose({ check_in: e.currentTarget.checked })} />
      </label>
      <label class="row cursor-pointer">
        <span class="min-w-0"><span class="block font-medium">Day-of summary</span><span class="block text-sm text-muted-foreground">What starts today, from 7:00 on Waypoint’s clock.</span></span>
        <input type="checkbox" class="size-5 shrink-0" checked={list.day_of} disabled={busy} onchange={(e) => choose({ day_of: e.currentTarget.checked })} />
      </label>

      {#each devices as d (d.id)}
        <div class="row" data-testid="device">
          <div class="min-w-0"><p class="truncate font-medium">Notifications to {d.service}</p><p class="text-sm text-muted-foreground">Turned on {when(d.created)}.</p></div>
          <Button variant="outline" disabled={busy} onclick={() => removeDevice(d.id)}>Turn off</Button>
        </div>
      {/each}
      <div class="row">
        <div class="min-w-0">
          <p class="font-medium">{devices.length ? "Notify another device" : "Get notifications on this device"}</p>
          <p class="text-sm text-muted-foreground">
            {#if canPush}They show your own trips only, never a loyalty number.{:else}This browser can’t show notifications. On an iPhone, add Waypoint to the Home Screen first.{/if}
          </p>
        </div>
        <Button disabled={busy || !canPush} onclick={turnOn}>Turn on</Button>
      </div>

      <div class="row" data-testid="calendar-feed">
        <div class="min-w-0">
          <p class="font-medium">Calendar feed</p>
          <p class="text-sm text-muted-foreground">
            {#if list.feed}Your trips, as a private address your calendar app subscribes to. Waypoint can’t show the address again: make a new one if you’ve lost it.
            {:else}Subscribe your calendar app to your trips, at an address only you have.{/if}
          </p>
        </div>
        <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
          {#if list.feed}<Badge variant="outline">On</Badge>
            <Button variant="outline" disabled={busy} onclick={() => (replacing = true)}>New address</Button>
            <Button variant="outline" disabled={busy} onclick={() => (turningOff = true)}>Turn off</Button>
          {:else}<Button disabled={busy} onclick={makeFeed}>Make my calendar address</Button>{/if}
        </div>
      </div>
      {#if address}
        <div class="row" data-testid="feed-address">
          <div class="min-w-0 grow space-y-2">
            <p class="text-sm text-muted-foreground" role="status">Add this address to your calendar app as a subscription. It’s shown only now; anyone who has it can see your trips.</p>
            <div class="flex gap-2"><Input readonly value={address} aria-label="Calendar address" onfocus={(e) => e.currentTarget.select()} /><Button variant="outline" onclick={copy}>Copy</Button></div>
          </div>
        </div>
      {/if}
    {/if}
  </div>
</section>

<ConfirmDialog bind:open={replacing} title="Make a new calendar address?" confirmLabel="Make a new address" busyLabel="Making…" onconfirm={replaceFeed}>
  {#snippet description()}
    <p>The old address stops working at once, so subscribe your calendar app to the new one.</p>
  {/snippet}
</ConfirmDialog>

<ConfirmDialog bind:open={turningOff} title="Turn the calendar feed off?" confirmLabel="Turn off" busyLabel="Turning off…" destructive onconfirm={turnOffFeed}>
  {#snippet description()}
    <p>The address stops working. You can make a new one later.</p>
  {/snippet}
</ConfirmDialog>
