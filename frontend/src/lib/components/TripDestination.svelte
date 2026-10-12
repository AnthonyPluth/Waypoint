<script lang="ts">
  import { act } from "$lib/act";
  import { app } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { Trip } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import { toast } from "svelte-sonner";

  let { trip, dates, onsaved }: { trip: Trip; dates: string; onsaved: (next: Trip) => void } = $props();

  let editing = $state(false);
  let value = $state("");
  let saving = $state(false);
  let suggesting = $state(false);
  let error = $state("");

  const typed = $derived(value.trim());
  const helper = $derived(typed
    ? "You set this, so Waypoint won’t change it when you add, move, merge or remove bookings. Clear it to let Waypoint choose again."
    : "Waypoint picks this from the places of your bookings and updates it whenever they change. Type your own to keep it as written.");

  const open = () => { value = trip.destination_manual ? (trip.destination ?? "") : ""; error = ""; editing = true; };
  const close = () => { editing = false; error = ""; };

  const save = (e: SubmitEvent) => {
    e.preventDefault();
    return act(async () => {
      const next = await apiCall<"POST /api/trips/{id}">(`/api/trips/${trip.id}`, { method: "POST", body: { destination: typed || null } });
      close();
      toast.success("Saved");
      onsaved(next);
    }, { busy: (on) => (saving = on), onError: (m) => (error = m) });
  };

  const suggest = () => act(async () => {
    value = (await apiCall<"POST /api/trips/{id}/destination/suggest">(`/api/trips/${trip.id}/destination/suggest`, { method: "POST" })).suggestion;
    error = "";
  }, { busy: (on) => (suggesting = on) });
</script>

{#if !editing}
  <div class="flex flex-wrap items-center gap-1">
    <p class="min-w-0 break-words text-muted-foreground">{dates}{trip.destination ? ` · ${trip.destination}` : ""}</p>
    <Button variant="ghost" size="icon" class="shrink-0" aria-label="Edit destination" onclick={open}><Pencil /></Button>
  </div>
{:else}
  <p class="text-muted-foreground">{dates}</p>
  <form class="mt-2 flex max-w-xl flex-col gap-2" onsubmit={save} aria-label="Edit destination">
    <label class="text-sm font-medium" for="trip-destination">Destination</label>
    <div class="flex items-center gap-2">
      <Input id="trip-destination" class="min-w-0 flex-1" bind:value maxlength={100} autocomplete="off" autofocus
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
    {#if error}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{error}</p>{/if}
    <div class="flex gap-2">
      <Button type="submit" disabled={saving || suggesting}>{saving ? "Saving…" : "Save"}</Button>
      <Button type="button" variant="outline" disabled={saving} onclick={close}>Cancel</Button>
    </div>
  </form>
{/if}
