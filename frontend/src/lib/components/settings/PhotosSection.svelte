<script lang="ts" module>
  import type { Chip } from "$lib/status";
  import type { PhotoSource } from "$lib/api-types";

  export const REFUSED_SAID = "Immich didn’t accept this key. Check that you copied all of it, or make a new key in Immich under Account settings › API keys.";
  export const UNREACHABLE_SAID = "Waypoint couldn’t connect to the address. Check the address and port, and that the server is on and reachable from Waypoint, then Test again.";
  export const ALREADY_SAID = "This library is already connected.";
  export const KEY_LOST = "Waypoint can’t unlock this library’s key any more; enter it again.";
  const IMMICH_REFUSED = ["Immich didn’t accept", "This Immich library isn’t set up"];
  const UNREACHABLE_STATUS = [502, 504];

  export type Outcome = { field?: "url" | "key"; chip?: Chip; text: string };

  export function outcome(err: unknown, message: string): Outcome {
    const status = (err as { status?: unknown } | null)?.status;
    if (typeof status === "number" && UNREACHABLE_STATUS.includes(status)) return { chip: { label: "Can’t reach Immich", tone: "warn" }, text: UNREACHABLE_SAID };
    if (message.startsWith("That library is already connected")) return { text: ALREADY_SAID };
    if (IMMICH_REFUSED.some((start) => message.startsWith(start))) return { chip: { label: "Key refused", tone: "bad" }, text: REFUSED_SAID };
    if (status === 400 && (message.includes("Immich address") || message.startsWith("Use https://"))) return { field: "url", text: message };
    if (status === 400 && message.includes("API key")) return { field: "key", text: message };
    if (message.startsWith("That key belongs")) return { chip: { label: "Key refused", tone: "bad" }, text: message };
    return { text: message };
  }

  export function sourceChip(s: PhotoSource, syncing: boolean): Chip {
    if (!s.mine) return { label: "Connected", tone: "quiet" };
    if (syncing) return { label: "Syncing", tone: "info" };
    if (s.status === "off") return { label: "Paused", tone: "quiet" };
    if (s.status === "ok" && s.last_error) return { label: "Not up to date", tone: "warn" };
    if (s.status === "refused") return { label: s.last_error === KEY_LOST ? "Key lost" : "Key refused", tone: "bad" };
    if (s.status === "unreachable") return { label: "Can’t reach Immich", tone: "warn" };
    return s.last_sync ? { label: "Up to date", tone: "ok" } : { label: "Not synced yet", tone: "quiet" };
  }

  export const host = (url: string): string => {
    try { return new URL(url).host || url; } catch { return url; }
  };
</script>

