<script lang="ts">
  import { app } from "$lib/app.svelte";
  import type { Person, Trip, TripPhotos as PhotoReply } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { OptionsMenu, type OptionsMenuItem } from "$lib/components/ui/options-menu";
  import AvatarStack from "$lib/components/AvatarStack.svelte";
  import KindTile from "$lib/components/KindTile.svelte";
  import RouteReplay from "$lib/components/RouteReplay.svelte";
  import TripDetails from "$lib/components/TripDetails.svelte";
  import TripPhotoSharing from "$lib/components/TripPhotoSharing.svelte";
  import TripPhotoSharingMenu from "$lib/components/TripPhotoSharingMenu.svelte";
  import TripPhotos from "$lib/components/TripPhotos.svelte";
  import TripSummary from "$lib/components/TripSummary.svelte";
  import { countNote, formatTotals } from "$lib/money";
  import { heroCaption, heroOf, thumbnailUrl } from "$lib/photos";
  import type { PersonSharing } from "$lib/trip-sharing.svelte";
  import { bookingCounts, tripPeople } from "$lib/trips";
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Play from "@lucide/svelte/icons/play";

  type Props = {
    trip: Trip; people: Person[]; now: number; dates: string; costsShown: boolean; loads: number; back: boolean;
    options: OptionsMenuItem[]; editing?: boolean; onsaved: (next: Trip) => void; onbookings?: (() => void) | null;
  };
  let { trip, people, now, dates, costsShown, loads, back, options, editing = $bindable(false), onsaved, onbookings = null }: Props = $props();

  let found = $state<PhotoReply | null>(null);
  let status = $state<"loading" | "ready" | "error">("loading");
  let photoChanges = $state(0);
  let looks = $state(0);
  let stopCount = $state(0);
  let replaying = $state(false);
  let gallery = $state<{ showCluster: (cluster: number) => Promise<void>; viewFirst: () => void; headingElement: () => HTMLElement | null } | null>(null);
  let acting = $state<PersonSharing[]>([]);
  let settled = $state(false);
  let details = $state<{ open: () => Promise<void> } | null>(null);
  let editButton = $state<HTMLElement | null>(null);
  let lost = $state<Set<number>>(new Set());

  const signedIn = $derived(!!app.state?.user && !app.state.user.local);
  const heroIds = $derived(heroOf(found));
  const heroKind = $derived.by((): "photos" | "pending" | "map" => {
    if (!signedIn) return "map";
    if (heroIds.length > 0) return "photos";
    return status === "loading" ? "pending" : "map";
  });
  const leftOut = $derived<ReadonlySet<number>>(new Set(heroKind === "photos" ? heroIds : []));
  const noPhotos = $derived(signedIn && status === "ready" && found !== null && found.photos.length === 0);
  const viewDrawn = $derived(heroKind === "photos" && found !== null && found.photos.length === heroIds.length);
  const hasControl = $derived(acting.some((a) => a.mode === "card"));
  const holdSlot = $derived(signedIn && !settled);
  const controlRow = $derived(viewDrawn || hasControl || holdSlot);
  const caption = $derived(heroCaption(trip, dates));
  const avatars = $derived(tripPeople(trip));
  const counts = $derived(bookingCounts(trip));
  const hasTotal = $derived(costsShown && trip.costs.totals.length > 0);
  const looksWords = $derived(`${looks} ${looks === 1 ? "photo needs" : "photos need"} a look`);

  $effect(() => {
    void trip.id;
    replaying = false;
    settled = false;
    lost = new Set();
  });
  $effect(() => {
    if (heroKind === "map") replaying = false;
  });
</script>

