<script lang="ts">
  import { Sheet } from "./index";

  let { open = $bindable(false) }: { open?: boolean } = $props();
</script>

<button onclick={() => (open = true)}>Open it</button>
<button>Elsewhere</button>
<Sheet bind:open title="Edit this thing" description="Changes are kept.">
  <label>Name <input /></label>
  <button>Save it</button>
</Sheet>
