<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { api } from "$lib/api";
  import type { ImportPreview, ImportRow, Person } from "$lib/api-types";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { apiCall } from "$lib/contract";
  import { SvelteSet } from "svelte/reactivity";
  import { toast } from "svelte-sonner";

  const MAX_BYTES = 5 * 1024 * 1024;
  const BATCH = 1000;
  const PAGE = 50;

  let preview = $state<ImportPreview | null>(null);
  let people = $state<Person[]>([]);
  let travelling = $state<number[]>([]);
  let reading = $state(false);
  let saving = $state(false);
  let problem = $state("");
  let input = $state<HTMLInputElement | null>(null);
  let filter = $state<Filter>("all");
  let query = $state("");
  let page = $state(0);
  let progress = $state(0);
  let sending = $state(0);
  const left = new SvelteSet<number>();
  const added = new SvelteSet<number>();
  let chosen = 0;

  type Filter = "all" | "new" | "exists" | "unreadable";
  const FILTERS: { key: Filter; name: string }[] = [
    { key: "all", name: "All" }, { key: "new", name: "New" }, { key: "exists", name: "Already here" }, { key: "unreadable", name: "Problems only" },
  ];
  const count = (status: ImportRow["status"]) => preview?.rows.filter((r) => r.status === status).length ?? 0;
  const counts = $derived({ all: preview?.rows.length ?? 0, new: count("new"), exists: count("exists"), unreadable: count("unreadable") });
  const included = (r: ImportRow) => r.status === "new" && !left.has(r.line) && !added.has(r.line);
  const toAdd = $derived(preview?.rows.filter(included) ?? []);
  const fresh = $derived(toAdd.length);
  const matches = (r: ImportRow, q: string) =>
    [r.line, r.origin, r.destination, r.flight_number, r.airline, r.day, r.reason, label(r.status)].some((v) => String(v ?? "").toLowerCase().includes(q));
  const shown = $derived.by(() => {
    const q = query.trim().toLowerCase();
    return (preview?.rows ?? []).filter((r) => (filter === "all" || r.status === filter) && (!q || matches(r, q)));
  });
  const pages = $derived(Math.max(1, Math.ceil(shown.length / PAGE)));
  const here = $derived(Math.min(page, pages - 1));
  const visible = $derived(shown.slice(here * PAGE, (here + 1) * PAGE));
  const n = (k: number, word: string) => `${k.toLocaleString("en-US")} ${word}${k === 1 ? "" : "s"}`;
  const day = (d: string | null) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "No date");
  const label = (s: ImportRow["status"]) => (s === "new" ? "New" : s === "exists" ? "Already in Waypoint" : "Can’t read");

  async function choose(file: File | null) {
    const mine = ++chosen;
    preview = null; problem = "";
    left.clear(); added.clear(); filter = "all"; query = ""; page = 0;
    if (!file) return;
    if (file.size > MAX_BYTES) { problem = "That file is larger than 5 MB."; return; }
    reading = true;
    try {
      const [p, list] = await Promise.all([
        api<ImportPreview>("/api/import/preview", { method: "POST", body: file, failed: "Couldn’t read that file" }),
        apiCall<"GET /api/people">("/api/people"),
      ]);
      if (mine !== chosen) return;
      people = list.people; travelling = p.me === null ? [] : [p.me]; preview = p;
    } catch (err) { if (mine === chosen) problem = errMsg(err); }
    finally { if (mine === chosen) reading = false; }
  }

  function done() {
    preview = null; problem = "";
    left.clear(); added.clear();
    if (input) input.value = "";
  }

  function include(r: ImportRow, on: boolean) {
    if (on) left.delete(r.line); else left.add(r.line);
  }

  const show = (f: Filter) => { filter = f; page = 0; };

  async function add() {
    const rows = [...toAdd]
      .sort((a, b) => (a.day! + (a.start_local ?? "")).localeCompare(b.day! + (b.start_local ?? "")) || a.line - b.line);
    let total = 0, existing = 0;
    progress = 0; sending = rows.length;
    const ok = await act(async () => {
      for (let i = 0; i < rows.length; i += BATCH) {
        const batch = rows.slice(i, i + BATCH);
        const flights = batch.map((r) => ({
          day: r.day!, origin: r.origin!, destination: r.destination!, flight_number: r.flight_number, airline: r.airline,
          start_local: r.start_local, end_local: r.end_local, seat: r.seat, cabin: r.cabin, aircraft: r.aircraft,
        }));
        const r = await apiCall<"POST /api/import">("/api/import", { method: "POST", body: { flights, person_ids: travelling }, failed: "Couldn’t add the flights" });
        total += r.added; existing += r.existing;
        for (const b of batch) added.add(b.line);
        progress = Math.min(i + BATCH, rows.length);
      }
    }, { busy: (on) => (saving = on), onError: (m) => { problem = progress ? `Added ${n(progress, "flight")} before this stopped: ${m} ${n(rows.length - progress, "flight")} left; add again to retry only those.` : m; } });
    if (ok) { toast.success(`Added ${n(total, "flight")}${existing ? `; ${existing.toLocaleString("en-US")} were already here` : ""}`); done(); }
  }
</script>

