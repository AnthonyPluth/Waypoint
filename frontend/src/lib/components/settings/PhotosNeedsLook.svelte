<script lang="ts" module>
  import { kilometres } from "$lib/photos";
  import { clock, dayLabel } from "$lib/trips";
  import type { ReviewPhoto } from "$lib/api-types";
  import type { Who } from "$lib/photo-sharing";

  export const SHOWN = 3;

  export const stampOf = (p: Pick<ReviewPhoto, "taken_local">): string => `${dayLabel(p.taken_local)}, ${clock(p.taken_local)}`;

  export function listOf(names: string[]): string {
    if (names.length < 2) return names[0] ?? "";
    return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  }

  export const offWhere = (n: number): string => (n === 2 ? "both trips" : n === 1 ? "that trip" : "all those trips");

  export const tripOf = (p: ReviewPhoto): string => p.candidates.find((c) => c.id === p.trip_id)?.name ?? "this trip";

  export type Reversal = { kind: "placed"; trip: number } | { kind: "left"; stamp: number } | { kind: "removed"; trip: number; stamp: number };

  export const putText = (who: Who, trip: string): string => (who.mine ? `Put on ${trip}.` : `Put ${who.first}’s photo on ${trip}.`);

  export const keptText = (who: Who, trip: string): string => (who.mine ? `Kept on ${trip}.` : `Kept ${who.first}’s photo on ${trip}.`);

  export const leftText = (who: Who, trips: number): string => (who.mine ? `Left off ${offWhere(trips)}.` : `Left ${who.first}’s photo off ${offWhere(trips)}.`);

  export const removedText = (who: Who, trip: string): string => (who.mine ? `Removed from ${trip}.` : `Removed ${who.first}’s photo from ${trip}.`);

  export const backText = (who: Who): string => (who.mine ? "Back in Needs a look." : `${who.first}’s photo is back in Needs a look.`);

  export const choicesOf = (p: ReviewPhoto) => p.candidates.filter((c) => c.id !== p.trip_id);

  export function aboutOf(p: ReviewPhoto): string {
    if (p.match === "far") return `On ${tripOf(p)}, but taken ${kilometres(p.distance_km)} from every booking.`;
    const names = p.candidates.map((c) => c.name);
    if (names.length === 1) return `Could belong to ${names[0]}.`;
    if (names.length === 2) return `Fits two trips: ${listOf(names)}.`;
    return names.length ? `Fits ${names.length} trips: ${listOf(names)}.` : "Fits more than one trip.";
  }
</script>

