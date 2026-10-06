<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { LogoDevStatus } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  let st = $state<LogoDevStatus | null>(null);
  let problem = $state("");
  let token = $state("");
  let secret = $state("");
  let formError = $state("");
  let saving = $state(false);

  async function load() {
    try { st = await apiCall<"GET /api/logodev">("/api/logodev"); problem = ""; }
    catch (err) { st = null; problem = errMsg(err); }
  }
  onMount(load);

  const save = (body: { token?: string; secret?: string; clear?: boolean; clear_secret?: boolean }, done: string) => act(async () => {
    st = await apiCall<"POST /api/logodev">("/api/logodev", { method: "POST", body });
    token = ""; secret = ""; formError = "";
    toast.success(done);
  }, { busy: (on) => (saving = on), onError: (m) => (formError = m) });

  const saveToken = (e: SubmitEvent) => { e.preventDefault(); if (token.trim()) return save({ token }, "Key saved: fetching logos now. They fill in over the next few minutes."); };
  const saveSecret = (e: SubmitEvent) => { e.preventDefault(); if (secret.trim()) return save({ secret }, "Key saved: looking brands up with Brand Search."); };
  const fetchNow = () => act(async () => {
    await apiCall<"POST /api/logodev/fetch">("/api/logodev/fetch", { method: "POST" });
    toast.success("Fetching logos now. They fill in over the next few minutes.");
    setTimeout(load, 4000);
  }, { busy: (on) => (saving = on), onError: (m) => (formError = m) });
</script>

<section aria-labelledby="logos-title" class="space-y-2">
  <h2 id="logos-title" class="eyebrow px-1">Brand logos</h2>
  <p class="px-1 text-sm text-muted-foreground">Optional. Shows the logo of each booking’s airline, hotel, rental company or cruise line. Waypoint asks <a class="underline" href="https://www.logo.dev" target="_blank" rel="noopener">Logo.dev</a> for each logo once and keeps it, and a hotel’s own brand (Hyatt Place, Courtyard) from Wikidata and Wikimedia Commons, so your browser never contacts any of them. They are told the brand’s name (and Logo.dev your key), nothing else: no traveller, date or confirmation code, but they do learn which brands you book. Get a free publishable key (<code class="code rounded bg-muted px-1 normal-case tracking-normal">pk_…</code>) from Logo.dev.</p>
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={load}>Try again</Button></div>
    {:else if !st}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      <form class="row flex-col items-stretch gap-2" onsubmit={saveToken}>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Publishable key</span>
          <Input type="password" bind:value={token} maxlength={200} autocomplete="off" spellcheck={false} placeholder={st.configured ? "Saved. Type a new one to replace it" : "pk_…"} /></label>
        <div class="flex flex-wrap gap-2">
          <Button type="submit" disabled={saving || !token.trim()}>{saving ? "Saving…" : "Save"}</Button>
          {#if st.configured}<Button type="button" variant="outline" disabled={saving} onclick={() => save({ clear: true }, "Key forgotten")}>Forget the keys</Button>{/if}
        </div>
      </form>
      {#if st.configured}
        <form class="row flex-col items-stretch gap-2" onsubmit={saveSecret}>
          <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Secret key <span class="font-normal text-muted-foreground">(optional)</span></span>
            <Input type="password" bind:value={secret} maxlength={200} autocomplete="off" spellcheck={false} placeholder={st.searchable ? "Saved. Type a new one to replace it" : "sk_…"} />
            <span class="text-muted-foreground">Lets Waypoint use Brand Search to pick the right brand for a hotel’s name. Stored encrypted. It never shows again.</span></label>
          <div class="flex flex-wrap gap-2">
            <Button type="submit" variant="outline" disabled={saving || !secret.trim()}>Save</Button>
            {#if st.searchable}<Button type="button" variant="outline" disabled={saving} onclick={() => save({ clear_secret: true }, "Secret key forgotten")}>Forget the secret key</Button>{/if}
          </div>
        </form>
        <div class="row flex-col items-stretch gap-2" data-testid="logo-status">
          <p class="text-sm tabular-nums">
            <b class="font-medium">{st.with_logo}</b> {st.with_logo === 1 ? "brand has" : "brands have"} a logo
            {#if st.unknown} · {st.unknown} Logo.dev doesn’t know{/if}
            {#if st.waiting} · {st.waiting} waiting to be fetched{/if}
          </p>
          {#if st.last_error}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="status">The last lookup failed. {st.last_error}</p>{/if}
          {#if st.waiting}<div><Button type="button" variant="outline" size="sm" disabled={saving} onclick={fetchNow}>Fetch them now</Button></div>{/if}
        </div>
      {/if}
      {#if formError}<div class="row"><p class="w-full rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{formError}</p></div>{/if}
    {/if}
  </div>
</section>
