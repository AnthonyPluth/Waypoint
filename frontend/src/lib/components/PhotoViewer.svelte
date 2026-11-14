<script lang="ts">
  import type { Person, Segment, TripPhoto } from "$lib/api-types";
  import { avatarTone } from "$lib/avatar";
  import { Button } from "$lib/components/ui/button";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { initials } from "$lib/nav";
  import { FAR_FROM_BOOKINGS, FROM_ITINERARY, fullName, isFar, isInferred, kilometres, originalUrl, placeOf, previewUrl, zoneCity } from "$lib/photos";
  import { clock, dayLabel, headline } from "$lib/trips";
  import { Dialog } from "bits-ui";
  import ChevronLeft from "@lucide/svelte/icons/chevron-left";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import ImageOff from "@lucide/svelte/icons/image-off";
  import MapPin from "@lucide/svelte/icons/map-pin";
  import Play from "@lucide/svelte/icons/play";
  import X from "@lucide/svelte/icons/x";
  import type { Snippet } from "svelte";

  type Props = {
    open?: boolean; index?: number; photos: TripPhoto[]; people: Person[]; segments: Map<number, Segment>;
    returnTo?: () => HTMLElement | null; actions?: Snippet<[TripPhoto]>;
    gone?: "next" | "previous" | null; notice?: string; onfail?: (photo: TripPhoto) => void;
  };
  let { open = $bindable(false), index = $bindable(0), photos, people, segments, returnTo, actions, gone = $bindable(null), notice = "", onfail }: Props = $props();

  const SWIPE = 50;
  const CLOSE_DISTANCE = 96;

  let closeButton = $state<HTMLElement | null>(null);
  let stage = $state<HTMLElement | null>(null);
  let playing = $state(false);
  let failed = $state(false);
  let attempt = $state(0);
  let start: { x: number; y: number } | null = null;

  const photo = $derived(photos[index] as TripPhoto | undefined);
  const segment = $derived(photo && photo.segment_id !== null ? segments.get(photo.segment_id) : undefined);
  const place = $derived(photo ? placeOf(photo, segment) : "");
  const owner = $derived(photo ? fullName(people, photo.person_id) : "");
  const word = $derived(photo?.kind === "video" ? "Video" : "Photo");
  const title = $derived(gone ? "Photo no longer shared" : failed ? `${word} can’t be loaded` : `${word} ${index + 1} of ${photos.length}`);
  const zoneWords = $derived(!photo?.zone ? "" : photo.zone.includes("/") ? `${zoneCity(photo.zone)} time` : photo.zone);

  $effect(() => {
    void photo?.id;
    void gone;
    void open;
    playing = false;
    failed = false;
  });

  export function focusStage() {
    stage?.focus();
  }

  function move(by: number) {
    if (gone) return;
    const next = index + by;
    if (next < 0 || next >= photos.length) return;
    index = next;
  }

  const onMedia = (target: EventTarget | null) => target instanceof Element && !!target.closest("video, audio, button, a");

  function keys(e: KeyboardEvent) {
    if (e.target instanceof HTMLMediaElement) return;
    if (e.key === "ArrowRight") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); move(-1); }
  }

  let last: { x: number; y: number } | null = null;
  function press(e: PointerEvent) {
    start = onMedia(e.target) ? null : { x: e.clientX, y: e.clientY };
    last = start;
  }
  function track(e: PointerEvent) { if (start) last = { x: e.clientX, y: e.clientY }; }
  function lift(e: PointerEvent) { settle({ x: e.clientX, y: e.clientY }); }
  function cancel() { settle(last); }
  function settle(end: { x: number; y: number } | null) {
    const from = start;
    start = null;
    last = null;
    if (!from || !end) return;
    const dx = end.x - from.x;
    const dy = end.y - from.y;
    if (Math.abs(dx) >= SWIPE && Math.abs(dx) > Math.abs(dy)) move(dx < 0 ? 1 : -1);
    else if (dy >= CLOSE_DISTANCE && dy > Math.abs(dx)) open = false;
  }

  function firstFocus(e: Event) {
    e.preventDefault();
    closeButton?.focus();
  }

  function giveFocusBack(e: Event) {
    e.preventDefault();
    returnTo?.()?.focus();
  }

  function lost() {
    failed = true;
    if (photo) onfail?.(photo);
  }

  function retry() {
    failed = false;
    playing = false;
    attempt++;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Content class="photo-viewer" onOpenAutoFocus={firstFocus} onCloseAutoFocus={giveFocusBack} onkeydown={keys} data-testid="photo-viewer">
      <Dialog.Title class="sr-only">{title}</Dialog.Title>
      <Dialog.Description class="sr-only">Use the arrow keys or swipe to move between photos.</Dialog.Description>
      <div class="photo-viewer-bar">
        <Dialog.Close>
          {#snippet child({ props })}
            <Button {...props} bind:ref={closeButton} variant="ghost" size="icon" aria-label="Close"><X /></Button>
          {/snippet}
        </Dialog.Close>
        {#if !failed && !gone}<p class="font-mono text-caption text-muted-foreground" aria-hidden="true">{index + 1} of {photos.length}</p>{/if}
        {#if gone}<span></span>{:else}
          <span class="flex gap-1 desktop:hidden">
            <Button variant="ghost" size="icon" aria-label="Previous photo" disabled={index === 0} onclick={() => move(-1)}><ChevronLeft /></Button>
            <Button variant="ghost" size="icon" aria-label="Next photo" disabled={index >= photos.length - 1} onclick={() => move(1)}><ChevronRight /></Button>
          </span>
        {/if}
      </div>
      {#if notice}<p class="sr-only" role="status">{notice}</p>{/if}
      {#if gone}
        <div class="photo-viewer-stage" role="presentation">
          <div class="flex flex-col items-center gap-2 px-6 text-center text-muted-foreground" role="status">
            <ImageOff class="size-8" aria-hidden="true" />
            <p class="text-heading text-foreground">This photo is no longer shared</p>
            <p class="text-caption">It isn’t shared with you any more.</p>
            <div class="mt-2 flex flex-wrap justify-center gap-2">
              <Button variant="outline" onclick={() => (gone = null)}>{gone === "next" ? "Next photo" : "Previous photo"}</Button>
              <Button variant="ghost" onclick={() => (open = false)}>Back to the trip</Button>
            </div>
          </div>
        </div>
      {:else if photo}
        <div class="photo-viewer-stage" bind:this={stage} tabindex="-1" onpointerdown={press} onpointermove={track} onpointerup={lift} onpointercancel={cancel} role="presentation">
          <Button class="photo-viewer-nav left-4" variant="outline" size="icon" aria-label="Previous photo" disabled={index === 0} onclick={() => move(-1)}><ChevronLeft /></Button>
          {#if failed}
            <div class="flex flex-col items-center gap-2 px-6 text-center text-muted-foreground" role="status">
              <ImageOff class="size-8" aria-hidden="true" />
              <p class="text-heading text-foreground">Can’t load this photo right now</p>
              <p class="text-caption">Try again in a moment.</p>
              <div class="mt-2 flex flex-wrap justify-center gap-2">
                <Button variant="outline" onclick={retry}>Retry</Button>
                {#if index < photos.length - 1}<Button variant="ghost" onclick={() => move(1)}>Next photo</Button>{/if}
                <Button variant="ghost" onclick={() => (open = false)}>Back to the trip</Button>
              </div>
            </div>
          {:else if playing}
            <video class="photo-viewer-media" src={originalUrl(photo.id)} controls autoplay playsinline onerror={lost}><track kind="captions" /></video>
          {:else}
            {#key `${photo.id}-${attempt}`}
              <img class="photo-viewer-media" src={previewUrl(photo.id)} alt={photo.kind === "video" ? "Video still" : "Photo"} draggable="false" onerror={lost} />
            {/key}
            {#if photo.kind === "video"}
              <button type="button" class="photo-viewer-play" aria-label="Play video" onclick={() => (playing = true)}><Play class="size-6 fill-current" /></button>
            {/if}
          {/if}
          <Button class="photo-viewer-nav right-4" variant="outline" size="icon" aria-label="Next photo" disabled={index >= photos.length - 1} onclick={() => move(1)}><ChevronRight /></Button>
        </div>
        {#if !failed}
          <div class="photo-viewer-info">
            <div>
              <p class="font-mono text-title"><time datetime={photo.taken_local}>{clock(photo.taken_local)}</time></p>
              <p class="text-caption text-muted-foreground">{[dayLabel(photo.taken_local, true), zoneWords, photo.kind === "video" ? "Video" : ""].filter(Boolean).join(" · ")}</p>
            </div>
            <div class="flex items-start gap-2.5 text-sm">
              <MapPin class="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div class="min-w-0">
                {#if isFar(photo)}
                  <p>{FAR_FROM_BOOKINGS}</p>
                  <p class="text-caption text-muted-foreground">From the photo’s location</p>
                {:else if isInferred(photo)}
                  <p class="flex flex-wrap items-center gap-1.5">{place}<StatusChip chip={{ tone: "quiet", label: FROM_ITINERARY }} small /></p>
                  <p class="text-caption text-muted-foreground">This {word.toLowerCase()} has no location.{#if segment}{" "}{segment.kind === "hotel" ? `You were staying at ${headline(segment)}${segment.destination ? `, ${segment.destination}` : ""}.` : `It was placed from ${headline(segment)}.`}{/if}</p>
                {:else}
                  <p>{place ? `Near ${place}` : "Where it was taken"}</p>
                  <p class="text-caption text-muted-foreground">From the photo’s location{#if segment && photo.distance_km !== null}{` · ${kilometres(photo.distance_km)} from ${headline(segment)}`}{/if}</p>
                {/if}
              </div>
            </div>
            {#if isFar(photo)}<StatusChip chip={{ tone: "warn", label: `Far: ${kilometres(photo.distance_km)} from every booking` }} />{/if}
            {#if owner}
              <div class="flex items-center gap-2.5 text-sm">
                <span class={`inline-flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${avatarTone({ id: photo.person_id, name: owner })}`} aria-hidden="true">{initials(owner)}</span>
                <p>From {owner}’s library</p>
              </div>
            {/if}
            <div class="flex flex-wrap gap-2">
              <Button class="phone:flex-1" variant="outline" href={originalUrl(photo.id)} target="_blank" rel="noopener noreferrer"><ExternalLink /> Open original</Button>
              {@render actions?.(photo)}
            </div>
          </div>
        {/if}
      {/if}
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