<script lang="ts">
  import { onDestroy, tick, untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { act, errMsg } from "$lib/act";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Sheet } from "$lib/components/ui/sheet";
  import type { PhotoSharing, TripPhoto } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import { isStale, plural } from "$lib/photo-sharing";
  import { thumbnailUrl } from "$lib/photos";
  import ImageOff from "@lucide/svelte/icons/image-off";

  let { photos, who, ondecided, onreload }: { photos: ReviewPhoto[]; who: Who; ondecided: (id: number) => Promise<unknown>; onreload: () => Promise<boolean> } = $props();

  type Failure = { message: string; retry: boolean };

  let busy = $state<number | null>(null);
  let undoing = $state(false);
  let notes = $state<Record<number, string | undefined>>({});
  let showAll = $state(false);
  let broken = $state<Set<number>>(new Set());
  let summary = $state<HTMLElement | null>(null);
  let emptyLine = $state<HTMLElement | null>(null);
  let announce = $state("");
  let waiting: (() => void)[] = [];

  let pickingId = $state<number | null>(null);
  let sheetOpen = $state(false);
  let wanted = $state<number | null>(null);
  let sheetProblem = $state("");

  const shown = $derived(showAll ? photos : photos.slice(0, SHOWN));
  const rest = $derived(photos.length - shown.length);
  const picking = $derived(pickingId === null ? null : (photos.find((p) => p.id === pickingId) ?? null));
  const choices = $derived(picking ? choicesOf(picking) : []);
  const chosen = $derived(choices.some((c) => c.id === wanted) ? wanted : null);
  const chosenName = $derived(choices.find((c) => c.id === chosen)?.name ?? "");

  const note = (id: number, text: string | undefined) => { notes = { ...notes, [id]: text }; };

  const CHANGED = "That photo changed while you were looking. The list is up to date; check it and try again.";
  const UP_TO_DATE = "The list is up to date; check it before you choose again.";
  const sentence = (text: string): string => (/[.!?]$/.test(text) ? text : `${text}.`);
  const UNSURE = "Couldn’t refresh the list, so it may be out of date.";
  const UNDONE = "Couldn’t undo that";

  $effect(() => {
    void photos;
    untrack(() => {
      notes = Object.fromEntries(Object.entries(notes).filter(([, text]) => !text?.endsWith(UNSURE)));
      if (sheetProblem.endsWith(UNSURE)) sheetProblem = "";
    });
  });

  $effect(() => {
    if (sheetOpen && picking === null && busy === null) sheetOpen = false;
  });

  const release = () => { for (const wake of waiting.splice(0)) wake(); };

  $effect(() => {
    if (busy === null) release();
  });

  onDestroy(release);

  async function idle(): Promise<void> {
    while (busy !== null) await new Promise<void>((wake) => waiting.push(wake));
  }

  async function settle<R>(id: number, send: () => Promise<R>, said: string, failed: string, reverse?: (reply: R) => Reversal | null, again = CHANGED): Promise<Failure | null> {
    note(id, undefined);
    let failure: Failure | null = null;
    await act(async () => {
      let reply: R;
      try {
        reply = await send();
      } catch (err) {
        const status = (err as { status?: unknown } | null)?.status;
        if (status !== 400 && status !== 404 && status !== 409) throw err;
        const reason = errMsg(err) || failed;
        const fresh = await onreload();
        failure = { message: [sentence(reason), fresh ? (isStale(err) ? again : "") : UNSURE].filter(Boolean).join(" "), retry: false };
        return;
      }
      const reversal = reverse?.(reply) ?? null;
      if (reversal) {
        let used = false;
        toast.success(said, { action: { label: "Undo", onClick: () => { if (!used) { used = true; void undo(id, reversal); } } } });
      } else toast.success(said);
      await ondecided(id);
    }, {
      busy: (on) => (busy = on ? id : null),
      onError: (message) => { failure = { message: message || failed, retry: true }; },
    });
    return failure;
  }

  async function settled(id: number, failure: Failure | null, again?: () => void) {
    if (failure) {
      await tick();
      if (photos.some((x) => x.id === id)) note(id, failure.message);
      else if (failure.retry && again) toast(failure.message, { action: { label: "Try again", onClick: again } });
      else toast(failure.message);
      return;
    }
    await tick();
    const count = photos.length;
    announce = count ? `Saved. ${plural(count, "photo", "photos")} still ${count === 1 ? "needs" : "need"} a look.` : "Saved. Nothing else needs a look.";
    const target = () => (count ? summary : emptyLine);
    target()?.focus();
    setTimeout(() => { if (!document.activeElement || document.activeElement === document.body) target()?.focus(); }, 50);
  }

  const post = (p: ReviewPhoto, body: { trip_id?: number; excluded?: boolean }) =>
    apiCall<"POST /api/photos/{id}">(`/api/photos/${p.id}`, { method: "POST", body, failed: "Couldn’t save that choice" });

  const placed = (trip: number) => (): Reversal => ({ kind: "placed", trip });
  const left = (reply: TripPhoto): Reversal | null => (typeof reply.removed_at === "number" ? { kind: "left", stamp: reply.removed_at } : null);
  const removedFrom = (id: number, trip: number) => (reply: PhotoSharing): Reversal | null => {
    const stamp = reply.removed?.find((r) => r.id === id)?.removed_at;
    return typeof stamp === "number" ? { kind: "removed", trip, stamp } : null;
  };

  async function keep(p: ReviewPhoto) {
    const trip = p.trip_id;
    if (trip === null) return;
    await settled(p.id, await settle(p.id, () => post(p, { trip_id: trip }), keptText(who, tripOf(p)), "Couldn’t keep it", placed(trip)));
  }

  async function leaveOff(p: ReviewPhoto) {
    await settled(p.id, await settle(p.id, () => post(p, { excluded: true }), leftText(who, p.candidates.length), "Couldn’t leave it off", left));
  }

  async function remove(p: ReviewPhoto) {
    const trip = p.trip_id;
    if (trip === null) return;
    const send = () => apiCall<"POST /api/trips/{id}/photo-exclusions">(`/api/trips/${trip}/photo-exclusions`, { method: "POST", body: { photo_ids: [p.id] }, failed: "Couldn’t remove it" });
    await settled(p.id, await settle(p.id, send, removedText(who, tripOf(p)), "Couldn’t remove it", removedFrom(p.id, trip)));
  }

  async function undo(id: number, reversal: Reversal) {
    await idle();
    const again = () => { void undo(id, reversal); };
    const send = (): Promise<unknown> => reversal.kind === "removed"
      ? apiCall<"DELETE /api/trips/{id}/photo-exclusions/{id}">(`/api/trips/${reversal.trip}/photo-exclusions/${id}?created=${encodeURIComponent(String(reversal.stamp))}`, { method: "DELETE", failed: UNDONE })
      : apiCall<"POST /api/photos/{id}/undo">(`/api/photos/${id}/undo`, { method: "POST", body: reversal.kind === "placed" ? { trip_id: reversal.trip } : { left_off: reversal.stamp }, failed: UNDONE });
    undoing = true;
    try {
      const failure = await settle(id, send, backText(who), UNDONE, undefined, UP_TO_DATE);
      if (failure) await settled(id, failure, again);
      else announce = backText(who);
    } finally {
      undoing = false;
    }
  }

  function openPick(p: ReviewPhoto) {
    note(p.id, undefined);
    pickingId = p.id;
    wanted = choicesOf(p)[0]?.id ?? null;
    sheetProblem = "";
    sheetOpen = true;
  }

  async function put() {
    const p = picking;
    const trip = chosen;
    if (!p || trip === null) return;
    const name = chosenName;
    sheetProblem = "";
    const failure = await settle(p.id, () => post(p, { trip_id: trip }), putText(who, name), "Couldn’t put it on that trip", placed(trip));
    if (!failure) { sheetOpen = false; await settled(p.id, null); return; }
    await tick();
    if (photos.some((x) => x.id === p.id)) sheetProblem = failure.message;
    else { sheetOpen = false; toast(failure.message); }
  }

  const label = (p: ReviewPhoto) => stampOf(p);
