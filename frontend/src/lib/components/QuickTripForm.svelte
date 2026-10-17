<script lang="ts">
  import { onMount, tick } from "svelte";
  import { actGet } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Trip } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { DiscardDialog } from "$lib/components/ui/discard-dialog";
  import { Input } from "$lib/components/ui/input";
  import { baseline, draftGuard, leave } from "$lib/drafts.svelte";
  import { blankTrip, TRIP_NAME_LIMIT, tripBody, tripIssues, type TripDraft } from "$lib/quick-trip";

  let { me, oncreated, oncancel }: { me: number | null; oncreated: (t: Trip) => void; oncancel: () => void } = $props();

  let d = $state<TripDraft>(blankTrip());
  const uid = $props.id();
  let error = $state("");
  let attempted = $state(false);
  let saving = $state(false);
  let formEl: HTMLFormElement | null = $state(null);
  const unchanged = baseline(() => d);
  const guard = draftGuard({ dirty: unchanged.changed, saving: () => saving, discard: () => oncancel() });

  onMount(() => formEl?.querySelector("input")?.focus());

  const found = $derived(attempted ? tripIssues(d) : []);
  const shown = $derived(Object.fromEntries([...found].reverse().map((i) => [i.field, i.message])) as Record<string, string | undefined>);
  const fieldId = (field: string) => `${uid}-${field}`;
  const aria = (field: string) => (shown[field] ? { "aria-invalid": "true" as const, "aria-describedby": fieldId(field) } : {});

  async function save(e: SubmitEvent) {
    e.preventDefault();
    const list = tripIssues(d);
    if (list.length) {
      attempted = true;
      error = "";
      await tick();
      formEl?.querySelector<HTMLElement>(`[data-field="${list[0].field}"] input`)?.focus();
      return;
    }
    error = "";
    const made = await actGet(() => apiCall<"POST /api/trips">("/api/trips", { method: "POST", body: tripBody(d, me) }), { busy: (on) => (saving = on), onError: (m) => (error = m) });
    if (made) oncreated(made);
  }
</script>

<form class="rows mb-6" data-editor novalidate bind:this={formEl} onsubmit={save} aria-labelledby={fieldId("title")}>
  <div class="row items-stretch">
    <div class="flex w-full flex-col gap-5">
      <div class="flex flex-col gap-1">
        <h2 id={fieldId("title")} class="font-medium">Add a trip</h2>
        <p class="text-sm text-muted-foreground">Start with a place and dates. You add flights and stays on the trip’s page, and its dates then follow its bookings.</p>
      </div>
      <div data-field="name" class="flex flex-col gap-1.5">
        <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Where to, or a name</span>
          <Input bind:value={d.name} maxlength={TRIP_NAME_LIMIT} autocomplete="off" placeholder="Lisbon, or Summer at the lake" {...aria("name")} /></label>
        {#if shown.name}<p id={fieldId("name")} class="text-sm text-signal-ink" data-error>{shown.name}</p>{/if}
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div data-field="start" class="flex flex-col gap-1.5">
          <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">First day (optional)</span>
            <Input type="date" bind:value={d.start} autocomplete="off" {...aria("start")} /></label>
          {#if shown.start}<p id={fieldId("start")} class="text-sm text-signal-ink" data-error>{shown.start}</p>{/if}
        </div>
        <div data-field="end" class="flex flex-col gap-1.5">
          <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Last day (optional)</span>
            <Input type="date" bind:value={d.end} autocomplete="off" {...aria("end")} /></label>
          {#if shown.end}<p id={fieldId("end")} class="text-sm text-signal-ink" data-error>{shown.end}</p>{/if}
        </div>
      </div>
      {#if error}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{error}</p>{/if}
      {#if found.length}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{found.length === 1 ? "One thing needs fixing before this can be saved. It is marked above." : `${found.length} things need fixing before this can be saved. They are marked above.`}</p>{/if}
      <div class="flex flex-wrap gap-2">
        <Button type="submit" disabled={saving}>{saving ? "Adding…" : "Add trip"}</Button>
        <Button type="button" variant="outline" disabled={saving} onclick={() => leave(oncancel, [guard])}>Cancel</Button>
      </div>
    </div>
  </div>
</form>

<DiscardDialog {guard} />
