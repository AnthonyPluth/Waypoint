<script lang="ts">
  import { act } from "$lib/act";
  import { app } from "$lib/app.svelte";
  import { Button } from "$lib/components/ui/button";
  import { apiCall } from "$lib/contract";
  import { toast } from "svelte-sonner";

  const shown = $derived(app.state?.show_costs !== false);
  let saving = $state(false);

  const choose = (next: boolean) => act(async () => {
    const saved = await apiCall<"POST /api/show-costs">("/api/show-costs", { method: "POST", body: { show_costs: next } });
    if (app.state) app.state.show_costs = saved.show_costs;
    toast.success("Saved");
  }, { busy: (on) => (saving = on) });
</script>

<section aria-labelledby="costs-title" class="space-y-2">
  <h2 id="costs-title" class="eyebrow px-1">Trip costs</h2>
  <div class="rows">
    <div class="row">
      <div><p class="font-medium">Show trip costs</p><p class="text-sm text-muted-foreground">Applies to the household. Hidden costs stay saved.</p></div>
      <div class="flex gap-2" role="group" aria-label="Trip costs">
        <Button variant={shown ? "default" : "outline"} aria-pressed={shown} disabled={saving} onclick={() => choose(true)}>Show</Button>
        <Button variant={!shown ? "default" : "outline"} aria-pressed={!shown} disabled={saving} onclick={() => choose(false)}>Hide</Button>
      </div>
    </div>
  </div>
</section>
