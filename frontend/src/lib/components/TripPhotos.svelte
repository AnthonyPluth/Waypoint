<script lang="ts">
  import { tick, untrack } from "svelte";
  import { app } from "$lib/app.svelte";
  import type { Person, PhotoSource, Trip, TripPhoto, TripPhotos } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import { Button } from "$lib/components/ui/button";
  import PhotoViewer from "$lib/components/PhotoViewer.svelte";
  import TripPhotoSharing from "$lib/components/TripPhotoSharing.svelte";
  import { actingPersons, PersonSharing } from "$lib/trip-sharing.svelte";
  import { byDay, dayCaption, daysFor, firstOfCluster, isFar, isInferred, localDay, personName, STRIP_SIZE, thumbnailUrl, tileLabel } from "$lib/photos";
  import { MAX_REMOVED, REMOVE, removeText, toggled } from "$lib/photo-sharing";
  import { clock, dayIn, dayLabel, viewerZone } from "$lib/trips";
  import Check from "@lucide/svelte/icons/check";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import ImageOff from "@lucide/svelte/icons/image-off";
  import Play from "@lucide/svelte/icons/play";

  let { trip, people, now, onloaded, onchanged }: { trip: Trip; people: Person[]; now: number; onloaded?: (found: TripPhotos | null) => void; onchanged?: () => void } = $props();

  type Loaded = { state: "loading" } | { state: "ready"; found: TripPhotos } | { state: "error" };
  let loaded = $state<Loaded>({ state: "loading" });
  let sources = $state<PhotoSource[] | null>(null);
  let acting = $state<PersonSharing[]>([]);
  let actingProblem = $state(false);
  let staleView = $state(false);
  let refreshing = $state(false);
  let checking = $state(false);
  let expanded = $state(false);
  let shownDays = $state(0);
  let announce = $state("");
  let viewing = $state(false);
  let at = $state(0);
  let viewedId = $state<number | null>(null);
  let gone = $state<"next" | "previous" | null>(null);
  let viewerNote = $state("");
  let viewer = $state<ReturnType<typeof PhotoViewer> | null>(null);
  let selecting = $state(false);
  let selected = $state<Set<number>>(new Set());
  let removing = $state(false);
  let heading = $state<HTMLElement | null>(null);
  let selectButton = $state<HTMLElement | null>(null);
  let broken = $state<Set<number>>(new Set());
  let gallery = $state<HTMLElement | null>(null);
  let sentinel = $state<HTMLElement | null>(null);
  let opener: HTMLElement | null = null;

  const signedIn = $derived(!!app.state?.user && !app.state.user.local);
  const tripId = $derived(trip.id);
  const days = $derived(byDay(loaded.state === "ready" ? loaded.found.photos : []));
  const photos = $derived(days.flatMap((d) => d.photos));
  const total = $derived(photos.length);
  const shown = $derived(days.slice(0, shownDays));
  const shownCount = $derived(shown.reduce((n, d) => n + d.photos.length, 0));
  const strip = $derived(photos.slice(0, STRIP_SIZE));
  const segments = $derived(new Map(trip.segments.map((s) => [s.id, s])));
  const indexOf = $derived(new Map(photos.map((p, i) => [p.id, i])));
  const started = $derived(!!trip.start_date && trip.start_date <= dayIn(now, viewerZone()));
  const waiting = $derived((sources ?? []).find((s) => s.mine && s.last_sync === null && s.status !== "off") ?? null);
  const brokenOwners = $derived([...new Set(photos.filter((p) => broken.has(p.id)).map((p) => personName(people, p.person_id)).filter(Boolean))]);
  const empty = $derived.by(() => {
    if (loaded.state !== "ready" || total > 0 || sources === null) return null;
    if (sources.length === 0) return started ? "connect" : null;
    return waiting ? "waiting" : "nothing";
  });
  const asking = $derived(acting.some((a) => a.mode === "prompt" || a.mode === "reminder"));
  const sharingShown = $derived(actingProblem || acting.some((a) => a.visible));
  const shows = $derived(loaded.state === "error" || total > 0 || empty !== null || sharingShown);
  const mineOf = (p: Pick<TripPhoto, "person_id">): PersonSharing | undefined => acting.find((a) => a.personId === p.person_id);
  const ownCount = $derived(photos.filter((p) => mineOf(p)).length);
  const frozen = $derived(removing || staleView || acting.some((a) => a.locked));
  const selectedPersons = $derived([...new Set(photos.filter((p) => selected.has(p.id)).map((p) => p.person_id))]);
  const removeLabel = $derived.by(() => {
    const only = selectedPersons.length === 1 ? acting.find((a) => a.personId === selectedPersons[0]) : undefined;
    return only ? removeText(only.who, selected.size) : REMOVE;
  });
  const selectNote = $derived.by(() => {
    if (selected.size >= MAX_REMOVED) return `You can remove up to ${MAX_REMOVED} photos at once.`;
    if (acting.length > 1) return "You can select only your own photos and those of people you manage.";
    const only = acting[0];
    return only && !only.who.mine ? `You can select only ${only.who.first}’s photos.` : "You can select only your own photos.";
  });
  const waitingName = $derived(waiting ? personName(people, waiting.person_id) : "");
  const seeAll = $derived(`See all ${total} ${total === 1 ? "photo" : "photos"}`);

  let latest = 0;
  let mapStale = false;
  async function load(id: number, soft = false) {
    const mine = ++latest;
    refreshing = soft;
    if (!soft) {
      loaded = { state: "loading" };
      onloaded?.(null);
      sources = null;
      expanded = false;
      shownDays = 0;
      broken = new Set();
      selecting = false;
      selected = new Set();
    }
    try {
      const found = await (soft ? apiCall<"GET /api/trips/{id}/photos">(`/api/trips/${id}/photos`, { keep: true }) : apiCall<"GET /api/trips/{id}/photos">(`/api/trips/${id}/photos`));
      const listed = found.photos.length === 0 ? (await apiCall<"GET /api/photo-sources">("/api/photo-sources", soft ? { keep: true } : undefined)).sources : [];
      if (mine !== latest) return;
      sources = listed;
      loaded = { state: "ready", found };
      staleView = false;
      mapStale = false;
      onloaded?.(found);
      if (soft) {
        broken = new Set();
        if (found.photos.length === 0) { expanded = false; shownDays = 0; }
      }
    } catch {
      if (mine !== latest) return;
      if (soft && loaded.state === "ready") {
        staleView = true;
        if (mapStale) onloaded?.(null);
      } else loaded = { state: "error" };
    } finally {
      if (mine === latest) refreshing = false;
    }
  }

  async function changed() {
    mapStale = true;
    onchanged?.();
    await load(trip.id, true);
  }

  function dropped(ids: number[]) {
    if (loaded.state !== "ready") return;
    const leaving = new Set(ids);
    latest++;
    if (viewing && viewedId !== null && leaving.has(viewedId)) {
      const here = photos.findIndex((p) => p.id === viewedId);
      const next = photos.slice(here + 1).find((p) => !leaving.has(p.id)) ?? photos.slice(0, here).reverse().find((p) => !leaving.has(p.id)) ?? null;
      viewedId = next?.id ?? null;
      if (next === null) viewing = false;
      else void tick().then(() => { viewerNote = `Photo ${at + 1} of ${total}`; viewer?.focusStage(); });
    }
    selected = new Set([...selected].filter((id) => !leaving.has(id)));
    loaded = { state: "ready", found: { ...loaded.found, photos: loaded.found.photos.filter((p) => !leaving.has(p.id)) } };
  }

  let setups = 0;
  async function sync(id: number, me: number | null) {
    const mine = ++setups;
    checking = true;
    try {
      const ids = await actingPersons(trip, people, me);
      if (mine !== setups) return;
      actingProblem = ids === null;
      const wanted = ids ?? (acting.length ? acting.map((a) => a.personId) : me === null ? [] : [me]);
      for (const a of acting) if (!wanted.includes(a.personId)) a.dispose();
      const next = wanted.map((who) => {
        const kept = acting.find((a) => a.personId === who);
        if (kept) { kept.relabel(me, people, trip.name); return kept; }
        return new PersonSharing(id, who, me, people, { changed, dropped }, trip.name);
      });
      acting = next;
      await Promise.all(next.map((a) => a.load()));
    } finally {
      if (mine === setups) checking = false;
    }
  }

  const changeKey = $derived(JSON.stringify([trip.id, trip.start_date, trip.end_date, [...trip.people].sort(), trip.segments.map((s) => [s.id, s.status, s.kind, s.start_local, s.start_zone, s.end_local, s.end_zone, s.origin, s.destination, s.details.address, s.details.state, s.itinerary]), people.map((p) => [p.id, p.member, p.first_name, p.display_name])]));
  let seen: { id: number; key: string } | null = null;

  $effect(() => {
    const id = tripId;
    const me = app.state?.person_id ?? null;
    if (!signedIn) return;
    untrack(() => void load(id));
    untrack(() => void sync(id, me));
    return () => untrack(() => {
      setups++;
      checking = false;
      for (const a of acting) a.dispose();
      acting = [];
    });
  });

  $effect(() => {
    const key = changeKey;
    const id = tripId;
    const me = app.state?.person_id ?? null;
    const before = seen;
    seen = { id, key };
    if (!signedIn || before === null || before.id !== id || before.key === key) return;
    untrack(() => {
      void load(id, true);
      void sync(id, me);
    });
  });

  const ownerOf = (p: TripPhoto) => personName(people, p.person_id);

  function focusTile(id: number | undefined) {
    if (id === undefined) return;
    gallery?.querySelector<HTMLElement>(`[data-photo="${id}"]`)?.focus();
  }

  async function open(fromStrip: boolean) {
    expanded = true;
    shownDays = daysFor(days, 0);
    announce = `Showing all ${total} ${total === 1 ? "photo" : "photos"} by day`;
    if (fromStrip) { await tick(); focusTile(days[0]?.photos[0]?.id); }
  }

  export async function showCluster(index: number) {
    const target = firstOfCluster(photos, index);
    if (!target) return;
    const needed = days.findIndex((d) => d.day === localDay(target)) + 1;
    expanded = true;
    shownDays = Math.max(shownDays, daysFor(days, 0), needed);
    const near = photos.filter((p) => p.cluster === index).length;
    announce = `Showing ${near} ${near === 1 ? "photo" : "photos"} from the map, from ${clock(target.taken_local)}`;
    await tick();
    const tile = gallery?.querySelector<HTMLElement>(`[data-photo="${target.id}"]`);
    if (!tile) return;
    tile.scrollIntoView?.({ block: "center", behavior: "auto" });
    tile.focus({ preventScroll: true });
  }

  function close() {
    expanded = false;
    shownDays = 0;
    announce = "";
  }

  function more(moveFocus: boolean) {
    const from = shownDays;
    const before = shownCount;
    shownDays = daysFor(days, from);
    const added = days.slice(from, shownDays).reduce((n, d) => n + d.photos.length, 0);
    if (!moveFocus || added === 0) return;
    announce = `Loaded ${added} more ${added === 1 ? "photo" : "photos"}, ${before + added} of ${total} shown`;
    void tick().then(() => focusTile(days[from]?.photos[0]?.id));
  }

  $effect(() => {
    const watched = sentinel;
    if (!watched || typeof IntersectionObserver !== "function") return;
    const seen = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) untrack(() => more(false)); }, { rootMargin: "600px 0px" });
    seen.observe(watched);
    return () => seen.disconnect();
  });

  function view(p: TripPhoto, e: MouseEvent) {
    opener = e.currentTarget as HTMLElement;
    at = indexOf.get(p.id) ?? 0;
    viewedId = p.id;
    gone = null;
    viewerNote = "";
    viewing = true;
  }

  $effect(() => {
    const list = photos;
    untrack(() => {
      if (!viewing || viewedId === null || gone) return;
      const i = list.findIndex((p) => p.id === viewedId);
      if (i >= 0) { if (at !== i) at = i; return; }
      if (list.length === 0) { viewing = false; return; }
      const was = at;
      at = Math.min(was, list.length - 1);
      gone = was < list.length ? "next" : "previous";
    });
  });

  $effect(() => {
    const here = at;
    if (gone) return;
    untrack(() => { if (viewing) viewedId = photos[here]?.id ?? viewedId; });
  });

  $effect(() => {
    if (viewing) return;
    untrack(() => { viewedId = null; gone = null; viewerNote = ""; });
  });

  $effect(() => {
    const own = ownCount;
    const present = new Set(photos.map((p) => p.id));
    untrack(() => {
      if (selecting && own === 0) { selecting = false; selected = new Set(); return; }
      if ([...selected].some((id) => !present.has(id))) selected = new Set([...selected].filter((id) => present.has(id)));
    });
  });

  function comeBack(): HTMLElement | null {
    if (opener?.isConnected) return opener;
    return gallery?.querySelector<HTMLElement>("[data-photo]") ?? gallery?.querySelector<HTMLElement>("button") ?? heading;
  }

  function revalidate() {
    void load(trip.id, true);
  }

  async function removePhotos(ids: number[]): Promise<boolean> {
    if (removing || ids.length === 0) return false;
    removing = true;
    try {
      const groups = new Map<number, number[]>();
      for (const id of ids) {
        const found = photos.find((p) => p.id === id);
        if (!found || !mineOf(found)) continue;
        groups.set(found.person_id, [...(groups.get(found.person_id) ?? []), id]);
      }
      if (groups.size === 0) return false;
      for (const [person, list] of groups) {
        const who = acting.find((a) => a.personId === person);
        if (!who || !(await who.remove(list))) return false;
      }
      return true;
    } finally {
      removing = false;
    }
  }

  function toggle(p: TripPhoto) {
    selected = toggled(selected, p.id);
  }

  async function startSelect() {
    selecting = true;
    selected = new Set();
    if (!expanded) await open(false);
    announce = "Select your photos to remove";
  }

  function endSelect() {
    selecting = false;
    selected = new Set();
    announce = "";
    void tick().then(() => (selectButton ?? heading)?.focus());
  }

  async function removeSelected() {
    if (await removePhotos([...selected])) endSelect();
  }

  function keys(e: KeyboardEvent) {
    if (e.key === "Escape" && selecting && !viewing && !removing && !e.defaultPrevented) endSelect();
  }

  function lost(id: number) {
    broken = new Set([...broken, id]);
  }