<section aria-labelledby="import-title" class="space-y-2">
  <h2 id="import-title" class="eyebrow px-1">Import past flights</h2>
  <div class="rows">
    <div class="row items-stretch">
      <div class="flex w-full flex-col gap-3">
        <label class="flex min-w-0 flex-col gap-1.5 text-sm text-muted-foreground">
          <span class="font-medium text-foreground">Add flights from another app</span>
          <span>Choose a CSV exported from Flighty, myFlightRadar24, OpenFlights or App in the Air (up to 5 MB and 10,000 rows). You’ll see each flight before anything is added, and the file isn’t kept.</span>
          <input bind:this={input} type="file" accept=".csv,text/csv" onchange={(e) => choose(e.currentTarget.files?.[0] ?? null)}
            class="w-full max-w-72 cursor-pointer text-sm file:mr-3 file:cursor-pointer file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium file:text-secondary-foreground" />
        </label>
        {#if reading}<p class="text-sm text-muted-foreground">Reading the file…</p>{/if}
        {#if problem}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{problem}</p>{/if}
        {#if preview}
          <div class="flex flex-col gap-3" data-testid="import-preview">
            <p class="text-sm"><span class="font-medium">{preview.format} export:</span>
              {n(counts.new, "new flight")}, {counts.exists} already in Waypoint, {counts.unreadable} can’t be read.</p>
            {#if fresh}
              <fieldset class="flex flex-col gap-1.5 text-sm">
                <legend class="mb-1 font-medium">Who was on these flights?</legend>
                {#each people as p (p.id)}
                  <label class="flex items-center gap-2"><input type="checkbox" value={p.id} bind:group={travelling} class="size-4" /> {p.display_name}{#if p.id === preview.me} <span class="text-muted-foreground">(you)</span>{/if}</label>
                {/each}
              </fieldset>
            {/if}
            <div class="flex flex-col gap-2" role="group" aria-label="Review the rows">
              <div class="flex flex-wrap gap-1.5">
                {#each FILTERS as f (f.key)}
                  <Button size="sm" variant={filter === f.key ? "secondary" : "outline"} aria-pressed={filter === f.key} onclick={() => show(f.key)}>{f.name} ({counts[f.key].toLocaleString("en-US")})</Button>
                {/each}
              </div>
              <label class="flex flex-col gap-1 text-sm"><span class="text-muted-foreground">Search rows</span>
                <input type="search" bind:value={query} oninput={() => (page = 0)} placeholder="Airport, flight number, airline, date or line" class="w-full max-w-72 rounded-md bg-secondary px-3 py-2 text-sm" /></label>
            </div>
            <ul class="divide-y rounded-lg bg-muted text-sm" data-testid="import-rows">
              {#each visible as r (r.line)}
                <li class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2" class:opacity-80={!included(r)}>
                  <svelte:element this={r.status === "new" && !added.has(r.line) ? "label" : "div"} class="flex min-h-11 min-w-0 items-center gap-2">
                    {#if r.status === "new" && !added.has(r.line)}
                      <input type="checkbox" checked={!left.has(r.line)} disabled={saving} onchange={(e) => include(r, e.currentTarget.checked)}
                        aria-label={`Add line ${r.line}${r.origin && r.destination ? `, ${r.origin} to ${r.destination}` : ""}`} class="size-4 shrink-0" />
                    {/if}
                    <div class="min-w-0 break-words">
                      <p class="font-medium">{r.origin && r.destination ? `${r.origin} → ${r.destination}` : `Line ${r.line}`}{#if r.flight_number}{" "}<span class="text-muted-foreground">{r.flight_number}</span>{/if}</p>
                      <p class="text-muted-foreground">{[r.day ? day(r.day) : null, r.status !== "unreadable" && !r.start_local ? "no times" : null, r.status !== "new" ? r.reason : null].filter(Boolean).join(" · ")}</p>
                    </div>
                  </svelte:element>
                  <Badge variant={r.status === "new" && !added.has(r.line) && !left.has(r.line) ? "secondary" : "outline"}>{added.has(r.line) ? "Added" : r.status === "new" && left.has(r.line) ? "Left out" : label(r.status)}</Badge>
                </li>
              {:else}
                <li class="px-3 py-2 text-muted-foreground">No rows match.</li>
              {/each}
            </ul>
            <div class="flex flex-wrap items-center gap-2 text-sm">
              <Button size="sm" variant="outline" disabled={here === 0} onclick={() => (page = here - 1)}>Previous</Button>
              <Button size="sm" variant="outline" disabled={here >= pages - 1} onclick={() => (page = here + 1)}>Next</Button>
              <p class="text-muted-foreground" aria-live="polite">{shown.length ? `Rows ${(here * PAGE + 1).toLocaleString("en-US")}–${Math.min((here + 1) * PAGE, shown.length).toLocaleString("en-US")} of ${shown.length.toLocaleString("en-US")}` : "No rows"} · page {here + 1} of {pages}</p>
            </div>
            {#if counts.new}<p class="text-sm text-muted-foreground">{n(fresh, "new flight")} will be added{counts.new - fresh - added.size > 0 ? `; ${counts.new - fresh - added.size} left out` : ""}.</p>{/if}
            <div class="flex flex-wrap gap-2">
              <Button disabled={saving || !fresh || (!travelling.length && preview.me !== null)} onclick={add}>{saving ? `Adding… ${progress.toLocaleString("en-US")} of ${sending.toLocaleString("en-US")}` : fresh ? `Add ${n(fresh, "flight")}` : "Nothing new to add"}</Button>
              <Button variant="outline" disabled={saving} onclick={done}>Cancel</Button>
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>
</section>
