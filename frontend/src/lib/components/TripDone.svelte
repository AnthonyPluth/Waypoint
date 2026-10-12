<script lang="ts">
  import { act } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import type { Trip } from "$lib/api-types";
  import { toast } from "svelte-sonner";

  let { trip, ondone }: { trip: Trip; ondone: () => void } = $props();

  let asking = $state(false);

  const clear = () => act(async () => {
    const { removed } = await apiCall<"POST /api/trips/{id}/emails/clear">(`/api/trips/${trip.id}/emails/clear`, { method: "POST" });
    toast.success(removed === 1 ? "Removed 1 saved email" : `Removed ${removed} saved emails`);
    ondone();
  });
</script>

{#if trip.can_clear_emails}
  <section class="mt-8 flex flex-col gap-3 rounded-2xl border border-border bg-card p-4" aria-label="Done with this trip">
    <p class="text-sm text-muted-foreground">This trip is over. Waypoint still keeps {trip.emails === 1 ? "the email" : `${trip.emails} emails`} its bookings were read from. If the bookings look right, you can remove {trip.emails === 1 ? "it" : "them"}.</p>
    <div><Button variant="outline" onclick={() => (asking = true)}>Done: looks right, remove the emails</Button></div>
  </section>
{/if}

<ConfirmDialog bind:open={asking} title="Remove the saved emails for this trip?" confirmLabel="Remove emails" busyLabel="Removing…" destructive
  description="The saved emails for this trip will be deleted. The bookings stay. This can’t be undone."
  onconfirm={async () => await clear()} />
