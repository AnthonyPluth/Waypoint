<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import { api } from "$lib/api";
  import type { ImportPreview, ImportRow, Person } from "$lib/api-types";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";

  // Settings → Import past flights: choose a CSV exported from another app, see what each row would add, pick who was on the
  // flights, then add the new ones. The file goes up once, for the preview, and isn't kept: saving sends back only the flights
  // being added, a thousand at a time (the most one request takes).
  const MAX_BYTES = 5 * 1024 * 1024;
  const BATCH = 1000;
  const SHOWN = 200;   // rows listed at once: a long file shows its first rows and the counts of them all

  let preview = $state<ImportPreview | null>(null);
  let people = $state<Person[]>([]);
  let travelling = $state<number[]>([]);
  let reading = $state(false);
  let saving = $state(false);
  let problem = $state("");
  let input = $state<HTMLInputElement | null>(null);
  let chosen = 0;   // which choosing this answer belongs to, so a slow one can't replace a newer one

  const count = (status: ImportRow["status"]) => preview?.rows.filter((r) => r.status === status).length ?? 0;
  const fresh = $derived(count("new"));
  const n = (k: number, word: string) => `${k.toLocaleString("en-US")} ${word}${k === 1 ? "" : "s"}`;
  const day = (d: string | null) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "No date");
  const label = (s: ImportRow["status"]) => (s === "new" ? "New" : s === "exists" ? "Already in Waypoint" : "Can’t read");

  async function choose(file: File | null) {
    const mine = ++chosen;
    preview = null; problem = "";
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
    if (input) input.value = "";
  }

  async function add() {
    const rows = preview?.rows.filter((r) => r.status === "new") ?? [];
    let added = 0, existing = 0;
    const ok = await act(async () => {
      for (let i = 0; i < rows.length; i += BATCH) {
        const flights = rows.slice(i, i + BATCH).map((r) => ({
          day: r.day!, origin: r.origin!, destination: r.destination!, flight_number: r.flight_number, airline: r.airline,
          start_local: r.start_local, end_local: r.end_local, seat: r.seat, cabin: r.cabin,
        }));
        const r = await apiCall<"POST /api/import">("/api/import", { method: "POST", body: { flights, person_ids: travelling }, failed: "Couldn’t add the flights" });
        added += r.added; existing += r.existing;
      }
    }, { busy: (on) => (saving = on), onError: (m) => { problem = added ? `Added ${n(added, "flight")} before this stopped: ${m} Choose the file again to add the rest.` : m; } });
    if (ok) { toast.success(`Added ${n(added, "flight")}${existing ? `; ${existing.toLocaleString("en-US")} were already here` : ""}`); done(); }
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
              {n(count("new"), "new flight")}, {count("exists")} already in Waypoint, {count("unreadable")} can’t be read.</p>
            {#if fresh}
              <fieldset class="flex flex-col gap-1.5 text-sm">
                <legend class="mb-1 font-medium">Who was on these flights?</legend>
                {#each people as p (p.id)}
                  <label class="flex items-center gap-2"><input type="checkbox" value={p.id} bind:group={travelling} class="size-4" /> {p.display_name}{#if p.id === preview.me} <span class="text-muted-foreground">(you)</span>{/if}</label>
                {/each}
              </fieldset>
            {/if}
            <ul class="divide-y rounded-lg bg-muted text-sm">
              {#each preview.rows.slice(0, SHOWN) as r (r.line)}
                <li class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2" class:opacity-70={r.status !== "new"}>
                  <div class="min-w-0">
                    <p class="font-medium">{r.origin && r.destination ? `${r.origin} → ${r.destination}` : `Line ${r.line}`}{#if r.flight_number}{" "}<span class="text-muted-foreground">{r.flight_number}</span>{/if}</p>
                    <p class="text-muted-foreground">{[r.day ? day(r.day) : null, r.status !== "unreadable" && !r.start_local ? "no times" : null, r.status !== "new" ? r.reason : null].filter(Boolean).join(" · ")}</p>
                  </div>
                  <Badge variant={r.status === "new" ? "secondary" : "outline"}>{label(r.status)}</Badge>
                </li>
              {/each}
            </ul>
            {#if preview.rows.length > SHOWN}<p class="text-sm text-muted-foreground">The first {SHOWN} of {n(preview.rows.length, "row")} are listed; all {n(fresh, "new flight")} are added.</p>{/if}
            <div class="flex flex-wrap gap-2">
              <Button disabled={saving || !fresh || (!travelling.length && preview.me !== null)} onclick={add}>{saving ? "Adding…" : fresh ? `Add ${n(fresh, "flight")}` : "Nothing new to add"}</Button>
              <Button variant="outline" disabled={saving} onclick={done}>Cancel</Button>
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>
</section>