</script>

<div class="space-y-2" data-testid="needs-a-look">
  {#if photos.length}
    <details open>
      <summary bind:this={summary} class="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg text-sm font-semibold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
        <StatusChip chip={{ label: "Needs a look", tone: "warn" }} /><span>{plural(photos.length, "photo", "photos")}</span>
      </summary>
      <p class="text-sm text-muted-foreground">{who.mine ? "Only you see this list." : `Only you see this list, because you manage ${who.library}.`}</p>
      <ul aria-label="Photos that need a look" class="divide-y divide-border">
        {#each shown as p (p.id)}
          {@const others = choicesOf(p)}
          <li class="flex items-start gap-3 py-3" data-photo={p.id}>
            <span class="relative block size-16 shrink-0 overflow-hidden rounded-[10px] bg-surface-3">
              {#if broken.has(p.id)}
                <span class="flex size-full items-center justify-center text-muted-foreground" role="img" aria-label="Photo, can’t be loaded right now"><ImageOff class="size-5" aria-hidden="true" /></span>
              {:else}
                <img class="size-full object-cover" src={thumbnailUrl(p.id)} alt="" loading="lazy" decoding="async" draggable="false" onerror={() => (broken = new Set([...broken, p.id]))} />
              {/if}
              {#if p.match === "far"}<span class="absolute left-[5px] top-[5px] rounded-full bg-status-warn-soft px-1.5 py-[3px] text-[10px] font-semibold leading-none text-status-warn-ink shadow-[0_0_0_1px_rgb(0_0_0/30%)]" aria-hidden="true">Far</span>{/if}
            </span>
            <div class="flex min-w-0 flex-1 flex-col gap-1">
              <p class="font-mono text-caption">{dayLabel(p.taken_local)} · {clock(p.taken_local)}</p>
              <p>{aboutOf(p)}</p>
              <div class="flex flex-wrap items-center gap-2">
                {#if p.match === "far"}
                  <Button variant="outline" size="sm" disabled={busy !== null} aria-label={`Keep on this trip, the photo from ${label(p)}`} onclick={() => keep(p)}>Keep on this trip</Button>
                {/if}
                {#if others.length}
                  <Button variant="outline" size="sm" disabled={busy !== null} aria-label={`Pick a trip for the photo from ${label(p)}`} onclick={() => openPick(p)}>Pick a trip</Button>
                {/if}
                {#if p.match === "far"}
                  <Button variant="ghost" size="sm" disabled={busy !== null} aria-label={`Remove from this trip, the photo from ${label(p)}`} onclick={() => remove(p)}>Remove from this trip</Button>
                {:else}
                  <Button variant="ghost" size="sm" disabled={busy !== null} aria-label={`Leave off, the photo from ${label(p)}`} onclick={() => leaveOff(p)}>Leave off</Button>
                {/if}
              </div>
              {#if busy === p.id}<p class="text-sm text-muted-foreground" role="status">Saving…</p>{/if}
              {#if notes[p.id]}<p class="text-sm text-signal-ink" role="alert">{notes[p.id]}</p>{/if}
            </div>
          </li>
        {/each}
      </ul>
      {#if rest > 0}
        <Button variant="ghost" size="sm" onclick={() => (showAll = true)}>Show {rest} more</Button>
      {:else if showAll && photos.length > SHOWN}
        <Button variant="ghost" size="sm" onclick={() => (showAll = false)}>Show fewer</Button>
      {/if}
    </details>
  {:else}
    <p bind:this={emptyLine} tabindex="-1" class="text-sm text-muted-foreground outline-none">Nothing needs a look.</p>
  {/if}
  {#if undoing}<p class="text-sm text-muted-foreground" role="status">Undoing…</p>{/if}
  <p class="sr-only" role="status">{announce}</p>
</div>

<Sheet bind:open={() => sheetOpen, (v) => { if (busy === null || v) sheetOpen = v; }} title="Pick a trip for this photo" description="Waypoint won’t move it again by itself.">
  {#if picking}
    <div class="flex flex-col gap-4">
      <div class="flex items-center gap-3">
        {#if !broken.has(picking.id)}<img class="size-[72px] shrink-0 rounded-xl object-cover" src={thumbnailUrl(picking.id)} alt="" draggable="false" />{/if}
        <div>
          <p class="font-mono">{dayLabel(picking.taken_local, true)} · {clock(picking.taken_local)}</p>
          <p class="text-caption text-muted-foreground">{who.mine ? "Your" : `${who.first}’s`} library</p>
        </div>
      </div>
      <fieldset class="m-0 flex flex-col gap-2 border-0 p-0">
        <legend class="eyebrow mb-2">Trips it could belong to</legend>
        {#each choices as c (c.id)}
          <label class="flex cursor-pointer items-start gap-3 rounded-2xl border border-border p-3 has-[:checked]:border-ring has-[:checked]:bg-primary/10">
            <input class="mt-0.5 size-[18px] shrink-0 accent-primary" type="radio" name="needs-a-look-trip" value={c.id} checked={chosen === c.id} disabled={busy !== null} onchange={() => (wanted = c.id)} />
            <span class="font-semibold">{c.name}</span>
          </label>
        {/each}
      </fieldset>
      <p class="text-caption text-muted-foreground">Only trips {who.subject} {who.mine ? "have" : "has"} shared photos on are listed. To use another trip, share {who.own} photos on it first.</p>
      {#if sheetProblem}<p class="text-sm text-signal-ink" role="alert">{sheetProblem}</p>{/if}
      <div class="flex flex-wrap justify-end gap-2">
        <Button variant="outline" disabled={busy !== null} onclick={() => (sheetOpen = false)}>Cancel</Button>
        <Button disabled={busy !== null || chosen === null} onclick={put}>{busy !== null ? "Saving…" : `Put on ${chosenName}`}</Button>
      </div>
    </div>
  {/if}
</Sheet>
