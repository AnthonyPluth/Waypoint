<script lang="ts">
  import { act } from "$lib/act";
  import { app } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { Trip } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { DiscardDialog } from "$lib/components/ui/discard-dialog";
  import { Input } from "$lib/components/ui/input";
  import { draftGuard, leave } from "$lib/drafts.svelte";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import { tick } from "svelte";
  import { toast } from "svelte-sonner";

  let { trip, dates, onsaved, editing = $bindable(false) }: { trip: Trip; dates: string; onsaved: (next: Trip) => void; editing?: boolean } = $props();

  let name = $state("");
  let destination = $state("");
  let notes = $state("");
  let hasNotes = $state(false);
  let saving = $state(false);
  let suggesting = $state(false);
  let error = $state("");
  let pencil = $state<HTMLButtonElement | null>(null);
  let nameField = $state<HTMLInputElement | null>(null);
  let formEl = $state<HTMLFormElement | null>(null);

  const typed = $derived(destination.trim());
  const helper = $derived(typed
    ? "You set this, so Waypoint won’t change it when you add, move, merge or remove bookings. Clear it to let Waypoint choose again."
    : "Waypoint picks this from the places of your bookings and updates it whenever they change. Type your own to keep it as written.");

  const savedDestination = () => (trip.destination_manual ? (trip.destination ?? "") : "");
  const changed = () => name.trim() !== trip.name || typed !== savedDestination() || (hasNotes && notes !== (trip.notes ?? ""));

  const close = () => { editing = false; error = ""; };
  const back = async () => { close(); await tick(); pencil?.focus(); };
  const guard = draftGuard({ dirty: () => editing && changed(), saving: () => saving, discard: back });
  const cancel = () => leave(back, [guard]);
  $effect(() => {
    const form = formEl;
    if (!form) return;
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); cancel(); } };
    form.addEventListener("keydown", escape);
    return () => form.removeEventListener("keydown", escape);
  });

  async function open() {
    name = trip.name;
    destination = savedDestination();
    hasNotes = !!trip.notes;
    notes = trip.notes ?? "";
    error = "";
    editing = true;
    await tick();
    nameField?.focus();
  }

  const save = (e: SubmitEvent) => {
    e.preventDefault();
    const nextName = name.trim();
    if (!nextName) { error = "Enter a name for the trip"; return; }
    const body: { name?: string; destination?: string | null; notes?: string } = {};
    if (nextName !== trip.name) body.name = nextName;
    if (typed !== savedDestination()) body.destination = typed || null;
    if (hasNotes && notes !== (trip.notes ?? "")) body.notes = notes;
    if (!Object.keys(body).length) { void back(); return; }
    return act(async () => {
      const next = await apiCall<"POST /api/trips/{id}">(`/api/trips/${trip.id}`, { method: "POST", body });
      close();
      toast.success("Saved");
      onsaved(next);
      await tick();
      pencil?.focus();
    }, { busy: (on) => (saving = on), onError: (m) => (error = m) });
  };

  const suggest = () => act(async () => {
    destination = (await apiCall<"POST /api/trips/{id}/destination/suggest">(`/api/trips/${trip.id}/destination/suggest`, { method: "POST", body: { name: name.trim() } })).suggestion;
    error = "";
  }, { busy: (on) => (suggesting = on) });
</script>

{#if !editing}
  <div class="flex items-start gap-2">
    <h1 class="break-words text-display">{trip.name}</h1>
    <Button bind:ref={pencil} variant="ghost" size="icon" class="mt-1 shrink-0" aria-label="Edit trip details" onclick={open}><Pencil /></Button>
  </div>
  <p class="min-w-0 break-words text-muted-foreground">{dates}{trip.destination ? ` · ${trip.destination}` : ""}</p>
{:else}
  <form class="mt-1 flex max-w-xl flex-col gap-4" onsubmit={save} aria-label="Edit trip details" bind:this={formEl}>
    <div class="flex flex-col gap-1.5">
      <label class="text-sm font-medium" for="trip-name">Name</label>
      <Input id="trip-name" bind:ref={nameField} bind:value={name} maxlength={100} autocomplete="off" />
    </div>
    <div class="flex flex-col gap-1.5">
      <label class="text-sm font-medium" for="trip-destination">Destination</label>
      <div class="flex items-center gap-2">
        <Input id="trip-destination" class="min-w-0 flex-1" bind:value={destination} maxlength={100} autocomplete="off"
          placeholder={(!trip.destination_manual && trip.destination) || "Chosen from your bookings"} aria-describedby="trip-destination-help" />
        {#if app.state?.ai}
          <Button type="button" variant="outline" size="icon" class="shrink-0" aria-label="Suggest a destination with AI" title="Suggest a destination with AI"
            disabled={suggesting || saving} aria-busy={suggesting} onclick={suggest}><Sparkles class={suggesting ? "animate-pulse motion-reduce:animate-none" : ""} /></Button>
        {/if}
      </div>
      <p id="trip-destination-help" class="text-sm text-muted-foreground">{helper}</p>
      {#if app.state?.ai}
        <p class="text-sm text-muted-foreground">The sparkle button sends only the trip’s name and the places of its bookings to your AI service, never dates, names, codes or emails. Nothing is saved until you press Save.</p>
      {/if}
    </div>
    {#if hasNotes}
      <div class="flex flex-col gap-1.5">
        <label class="text-sm font-medium" for="trip-notes">Notes</label>
        <textarea id="trip-notes" rows="3" maxlength={4000} bind:value={notes} autocomplete="off"
          class="border-input bg-secondary placeholder:text-muted-foreground w-full min-w-0 rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm"></textarea>
      </div>
    {/if}
    <p class="text-sm"><span class="eyebrow">Dates</span> <span class="font-medium">{dates}</span>
      <span class="text-muted-foreground"> · set by its bookings, so they can’t be changed here</span></p>
    {#if error}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{error}</p>{/if}
    <div class="flex gap-2">
      <Button type="submit" disabled={saving || suggesting}>{saving ? "Saving…" : "Save"}</Button>
      <Button type="button" variant="outline" disabled={saving} onclick={cancel}>Cancel</Button>
    </div>
  </form>
{/if}

<DiscardDialog {guard} returnFocus={() => pencil} />
