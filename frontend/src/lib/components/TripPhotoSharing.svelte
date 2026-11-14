<script lang="ts">
  import StatusChip from "$lib/components/StatusChip.svelte";
  import SharePrompt from "$lib/components/SharePrompt.svelte";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { allTitle, COULDNT_CHECK, plural, stopText, stopTitle, widenText, widenTitle } from "$lib/photo-sharing";
  import { NOT_LOADED_HERE, OUT_OF_DATE_HERE, type PersonSharing } from "$lib/trip-sharing.svelte";

  let { sharing, tripName, part }: { sharing: PersonSharing; tripName: string; part: "prompt" | "reminder" | "card" | "problem" | "dialog" } = $props();

  const who = $derived(sharing.who);
  const asking = $derived(sharing.asking);
  const s = $derived(sharing.sharing);
  const id = $derived(`${sharing.personId}`);
  const shown = $derived(sharing.pending ?? s?.scope ?? "only_me");
  const stopping = $derived(asking?.kind === "stop");
  const reminder = $derived(s?.count === null ? `${COULDNT_CHECK}. ${who.mine ? "Your" : `${who.first}’s`} photos from this trip aren’t on it.` : `${who.mine ? "Your" : `${who.first}’s`} ${plural(s?.count ?? 0, "photo", "photos")} from this trip aren’t on it. Only ${who.subject} see${who.mine ? "" : "s"} this.`);

  const dialogTitle = $derived.by(() => {
    if (asking?.kind === "all") return allTitle(who, asking.person, asking.photos);
    if (asking?.kind === "widen") return widenTitle(who, asking.sharing.count);
    return stopTitle(who);
  });
  const blocked = $derived((asking?.kind === "all" && asking.photos === null && asking.person.eligible.length > 0) || (asking?.kind === "widen" && asking.sharing.count === null));
</script>

{#if part === "problem" && sharing.problem && !sharing.off}
  <div class="flex flex-wrap items-center gap-3" role="alert">
    <p class="text-muted-foreground">{sharing.sharing ? OUT_OF_DATE_HERE : NOT_LOADED_HERE} {sharing.problem}</p>
    <Button variant="outline" size="sm" disabled={sharing.busy} onclick={sharing.retry}>Try again</Button>
  </div>
{:else if part === "prompt" && s && sharing.mode === "prompt"}
  <SharePrompt {who} sharing={s} bind:scope={sharing.scope} note={sharing.note} locked={sharing.locked} {id} heading="h3" eyebrow={who.mine ? "Your photos" : `${who.first}’s photos`} skipVariant="ghost"
    class="rounded-2xl border border-border bg-card p-4 shadow-card" onshare={sharing.share} onskip={sharing.notNow}>
    {#snippet actions()}
      <Button variant="outline" size="sm" disabled={sharing.locked || (sharing.scope === "trip" && s.count === null)} onclick={(e: MouseEvent) => sharing.shareAll(e)}>Share on all {who.mine ? "my" : `${who.first}’s`} trips</Button>
    {/snippet}
    {#snippet foot()}
      <p class="text-caption text-muted-foreground">Share on all {who.mine ? "my" : `${who.first}’s`} trips also covers trips {who.joins} later, shared the same way without asking. With Everyone on this trip chosen, it first asks {who.mine ? "you" : `${who.first}`} to confirm.</p>
      <p class="text-caption text-muted-foreground">{who.mine ? "You can" : `${who.first} can`} take back one photo, or stop sharing, whenever {who.mine ? "you like" : "they like"}. It takes effect at once, for everyone.</p>
    {/snippet}
  </SharePrompt>
{:else if part === "reminder" && s && sharing.mode === "reminder"}
  <div class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-border bg-card px-3 py-2.5 text-sm" data-testid="photo-reminder">
    <p class="min-w-0 flex-1 basis-[200px]">{reminder}</p>
    <Button variant="outline" size="sm" aria-label={`Share ${who.own} photos on this trip`} disabled={sharing.locked} onclick={sharing.reopen}>Share…</Button>
  </div>
{:else if part === "card" && s && sharing.mode === "card"}
  <section class="flex flex-col gap-3.5 rounded-2xl border border-border bg-card p-4 shadow-card" aria-labelledby={`photo-card-${id}`} data-testid="your-photos">
    <div class="flex flex-wrap items-start gap-3">
      <div class="flex min-w-0 flex-[1_1_200px] flex-col gap-0.5">
        <h3 id={`photo-card-${id}`} class="text-heading">{sharing.title}</h3>
        <p class="text-caption text-muted-foreground">{s.count ? `${plural(s.count, "photo", "photos")} from ${who.library}` : `No photos from ${who.library} yet`}</p>
      </div>
      <StatusChip chip={s.scope === "trip" ? { label: "Everyone on this trip", tone: "info" } : { label: who.only, tone: "quiet" }} />
    </div>
    <fieldset class="flex flex-col gap-2" disabled={sharing.locked}>
      <legend class="eyebrow mb-1">Who can see {who.own} photos on this trip</legend>
      <label class="flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm has-[:checked]:border-ring">
        <input type="radio" name={`scope-${id}`} class="mt-1" checked={shown === "only_me"} onchange={(e) => sharing.choose("only_me", e)} />
        <span><span class="font-medium">{who.only}</span><span class="block text-muted-foreground">Nobody else on the trip can tell they’re there.</span></span>
      </label>
      <label class="flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm has-[:checked]:border-ring">
        <input type="radio" name={`scope-${id}`} class="mt-1" checked={shown === "trip"} onchange={(e) => sharing.choose("trip", e)} />
        <span><span class="font-medium">Everyone on this trip</span><span class="block text-muted-foreground">Everyone else on the trip sees them, on the map and in the counts too.</span></span>
      </label>
    </fieldset>
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" class="text-status-bad-ink" disabled={sharing.locked} onclick={sharing.askStop}>Stop sharing on this trip</Button>
    </div>
  </section>
{:else if part === "dialog"}
  <ConfirmDialog bind:open={() => sharing.dialog, sharing.setDialog} title={dialogTitle} returnFocus={() => sharing.opener}
    confirmLabel={stopping ? "Stop sharing" : "Show them"} cancelLabel={stopping ? "Keep sharing" : "Cancel"} busyLabel={stopping ? "Stopping…" : "Saving…"} destructive={stopping}
    disabled={blocked} description={asking?.kind === "all" ? allText : asking?.kind === "widen" ? widenBody : stopBody}
    onconfirm={() => (asking?.kind === "all" ? sharing.confirmAll() : asking?.kind === "widen" ? sharing.confirmWiden() : sharing.confirmStop())} />
{/if}

{#snippet allText()}
  {#if asking?.kind === "all"}
    {#if asking.note}<p role="alert" class="text-signal-ink">{asking.note}</p>{/if}
    {#if asking.photos === null && asking.person.eligible.length}
      <p>{COULDNT_CHECK}. Try again later: nothing is shared until the photos can be counted.</p>
    {:else}
      <p>This applies to every trip {who.mine ? "you’re" : `${who.first} is`} on now and to trips {who.joins} later. Photos taken off a trip stay off it. Nothing changes in Immich.</p>
    {/if}
  {/if}
{/snippet}

{#snippet widenBody()}
  {#if asking?.kind === "widen"}
    {#if asking.note}<p role="alert" class="text-signal-ink">{asking.note}</p>{/if}
    <p>{widenText(who, tripName)}</p>
  {/if}
{/snippet}

{#snippet stopBody()}
  <p>{stopText(who, tripName, s?.count ?? null)}</p>
{/snippet}
