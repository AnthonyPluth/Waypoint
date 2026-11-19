<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { AiSettings } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  let saved = $state<AiSettings | null>(null);
  let problem = $state("");
  let url = $state("");
  let model = $state("");
  let formError = $state("");
  let saving = $state(false);

  const adopt = (s: AiSettings) => { saved = s; url = s.ollama_url; model = s.ollama_model; };

  async function load() {
    try { adopt(await apiCall<"GET /api/ai">("/api/ai")); problem = ""; }
    catch (err) { problem = errMsg(err); }
  }
  onMount(load);

  async function save(e: SubmitEvent) {
    e.preventDefault();
    formError = "";
    const body = { ollama_url: url.trim(), ollama_model: model.trim() };
    await act(async () => {
      adopt(await apiCall<"POST /api/ai">("/api/ai", { method: "POST", body }));
      toast.success(body.ollama_url ? "AI settings saved" : "AI is off");
    }, { busy: (on) => (saving = on), onError: (m) => (formError = m) });
  }
</script>

<section aria-labelledby="ai-title" class="space-y-2">
  <h2 id="ai-title" class="eyebrow px-1">AI</h2>
  <p class="px-1 text-sm text-muted-foreground">Use AI to fill in what Waypoint couldn’t read in booking emails, and to suggest a trip’s destination.</p>
  <details class="px-1 text-sm text-muted-foreground"><summary class="cursor-pointer py-1">How email is shared</summary><p class="mt-2">Applies to all household mailboxes. AI is used exactly when an Ollama address is saved here; leave it empty to not use AI. Once one is saved, Waypoint sends the text of booking emails it couldn’t read fully to that Ollama server to fill the gaps. It goes to your own server and nowhere else. Complete bookings are added automatically; missing details stay in Review.</p></details>
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={load}>Try again</Button></div>
    {:else if !saved}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      <form class="row flex-col items-stretch gap-4" onsubmit={save} aria-labelledby="ai-title">
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Ollama address</span>
          <Input bind:value={url} maxlength={200} autocomplete="off" spellcheck={false} placeholder="http://ollama.local:11434" />
          <span class="text-muted-foreground">An Ollama server on your own network. Leave it empty to not use AI.</span></label>
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Model</span>
          <Input bind:value={model} maxlength={100} autocomplete="off" spellcheck={false} placeholder="llama3.1" /></label>
        <p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="note">Once an address is saved, Waypoint sends the text of booking emails it couldn’t read fully to that server to fill the gaps. It stays on your household’s own server.</p>
        {#if formError}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{formError}</p>{/if}
        <div class="flex flex-wrap gap-2">
          <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
        </div>
      </form>
    {/if}
  </div>
</section>
