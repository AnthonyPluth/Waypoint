<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { app } from "$lib/app.svelte";
  import { apiCall } from "$lib/contract";
  import type { LoyaltyEntry, LoyaltyList, Person } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Input } from "$lib/components/ui/input";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash";
  import UserPlus from "@lucide/svelte/icons/user-plus";
  import { toast } from "svelte-sonner";

  let people = $state<Person[] | null>(null);
  let memberships = $state<LoyaltyEntry[]>([]);
  let programs = $state<LoyaltyList["programs"]>({});
  let conflicts = $state<LoyaltyList["conflicts"]>([]);
  let loadError = $state("");
  let revealed = $state<Record<number, string>>({});

  async function load() {
    loadError = "";
    try {
      const [p, l] = await Promise.all([apiCall<"GET /api/people">("/api/people"), apiCall<"GET /api/loyalty">("/api/loyalty")]);
      people = p.people; memberships = l.loyalty; programs = l.programs; conflicts = l.conflicts; revealed = {};
    } catch (err) { people = null; memberships = []; conflicts = []; loadError = errMsg(err); }
  }
  $effect(() => { void load(); });

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

  const linked = $derived((people?.find((x) => x.id === app.state?.person_id)?.links.length ?? 0) > 0);
  const canClaim = $derived(!!app.state?.user && !app.state.user.local && !linked);
  let claiming = $state<Person | null>(null);
  let claimAsking = $state(false);
  const claim = (p: Person) => act(async () => {
    await apiCall<"POST /api/people/{id}/claim">(`/api/people/${p.id}/claim`, { method: "POST" });
    toast.success(`Linked ${p.display_name} to you`);
    await load();
  });
  const doubled = (id: number) => conflicts.filter((c) => c.person_id === id).map((c) => c.program);

  const remove = (p: Person) => act(async () => {
    await apiCall<"DELETE /api/people/{id}">(`/api/people/${p.id}`, { method: "DELETE" });
    toast.success("Removed");
    await load();
  });

  const KINDS: [string, string][] = [["airline", "Airline"], ["hotel", "Hotel"], ["car", "Car rental"], ["known_traveler", "Known Traveler"], ["redress", "Redress"]];
  type IdDraft = { id: number | null; person_id: number; kind: string; program: string; number: string; expiry: string; notes: string; masked: string };
  let idDraft = $state<IdDraft | null>(null);
  let idError = $state("");
  let idSaving = $state(false);
  let idRemoving = $state<LoyaltyEntry | null>(null);
  let idAsking = $state(false);

  const choices = (personId: number, kind: string, editing: number | null = null): string[] => {
    const kept = editing === null ? null : memberships.find((m) => m.id === editing)?.program;
    const held = new Set(memberships.filter((m) => m.person_id === personId && m.kind === kind && m.id !== editing).map((m) => m.program));
    return (programs[kind] ?? []).filter((name) => name === "Other" || name === kept || !held.has(name));
  };
  const startAddId = (p: Person) => { idDraft = { id: null, person_id: p.id, kind: "airline", program: choices(p.id, "airline")[0] ?? "", number: "", expiry: "", notes: "", masked: "" }; idError = ""; };
  const startEditId = (m: LoyaltyEntry) => {
    idDraft = { id: m.id, person_id: m.person_id, kind: m.kind, program: m.program, number: "", expiry: m.expiry ?? "", notes: m.notes ?? "", masked: m.masked };
    idError = "";
  };
  const pickKind = (d: IdDraft) => { const open = choices(d.person_id, d.kind, d.id); if (!open.includes(d.program)) d.program = open[0] ?? ""; };

  async function saveId(e: SubmitEvent) {
    e.preventDefault();
    const d = idDraft;
    if (!d) return;
    const body = { person_id: d.person_id, kind: d.kind, program: d.program, number: d.number, expiry: EXPIRES.includes(d.kind) ? d.expiry : "", notes: d.notes };
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

  async function toggle(m: LoyaltyEntry) {
    if (revealed[m.id] !== undefined) { delete revealed[m.id]; return; }
    await act(async () => {
      const { number } = await apiCall<"POST /api/loyalty/{id}/reveal">(`/api/loyalty/${m.id}/reveal`, { method: "POST" });
      revealed[m.id] = number;
      try { await navigator.clipboard.writeText(number); toast.success("Copied"); }
      catch { toast("Couldn’t copy it: select the number instead."); }
    });
  }

  const EXPIRES = ["known_traveler", "redress"];
  const byKind = (id: number) => KINDS.map(([kind, name]) => ({ kind, name, items: memberships.filter((m) => m.person_id === id && m.kind === kind) })).filter((g) => g.items.length);
  const itemDetails = (m: LoyaltyEntry) => [m.expiry && `Expires ${m.expiry}`, m.notes].filter(Boolean).join(" · ");

  const selectClass = "border-input bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";

  const details = (p: Person) => [p.legal_name && `Legal name ${p.legal_name}`, p.aliases.length && `Printed as ${p.aliases.join(", ")}`].filter(Boolean).join(" · ");
</script>

<div class="mb-6 flex flex-wrap items-center justify-between gap-3">
  <h1 class="text-4xl font-bold tracking-tight">People</h1>
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
            class="border-input bg-secondary placeholder:text-muted-foreground w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm"></textarea>
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

{#snippet idForm(d: IdDraft)}
  <form class="mt-2 w-full rounded-2xl border bg-background/40 p-4" data-editor onsubmit={saveId} aria-labelledby="id-form-title">
    <div>
      <div class="flex w-full flex-col gap-4">
        <h2 id="id-form-title" class="font-medium">{d.id === null ? "Add a membership" : "Edit membership"} for {people?.find((p) => p.id === d.person_id)?.display_name ?? "this person"}</h2>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Kind</span>
          <select bind:value={d.kind} onchange={() => pickKind(d)} class={selectClass}>
            {#each KINDS as [key, name] (key)}<option value={key}>{name}</option>{/each}
          </select></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Program</span>
          <select bind:value={d.program} class={selectClass}>
            {#each choices(d.person_id, d.kind, d.id) as name (name)}<option value={name}>{name}</option>{/each}
          </select>
          {#if d.program === "Other"}<span class="text-muted-foreground">Say which program in the notes.</span>{/if}</label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Number</span>
          <Input bind:value={d.number} required={d.id === null} maxlength={64} autocomplete="off" spellcheck={false} placeholder={d.id === null ? "" : `Leave empty to keep ${d.masked}`} /></label>
        {#if EXPIRES.includes(d.kind)}
          <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Expiry</span>
            <Input type="date" bind:value={d.expiry} autocomplete="off" /></label>
        {/if}
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
{/snippet}

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
        <div class="min-w-0 basis-full">
          <div class="flex items-start justify-between gap-2">
            <p class="flex flex-wrap items-center gap-2 font-medium"><span class="break-words">{p.display_name}</span>
              <Badge variant={p.member ? "default" : "outline"}>{p.member ? "Member" : "Guest"}</Badge></p>
            <span class="-mt-1 -mr-2 flex shrink-0 gap-1">
              <Button variant="ghost" size="icon" class="size-8 text-muted-foreground phone:min-h-8 phone:min-w-8" aria-label={`Edit ${p.display_name}`} title="Edit" onclick={() => startEdit(p)}><Pencil class="size-4" /></Button>
            {#if !p.member}<Button variant="ghost" size="icon" class="size-8 text-muted-foreground phone:min-h-8 phone:min-w-8" aria-label={`Remove ${p.display_name}`} title="Remove" onclick={() => { removing = p; asking = true; }}><Trash class="size-4" /></Button>{/if}
            </span>
          </div>
          {#if details(p)}<p class="break-words text-sm text-muted-foreground">{details(p)}</p>{/if}
          {#each p.links as link (`${link.guest}-${link.on}`)}
            <p class="break-words text-sm text-muted-foreground">Linked from guest {link.guest} by {link.by} on {link.on}</p>
          {/each}
          {#each doubled(p.id) as program (program)}
            <p class="break-words text-sm text-signal-ink" role="status">Two numbers for {program}: both are kept. Remove the one that’s wrong.</p>
          {/each}
          {#each byKind(p.id) as group (group.kind)}
            <section class="mt-3" aria-label={`${p.display_name}’s ${group.name} memberships`}>
              <h3 class="text-xs font-medium uppercase tracking-wide text-muted-foreground">{group.name}</h3>
              <ul class="mt-1 flex flex-col gap-2">
                {#each group.items as m (m.id)}
                  <li class="flex items-start justify-between gap-x-3 text-sm">
                    <div class="min-w-0 flex-1">
                      <p class="break-words"><span class="font-medium">{m.program}</span>
                        {#if m.readable}
                          <button type="button" class="ml-2 rounded-md px-1.5 py-0.5 font-mono underline-offset-2 hover:underline focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none"
                            aria-label={revealed[m.id] !== undefined ? `Hide ${m.program} number` : `Show and copy ${m.program} number`} onclick={() => toggle(m)}>{revealed[m.id] ?? m.masked}</button>
                        {:else}
                          <span class="ml-2 text-muted-foreground">Can’t be read with this key: enter it again</span>
                        {/if}</p>
                      {#if itemDetails(m)}<p class="break-words text-muted-foreground">{itemDetails(m)}</p>{/if}
                    </div>
                    <div class="-mt-1 -mr-2 flex shrink-0 gap-1">
                      <Button variant="ghost" size="icon" class="size-8 text-muted-foreground phone:min-h-8 phone:min-w-8" aria-label={`Edit ${p.display_name}’s ${m.program}`} title="Edit" onclick={() => startEditId(m)}><Pencil class="size-4" /></Button>
                      <Button variant="ghost" size="icon" class="size-8 text-muted-foreground phone:min-h-8 phone:min-w-8" aria-label={`Remove ${p.display_name}’s ${m.program}`} title="Remove" onclick={() => { idRemoving = m; idAsking = true; }}><Trash class="size-4" /></Button>
                    </div>
                  </li>
                {/each}
              </ul>
            </section>
          {/each}
        </div>
        <div class="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" aria-label={`Add a membership for ${p.display_name}`} onclick={() => startAddId(p)}><Plus /> ID</Button>
          {#if !p.member && canClaim}<Button variant="outline" size="sm" aria-label={`This is me: ${p.display_name}`} onclick={() => { claiming = p; claimAsking = true; }}>This is me</Button>{/if}
        </div>
        {#if idDraft && idDraft.person_id === p.id}<div class="basis-full">{@render idForm(idDraft)}</div>{/if}
      </li>
    {/each}
  </ul>
{/if}

<ConfirmDialog bind:open={asking} title={`Remove ${removing?.display_name ?? ""}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="They’ll no longer appear in the household’s people, and their saved loyalty and Known Traveler numbers go with them. This can’t be undone."
  onconfirm={async () => { const p = removing; return p ? await remove(p) : true; }} />

<ConfirmDialog bind:open={claimAsking} title={`Link ${claiming?.display_name ?? "this guest"} to you?`} confirmLabel="This is me" busyLabel="Linking…"
  description="Their trips, loyalty and Known Traveler numbers and names become yours, and the guest is removed. This can’t be undone in Waypoint: restoring a backup is the way back."
  onconfirm={async () => { const p = claiming; return p ? await claim(p) : true; }} />

<ConfirmDialog bind:open={idAsking} title={`Remove ${idRemoving?.program ?? "this membership"}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="Its saved number is deleted. This can’t be undone."
  onconfirm={async () => { const m = idRemoving; return m ? await removeId(m) : true; }} />
