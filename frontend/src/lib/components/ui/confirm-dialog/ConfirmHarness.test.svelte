<script lang="ts">
  import { ConfirmDialog } from "./index";

  let { onconfirm, typeToConfirm, open = $bindable(false) }: { onconfirm: () => unknown; typeToConfirm?: string; open?: boolean } = $props();
</script>

<button onclick={() => (open = true)}>Delete it</button>
<ConfirmDialog bind:open title="Delete the thing?" confirmLabel="Delete" busyLabel="Deleting…" destructive {typeToConfirm} {onconfirm}
  description="It goes for good." />
