<script lang="ts" module>
  import type { PhotoGrantTrip, PhotoSharing } from "$lib/api-types";
  import { COULDNT_CHECK, plural, sharedWith, type Scope } from "$lib/photo-sharing";

  export const SHOWN_AT_FIRST = 3;
  export const OUT_OF_DATE = "Couldn’t refresh your sharing, so what shows may be out of date.";
  export const NOTHING_YET = "No trips with your photos yet.";

  export function tripLine(t: PhotoGrantTrip, dates: string): string {
    const shown = t.state === "shared";
    const count = t.count === null ? COULDNT_CHECK : plural(t.count, "photo", "photos");
    return [dates, count, shown && t.removed_count > 0 ? `${t.removed_count.toLocaleString()} removed` : "", shown ? "" : "not shared"].filter(Boolean).join(" · ");
  }

  export type Snapshot = { sharing: PhotoSharing; trip: PhotoGrantTrip };
</script>

<script lang="ts">
  import { act, actGet, errMsg } from "$lib/act";
  import type { Person, PhotoGrantPerson, PhotoGrants, PhotoPrefs } from "$lib/api-types";
  import { app } from "$lib/app.svelte";
  import SharePrompt from "$lib/components/SharePrompt.svelte";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { apiCall } from "$lib/contract";
  import { allTitle, isStale, narrowedToast, photosOf, shareAllBody, shareBody, stateOf as fetchState, stopText as stopCopy, stopTitle, unsharedOf, whoIs, widenText as widenCopy, widenTitle } from "$lib/photo-sharing";
  import { rangeLabel } from "$lib/trips";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  let { refresh = 0 }: { refresh?: number } = $props();

  let grants = $state<PhotoGrants | null>(null);
  let people = $state<Person[]>([]);
  let problem = $state("");
  let off = $state(false);
  let whose = $state<number | null>(null);
  let expanded = $state(false);
  let saving = $state(false);
  let draft = $state<{ scope: Record<number, Scope>; all: Record<number, boolean> }>({ scope: {}, all: {} });
  let ticket = 0;

  const me = $derived(app.state?.person_id ?? null);
  const current = $derived(grants?.people.find((p) => p.person_id === whose) ?? grants?.people.find((p) => p.person_id === me) ?? grants?.people[0] ?? null);
  const personOf = (id: number) => people.find((p) => p.id === id);
  const nameOf = (id: number) => personOf(id)?.display_name ?? "Someone";
  const who = $derived(whoIs(current?.person_id ?? -1, me, people));
  const mine = $derived(who.mine);
  const first = $derived(who.first);
  const own = $derived(who.own);
  const joins = $derived(who.joins);
  const shares = $derived(who.shares);
  const only = $derived(who.only);
  const stewarded = $derived(current !== null && !mine && personOf(current.person_id)?.member === false);
  const outOfDate = $derived(grants !== null && problem !== "");
  const locked = $derived(saving || outOfDate);

  async function load(keep = false): Promise<boolean> {
    ticket += 1;
    const mineTicket = ticket;
    const options = keep ? { keep: true } : undefined;
    try {
      const [found, everyone] = await Promise.all([apiCall<"GET /api/photo-grants">("/api/photo-grants", options), apiCall<"GET /api/people">("/api/people", options)]);
      if (mineTicket !== ticket) return true;
      grants = found; people = everyone.people; problem = ""; off = false;
      return true;
    } catch (err) {
      if (mineTicket !== ticket) return false;
      problem = errMsg(err);
      off = (err as { status?: unknown } | null)?.status === 404;
      return false;
    }
  }
  onMount(() => { void load(); });

  let seenRefresh: number | null = null;
  $effect(() => {
    const now = refresh;
    const before = seenRefresh;
    seenRefresh = now;
    if (before !== null && before !== now) void load(true);
  });

  async function holding<T>(fn: () => Promise<T>): Promise<T> {
    saving = true;
    try { return await fn(); }
    finally { saving = false; }
  }

  const patchPrefs = (personId: number, prefs: PhotoPrefs) => {
    if (grants) grants = { people: grants.people.map((p) => (p.person_id === personId ? { ...p, prefs } : p)) };
  };

  const setScope = async (p: PhotoGrantPerson, next: Scope, e: Event) => {
    opener = e.currentTarget as HTMLElement;
    draft.scope[p.person_id] = next;
    if (p.prefs.share_all && next === "trip") { ask({ kind: "later", person: p }); return; }
    await saveDefault(p, next);
    delete draft.scope[p.person_id];
  };

  const saveDefault = (p: PhotoGrantPerson, next: Scope) => act(async () => {
    patchPrefs(p.person_id, await apiCall<"POST /api/photo-sharing-prefs/{id}">(`/api/photo-sharing-prefs/${p.person_id}`, { method: "POST", body: { default_scope: next }, failed: "Couldn’t save it" }));
    toast.success("Saved");
  }, { busy: (on) => (saving = on) });

  type Asking =
    | { kind: "later"; person: PhotoGrantPerson }
    | { kind: "all"; person: PhotoGrantPerson; photos: number | null; note: string }
    | { kind: "widen"; person: PhotoGrantPerson; trip: PhotoGrantTrip; sharing: PhotoSharing; note: string }
    | { kind: "stop"; person: PhotoGrantPerson; trip: PhotoGrantTrip };
  let asking = $state<Asking | null>(null);
  let dialog = $state(false);
  let opener: HTMLElement | null = null;
  const ask = (next: Asking) => { asking = next; dialog = true; };
  $effect(() => { if (!dialog) draft = { scope: {}, all: {} }; });

  const stateOf = (p: PhotoGrantPerson, tripId: number) => fetchState(p.person_id, tripId);

  const allOf = (p: PhotoGrantPerson, note: string): Asking => ({ kind: "all", person: p, photos: photosOf(unsharedOf(p)), note });

  const switchAll = async (p: PhotoGrantPerson, on: boolean, e: Event) => {
    opener = e.currentTarget as HTMLElement;
    draft.all[p.person_id] = on;
    if (on && p.prefs.default_scope === "trip") { ask(allOf(p, "")); return; }
    await act(async () => {
      patchPrefs(p.person_id, await apiCall<"POST /api/photo-sharing-prefs/{id}">(`/api/photo-sharing-prefs/${p.person_id}`, { method: "POST", body: { share_all: on }, failed: on ? "Couldn’t turn it on" : "Couldn’t turn it off" }));
      toast.success("Saved");
      if (on) await load(true);
    }, { busy: (busy) => (saving = busy) });
    delete draft.all[p.person_id];
  };

  const confirmAll = () => holding(async () => {
    const a = asking;
    if (a?.kind !== "all" || a.photos === null) return false;
    const p = a.person;
    try {
      patchPrefs(p.person_id, await apiCall<"POST /api/photo-sharing-prefs/{id}">(`/api/photo-sharing-prefs/${p.person_id}`, {
        method: "POST", failed: "Couldn’t turn it on",
        body: shareAllBody(p),
      }));
    } catch (err) {
      if (!isStale(err)) { toast.error(errMsg(err)); return false; }
      const note = errMsg(err);
      const fresh = (await load(true)) ? grants?.people.find((x) => x.person_id === p.person_id) : undefined;
      if (fresh) asking = allOf(fresh, note); else dialog = false;
      return false;
    }
    toast.success("Saved");
    await load(true);
    return true;
  });

  const confirmLater = () => holding(async () => {
    const a = asking;
    if (a?.kind !== "later") return false;
    return saveDefault(a.person, "trip");
  });

  const datesOf = (t: PhotoGrantTrip) => (t.start_date ?? t.end_date ? rangeLabel((t.start_date ?? t.end_date)!, t.end_date ?? t.start_date!) : "No dates");

  async function widen(p: PhotoGrantPerson, t: PhotoGrantTrip, note = "") {
    const sharing = await actGet(() => stateOf(p, t.trip_id), { busy: (on) => (saving = on) });
    if (!sharing) return;
    const next: Asking = { kind: "widen", person: p, trip: t, sharing, note };
    if (dialog) asking = next; else ask(next);
  }

  const confirmWiden = () => holding(async () => {
    const a = asking;
    if (a?.kind !== "widen" || a.sharing.count === null) return false;
    try {
      await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${a.trip.trip_id}/photo-sharing`, { method: "POST", body: shareBody(a.person.person_id, a.sharing, "trip"), failed: "Couldn’t share it" });
    } catch (err) {
      if (!isStale(err)) { toast.error(errMsg(err)); return false; }
      const note = errMsg(err);
      const fresh = await actGet(() => stateOf(a.person, a.trip.trip_id));
      if (fresh) asking = { kind: "widen", person: a.person, trip: a.trip, sharing: fresh, note }; else dialog = false;
      return false;
    }
    toast.success(`Shared with everyone on ${a.trip.name}`);
    await load(true);
    return true;
  });

  const narrow = (p: PhotoGrantPerson, t: PhotoGrantTrip) => act(async () => {
    const reply = await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${t.trip_id}/photo-sharing`, { method: "POST", body: { person_id: p.person_id, scope: "only_me" }, failed: "Couldn’t change it" });
    toast(narrowedToast(who, t.name), { action: { label: "Undo", onClick: () => { void undo(p, t, reply); } } });
    await load(true);
  }, { busy: (on) => (saving = on) });

  const undo = (p: PhotoGrantPerson, t: PhotoGrantTrip, narrowed: PhotoSharing) => holding(async () => {
    try {
      await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${t.trip_id}/photo-sharing`, { method: "POST", body: shareBody(p.person_id, narrowed, "trip"), failed: "Couldn’t undo it" });
    } catch (err) {
      if (!isStale(err)) { toast.error(errMsg(err)); return; }
      opener = null;
      await widen(p, t, errMsg(err));
      return;
    }
    await load(true);
  });

  const changeScope = (p: PhotoGrantPerson, t: PhotoGrantTrip, e: Event & { currentTarget: HTMLSelectElement }) => {
    const next = e.currentTarget.value as Scope;
    e.currentTarget.value = t.scope ?? "only_me";
    opener = e.currentTarget;
    return next === "trip" ? widen(p, t) : narrow(p, t);
  };

  const askStop = (p: PhotoGrantPerson, t: PhotoGrantTrip, e: MouseEvent) => { opener = e.currentTarget as HTMLElement; ask({ kind: "stop", person: p, trip: t }); };

  const confirmStop = () => holding(async () => {
    const a = asking;
    if (a?.kind !== "stop") return false;
    return act(async () => {
      await apiCall<"DELETE /api/trips/{id}/photo-sharing">(`/api/trips/${a.trip.trip_id}/photo-sharing?person_id=${a.person.person_id}`, { method: "DELETE", failed: "Couldn’t stop sharing" });
      await load(true);
    });
  });

  type Prompt = { trip: number; sharing: PhotoSharing; scope: Scope; note: string };
  let prompt = $state<Prompt | null>(null);

  async function openPrompt(p: PhotoGrantPerson, t: PhotoGrantTrip) {
    if (prompt?.trip === t.trip_id) { prompt = null; return; }
    const sharing = await actGet(() => stateOf(p, t.trip_id), { busy: (on) => (saving = on) });
    if (sharing) prompt = { trip: t.trip_id, sharing, scope: p.prefs.default_scope, note: "" };
  }

  const sharePrompt = (p: PhotoGrantPerson, t: PhotoGrantTrip) => holding(async () => {
    const open = prompt;
    if (!open) return;
    try {
      await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${t.trip_id}/photo-sharing`, { method: "POST", body: shareBody(p.person_id, open.sharing, open.scope), failed: "Couldn’t share it" });
    } catch (err) {
      if (!isStale(err)) { toast.error(errMsg(err)); return; }
      const note = errMsg(err);
      const sharing = await actGet(() => stateOf(p, t.trip_id));
      prompt = sharing ? { ...open, sharing, note } : null;
      return;
    }
    toast.success(`Shared with ${sharedWith(open.scope, who)}. Change it any time under Your photos on this trip.`);
    prompt = null;
    await load(true);
  });

  const notNow = (p: PhotoGrantPerson, t: PhotoGrantTrip) => act(async () => {
    await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${t.trip_id}/photo-sharing`, { method: "POST", body: { person_id: p.person_id, declined: true }, failed: "Couldn’t save it" });
    prompt = null;
    await load(true);
  }, { busy: (on) => (saving = on) });

  const title = (a: Asking | null): string => {
    if (!a) return "";
    if (a.kind === "later") return allTitle(who, { ...a.person, eligible: [] }, null);
    if (a.kind === "all") return allTitle(who, a.person, a.photos);
    if (a.kind === "widen") return widenTitle(who, a.sharing.count);
    return stopTitle(who);
  };
</script>

{#if grants && grants.people.length && current}
  {@const p = current}
  {@const trips = expanded ? p.trips : p.trips.slice(0, SHOWN_AT_FIRST)}
  <section aria-labelledby="photo-sharing-title" class="space-y-2.5">
    <h2 id="photo-sharing-title" class="eyebrow px-1">Photo sharing</h2>
    {#if outOfDate}
      <div class="flex flex-wrap items-center gap-2 px-1" role="alert">
        <p class="text-sm text-signal-ink">{OUT_OF_DATE} {problem}</p>
        <Button variant="outline" size="sm" onclick={() => load(true)}>Try again</Button>
      </div>
    {/if}
    {#if grants.people.length > 1}
      <div class="flex flex-wrap gap-2" role="group" aria-label="Whose sharing">
        {#each grants.people as g (g.person_id)}
          <Button variant={g.person_id === p.person_id ? "default" : "outline"} aria-pressed={g.person_id === p.person_id} onclick={() => { whose = g.person_id; prompt = null; expanded = false; }}>{nameOf(g.person_id)}{g.person_id === me ? " (you)" : ""}</Button>
        {/each}
      </div>
      {#if stewarded}<p class="px-1 text-sm text-muted-foreground">You manage {first}’s sharing because {first} doesn’t sign in.</p>{/if}
    {/if}
    <div class="rows">
      <div class="space-y-4 p-4">
        <fieldset class="space-y-2" disabled={locked}>
          <legend class="mb-1.5 font-medium">Who sees the photos {shares}</legend>
          {#each [{ value: "only_me", name: only, hint: `Used when ${shares} on a trip. Each trip can be changed on its own.` }, { value: "trip", name: "Everyone on the trip", hint: `The other people on each trip see ${own} photos there.` }] as choice (choice.value)}
            <label class="flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm has-[:checked]:border-ring">
              <input type="radio" name={`default-scope-${p.person_id}`} value={choice.value} checked={(draft.scope[p.person_id] ?? p.prefs.default_scope) === choice.value} class="mt-1"
                onchange={(e) => setScope(p, choice.value as Scope, e)} />
              <span><span class="font-medium">{choice.name}</span><span class="block text-muted-foreground">{choice.hint}</span></span>
            </label>
          {/each}
        </fieldset>
        <label class="flex items-start gap-3 text-sm">
          <input type="checkbox" class="mt-1" checked={draft.all[p.person_id] ?? p.prefs.share_all} disabled={locked}
            onchange={(e) => switchAll(p, e.currentTarget.checked, e)} />
          <span>
            <span class="font-medium">{mine ? "Share on all my trips" : `Share on all of ${first}’s trips`}</span>
            <span class="block text-muted-foreground">On: trips with {own} photos, including ones {joins} later, are shared with the choice above without asking. Off: Waypoint asks the first time {mine ? "you open" : `${first} opens`} each trip.</span>
            <span class="block text-muted-foreground">Turning it off only stops sharing trips {joins} later. Trips already shared stay as they are; change them one by one below.</span>
          </span>
        </label>
      </div>
    </div>
    <h3 class="px-1 pt-1 font-medium">Trips with {own} photos</h3>
    {#if !p.trips.length}
      <p class="px-1 text-sm text-muted-foreground">{NOTHING_YET}</p>
    {:else}
      <ul class="rows" aria-label={`Trips with ${own} photos`}>
        {#each trips as t (t.trip_id)}
          <li class="space-y-3 p-4" data-testid="photo-grant">
            <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <div class="min-w-0">
                <p class="font-medium">{t.name}</p>
                <p class={`text-sm ${t.count === null ? "text-signal-ink" : "text-muted-foreground"}`}>{tripLine(t, datesOf(t))}</p>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                {#if t.state === "shared"}
                  <select class="border-input bg-secondary h-9 rounded-xl border px-3 text-base outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 md:text-sm"
                    aria-label={`Who sees ${own} photos on ${t.name}`} value={t.scope ?? "only_me"} disabled={locked} onchange={(e) => changeScope(p, t, e)}>
                    <option value="only_me">Only me</option>
                    <option value="trip">Everyone on this trip</option>
                  </select>
                  <Button variant="outline" size="sm" class="text-status-bad-ink" aria-label={`Stop sharing on ${t.name}`} disabled={locked} onclick={(e: MouseEvent) => askStop(p, t, e)}>Stop sharing</Button>
                {:else}
                  <StatusChip chip={{ label: "Not shared", tone: "quiet" }} />
                  <Button variant="outline" size="sm" aria-label={`Share on ${t.name}`} aria-expanded={prompt?.trip === t.trip_id} disabled={locked} onclick={() => openPrompt(p, t)}>Share…</Button>
                {/if}
              </div>
            </div>
            {#if prompt?.trip === t.trip_id}
              {@const open = prompt}
              <SharePrompt {who} sharing={open.sharing} bind:scope={open.scope} note={open.note} {locked} id={String(t.trip_id)} onshare={() => sharePrompt(p, t)} onskip={() => notNow(p, t)} />
            {/if}
          </li>
        {/each}
      </ul>
      {#if !expanded && p.trips.length > SHOWN_AT_FIRST}
        {@const more = p.trips.length - SHOWN_AT_FIRST}
        <Button variant="outline" size="sm" class="self-start" aria-expanded={false} aria-label={`Show ${plural(more, "more trip", "more trips")} with ${own} photos`} onclick={() => (expanded = true)}>Show {plural(more, "more trip", "more trips")}</Button>
      {/if}
    {/if}
  </section>
{:else if problem && !off}
  <section aria-labelledby="photo-sharing-title" class="space-y-2">
    <h2 id="photo-sharing-title" class="eyebrow px-1">Photo sharing</h2>
    <div class="rows"><div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={() => load()}>Try again</Button></div></div>
  </section>
{:else if !off && !grants}
  <section aria-labelledby="photo-sharing-title" class="space-y-2">
    <h2 id="photo-sharing-title" class="eyebrow px-1">Photo sharing</h2>
    <div class="rows"><div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div></div>
  </section>
{/if}

{#snippet allText()}
  {#if asking?.kind === "all"}
    {#if asking.note}<p role="alert" class="text-signal-ink">{asking.note}</p>{/if}
    {#if asking.photos === null}
      <p>{COULDNT_CHECK}. Try again later: nothing is shared until the photos can be counted.</p>
    {:else}
      <p>This applies to every trip {mine ? "you’re" : `${first} is`} on now and to trips {joins} later. Photos taken off a trip stay off it. Nothing changes in Immich.</p>
    {/if}
  {/if}
{/snippet}

{#snippet widenText()}
  {#if asking?.kind === "widen"}
    {#if asking.note}<p role="alert" class="text-signal-ink">{asking.note}</p>{/if}
    <p>{widenCopy(who, asking.trip.name)}</p>
  {/if}
{/snippet}

{#snippet laterText()}
  <p>This applies to trips {joins} later; trips already shared keep their own scope.</p>
{/snippet}

{#snippet stopText()}
  {#if asking?.kind === "stop"}
    <p>{stopCopy(who, asking.trip.name, asking.trip.count)}</p>
  {/if}
{/snippet}

<ConfirmDialog bind:open={dialog} title={title(asking)} returnFocus={() => opener}
  confirmLabel={asking?.kind === "stop" ? "Stop sharing" : asking?.kind === "later" ? "Save" : "Show them"} cancelLabel={asking?.kind === "stop" ? "Keep sharing" : "Cancel"}
  busyLabel={asking?.kind === "stop" ? "Stopping…" : "Saving…"} destructive={asking?.kind === "stop"}
  disabled={(asking?.kind === "all" && asking.photos === null) || (asking?.kind === "widen" && asking.sharing.count === null)}
  description={asking?.kind === "all" ? allText : asking?.kind === "widen" ? widenText : asking?.kind === "stop" ? stopText : laterText}
  onconfirm={() => (asking?.kind === "all" ? confirmAll() : asking?.kind === "widen" ? confirmWiden() : asking?.kind === "stop" ? confirmStop() : confirmLater())} />
