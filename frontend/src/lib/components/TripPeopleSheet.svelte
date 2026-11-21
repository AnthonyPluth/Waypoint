<script lang="ts">
  import { actGet } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Person, Trip } from "$lib/api-types";
  import { avatarTone } from "$lib/avatar";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Input } from "$lib/components/ui/input";
  import { Sheet } from "$lib/components/ui/sheet";
  import { initials } from "$lib/nav";
  import { toast } from "svelte-sonner";

  let { open = $bindable(false), trip, people, me = null, onsaved, onguest }: {
    open?: boolean; trip: Trip; people: Person[]; me?: number | null; onsaved: (next: Trip) => void; onguest: (guest: Person) => void;
  } = $props();

  let busy = $state(false);
  let error = $state("");
  let guestName = $state("");
  let removing = $state<Person | null>(null);
  let removeOpen = $state(false);
  let adding = $state<{ tripId: number; ids: number[]; names: string[] } | null>(null);
  let shareOpen = $state(false);

  const named = (id: number) => people.find((p) => p.id === id);
  const aboard = $derived(trip.people.flatMap((id) => { const p = named(id); return p ? [p] : []; }));
  const others = $derived(people.filter((p) => !trip.people.includes(p.id)));
  const onFlight = (id: number) => trip.segments.some((s) => s.kind === "flight" && s.travelers.some((t) => t.person_id === id));

  $effect(() => {
    if (!open) { error = ""; guestName = ""; }
  });
  let seen = trip.id;
  $effect(() => {
    const id = trip.id;
    if (id === seen) return;
    seen = id;
    open = false; removeOpen = false; shareOpen = false; adding = null; removing = null;
  });

  type Refusal = { status?: number; data?: { see_trip?: unknown } };

  async function change(tripId: number, ids: number[], confirm = false): Promise<boolean> {
    const result = await actGet(async (): Promise<"saved" | "asked"> => {
      const body = { people: ids, ...(confirm ? { confirm: true } : {}) };
      try {
        const next = await apiCall<"POST /api/trips/{id}">(`/api/trips/${tripId}`, { method: "POST", body });
        if (trip.id === tripId) onsaved(next);
        return "saved";
      } catch (e) {
        const said = e as Refusal;
        if (said.status === 409 && Array.isArray(said.data?.see_trip)) {
          if (trip.id !== tripId) return "asked";
          adding = { tripId, ids, names: said.data.see_trip.map((p) => String((p as { name?: unknown }).name ?? "")).filter(Boolean) };
          shareOpen = true;
          return "asked";
        }
        throw e;
      }
    }, { busy: (on) => (busy = on), onError: (m) => (error = m) });
    if (result === "saved") error = "";
    return result === "saved";
  }

  const add = async (p: Person) => {
    if (await change(trip.id, [...trip.people, p.id])) toast.success(`${p.display_name} added`);
  };

  const confirmShare = async () => {
    const pending = adding;
    if (!pending) return true;
    if (await change(pending.tripId, pending.ids, true)) toast.success("Added");
    return true;
  };

  async function addGuest(e: SubmitEvent) {
    e.preventDefault();
    const display_name = guestName.trim();
    if (!display_name || busy) return;
    const tripId = trip.id;
    const before = trip.people;
    const created = await actGet(() => apiCall<"POST /api/people">("/api/people", { method: "POST", body: { display_name } }),
      { busy: (on) => (busy = on), onError: (m) => (error = m) });
    if (!created) return;
    onguest(created);
    if (trip.id !== tripId) return;
    guestName = "";
    if (await change(tripId, [...before, created.id])) toast.success(`${created.display_name} added`);
  }

  const askRemove = (p: Person) => { removing = p; removeOpen = true; };
  const remove = async () => {
    const p = removing;
    if (!p) return true;
    if (await change(trip.id, trip.people.filter((id) => id !== p.id))) toast.success(`${p.display_name} removed`);
    return true;
  };
</script>