<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { Person, PhotoSources } from "$lib/api-types";
  import { app } from "$lib/app.svelte";
  import { avatarTone } from "$lib/avatar";
  import StatusChip from "$lib/components/StatusChip.svelte";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { Input } from "$lib/components/ui/input";
  import { apiCall } from "$lib/contract";
  import { draftGuard } from "$lib/drafts.svelte";
  import { initials } from "$lib/nav";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import { toast } from "svelte-sonner";
  import { onDestroy, onMount, tick } from "svelte";

  let list = $state<PhotoSources | null>(null);
  let people = $state<Person[]>([]);
  let problem = $state("");
  let off = $state(false);

  const me = $derived(app.state?.person_id ?? null);
  const personOf = (id: number) => people.find((p) => p.id === id);
  const nameOf = (id: number) => personOf(id)?.display_name ?? "Someone";
  const libraryOf = (s: PhotoSource) => `${nameOf(s.person_id)}’s library`;

  async function load() {
    try {
      const [found, everyone] = await Promise.all([
        apiCall<"GET /api/photo-sources">("/api/photo-sources"),
        people.length ? Promise.resolve({ people }) : apiCall<"GET /api/people">("/api/people"),
      ]);
      list = found; people = everyone.people; problem = ""; off = false;
    } catch (err) {
      problem = errMsg(err);
      off = (err as { status?: unknown } | null)?.status === 404;
    }
  }
  onMount(load);

  const plural = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
  const synced = (stamp: string) => new Date(stamp).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

  type Line = { text: string; problem?: boolean };

  function about(s: PhotoSource): Line[] {
    const person = personOf(s.person_id);
    if (!s.mine) return [{ text: `${person?.member ? person.display_name : "Another member"} manages this library and what it shares.` }];
    const lines: Line[] = [];
    if (s.person_id !== me && person && !person.member) lines.push({ text: `You manage this library because ${person.display_name} doesn’t sign in.` });
    if (s.status === "refused" && s.last_error === KEY_LOST) lines.push({ text: `${KEY_LOST} Photos already on trips stay; nothing new syncs until you change the key.`, problem: true });
    else if (s.status === "refused") lines.push({ text: "Immich turned the key down. It may have been deleted or lost a permission. Photos already on trips stay; nothing new syncs until you change the key.", problem: true });
    else if (s.status === "unreachable") lines.push({ text: "Waypoint couldn’t reach Immich. It tries again at the next sync.", problem: true });
    else if (s.status === "off") lines.push({ text: "Paused. Nothing new syncs until you resume it." });
    if ((s.status === "ok" || s.status === "off") && s.last_error) lines.push({ text: s.last_error, problem: true });
    if (s.status !== "refused") {
      const count = s.photos != null ? `${plural(s.photos, "photo", "photos")} on ${plural(s.trips ?? 0, "trip", "trips")}` : "";
      if (s.last_sync) lines.push({ text: [`Last synced ${synced(s.last_sync)}`, count].filter(Boolean).join(" · ") });
      else if (s.status === "ok") lines.push({ text: "Not synced yet." });
    }
    return lines;
  }

  let syncing = $state<number[]>([]);
  let starting = $state<number | null>(null);
  const SYNC_POLL_MS = 5000;
  const SYNC_POLLS = 120;
  const watching = new Set<ReturnType<typeof setInterval>>();
  onDestroy(() => { watching.forEach(clearInterval); watching.clear(); });

  function watchSync(s: PhotoSource) {
    syncing = [...syncing, s.id];
    let polls = 0;
    const timer = setInterval(async () => {
      polls += 1;
      await load();
      const now = list?.sources.find((x) => x.id === s.id);
      if (!now || polls >= SYNC_POLLS || now.last_sync !== s.last_sync || now.status !== s.status || now.last_error !== s.last_error) {
        clearInterval(timer);
        watching.delete(timer);
        syncing = syncing.filter((id) => id !== s.id);
      }
    }, SYNC_POLL_MS);
    watching.add(timer);
  }

  const syncNow = (s: PhotoSource) => act(async () => {
    const r = await apiCall<"POST /api/photo-sources/{id}/sync">(`/api/photo-sources/${s.id}/sync`, { method: "POST", failed: "Couldn’t start the sync" });
    if (r.started) watchSync(s);
    else toast("This library is already syncing, or has nothing to sync.");
  }, { busy: (on) => (starting = on ? s.id : null) });

  let pausing = $state<number | null>(null);
  let notices = $state<Record<number, Outcome | undefined>>({});
  const clearNotice = (id: number) => { notices = { ...notices, [id]: undefined }; };
  const RESUME_WAITS = "Resuming this library would add its photos to trips you share with everyone, which needs a confirmation Waypoint can’t ask for here yet.";

  const setPaused = (s: PhotoSource, paused: boolean) => act(async () => {
    clearNotice(s.id);
    let snapshot: string | undefined;
    if (!paused) {
      const check = await apiCall<"GET /api/photo-sources/{id}/resume">(`/api/photo-sources/${s.id}/resume`);
      if (check.asks) { notices = { ...notices, [s.id]: { text: RESUME_WAITS } }; return; }
      snapshot = check.snapshot;
    }
    await apiCall<"POST /api/photo-sources/{id}">(`/api/photo-sources/${s.id}`, { method: "POST", body: snapshot ? { paused, snapshot } : { paused }, failed: paused ? "Couldn’t pause it" : "Couldn’t resume it" });
    toast.success(paused ? "Paused" : "Resumed");
    await load();
  }, { busy: (on) => (pausing = on ? s.id : null), onError: (message, err) => (notices = { ...notices, [s.id]: outcome(err, message) }) });

  let rekeying = $state<number | null>(null);
  let newKey = $state("");
  let showNewKey = $state(false);
  let savingKey = $state(false);
  let rekeyField = $state<HTMLInputElement | null>(null);

  async function openRekey(s: PhotoSource) {
    rekeying = rekeying === s.id ? null : s.id;
    newKey = ""; showNewKey = false;
    clearNotice(s.id);
    await tick();
    rekeyField?.focus();
  }

  const saveKey = (s: PhotoSource, event: SubmitEvent) => {
    event.preventDefault();
    return act(async () => {
      await apiCall<"POST /api/photo-sources/{id}">(`/api/photo-sources/${s.id}`, { method: "POST", body: { key: newKey }, failed: "Couldn’t change the key" });
      newKey = ""; rekeying = null;
      toast.success("Key changed");
      await load();
    }, { busy: (on) => (savingKey = on), onError: (message, err) => (notices = { ...notices, [s.id]: outcome(err, message) }) });
  };

  let removing = $state<PhotoSource | null>(null);
  let askingToRemove = $state(false);
  let removeButton: HTMLElement | null = null;

  function askRemove(s: PhotoSource, e: MouseEvent) {
    removeButton = e.currentTarget as HTMLElement;
    removing = s;
    askingToRemove = true;
  }

  async function remove() {
    const s = removing;
    if (!s) return false;
    return act(async () => {
      await apiCall<"DELETE /api/photo-sources/{id}">(`/api/photo-sources/${s.id}`, { method: "DELETE", failed: "Couldn’t remove it" });
      toast.success(`${libraryOf(s)} removed`);
      await load();
    });
  }

  const removeText = (s: PhotoSource | null) =>
    s?.photos ? `${s.photos === 1 ? "Its 1 photo leaves" : `Its ${s.photos.toLocaleString()} photos leave`} every trip. Nothing changes in Immich.` : "Its photos leave every trip. Nothing changes in Immich.";

  let connecting = $state(false);
  let whose = $state<number | null>(null);
  let url = $state("");
  let key = $state("");
  let showKey = $state(false);
  let testing = $state(false);
  let saving = $state(false);
  let tested = $state<{ url: string; key: string; person: number | null; name: string | null } | null>(null);
  let result = $state<Outcome | null>(null);
  let firstField = $state<HTMLSelectElement | null>(null);

  const choices = $derived.by(() => {
    const takenByOthers = new Set((list?.sources ?? []).filter((s) => !s.mine).map((s) => s.person_id));
    const others = people.filter((p) => !p.member && p.id !== me && !takenByOthers.has(p.id));
    const self = people.find((p) => p.id === me);
    return [...(self ? [{ id: self.id, label: `${self.display_name} (you)` }] : []), ...others.map((p) => ({ id: p.id, label: p.display_name }))];
  });
  const chosen = $derived(whose ?? choices[0]?.id ?? null);
  const chosenPerson = $derived(chosen != null ? personOf(chosen) : undefined);
  const forSelf = $derived(chosen == null || chosen === me);
  const passed = $derived(!!tested && tested.url === url.trim() && tested.key === key.trim() && tested.person === chosen);

  function clearForm() {
    url = ""; key = ""; showKey = false; tested = null; result = null; whose = null;
  }

  draftGuard({ dirty: () => connecting && !!(url.trim() || key.trim()), saving: () => saving, discard: () => { clearForm(); connecting = false; } });

  async function toggleConnect() {
    connecting = !connecting;
    if (!connecting) { clearForm(); return; }
    await tick();
    firstField?.focus();
  }

  function edited() {
    tested = null;
    result = null;
  }

  const asTyped = () => ({ url: url.trim(), key: key.trim(), person: chosen });
  const stillTyped = (sent: { url: string; key: string; person: number | null }) => {
    const now = asTyped();
    return now.url === sent.url && now.key === sent.key && now.person === sent.person;
  };

  function test() {
    const sent = asTyped();
    return act(async () => {
      result = null;
      const r = await apiCall<"POST /api/photo-sources/test">("/api/photo-sources/test", { method: "POST", body: { url: sent.url, key: sent.key } });
      if (stillTyped(sent)) tested = { ...sent, name: r.name };
    }, { busy: (on) => (testing = on), onError: (message, err) => { if (!stillTyped(sent)) return; tested = null; result = outcome(err, message); } });
  }

  const save = (event: SubmitEvent) => {
    event.preventDefault();
    if (!passed) return;
    return act(async () => {
      await apiCall<"POST /api/photo-sources">("/api/photo-sources", { method: "POST", body: { person_id: chosen, url: url.trim(), key: key.trim() } });
      clearForm();
      connecting = false;
      toast.success("Library connected");
      await load();
    }, { busy: (on) => (saving = on), onError: (message, err) => { tested = null; result = outcome(err, message); } });
  };

  const fieldProblem = (field: "url" | "key") => (result?.field === field ? result.text : "");
