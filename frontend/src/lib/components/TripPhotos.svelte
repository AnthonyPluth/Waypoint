<script lang="ts">
  import { tick, untrack } from "svelte";
  import { app } from "$lib/app.svelte";
  import type { Person, PhotoSource, Trip, TripPhoto, TripPhotos } from "$lib/api-types";
  import { apiCall } from "$lib/contract";
  import { Button } from "$lib/components/ui/button";
  import PhotoViewer from "$lib/components/PhotoViewer.svelte";
  import { byDay, dayCaption, daysFor, isFar, isInferred, personName, STRIP_SIZE, thumbnailUrl, tileLabel } from "$lib/photos";
  import { dayIn, dayLabel, viewerZone } from "$lib/trips";
  import ImageOff from "@lucide/svelte/icons/image-off";
  import Play from "@lucide/svelte/icons/play";

  let { trip, people, now }: { trip: Trip; people: Person[]; now: number } = $props();

  type Loaded = { state: "loading" } | { state: "ready"; found: TripPhotos } | { state: "error" };
  let loaded = $state<Loaded>({ state: "loading" });
  let sources = $state<PhotoSource[] | null>(null);
  let expanded = $state(false);
  let shownDays = $state(0);
  let announce = $state("");
  let viewing = $state(false);
  let at = $state(0);
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
  const shows = $derived(loaded.state === "error" || total > 0 || empty !== null);
  const waitingName = $derived(waiting ? personName(people, waiting.person_id) : "");
  const seeAll = $derived(`See all ${total} ${total === 1 ? "photo" : "photos"}`);

  let latest = 0;
  async function load(id: number) {
    const mine = ++latest;
    loaded = { state: "loading" };
    sources = null;
    expanded = false;
    shownDays = 0;
    broken = new Set();
    try {
      const found = await apiCall<"GET /api/trips/{id}/photos">(`/api/trips/${id}/photos`);
      const listed = found.photos.length === 0 ? (await apiCall<"GET /api/photo-sources">("/api/photo-sources")).sources : [];
      if (mine !== latest) return;
      sources = listed;
      loaded = { state: "ready", found };
    } catch {
      if (mine === latest) loaded = { state: "error" };
    }
  }

  $effect(() => {
    const id = tripId;
    if (!signedIn) return;
    untrack(() => void load(id));
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
    viewing = true;
  }

  function lost(id: number) {
    broken = new Set([...broken, id]);
  }
</script>

{#if signedIn && shows}
  <section class="mb-6 flex flex-col gap-3" aria-labelledby="trip-photos-title" data-testid="trip-photos">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 id="trip-photos-title" class="flex items-baseline gap-2 text-heading">Photos{#if total}<span class="text-caption text-muted-foreground">{total}</span>{/if}</h2>
      {#if total}
        <Button variant="outline" size="sm" aria-expanded={expanded} aria-controls="trip-photos-gallery" onclick={() => (expanded ? close() : open(false))}>{expanded ? "Show fewer" : seeAll}</Button>
      {/if}
    </div>

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
      <p class="text-muted-foreground">No photos on this trip yet.</p>
    {:else}
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
    <p class="sr-only" role="status">{announce}</p>
  </section>
  <PhotoViewer bind:open={viewing} bind:index={at} {photos} {people} {segments} returnTo={() => opener} />
{/if}

{#snippet tile(p: TripPhoto, round: string)}
  {#if broken.has(p.id)}
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