<Sheet bind:open title="People on this trip" description="Everyone here sees the trip and all its bookings.">
  <div class="flex flex-col gap-6" data-trip-people>
    {#if error}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{error}</p>{/if}

    <section aria-labelledby="trip-people-on">
      <h3 id="trip-people-on" class="eyebrow">On this trip · {aboard.length}</h3>
      {#if aboard.length}
        <ul class="mt-1 divide-y divide-border">
          {#each aboard as p (p.id)}
            {@const flying = onFlight(p.id)}
            <li class="flex items-center gap-3 py-2.5" data-person={p.id}>
              <span class={`inline-flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${avatarTone({ id: p.id, name: p.display_name })}`} aria-hidden="true">{initials(p.display_name)}</span>
              <div class="min-w-0 flex-1">
                <p class="break-words font-medium">{p.display_name}{#if p.id === me}<span class="font-normal text-muted-foreground"> (you)</span>{/if}</p>
                {#if flying}<p id={`trip-people-flight-${p.id}`} class="text-caption text-muted-foreground">On a flight in this trip. Take them off the flight first.</p>{/if}
              </div>
              <Button variant="outline" size="sm" class="min-h-11 shrink-0 md:min-h-8" disabled={busy || flying} aria-label={`Remove ${p.display_name} from this trip`}
                aria-describedby={flying ? `trip-people-flight-${p.id}` : undefined} onclick={() => askRemove(p)}>Remove</Button>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="mt-1 text-sm text-muted-foreground">Nobody is on this trip yet.</p>
      {/if}
    </section>

    <section aria-labelledby="trip-people-add">
      <h3 id="trip-people-add" class="eyebrow">Add someone</h3>
      {#if others.length}
        <ul class="mt-1 divide-y divide-border">
          {#each others as p (p.id)}
            <li class="flex items-center gap-3 py-2.5" data-person={p.id}>
              <span class={`inline-flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${avatarTone({ id: p.id, name: p.display_name })}`} aria-hidden="true">{initials(p.display_name)}</span>
              <p class="min-w-0 flex-1 break-words font-medium">{p.display_name}{#if p.id === me}<span class="font-normal text-muted-foreground"> (you)</span>{/if}</p>
              <Button variant="outline" size="sm" class="min-h-11 shrink-0 md:min-h-8" disabled={busy} aria-label={`Add ${p.display_name} to this trip`} onclick={() => void add(p)}>Add</Button>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="mt-1 text-sm text-muted-foreground">Everyone in People is already on this trip.</p>
      {/if}
      <form class="mt-3 flex items-end gap-2" onsubmit={addGuest} aria-label="Add a guest">
        <div class="flex min-w-0 flex-1 flex-col gap-1.5">
          <label class="text-sm font-medium" for="trip-people-guest">Someone new</label>
          <Input id="trip-people-guest" bind:value={guestName} maxlength={100} autocomplete="off" placeholder="Name of a guest" />
        </div>
        <Button type="submit" variant="outline" class="min-h-11 shrink-0 md:min-h-9" disabled={busy || !guestName.trim()}>Add guest</Button>
      </form>
      <p class="mt-2 text-sm text-muted-foreground">A guest travels with the household but has no sign-in. They also appear in People.</p>
    </section>
  </div>
</Sheet>

<ConfirmDialog bind:open={removeOpen} title={removing ? `Remove ${removing.display_name} from this trip?` : "Remove from this trip?"} confirmLabel="Remove" busyLabel="Removing…" destructive
  onconfirm={remove}>
  {#snippet description()}
    <p>They come off the trip’s stays, rentals and parking, and stop seeing the trip unless they booked it or its confirmation came to their own mailbox.</p>
    {#if removing && removing.id === me}<p><strong class="text-foreground">That is you.</strong> You won’t see this trip any more unless you booked it or its confirmation came to your mailbox.</p>{/if}
  {/snippet}
</ConfirmDialog>

<ConfirmDialog bind:open={shareOpen} title="Share this trip with them?" confirmLabel="Share anyway" busyLabel="Adding…" onconfirm={confirmShare}>
  {#snippet description()}
    <p>Adding people changes who sees what: everyone on a trip sees the whole trip and all its bookings.</p>
    {#if adding?.names.length}<p><strong class="text-foreground">Will newly see this trip:</strong> {adding.names.join(", ")}</p>{/if}
  {/snippet}
</ConfirmDialog>
