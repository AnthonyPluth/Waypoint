<script lang="ts">
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import { discardChanges, keepEditing, type DraftGuard } from "$lib/drafts.svelte";

  let { guard, returnFocus }: { guard: DraftGuard; returnFocus?: () => HTMLElement | null | undefined } = $props();
</script>

<ConfirmDialog bind:open={() => guard.asking, (v) => { guard.asking = v; if (!v) keepEditing(); }} title="Discard changes?" description="What you typed here won’t be saved."
  confirmLabel="Discard changes" cancelLabel="Keep editing" destructive {returnFocus} onconfirm={() => { discardChanges(); return true; }} />