<div class="flex flex-col gap-5" data-testid="past-trip">
  <div class="relative flex items-center justify-between gap-3">
    {#if back}
      <a class="-ml-1 inline-flex min-h-11 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground" href="#trips"><ArrowLeft class="size-4" aria-hidden="true" /> Past trips</a>
    {:else}
      <span></span>
    {/if}
    <div class="flex items-center">
      {#if !editing}<Button bind:ref={editButton} variant="ghost" size="icon" aria-label="Edit trip details" onclick={() => void details?.open()}><Pencil /></Button>{/if}
      {#if options.length}<OptionsMenu popup iconOnly variant="ghost" label="Trip options" text="Trip options" icon={Ellipsis} items={options} />{/if}
    </div>
  </div>

  <TripDetails bind:this={details} bind:editing {trip} {dates} {onsaved} bare returnFocus={() => editButton} />

  {#if editing}
    <h1 class="sr-only">{trip.name}</h1>
  {:else}
    {#if heroKind === "map"}
      <div class="min-w-0">
        <h1 class="break-words text-display">{trip.name}</h1>
        {#if caption}<p class="min-w-0 break-words text-muted-foreground">{caption}</p>{/if}
      </div>
      <RouteReplay {trip} {now} photos={found} onshow={(cluster) => void gallery?.showCluster(cluster)} />
      {#if noPhotos}<p class="-mt-3 text-sm text-muted-foreground" data-testid="no-photos">No photos yet</p>{/if}
      {@render controls()}
    {:else}
      <div class="relative h-[170px] overflow-hidden rounded-[22px] border border-border bg-surface-3" data-testid="trip-hero">
        {#if heroKind === "photos"}
          <div class="grid size-full grid-cols-[2fr_1fr] grid-rows-2 gap-0.5" aria-hidden="true">
            {#each heroIds as id, i (id)}
              <span class={`block overflow-hidden bg-surface-3 ${i === 0 ? "row-span-2" : ""}`}>
                {#if !lost.has(id)}<img class="size-full object-cover" src={thumbnailUrl(id)} alt="" decoding="async" draggable="false" onerror={() => (lost = new Set([...lost, id]))} />{/if}
              </span>
            {/each}
          </div>
        {/if}
        <span class="pointer-events-none absolute inset-y-0 left-0 right-[34%] bg-[linear-gradient(180deg,transparent_38%,color-mix(in_srgb,var(--lightbox)_84%,transparent)_100%)]" aria-hidden="true"></span>
        <div class="absolute bottom-4 left-[18px] right-[38%] flex flex-col gap-1 text-foreground">
          <h1 class="break-words text-2xl leading-[1.05] font-semibold tracking-tight">{trip.name}</h1>
          {#if caption}<span class="text-sm text-foreground/85">{caption}</span>{/if}
        </div>
      </div>
    {/if}

    {#if heroKind !== "map"}{@render controls()}{/if}

    <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2.5">
      <TripSummary tripId={trip.id} revision={`${loads}.${photoChanges}`} facts />
      <AvatarStack people={avatars} />
      {#if hasTotal || looks > 0 || (heroKind !== "map" && stopCount >= 2)}
        <div class="flex basis-full flex-wrap items-center gap-x-3.5 gap-y-2 text-sm text-muted-foreground">
          {#if hasTotal}
            <span data-trip-total>Total <b class="font-semibold text-foreground">{formatTotals(trip.costs.totals)}</b>{#if countNote(trip.costs)} · {countNote(trip.costs)}{/if}</span>
          {/if}
          {#if looks > 0}
            <a class="inline-flex w-fit items-center phone:min-h-11" href="#settings/photos"><span class="inline-flex items-center gap-1.5 rounded-full bg-status-warn-soft px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap text-status-warn-ink"><span class="size-1.5 rounded-full bg-current" aria-hidden="true"></span>{looksWords}</span></a>
          {/if}
          {#if heroKind !== "map" && stopCount >= 2}
            <Button variant="outline" size="sm" aria-label="Replay trip" aria-expanded={replaying} aria-controls="past-trip-replay" onclick={() => (replaying = !replaying)}><Play class="size-3.5" aria-hidden="true" /> Replay</Button>
          {/if}
        </div>
      {/if}
    </div>
    {#if trip.notes}<p class="whitespace-pre-line break-words text-sm">{trip.notes}</p>{/if}

    {#if heroKind !== "map"}
      <div id="past-trip-replay"><RouteReplay {trip} {now} photos={found} shown={replaying} onstops={(n) => (stopCount = n)} onshow={(cluster) => void gallery?.showCluster(cluster)} /></div>
    {/if}

    {#if onbookings && counts.total > 0}
      <div class="overflow-hidden rounded-[18px] border border-border bg-card">
        <button type="button" class="flex w-full cursor-pointer items-center gap-3 px-3.5 py-[11px] text-left hover:bg-surface-3 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none" aria-haspopup="dialog" aria-label={`Bookings · ${counts.total}, ${counts.words}`} onclick={onbookings}>
          <span class="flex items-center gap-1" aria-hidden="true">{#each counts.kinds as kind (kind)}<KindTile {kind} decorative size={34} />{/each}</span>
          <span class="flex min-w-0 flex-1 flex-col"><b class="truncate text-sm font-semibold">Bookings · {counts.total}</b><span class="text-caption text-muted-foreground">{counts.words}</span></span>
          <ChevronRight class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        </button>
      </div>
    {/if}
  {/if}

  <TripPhotos bind:this={gallery} onsharing={(next, done) => { acting = next; settled = done; }} onstatus={(next) => (status = next)} timeline {leftOut} onlook={(n) => (looks = n)} onloaded={(next) => (found = next)} onchanged={() => photoChanges++} {trip} {people} {now} />
</div>

{#snippet controls()}
  {#if controlRow}
    <div class="flex flex-wrap items-center gap-2">
      {#if viewDrawn}<Button variant="outline" size="sm" onclick={() => gallery?.viewFirst()}>View photos</Button>{/if}
      {#if hasControl}
        <TripPhotoSharingMenu {acting} tripName={trip.name} align="start" fallback={() => gallery?.headingElement()} />
      {:else if holdSlot}
        <span class="inline-block h-8 w-[84px] phone:h-11" aria-hidden="true" data-testid="sharing-slot"></span>
      {/if}
    </div>
  {/if}
  {#each acting as a (a.personId)}
    <TripPhotoSharing sharing={a} tripName={trip.name} part="reminder" />
  {/each}
{/snippet}
