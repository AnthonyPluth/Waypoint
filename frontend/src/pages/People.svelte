<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { LoyaltyEntry, LoyaltyList, Person } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Input } from "$lib/components/ui/input";
  import Plus from "@lucide/svelte/icons/plus";
  import UserPlus from "@lucide/svelte/icons/user-plus";
  import { toast } from "svelte-sonner";

  // Everyone who travels: members (they sign in; edit only) and guests (no login; any member adds, edits and removes them).
  // A failed load leaves nothing drawn that could pass for current, with a Try again.
  let people = $state<Person[] | null>(null);
  let memberships = $state<LoyaltyEntry[]>([]);
  let programs = $state<LoyaltyList["programs"]>({});
  let loadError = $state("");
  // Numbers shown in the clear, by membership id: asked for one at a time, kept only on this page (never in browser storage).
  let revealed = $state<Record<number, string>>({});

  async function load() {
    loadError = "";
    try {
      const [p, l] = await Promise.all([apiCall<"GET /api/people">("/api/people"), apiCall<"GET /api/loyalty">("/api/loyalty")]);
      people = p.people; memberships = l.loyalty; programs = l.programs; revealed = {};
    } catch (err) { people = null; memberships = []; loadError = errMsg(err); }
  }
  $effect(() => { void load(); });

  // The form for adding a guest (id null) or editing someone.
  type Draft = { id: number | null; member: boolean; display_name: string; first_name: string; legal_name: string; aliases: string };
  let draft = $state<Draft | null>(null);
  let formError = $state("");
  let saving = $state(false);
  let removing = $state<Person | null>(null);
  let asking = $state(false);

  const startAdd = () => { draft = { id: null, member: false, display_name: "", first_name: "", legal_name: "", aliases: "" }; formError = ""; };
  const startEdit = (p: Person) => {
    draft = { id: p.id, member: p.member, display_name: p.display_name, first_name: p.first_name ?? "", legal_name: p.legal_name ?? "", aliases: p.aliases.join("\n") };
    formError = "";
  };

  async function save(e: SubmitEvent) {
    e.preventDefault();
    const d = draft;
    if (!d) return;
    const body = { display_name: d.display_name, first_name: d.first_name, legal_name: d.legal_name, aliases: d.aliases.split("\n") };
    const ok = await act(async () => {
      if (d.id === null) await apiCall<"POST /api/people">("/api/people", { method: "POST", body });
      else await apiCall<"POST /api/people/{id}">(`/api/people/${d.id}`, { method: "POST", body });
    }, { busy: (on) => (saving = on), onError: (m) => (formError = m) });
    if (!ok) return;
    draft = null;
    toast.success(d.id === null ? "Guest added" : "Saved");
    await load();
  }

  const remove = (p: Person) => act(async () => {
    await apiCall<"DELETE /api/people/{id}">(`/api/people/${p.id}`, { method: "DELETE" });
    toast.success("Removed");
    await load();
  });

  // Memberships: the form to add one for a person (id null) or change one.
  const KINDS: [string, string][] = [["airline", "Airline"], ["hotel", "Hotel"], ["car", "Car rental"], ["known_traveler", "Known Traveler"], ["redress", "Redress"]];
  type IdDraft = { id: number | null; person_id: number; kind: string; program: string; number: string; tier: string; expiry: string; notes: string; masked: string };
  let idDraft = $state<IdDraft | null>(null);
  let idError = $state("");
  let idSaving = $state(false);
  let idRemoving = $state<LoyaltyEntry | null>(null);
  let idAsking = $state(false);

  const startAddId = (p: Person) => { idDraft = { id: null, person_id: p.id, kind: "airline", program: programs.airline?.[0] ?? "", number: "", tier: "", expiry: "", notes: "", masked: "" }; idError = ""; };
  const startEditId = (m: LoyaltyEntry) => {
    idDraft = { id: m.id, person_id: m.person_id, kind: m.kind, program: m.program, number: "", tier: m.tier ?? "", expiry: m.expiry ?? "", notes: m.notes ?? "", masked: m.masked };
    idError = "";
  };
  const pickKind = (d: IdDraft) => { if (!(programs[d.kind] ?? []).includes(d.program)) d.program = programs[d.kind]?.[0] ?? ""; };

  async function saveId(e: SubmitEvent) {
    e.preventDefault();
    const d = idDraft;
    if (!d) return;
    // A number left blank while changing a membership keeps the one saved.
    const body = { person_id: d.person_id, kind: d.kind, program: d.program, number: d.number, tier: d.tier, expiry: d.expiry, notes: d.notes };
    const ok = await act(async () => {
      if (d.id === null) await apiCall<"POST /api/loyalty">("/api/loyalty", { method: "POST", body });
      else await apiCall<"POST /api/loyalty/{id}">(`/api/loyalty/${d.id}`, { method: "POST", body });
    }, { busy: (on) => (idSaving = on), onError: (m) => (idError = m) });
    if (!ok) return;
    idDraft = null;
    toast.success(d.id === null ? "Membership added" : "Saved");
    await load();
  }

  const removeId = (m: LoyaltyEntry) => act(async () => {
    await apiCall<"DELETE /api/loyalty/{id}">(`/api/loyalty/${m.id}`, { method: "DELETE" });
    toast.success("Removed");
    await load();
  });

  // Tapping a masked number asks the server for that one number, shows it and copies it; tapping it again hides it.
  async function toggle(m: LoyaltyEntry) {
    if (revealed[m.id] !== undefined) { delete revealed[m.id]; return; }
    await act(async () => {
      const { number } = await apiCall<"POST /api/loyalty/{id}/reveal">(`/api/loyalty/${m.id}/reveal`, { method: "POST" });
      revealed[m.id] = number;
      try { await navigator.clipboard.writeText(number); toast.success("Copied"); }
      catch { toast("Couldn’t copy it: select the number instead."); }   // no clipboard (an insecure page, a refused permission)
    });
  }

  const byKind = (id: number) => KINDS.map(([kind, name]) => ({ kind, name, items: memberships.filter((m) => m.person_id === id && m.kind === kind) })).filter((g) => g.items.length);
  const itemDetails = (m: LoyaltyEntry) => [m.tier, m.expiry && `Expires ${m.expiry}`, m.notes].filter(Boolean).join(" · ");

  const selectClass = "border-input bg-background dark:bg-input/40 w-full rounded-lg border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";

  const details = (p: Person) => [p.legal_name && `Legal name ${p.legal_name}`, p.aliases.length && `Printed as ${p.aliases.join(", ")}`].filter(Boolean).join(" · ");
