<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { Home } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  let home = $state<Home | null>(null);
  let city = $state("");
  let region = $state("");
  let zip = $state("");
  let country = $state("");
  let problem = $state("");
  let refused = $state("");
  let saving = $state(false);

  const show = (found: Home) => { home = found; ({ city, state: region, zip, country } = found); };

  async function load() {
    problem = "";
    try { show(await apiCall<"GET /api/home">("/api/home")); }
    catch (err) { home = null; problem = errMsg(err); }
  }
  onMount(load);

  const save = (event: SubmitEvent) => {
    event.preventDefault();
    return act(async () => {
      refused = "";
      show(await apiCall<"POST /api/home">("/api/home", { method: "POST", body: { city, state: region, zip, country } }));
      toast.success("Saved");
    }, { busy: (on) => (saving = on), onError: (message) => (refused = message) });
  };

  const clear = () => act(async () => {
    refused = "";
    show(await apiCall<"DELETE /api/home">("/api/home", { method: "DELETE" }));
    toast.success("Home cleared");
  }, { busy: (on) => (saving = on), onError: (message) => (refused = message) });
</script>

<section aria-labelledby="home-title" class="space-y-2">
  <h2 id="home-title" class="eyebrow px-1">Home</h2>
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={load}>Try again</Button></div>
    {:else if home === null}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      <form class="row block space-y-3" onsubmit={save}>
        <p class="text-sm text-muted-foreground">Where a road trip’s route replay starts and ends. Only the city, state and ZIP are kept, never a street address, and they stay on this server.</p>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="space-y-1 text-sm"><span class="font-medium">City</span><Input bind:value={city} maxlength={80} autocomplete="off" aria-invalid={refused ? true : undefined} aria-describedby="home-problem" /></label>
          <label class="space-y-1 text-sm"><span class="font-medium">State or region</span><Input bind:value={region} maxlength={40} autocomplete="off" /></label>
          <label class="space-y-1 text-sm"><span class="font-medium">ZIP or postal code (optional)</span><Input bind:value={zip} maxlength={10} autocomplete="off" /></label>
          <label class="space-y-1 text-sm"><span class="font-medium">Country code</span><Input bind:value={country} maxlength={2} autocomplete="off" /></label>
        </div>
        <div id="home-problem" aria-live="polite">
          {#if refused}<p class="text-sm text-signal-ink" role="alert">{refused}</p>
          {:else if home.saved && !home.placed}<p class="text-sm text-signal-ink" role="status">Waypoint can’t place this on the map.</p>{/if}
        </div>
        <div class="flex gap-2">
          <Button type="submit" disabled={saving}>Save</Button>
          <Button type="button" variant="outline" disabled={saving || !home.saved} onclick={clear}>Clear</Button>
        </div>
      </form>
    {/if}
  </div>
</section>
