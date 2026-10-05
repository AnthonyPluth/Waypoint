<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Person } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Input } from "$lib/components/ui/input";
  import UserPlus from "@lucide/svelte/icons/user-plus";
  import { toast } from "svelte-sonner";

  // Everyone who travels: members (they sign in; edit only) and guests (no login; any member adds, edits and removes them).
  // A failed load leaves nothing drawn that could pass for current, with a Try again.
  let people = $state<Person[] | null>(null);
  let loadError = $state("");

  async function load() {
    loadError = "";
    try { people = (await apiCall<"GET /api/people">("/api/people")).people; }
    catch (err) { people = null; loadError = errMsg(err); }
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
      <li class="row">
        <div class="min-w-0">
          <p class="flex flex-wrap items-center gap-2 font-medium"><span class="break-words">{p.display_name}</span>
            <Badge variant={p.member ? "default" : "outline"}>{p.member ? "Member" : "Guest"}</Badge></p>
          {#if details(p)}<p class="break-words text-sm text-muted-foreground">{details(p)}</p>{/if}
        </div>
        <div class="flex gap-2">
          <Button variant="outline" size="sm" aria-label={`Edit ${p.display_name}`} onclick={() => startEdit(p)}>Edit</Button>
          {#if !p.member}<Button variant="outline" size="sm" aria-label={`Remove ${p.display_name}`} onclick={() => { removing = p; asking = true; }}>Remove</Button>{/if}
        </div>
      </li>
    {/each}
  </ul>
{/if}

<ConfirmDialog bind:open={asking} title={`Remove ${removing?.display_name ?? ""}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  description="They’ll no longer appear in the household’s people. This can’t be undone."
  onconfirm={async () => { const p = removing; return p ? await remove(p) : true; }} />