</script>

<div class="mb-6 flex flex-wrap items-center justify-between gap-3">
  <h1 class="text-3xl font-semibold tracking-tight">People</h1>
  {#if people && !draft}<Button onclick={startAdd}><UserPlus /> Add a guest</Button>{/if}
</div>

{#if draft}
  <form class="rows mb-6" data-editor onsubmit={save} aria-labelledby="person-form-title">
    <div class="row items-stretch">
      <div class="flex w-full flex-col gap-4">
        <h2 id="person-form-title" class="font-medium">{draft.id === null ? "Add a guest" : `Edit ${draft.display_name || "person"}`}</h2>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Name</span>
          <Input bind:value={draft.display_name} required maxlength={100} autocomplete="off" placeholder="How Waypoint shows them" /></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">First name</span>
          <Input bind:value={draft.first_name} maxlength={100} autocomplete="off" /></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Legal name</span>
          <Input bind:value={draft.legal_name} maxlength={200} autocomplete="off" />
          <span class="text-muted-foreground">As on their ID, for matching bookings.</span></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Name aliases</span>
          <textarea bind:value={draft.aliases} rows="3" autocomplete="off" spellcheck="false" placeholder={"DOE/JANE MS"}
            class="border-input bg-background dark:bg-input/40 placeholder:text-muted-foreground w-full rounded-lg border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm"></textarea>
          <span class="text-muted-foreground">How airlines print the name, one per line.</span></label>
        {#if draft.member}<p class="text-sm text-muted-foreground">They’re a household member: their link to their sign-in stays as it is.</p>{/if}
        {#if formError}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{formError}</p>{/if}
        <div class="flex flex-wrap gap-2">
          <Button type="submit" disabled={saving}>{saving ? "Saving…" : draft.id === null ? "Add guest" : "Save"}</Button>
          <Button type="button" variant="outline" disabled={saving} onclick={() => (draft = null)}>Cancel</Button>
        </div>
      </div>
    </div>
  </form>
{/if}

{#if idDraft}
  {@const d = idDraft}
  <form class="rows mb-6" data-editor onsubmit={saveId} aria-labelledby="id-form-title">
    <div class="row items-stretch">
      <div class="flex w-full flex-col gap-4">
        <h2 id="id-form-title" class="font-medium">{d.id === null ? "Add a membership" : "Edit membership"} for {people?.find((p) => p.id === d.person_id)?.display_name ?? "this person"}</h2>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Kind</span>
          <select bind:value={d.kind} onchange={() => pickKind(d)} class={selectClass}>
            {#each KINDS as [key, name] (key)}<option value={key}>{name}</option>{/each}
          </select></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Program</span>
          <select bind:value={d.program} class={selectClass}>
            {#each programs[d.kind] ?? [] as name (name)}<option value={name}>{name}</option>{/each}
          </select>
          {#if d.program === "Other"}<span class="text-muted-foreground">Say which program in the notes.</span>{/if}</label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Number</span>
          <Input bind:value={d.number} required={d.id === null} maxlength={64} autocomplete="off" spellcheck={false} placeholder={d.id === null ? "" : `Leave empty to keep ${d.masked}`} /></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Tier</span>
          <Input bind:value={d.tier} maxlength={100} autocomplete="off" placeholder="Gold" /></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Expiry</span>
          <Input type="date" bind:value={d.expiry} autocomplete="off" /></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Notes</span>
          <Input bind:value={d.notes} maxlength={500} autocomplete="off" /></label>
        {#if idError}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{idError}</p>{/if}
        <div class="flex flex-wrap gap-2">
          <Button type="submit" disabled={idSaving}>{idSaving ? "Saving…" : d.id === null ? "Add" : "Save"}</Button>
          <Button type="button" variant="outline" disabled={idSaving} onclick={() => (idDraft = null)}>Cancel</Button>
        </div>
      </div>
    </div>
  </form>
{/if}

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if people === null}
  <div class="h-40 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading"></div>
{:else if people.length === 0}
  <p class="text-muted-foreground">Nobody yet. Household members appear here when they sign in; add a guest for someone who travels with you but has no login.</p>
{:else}
  <ul class="rows" aria-label="People">
    {#each people as p (p.id)}
      <li class="row items-start">
        <div class="min-w-0 basis-full sm:basis-0 sm:flex-1">
          <p class="flex flex-wrap items-center gap-2 font-medium"><span class="break-words">{p.display_name}</span>
            <Badge variant={p.member ? "default" : "outline"}>{p.member ? "Member" : "Guest"}</Badge></p>
          {#if details(p)}<p class="break-words text-sm text-muted-foreground">{details(p)}</p>{/if}
          {#each byKind(p.id) as group (group.kind)}
            <section class="mt-3" aria-label={`${p.display_name}’s ${group.name} memberships`}>
              <h3 class="text-xs font-medium uppercase tracking-wide text-muted-foreground">{group.name}</h3>
              <ul class="mt-1 flex flex-col gap-2">
                {#each group.items as m (m.id)}
                  <li class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
                    <div class="min-w-0">
                      <p class="break-words"><span class="font-medium">{m.program}</span>
                        {#if m.readable}
                          <button type="button" class="ml-2 rounded-md px-1.5 py-0.5 font-mono underline-offset-2 hover:underline focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none"
                            aria-label={revealed[m.id] !== undefined ? `Hide ${m.program} number` : `Show and copy ${m.program} number`} onclick={() => toggle(m)}>{revealed[m.id] ?? m.masked}</button>
                        {:else}
                          <span class="ml-2 text-muted-foreground">Can’t be read with this key: enter it again</span>
                        {/if}</p>
                      {#if itemDetails(m)}<p class="break-words text-muted-foreground">{itemDetails(m)}</p>{/if}
                    </div>
                    <div class="flex gap-2">
                      <Button variant="outline" size="sm" aria-label={`Edit ${p.display_name}’s ${m.program}`} onclick={() => startEditId(m)}>Edit</Button>
                      <Button variant="outline" size="sm" aria-label={`Remove ${p.display_name}’s ${m.program}`} onclick={() => { idRemoving = m; idAsking = true; }}>Remove</Button>
                    </div>
                  </li>
                {/each}
              </ul>
            </section>
          {/each}
        </div>
        <div class="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" aria-label={`Add a membership for ${p.display_name}`} onclick={() => startAddId(p)}><Plus /> ID</Button>
          <Button variant="outline" size="sm" aria-label={`Edit ${p.display_name}`} onclick={() => startEdit(p)}>Edit</Button>
          {#if !p.member}<Button variant="outline" size="sm" aria-label={`Remove ${p.display_name}`} onclick={() => { removing = p; asking = true; }}>Remove</Button>{/if}
        </div>
      </li>
    {/each}
  </ul>
{/if}

<ConfirmDialog bind:open={asking} title={`Remove ${removing?.display_name ?? ""}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="They’ll no longer appear in the household’s people, and their saved loyalty and Known Traveler numbers go with them. This can’t be undone."
  onconfirm={async () => { const p = removing; return p ? await remove(p) : true; }} />

<ConfirmDialog bind:open={idAsking} title={`Remove ${idRemoving?.program ?? "this membership"}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="Its saved number is deleted. This can’t be undone."
  onconfirm={async () => { const m = idRemoving; return m ? await removeId(m) : true; }} />
