<script lang="ts">
  import { OptionsMenu } from "./index";

  let { onmerge, ondelete }: { onmerge: () => void; ondelete: () => void } = $props();
</script>

<button>Before</button>
<OptionsMenu label="Trip options" text="Trip options" items={[
  { label: "Merge another trip", onselect: onmerge },
  { label: "Delete trip", destructive: true, onselect: ondelete },
]} />
<button>After</button>