</script>

<svelte:window onkeydown={keys} />

{#if signedIn && shows}
  <section class="mb-6 flex flex-col gap-3" aria-labelledby="trip-photos-title" data-testid="trip-photos">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 id="trip-photos-title" class="flex items-baseline gap-2 text-heading" tabindex="-1" bind:this={heading}>Photos{#if total}<span class="text-caption text-muted-foreground">{total}</span>{/if}</h2>
      {#if total}
        <div class="flex flex-wrap items-center gap-2">
          {#if ownCount > 0 && !selecting}
            <Button variant="outline" size="sm" bind:ref={selectButton} aria-label="Select your photos to remove" disabled={frozen} onclick={() => void startSelect()}>Select</Button>
          {/if}
          <Button variant="outline" size="sm" aria-expanded={expanded} aria-controls="trip-photos-gallery" onclick={() => (expanded ? close() : open(false))}>{expanded ? "Show fewer" : seeAll}</Button>
        </div>
      {/if}
    </div>
    {#if selecting}
      <div class="sticky top-[calc(env(safe-area-inset-top)+4rem)] z-[2] flex flex-wrap items-center justify-between gap-x-3 gap-y-2 bg-background py-2 lg:top-0" data-testid="photo-selection">
        <p class="text-heading" role="status">{selected.size} selected</p>
        <div class="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" class="text-status-bad-ink" disabled={selected.size === 0 || frozen} onclick={() => void removeSelected()}>{removeLabel}</Button>
          <Button variant="ghost" size="sm" disabled={removing} onclick={endSelect}>Cancel</Button>
        </div>
      </div>
      <p class="text-caption text-muted-foreground">{selectNote}</p>
    {/if}

    {#if actingProblem}
      <div class="flex flex-wrap items-center gap-3" role="alert">
        <p class="text-muted-foreground">Couldn’t check which libraries you manage on this trip, so some sharing choices may be missing.</p>
        <Button variant="outline" size="sm" disabled={checking} onclick={() => void sync(trip.id, app.state?.person_id ?? null)}>Try again</Button>
      </div>
    {/if}
    {#if staleView}
      <div class="flex flex-wrap items-center gap-3" role="alert">
        <p class="text-muted-foreground">Couldn’t refresh the photos on this trip, so what shows may be out of date.</p>
        <Button variant="outline" size="sm" disabled={refreshing} onclick={() => void load(trip.id, true)}>Try again</Button>
      </div>
    {/if}
    {#each acting as a (a.personId)}
      <TripPhotoSharing sharing={a} tripName={trip.name} part="problem" />
      <TripPhotoSharing sharing={a} tripName={trip.name} part="prompt" />
    {/each}

    {#if loaded.state === "error"}
      <div class="flex flex-wrap items-center gap-3" role="status">
        <p class="text-muted-foreground">Couldn’t load the photos on this trip.</p>
        <Button variant="outline" size="sm" onclick={() => void load(trip.id)}>Try again</Button>
      </div>
    {:else if empty === "connect"}
      <div class="flex flex-col items-start gap-2.5 rounded-2xl border border-border bg-card p-4">
        <p>Photos from Immich can show on every trip, matched by when and where they were taken.</p>
        <Button variant="outline" size="sm" href="#settings/photos">Connect a library in Settings</Button>
      </div>
    {:else if empty === "waiting"}
      <p class="text-muted-foreground">{waitingName ? `${waitingName}’s library` : "Your library"} is connected. The first sync finds your photos; then you choose whether, and with whom, to share them on each trip.</p>
    {:else if empty === "nothing"}
      {#if !asking}<p class="text-muted-foreground">{acting.some((a) => (a.sharing?.removed_count ?? 0) > 0) ? "No photos on this trip." : "No photos on this trip yet."}</p>{/if}
    {:else if total > 0}
      <div id="trip-photos-gallery" bind:this={gallery}>
        {#if !expanded}
          <div class="flex gap-2 overflow-x-auto pb-1" data-testid="photo-strip">
            {#each strip as p (p.id)}
              <div class="w-[92px] shrink-0 desktop:w-[112px]">{@render tile(p, "rounded-xl")}</div>
            {/each}
            {#if total > STRIP_SIZE}
              <button type="button" class="relative flex aspect-square w-[92px] shrink-0 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-xl border border-input bg-secondary text-[13px] font-semibold desktop:w-[112px]"
                onclick={() => open(true)}><b class="font-mono text-[17px]" aria-hidden="true">+{total - STRIP_SIZE}</b><span aria-hidden="true">See all</span><span class="sr-only">{seeAll}</span></button>
            {/if}
          </div>
        {:else}
          <div class="flex flex-col gap-3">
            {#each shown as group (group.day)}
              <section class="flex flex-col gap-2" aria-labelledby={`photo-day-${group.day}`} data-day={group.day}>
                <div class="sticky top-[calc(env(safe-area-inset-top)+4rem)] z-[1] flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 bg-background py-2 lg:top-0">
                  <h3 id={`photo-day-${group.day}`} class="text-heading">{dayLabel(`${group.day}T00:00`)}</h3>
                  <p class="text-caption text-muted-foreground">{dayCaption(trip, group, segments)}</p>
                </div>
                <div class="grid grid-cols-3 gap-[3px] desktop:grid-cols-8 desktop:gap-[5px]">
                  {#each group.photos as p (p.id)}{@render tile(p, "rounded-md")}{/each}
                </div>
              </section>
            {/each}
            {#if shownDays < days.length}
              <div class="flex flex-wrap items-center gap-2" bind:this={sentinel}>
                <Button variant="outline" aria-describedby="trip-photos-count" onclick={() => more(true)}>Show more days</Button>
                <p id="trip-photos-count" class="text-caption text-muted-foreground">Showing {shownCount} of {total} photos</p>
              </div>
            {/if}
          </div>
        {/if}
      </div>
      {#if brokenOwners.length}
        <p class="text-caption text-muted-foreground">{brokenOwners.map((n) => `${n}’s`).join(" and ")} photos can’t be loaded right now. They show again once Waypoint can reach their Immich.</p>
      {/if}
    {/if}
    {#each acting as a (a.personId)}
      <TripPhotoSharing sharing={a} tripName={trip.name} part="reminder" />
    {/each}
    {#each acting as a (a.personId)}
      <TripPhotoSharing sharing={a} tripName={trip.name} part="card" />
    {/each}
    <p class="sr-only" role="status">{announce}</p>
  </section>
  {#each acting as a (a.personId)}
    <TripPhotoSharing sharing={a} tripName={trip.name} part="dialog" />
  {/each}
  <PhotoViewer bind:this={viewer} bind:open={viewing} bind:index={at} bind:gone {photos} {people} {segments} returnTo={comeBack} notice={viewerNote} onfail={revalidate}>
    {#snippet actions(p)}
      {@const who = mineOf(p)}
      {#if who}
        <Button class="phone:flex-1" variant="ghost" disabled={frozen} onclick={() => void removePhotos([p.id])}><EyeOff /> {removeText(who.who)}</Button>
      {/if}
    {/snippet}
  </PhotoViewer>
{/if}

{#snippet tile(p: TripPhoto, round: string)}
  {#if selecting && !broken.has(p.id)}
    {#if mineOf(p)}
      {@const picked = selected.has(p.id)}
      <button type="button" role="checkbox" aria-checked={picked} class={`relative block aspect-square w-full cursor-pointer overflow-hidden bg-surface-3 ${round} ${picked ? "outline outline-[3px] -outline-offset-[3px] outline-ring" : ""}`} data-photo={p.id} data-selected={picked}
        disabled={frozen} onclick={() => toggle(p)}>
        <span class="sr-only">{tileLabel(p, p.segment_id === null ? undefined : segments.get(p.segment_id), ownerOf(p))}</span>
        <img class="size-full object-cover" src={thumbnailUrl(p.id)} alt="" loading="lazy" decoding="async" draggable="false" onerror={() => lost(p.id)} />
        <span class={`absolute right-[5px] top-[5px] inline-flex size-5 items-center justify-center rounded-full border-2 ${picked ? "border-primary bg-primary text-primary-foreground" : "border-white/80 bg-lightbox/40"}`} aria-hidden="true">{#if picked}<Check class="size-3" />{/if}</span>
      </button>
    {:else}
      <span class={`relative block aspect-square w-full overflow-hidden bg-surface-3 opacity-55 ${round}`} role="img" data-photo-other={p.id}
        aria-label={`${p.kind === "video" ? "Video" : "Photo"}${ownerOf(p) ? ` by ${ownerOf(p)}` : ""}, ${clock(p.taken_local)}, not yours to remove`}>
        <img class="size-full object-cover" src={thumbnailUrl(p.id)} alt="" loading="lazy" decoding="async" draggable="false" onerror={() => lost(p.id)} />
      </span>
    {/if}
  {:else if broken.has(p.id)}
    <span class={`relative flex aspect-square w-full items-center justify-center overflow-hidden bg-surface-3 text-muted-foreground ${round}`} role="img"
      aria-label={`${p.kind === "video" ? "Video" : "Photo"} from ${ownerOf(p) ? `${ownerOf(p)}’s library` : "a library"}, can’t be loaded right now`}><ImageOff class="size-5" aria-hidden="true" /></span>
  {:else}
    <button type="button" class={`relative block aspect-square w-full cursor-pointer overflow-hidden bg-surface-3 ${round}`} data-photo={p.id}
      onclick={(e) => view(p, e)}>
      <span class="sr-only">{tileLabel(p, p.segment_id === null ? undefined : segments.get(p.segment_id), ownerOf(p))}</span>
      <img class="size-full object-cover" src={thumbnailUrl(p.id)} alt="" loading="lazy" decoding="async" draggable="false" onerror={() => lost(p.id)} />
      {#if isFar(p)}<span class="absolute left-[5px] top-[5px] rounded-full bg-status-warn-soft px-1.5 py-[3px] text-[10px] font-semibold leading-none text-status-warn-ink shadow-[0_0_0_1px_rgb(0_0_0/30%)]" aria-hidden="true">Far</span>{/if}
      {#if isInferred(p)}<span class="absolute bottom-[5px] left-[5px] rounded-full bg-lightbox/70 p-[3px]" aria-hidden="true" data-mark="inferred"><span class="block size-2.5 rounded-full border-2 border-map-photo"></span></span>{/if}
      {#if p.kind === "video"}<span class="absolute bottom-[5px] right-[5px] inline-flex items-center rounded-full bg-lightbox/70 p-1 text-foreground" aria-hidden="true" data-mark="video"><Play class="size-2.5 fill-current" /></span>{/if}
    </button>
  {/if}
{/snippet}
