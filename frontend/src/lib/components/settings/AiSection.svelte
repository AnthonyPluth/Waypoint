<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { AiSettings } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  // Settings → AI: off unless turned on. It reads only the mail Waypoint couldn’t, and what it makes of it is a suggestion
  // on the Review page that a person confirms or edits. The OpenRouter key is typed here once and never comes back: the
  // server only says whether one is saved (or comes from the environment).
  type Mode = AiSettings["mode"];
  let saved = $state<AiSettings | null>(null);
  let problem = $state("");
  let mode = $state<Mode>("off");
  let url = $state("");
  let ollamaModel = $state("");
  let routerModel = $state("");
  let key = $state("");
  let formError = $state("");
  let saving = $state(false);

  const adopt = (s: AiSettings) => { saved = s; mode = s.mode; url = s.ollama_url; ollamaModel = s.ollama_model; routerModel = s.openrouter_model; key = ""; };

  async function load() {
    try { adopt(await apiCall<"GET /api/ai">("/api/ai")); problem = ""; }
    catch (err) { problem = errMsg(err); }
  }
  onMount(load);

  const MODES: { value: Mode; name: string; hint: string }[] = [
    { value: "off", name: "Off", hint: "Email never goes to an AI." },
    { value: "local", name: "Local (Ollama)", hint: "An Ollama server on your own network reads it. Email never leaves your network." },
    { value: "openrouter", name: "OpenRouter", hint: "Sent to OpenRouter, only to providers that keep nothing and don’t train on it. If none can answer, nothing is sent." },
  ];

  async function save(e: SubmitEvent) {
    e.preventDefault();
    formError = "";
    const body = { mode, ollama_url: url, ollama_model: ollamaModel, openrouter_model: routerModel, ...(key ? { openrouter_key: key } : {}) };
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
  <p class="px-1 text-sm text-muted-foreground">Optional. When it’s on, Waypoint offers mail it couldn’t read (new items on the Review page’s “Couldn’t read” list, not ones already there) to an AI, which suggests the booking. You confirm or edit it; nothing is saved without you. Quoted replies, footers and anything that looks like a loyalty, Known Traveler or card number are removed first, and a booking Waypoint could read is never sent.</p>
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
        {#if formError}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{formError}</p>{/if}
        <div class="flex flex-wrap gap-2">
          <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
          {#if saved.key === "saved"}<Button type="button" variant="outline" disabled={saving} onclick={forgetKey}>Forget the saved key</Button>{/if}
        </div>
      </form>
    {/if}
  </div>
</section>
