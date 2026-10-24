<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { AiSettings } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  type Mode = AiSettings["mode"];
  let saved = $state<AiSettings | null>(null);
  let problem = $state("");
  let mode = $state<Mode>("off");
  let url = $state("");
  let ollamaModel = $state("");
  let routerModel = $state("");
  let key = $state("");
  let auto = $state(false);
  let formError = $state("");
  let saving = $state(false);

  const adopt = (s: AiSettings) => { saved = s; mode = s.mode; url = s.ollama_url; ollamaModel = s.ollama_model; routerModel = s.openrouter_model; key = ""; auto = s.auto; };

  async function load() {
    try { adopt(await apiCall<"GET /api/ai">("/api/ai")); problem = ""; }
    catch (err) { problem = errMsg(err); }
  }
  onMount(load);

  const MODES: { value: Mode; name: string; hint: string }[] = [
    { value: "off", name: "Off", hint: "Email never goes to an AI, and nothing is sent for trip destinations." },
    { value: "local", name: "Local (Ollama)", hint: "An Ollama server on your own network reads email. It never leaves your network." },
    { value: "openrouter", name: "OpenRouter", hint: "Suggests a trip’s destination from its name and places, only with providers that keep nothing and don’t train on it. It never reads email." },
  ];

  async function save(e: SubmitEvent) {
    e.preventDefault();
    formError = "";
    const body = { mode, ollama_url: url, ollama_model: ollamaModel, openrouter_model: routerModel, auto: mode === "local" && auto, ...(key ? { openrouter_key: key } : {}) };
    await act(async () => {
      adopt(await apiCall<"POST /api/ai">("/api/ai", { method: "POST", body }));
      toast.success(mode === "off" ? "AI is off" : "AI settings saved");
    }, { busy: (on) => (saving = on), onError: (m) => (formError = m) });
  }

  const forgetKey = () => act(async () => {
    adopt(await apiCall<"POST /api/ai">("/api/ai", { method: "POST", body: { mode: mode === "openrouter" ? "off" : mode, openrouter_key: "" } }));
    toast.success("Key forgotten");
  }, { busy: (on) => (saving = on), onError: (m) => (formError = m) });
</script>

<section aria-labelledby="ai-title" class="space-y-2">
  <h2 id="ai-title" class="eyebrow px-1">AI</h2>
  <p class="px-1 text-sm text-muted-foreground">Use AI to extract bookings from emails Waypoint couldn’t read, and to suggest a trip’s destination.</p>
  <details class="px-1 text-sm text-muted-foreground"><summary class="cursor-pointer py-1">How email is shared</summary><p class="mt-2">Applies to all household mailboxes. Email is read with AI only in Local (Ollama) mode, and only when you choose Ask AI or enable automatic reading: the original text goes to your own Ollama server and nowhere else. OpenRouter never sees email; it is used only for trip destinations. Complete bookings are added automatically; missing details stay in Review.</p></details>
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={load}>Try again</Button></div>
    {:else if !saved}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      <form class="row flex-col items-stretch gap-4" onsubmit={save} aria-labelledby="ai-title">
        <fieldset class="space-y-2">
          <legend class="sr-only">How Waypoint uses AI</legend>
          {#each MODES as m (m.value)}
            <label class="flex items-start gap-3 text-sm">
              <input type="radio" name="ai-mode" value={m.value} bind:group={mode} class="mt-1" />
              <span><span class="font-medium">{m.name}</span><span class="block text-muted-foreground">{m.hint}</span></span>
            </label>
          {/each}
        </fieldset>
        {#if mode === "local"}
          <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Ollama address</span>
            <Input bind:value={url} maxlength={200} autocomplete="off" spellcheck={false} placeholder="http://ollama.local:11434" /></label>
          <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Model</span>
            <Input bind:value={ollamaModel} maxlength={100} autocomplete="off" spellcheck={false} placeholder="llama3.1" /></label>
        {:else if mode === "openrouter"}
          <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Model</span>
            <Input bind:value={routerModel} maxlength={100} autocomplete="off" spellcheck={false} placeholder="anthropic/claude-haiku-4.5" /></label>
          <div class="flex flex-col gap-1.5 text-sm"><span class="font-medium">OpenRouter key</span>
            {#if saved.key === "env"}
              <span class="text-muted-foreground">Taken from <code class="code rounded bg-muted px-1 normal-case tracking-normal">OPENROUTER_API_KEY</code> where Waypoint runs.</span>
            {:else}
              <Input type="password" aria-label="OpenRouter key" bind:value={key} maxlength={200} autocomplete="off" spellcheck={false}
                placeholder={saved.key === "saved" ? "Saved. Type a new one to replace it" : "sk-or-…"} />
              <span class="text-muted-foreground">Stored encrypted. It never shows again.</span>
            {/if}
          </div>
        {/if}
        {#if mode === "openrouter"}
          <p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="note">Reading email with AI needs Local (Ollama). OpenRouter is used only for trip destinations, so Ask AI and automatic reading are off while it is chosen.</p>
        {:else if mode === "local"}
          <div class="space-y-2">
            <label class="flex items-start gap-3 text-sm">
              <input type="checkbox" bind:checked={auto} class="mt-1" />
              <span><span class="font-medium">Read unreadable mail with AI automatically</span><span class="block text-muted-foreground">Off by default. “Ask AI” on a Review item works either way.</span></span>
            </label>
            {#if auto}
              <p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="note">Waypoint will send the text of travel emails it couldn’t read to the AI you chose, and of emails it did read when a booking is missing a detail, without asking each time.</p>
            {/if}
          </div>
        {/if}
        {#if formError}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{formError}</p>{/if}
        <div class="flex flex-wrap gap-2">
          <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
          {#if saved.key === "saved"}<Button type="button" variant="outline" disabled={saving} onclick={forgetKey}>Forget the saved key</Button>{/if}
        </div>
      </form>
    {/if}
  </div>
</section>
