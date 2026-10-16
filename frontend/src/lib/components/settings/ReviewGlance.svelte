<script lang="ts" module>
  import type { ReviewGlance } from "$lib/api-types";

  export const WHY: Record<ReviewGlance["reasons"][number]["reason"], string> = {
    no_markup: "No booking data found",
    incomplete: "Dates or place missing",
    broken: "Couldn’t be opened",
    match: "Could be one of your bookings",
    generic: "Read by the lodging reader, needs a check",
  };

  export const reviewLink = (domain: string, address: string) => `#review?sender=${encodeURIComponent(domain)}&mailbox=${encodeURIComponent(address)}`;
</script>

<script lang="ts">
  import { act, ignoreFailure } from "$lib/act";
  import type { Mailbox } from "$lib/api-types";
  import { refreshState } from "$lib/app.svelte";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  let { mailbox, onchange }: { mailbox: Mailbox; onchange: () => unknown } = $props();

  let glance = $state<ReviewGlance | null>(null);
  let failed = $state(false);
  let ignoring = $state<ReviewGlance["domains"][number] | null>(null);
  let asking = $state(false);

  async function load() {
    try {
      glance = await apiCall<"GET /api/mailboxes/{id}/review-glance">(`/api/mailboxes/${mailbox.id}/review-glance`);
      failed = false;
    } catch { failed = true; }
  }
  onMount(() => { void load(); });

  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

  const UNDO_MS = 8000;
  const undo = (domain: string) => act(async () => {
    await apiCall<"POST /api/mailboxes/{id}/unignore">(`/api/mailboxes/${mailbox.id}/unignore`, { method: "POST", body: { domain }, failed: "Couldn’t undo that" });
    toast.success(`Reading again what was skipped from ${domain}`);
    await settle();
  });

  async function settle() {
    await load();
    await onchange();
    await refreshState().catch(ignoreFailure);
  }

  async function ignore() {
    const target = ignoring;
    if (!target || target.item_id === null) return false;
    const itemId = target.item_id;
    return act(async () => {
      const r = await apiCall<"POST /api/review/{id}/ignore">(`/api/review/${itemId}/ignore`, { method: "POST" });
      toast.success(`Ignoring ${r.domain}`, {
        description: "You can undo this in the list of ignored senders below",
        duration: UNDO_MS,
        action: { label: "Undo", onClick: () => { void undo(r.domain); } },
      });
      await settle();
    });
  }
</script>

<div class="mt-2" data-testid="review-glance" data-state={glance ? (glance.waiting ? "data" : "empty") : failed ? "failed" : "loading"}>
  <h3 class="text-sm font-medium">Review at a glance</h3>
  {#if failed}
    <p class="text-sm text-muted-foreground">Couldn’t load it.</p>
  {:else if !glance}
    <p class="text-sm text-muted-foreground" role="status">Loading…</p>
  {:else if glance.waiting === 0}
    <p class="text-sm text-muted-foreground">Nothing from this mailbox is waiting in Review.</p>
  {:else}
    <p class="text-sm text-muted-foreground">{plural(glance.waiting, "item is", "items are")} waiting in Review from this mailbox. Only counts and sender domains are shown, never anything from a message.</p>

    <h4 class="mt-2 text-sm font-medium">Why</h4>
    <div class="overflow-x-auto">
      <table class="w-full text-left text-sm" data-testid="glance-reasons">
        <thead><tr class="text-xs text-muted-foreground"><th class="pb-1 pr-3 font-medium">Reason</th><th class="pb-1 pr-3 text-right font-medium">Waiting</th><th class="pb-1 text-right font-medium">Added in the last {glance.days} days</th></tr></thead>
        <tbody>{#each glance.reasons as r (r.reason)}<tr><td class="py-0.5 pr-3">{WHY[r.reason]}</td><td class="py-0.5 pr-3 text-right">{r.waiting}</td><td class="py-0.5 text-right">{r.recent}</td></tr>{/each}</tbody>
      </table>
    </div>

    {#if glance.gaps.length}
      <h4 class="mt-2 text-sm font-medium">What’s missing where dates or place are missing</h4>
      <ul class="text-sm" data-testid="glance-gaps">
        {#each glance.gaps as g (g.label)}<li class="flex justify-between gap-3"><span>{g.label[0].toUpperCase() + g.label.slice(1)}</span><span>{g.count}</span></li>{/each}
      </ul>
    {/if}

    <h4 class="mt-2 text-sm font-medium">Senders with the most waiting</h4>
    <ul class="mt-1 space-y-2" data-testid="glance-domains">
      {#each glance.domains as d (d.domain)}
        <li class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
          <div class="min-w-0">
            {#if d.domain}
              <a class="break-all font-medium underline underline-offset-2" href={reviewLink(d.domain, mailbox.address)} aria-label={`Show ${d.domain} in Review`}>{d.domain}</a>
            {:else}<span class="font-medium">Unknown sender</span>{/if}
            <span class="block text-muted-foreground">{plural(d.count, "item", "items")} · mostly {WHY[d.reason].toLowerCase()}</span>
          </div>
          {#if d.item_id !== null}
            <Button variant="outline" size="sm" aria-label={`Ignore this sender (${d.domain})`} onclick={() => { ignoring = d; asking = true; }}>Ignore this sender</Button>
          {/if}
        </li>
      {/each}
    </ul>

    <h4 class="mt-2 text-sm font-medium">Added to Review per scan, last 10 scans</h4>
    {#if glance.scans.length}
      <ul class="text-sm" data-testid="glance-scans">
        {#each glance.scans as s (s.at)}<li class="flex justify-between gap-3"><span class="text-muted-foreground">{when(s.at)}</span><span>{plural(s.added, "item", "items")}</span></li>{/each}
      </ul>
      <p class="text-sm text-muted-foreground">Counts the ones still waiting, from scans in the last {glance.days} days that added any.</p>
    {:else}
      <p class="text-sm text-muted-foreground">None in the last {glance.days} days.</p>
    {/if}
  {/if}
</div>

<ConfirmDialog bind:open={asking} title={`Ignore ${ignoring?.domain ?? "this sender"}?`} confirmLabel="Ignore" busyLabel="Ignoring…" destructive onconfirm={ignore}>
  {#snippet description()}
    {#if ignoring?.known_sender}<p class="text-signal-ink" data-testid="known-sender-warning">This sender is a travel company Waypoint knows. Ignoring it means its bookings won’t be added.</p>{/if}
    <p>Not travel: Waypoint stops looking at mail from this sender in that mailbox, and the items waiting from them leave Review. Bookings already made from their emails stay. Other mailboxes aren’t affected.</p>
    <p>You can undo this under Ignored senders in this mailbox.</p>
  {/snippet}
</ConfirmDialog>
