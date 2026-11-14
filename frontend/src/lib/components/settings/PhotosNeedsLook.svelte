<script lang="ts" module>
  import { kilometres } from "$lib/photos";
  import { clock, dayLabel } from "$lib/trips";
  import type { ReviewPhoto } from "$lib/api-types";

  export const SHOWN = 3;

  export const stampOf = (p: Pick<ReviewPhoto, "taken_local">): string => `${dayLabel(p.taken_local)}, ${clock(p.taken_local)}`;

  export function listOf(names: string[]): string {
    if (names.length < 2) return names[0] ?? "";
    return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  }

  export const offWhere = (n: number): string => (n === 2 ? "both trips" : n === 1 ? "that trip" : "all those trips");

  export const tripOf = (p: ReviewPhoto): string => p.candidates.find((c) => c.id === p.trip_id)?.name ?? "this trip";

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
  import { tick } from "svelte";
  import { toast } from "svelte-sonner";
  import { act } from "$lib/act";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Sheet } from "$lib/components/ui/sheet";
  import { apiCall } from "$lib/contract";
  import { isStale, plural, type Who } from "$lib/photo-sharing";
  import { thumbnailUrl } from "$lib/photos";
  import ImageOff from "@lucide/svelte/icons/image-off";

  let { photos, who, ondecided }: { photos: ReviewPhoto[]; who: Who; ondecided: (id: number) => Promise<unknown> } = $props();

  type Failure = { message: string; stale: boolean };

  let busy = $state<number | null>(null);
  let notes = $state<Record<number, string | undefined>>({});
  let showAll = $state(false);
  let broken = $state<Set<number>>(new Set());
  let summary = $state<HTMLElement | null>(null);

  let picking = $state<ReviewPhoto | null>(null);
  let sheetOpen = $state(false);
  let chosen = $state<number | null>(null);
  let sheetProblem = $state("");

  const shown = $derived(showAll ? photos : photos.slice(0, SHOWN));
  const rest = $derived(photos.length - shown.length);
  const choices = $derived(picking ? choicesOf(picking) : []);
  const chosenName = $derived(choices.find((c) => c.id === chosen)?.name ?? "");

  const note = (id: number, text: string | undefined) => { notes = { ...notes, [id]: text }; };

  const CHANGED = "That photo changed while you were looking. The list is up to date; check it and try again.";

  async function settle(p: ReviewPhoto, send: () => Promise<unknown>, said: string, failed: string): Promise<Failure | null> {
    note(p.id, undefined);
    let failure: Failure | null = null;
    await act(async () => {
      await send();
      toast.success(said);
      await ondecided(p.id);
    }, {
      busy: (on) => (busy = on ? p.id : null),
      onError: (message, err) => {
        const stale = isStale(err);
        failure = { message: stale ? `${message || failed} ${CHANGED}` : message || failed, stale };
      },
    });
    return failure;
  }

  async function settled(p: ReviewPhoto, failure: Failure | null) {
    if (failure) { note(p.id, failure.message); return; }
    await tick();
    summary?.focus();
  }

  const post = (p: ReviewPhoto, body: { trip_id?: number; excluded?: boolean }) =>
    apiCall<"POST /api/photos/{id}">(`/api/photos/${p.id}`, { method: "POST", body, failed: "Couldn’t save that choice" });

  async function keep(p: ReviewPhoto) {
    const trip = p.trip_id;
    if (trip === null) return;
    await settled(p, await settle(p, () => post(p, { trip_id: trip }), `Kept on ${tripOf(p)}.`, "Couldn’t keep it"));
  }

  async function leaveOff(p: ReviewPhoto) {
    await settled(p, await settle(p, () => post(p, { excluded: true }), `Left off ${offWhere(p.candidates.length)}.`, "Couldn’t leave it off"));
  }

  async function remove(p: ReviewPhoto) {
    const trip = p.trip_id;
    if (trip === null) return;
    const send = () => apiCall<"POST /api/trips/{id}/photo-exclusions">(`/api/trips/${trip}/photo-exclusions`, { method: "POST", body: { photo_ids: [p.id] }, failed: "Couldn’t remove it" });
    await settled(p, await settle(p, send, `Removed from ${tripOf(p)}.`, "Couldn’t remove it"));
  }

  function openPick(p: ReviewPhoto) {
    note(p.id, undefined);
    picking = p;
    chosen = choicesOf(p)[0]?.id ?? null;
    sheetProblem = "";
    sheetOpen = true;
  }

  async function put() {
    const p = picking;
    const trip = chosen;
    if (!p || trip === null) return;
    sheetProblem = "";
    const failure = await settle(p, () => post(p, { trip_id: trip }), `Put on ${chosenName}.`, "Couldn’t put it on that trip");
    if (!failure) { sheetOpen = false; await settled(p, null); return; }
    if (failure.stale) { sheetOpen = false; note(p.id, failure.message); return; }
    sheetProblem = failure.message;
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
    <p class="text-sm text-muted-foreground">Nothing needs a look.</p>
  {/if}
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
            <input class="mt-0.5 size-[18px] shrink-0 accent-primary" type="radio" name="needs-a-look-trip" value={c.id} checked={chosen === c.id} disabled={busy !== null} onchange={() => (chosen = c.id)} />
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
