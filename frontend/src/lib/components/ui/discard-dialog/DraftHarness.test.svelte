<script lang="ts">
  import { DiscardDialog } from "./index";
  import { draftGuard } from "$lib/drafts.svelte";

  let { dirty = false, saving = false }: { dirty?: boolean; saving?: boolean } = $props();
  let discarded = $state(0);
  let changed = $derived(dirty);
  const guard = draftGuard({ dirty: () => changed, saving: () => saving, discard: () => { discarded++; changed = false; } });
</script>

<DiscardDialog {guard} />
<output data-testid="discarded">{discarded}</output>
