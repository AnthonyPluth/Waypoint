<script lang="ts">
  import { act, errMsg } from "$lib/act";
  import type { Stats } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";
  import { onMount } from "svelte";

  let unit = $state<Stats["distance_unit"] | null>(null);
  let problem = $state("");
  let saving = $state(false);

  async function load() {
    problem = "";
    try { unit = (await apiCall<"GET /api/distance-unit">("/api/distance-unit")).distance_unit; }
    catch (err) { unit = null; problem = errMsg(err); }
  }
  onMount(load);

  const choose = (next: Stats["distance_unit"]) => act(async () => {
    unit = (await apiCall<"POST /api/distance-unit">("/api/distance-unit", { method: "POST", body: { distance_unit: next } })).distance_unit;
    toast.success("Saved");
  }, { busy: (on) => (saving = on) });
</script>

<section aria-labelledby="distance-title" class="space-y-2">
  <h2 id="distance-title" class="eyebrow px-1">Distances</h2>
  <div class="rows">
    {#if problem}
      <div class="row"><p class="text-sm text-signal-ink" role="status">{problem}</p><Button variant="outline" onclick={load}>Try again</Button></div>
    {:else if unit === null}
      <div class="row"><p class="text-sm text-muted-foreground">Loading…</p></div>
    {:else}
      <div class="row">
        <div><p class="font-medium">Show distances in</p><p class="text-sm text-muted-foreground">On the Stats page, for everyone in the household.</p></div>
        <div class="flex gap-2" role="group" aria-label="Distance unit">
          <Button variant={unit === "mi" ? "default" : "outline"} aria-pressed={unit === "mi"} disabled={saving} onclick={() => choose("mi")}>Miles</Button>
          <Button variant={unit === "km" ? "default" : "outline"} aria-pressed={unit === "km"} disabled={saving} onclick={() => choose("km")}>Kilometres</Button>
        </div>
      </div>
    {/if}
  </div>
</section>