</script>

<section aria-labelledby="photos-title" class="space-y-2">
  <h2 id="photos-title" class="eyebrow px-1">Photos</h2>
  <p class="px-1 text-sm text-muted-foreground">Waypoint shows each person’s photos from their Immich library on the trips they were on.</p>
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p>{#if !off}<Button variant="outline" onclick={load}>Try again</Button>{/if}</div>
    {:else if !list}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      {#if !list.sources.length}
        <div class="row"><p class="text-sm text-muted-foreground">No Immich library connected yet.</p></div>
      {/if}
      {#each list.sources as s (s.id)}
        {@const name = nameOf(s.person_id)}
        {@const notice = notices[s.id]}
        <div class="space-y-3 p-4" data-testid="photo-source">
          <div class="flex items-start gap-3">
            <span class={`inline-flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${avatarTone({ id: s.person_id, name })}`} aria-hidden="true">{initials(name)}</span>
            <div class="min-w-0 flex-1">
              <p class="font-medium">{name}</p>
              <p class="truncate font-mono text-sm text-muted-foreground">{host(s.url)}</p>
              {#each about(s) as line (line.text)}<p class={`text-sm ${line.problem ? "" : "text-muted-foreground"}`}>{line.text}</p>{/each}
            </div>
            <StatusChip chip={sourceChip(s, syncing.includes(s.id))} class="shrink-0" />
          </div>
          {#if s.mine}
            {@const library = libraryOf(s)}
            {#if syncing.includes(s.id)}<p class="text-sm text-muted-foreground" role="status">Sync started for {library}. This card updates when it finishes.</p>{/if}
            <div class="flex flex-wrap gap-2">
              {#if s.status === "refused"}
                <Button size="sm" aria-label={`Change key, ${library}`} aria-expanded={rekeying === s.id} onclick={() => openRekey(s)}><KeyRound aria-hidden="true" />Change key</Button>
              {:else}
                <Button variant="outline" size="sm" aria-label={`Sync now, ${library}`} disabled={starting === s.id || syncing.includes(s.id) || s.status === "off"} onclick={() => syncNow(s)}><RefreshCw aria-hidden="true" />{starting === s.id || syncing.includes(s.id) ? "Syncing…" : "Sync now"}</Button>
                <Button variant="outline" size="sm" aria-label={`Change key, ${library}`} aria-expanded={rekeying === s.id} onclick={() => openRekey(s)}>Change key</Button>
                <Button variant="outline" size="sm" aria-label={`${s.status === "off" ? "Resume" : "Pause"}, ${library}`} disabled={pausing === s.id} onclick={() => setPaused(s, s.status !== "off")}>{s.status === "off" ? "Resume" : "Pause"}</Button>
              {/if}
              <Button variant="outline" size="sm" class="text-status-bad-ink" aria-label={`Remove ${library}`} onclick={(e: MouseEvent) => askRemove(s, e)}>Remove</Button>
            </div>
            {#if rekeying === s.id}
              <form class="space-y-2" onsubmit={(e) => saveKey(s, e)} aria-label={`New key for ${library}`}>
                <label class="block text-sm font-medium" for={`photo-rekey-${s.id}`}>API key</label>
                <div class="flex gap-2">
                  <Input id={`photo-rekey-${s.id}`} bind:ref={rekeyField} bind:value={newKey} class="font-mono" type={showNewKey ? "text" : "password"} autocomplete="off" spellcheck={false}
                    aria-invalid={notice?.chip ? true : undefined} aria-describedby={notice ? `photo-notice-${s.id}` : undefined} oninput={() => clearNotice(s.id)} />
                  <Button type="button" variant="outline" aria-pressed={showNewKey} aria-label="Show the key" onclick={() => (showNewKey = !showNewKey)}>{showNewKey ? "Hide" : "Show"}</Button>
                </div>
                <div class="flex flex-wrap gap-2">
                  <Button type="submit" size="sm" disabled={savingKey || !newKey.trim()}>{savingKey ? "Saving…" : "Save key"}</Button>
                  <Button type="button" variant="outline" size="sm" onclick={() => { rekeying = null; newKey = ""; }}>Cancel</Button>
                </div>
              </form>
            {/if}
            {#if notice}
              <p id={`photo-notice-${s.id}`} class="text-sm" role="alert">{#if notice.chip}<StatusChip chip={notice.chip} class="mr-2 align-middle" />{/if}<span>{notice.text}</span></p>
            {/if}
          {/if}
        </div>
      {/each}
      <div class="row">
        <h3 id="photo-connect-title" class="font-medium">Connect an Immich library</h3>
        <Button size="sm" aria-expanded={connecting} aria-controls={connecting ? "photo-connect" : undefined} onclick={toggleConnect}>{connecting ? "Cancel" : "Connect"}</Button>
      </div>
      {#if connecting}
        <form id="photo-connect" class="space-y-4 p-4" aria-labelledby="photo-connect-title" onsubmit={save}>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="space-y-1 text-sm">
              <span class="font-medium">Whose library</span>
              <select bind:this={firstField} class="border-input bg-secondary flex h-10 w-full rounded-xl border px-3 text-base outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 md:text-sm"
                value={chosen} onchange={(e) => { whose = Number(e.currentTarget.value); edited(); }}>
                {#each choices as c (c.id)}<option value={c.id}>{c.label}</option>{/each}
              </select>
            </label>
            <div class="space-y-1 text-sm">
              <label class="font-medium" for="photo-url">Immich address</label>
              <Input id="photo-url" bind:value={url} class="font-mono" autocomplete="off" spellcheck={false} inputmode="url" oninput={edited}
                aria-invalid={fieldProblem("url") ? true : undefined} aria-describedby={fieldProblem("url") ? "photo-url-problem" : undefined} />
              {#if fieldProblem("url")}<p id="photo-url-problem" class="text-sm text-signal-ink" role="alert">{fieldProblem("url")}</p>{/if}
            </div>
            <div class="space-y-1 text-sm sm:col-span-2">
              <label class="font-medium" for="photo-key">API key</label>
              <div class="flex gap-2">
                <Input id="photo-key" bind:value={key} class="font-mono" type={showKey ? "text" : "password"} autocomplete="off" spellcheck={false} oninput={edited}
                  aria-invalid={fieldProblem("key") || result?.chip?.tone === "bad" ? true : undefined}
                  aria-describedby={["photo-key-help", fieldProblem("key") ? "photo-key-problem" : "", result && !result.field ? "photo-result" : ""].filter(Boolean).join(" ")} />
                <Button type="button" variant="outline" aria-pressed={showKey} aria-label="Show the key" onclick={() => (showKey = !showKey)}>{showKey ? "Hide" : "Show"}</Button>
              </div>
              {#if fieldProblem("key")}<p id="photo-key-problem" class="text-sm text-signal-ink" role="alert">{fieldProblem("key")}</p>{/if}
              <div id="photo-key-help">
                <p class="text-muted-foreground">Make the key in Immich under Account settings › API keys, signed in as {forSelf ? "yourself" : chosenPerson?.display_name}, and tick:</p>
                <p class="mt-1 flex flex-wrap gap-1.5">{#each list.permissions as p (p)}<code class="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-xs">{p}</code>{/each}</p>
              </div>
            </div>
          </div>
          <div class="space-y-2 rounded-xl bg-surface-2 p-3 text-sm">
            <p><span class="font-semibold">What Waypoint reads.</span> Photos taken during {forSelf ? "your" : `${chosenPerson?.display_name}’s`} trips and the 12 hours around them. For each one it keeps when and where it was taken, including photos that turn out not to belong to a trip. It never keeps the pictures: they stay in Immich, and Waypoint fetches each one from Immich when it is shown, without storing it.</p>
            <p class="text-muted-foreground">Nothing from this library shows on a trip until it is shared there, and then only to the people chosen.{forSelf ? "" : ` ${chosenPerson?.display_name} doesn’t sign in, so you manage what ${chosenPerson?.display_name}’s library shares.`} The key is stored encrypted and is never shown again.</p>
          </div>
          {#if result && !result.field}
            <p id="photo-result" class="text-sm" role="alert">{#if result.chip}<StatusChip chip={result.chip} class="mr-2 align-middle" />{/if}<span>{result.text}</span></p>
          {:else if passed}
            <p class="text-sm" role="status"><StatusChip chip={{ label: "Key works", tone: "ok" }} class="mr-2 align-middle" /><span>It belongs to the Immich user <span class="font-mono">{tested?.name ?? "with no name"}</span>.</span></p>
          {/if}
          <div class="flex flex-wrap gap-2">
            <Button type="button" variant="outline" disabled={testing || !url.trim() || !key.trim()} onclick={test}>{testing ? "Testing…" : "Test"}</Button>
            <Button type="submit" disabled={!passed || saving}>{saving ? "Saving…" : "Save"}</Button>
          </div>
        </form>
      {/if}
    {/if}
  </div>
</section>

<ConfirmDialog bind:open={askingToRemove} title={`Remove ${removing ? libraryOf(removing) : "this library"}?`} confirmLabel="Remove" busyLabel="Removing…" destructive
  returnFocus={() => removeButton} onconfirm={remove} description={removeText(removing)} />
